
import os
import traceback
import threading
from flask import request, jsonify

from . import graph_bp
from lightworld.config import Config
from lightworld.graph.ontology_generator import OntologyGenerator
from lightworld.graph.graph_builder import GraphBuilderService
from lightworld.ingestion.multimodal_ingestion import MultimodalIngestionService
from lightworld.ingestion.text_processor import TextProcessor
from lightworld.telemetry.logging_config import get_logger
from lightworld.domain.task import TaskManager, TaskStatus
from lightworld.domain.project import ProjectManager, ProjectStatus


logger = get_logger('lightworld.api')


def allowed_file(filename: str) -> bool:
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    project = ProjectManager.get_project(project_id)

    if not project:
        return jsonify({
            "success": False,
            "error": f"Project not found: {project_id}"
        }), 404

    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)

    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    success = ProjectManager.delete_project(project_id)

    if not success:
        return jsonify({
            "success": False,
            "error": f"Project not found or deletion failed: {project_id}"
        }), 404

    return jsonify({
        "success": True,
        "message": f"Project deleted: {project_id}"
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    project = ProjectManager.get_project(project_id)

    if not project:
        return jsonify({
            "success": False,
            "error": f"Project not found: {project_id}"
        }), 404


    if project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED

    project.graph_id = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)

    return jsonify({
        "success": True,
        "message": f"Project reset: {project_id}",
        "data": project.to_dict()
    })


@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    try:
        logger.info("=== Starting ontology generation ===")


        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')

        logger.debug(f"Project name: {project_name}")
        logger.debug(f"Simulation requirement: {simulation_requirement[:100]}...")

        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "Please provide simulation_requirement"
            }), 400


        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": "Please upload at least one document file"
            }), 400


        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"Created project: {project.project_id}")


        saved_inputs = []

        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):

                file_info = ProjectManager.save_file_to_project(
                    project.project_id,
                    file,
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })
                saved_inputs.append({
                    "path": file_info["path"],
                    "display_name": file_info["original_filename"],
                })

        if not saved_inputs:
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": "No documents processed successfully, please check file formats"
            }), 400

        ingestion = MultimodalIngestionService().ingest_files(
            saved_inputs,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context,
        )
        document_texts = ingestion.get("document_texts", [])
        all_text = ingestion.get("all_text", "")
        if not document_texts or not all_text.strip():
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": "No usable text generated from multimodal input, please check file content"
            }), 400


        project.total_text_length = len(all_text)
        project.ingestion_summary = ingestion.get("manifest")
        ProjectManager.save_extracted_text(project.project_id, all_text)
        ProjectManager.save_json_artifact(
            project.project_id,
            "parsed_content.json",
            ingestion.get("parsed_content", {}),
        )
        ProjectManager.save_json_artifact(
            project.project_id,
            "source_manifest.json",
            ingestion.get("manifest", {}),
        )
        logger.info(f"Text extraction completed, {len(all_text)} characters total")


        logger.info("Calling LLM to generate ontology...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )


        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"Ontology generation complete: {entity_count} entity types, {edge_count} relation types")

        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== Ontology generation complete === Project ID: {project.project_id}")

        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length,
                "ingestion_summary": project.ingestion_summary,
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/build', methods=['POST'])
def build_graph():
    try:
        logger.info("=== Starting graph construction ===")


        errors = []
        if not Config.ZEP_API_KEY:
            errors.append("ZEP_API_KEY is not configured")
        if errors:
            logger.error(f"Configuration error: {errors}")
            return jsonify({
                "success": False,
                "error": "Configuration error: " + "; ".join(errors)
            }), 500


        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"Request params: project_id={project_id}")

        if not project_id:
            return jsonify({
                "success": False,
                "error": "Please provide project_id"
            }), 400


        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"Project not found: {project_id}"
            }), 404


        force = data.get('force', False)

        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": "Ontology not yet generated, please call /ontology/generate first"
            }), 400

        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": "Graph is being built, do not resubmit. To force rebuild, add force: true",
                "task_id": project.graph_build_task_id
            }), 400


        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None


        graph_name = data.get('graph_name', project.name or 'MicroWorld Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)


        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap


        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": "Extracted text content not found"
            }), 400


        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": "Ontology definition not found"
            }), 400


        task_manager = TaskManager()
        task_id = task_manager.create_task(f"Build graph: {graph_name}")
        logger.info(f"Created graph build task: task_id={task_id}, project_id={project_id}")


        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)


        def build_task():
            build_logger = get_logger('lightworld.build')
            try:
                build_logger.info(f"[{task_id}] Starting graph construction...")
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    message="Initializing graph builder service..."
                )


                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)


                task_manager.update_task(
                    task_id,
                    message="Splitting text into chunks...",
                    progress=5
                )
                chunks = TextProcessor.split_text(
                    text,
                    chunk_size=chunk_size,
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)


                task_manager.update_task(
                    task_id,
                    message="Creating Zep graph...",
                    progress=10
                )
                graph_id = builder.create_graph(name=graph_name)


                project.graph_id = graph_id
                ProjectManager.save_project(project)


                task_manager.update_task(
                    task_id,
                    message="Setting ontology definition...",
                    progress=15
                )
                builder.set_ontology(graph_id, ontology)


                def add_progress_callback(msg, progress_ratio):
                    progress = 15 + int(progress_ratio * 40)
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )

                task_manager.update_task(
                    task_id,
                    message=f"Adding {total_chunks} text chunks...",
                    progress=15
                )

                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback
                )


                task_manager.update_task(
                    task_id,
                    message="Waiting for Zep to process data...",
                    progress=55
                )

                def wait_progress_callback(msg, progress_ratio):
                    progress = 55 + int(progress_ratio * 35)
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )

                builder._wait_for_episodes(episode_uuids, wait_progress_callback)


                task_manager.update_task(
                    task_id,
                    message="Retrieving graph data...",
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)


                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)

                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] Graph construction complete: graph_id={graph_id}, nodes={node_count}, edges={edge_count}")


                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="Graph construction complete",
                    progress=100,
                    result={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks
                    }
                )

            except Exception as e:

                build_logger.error(f"[{task_id}] Graph construction failed: {str(e)}")
                build_logger.debug(traceback.format_exc())

                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)

                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"Build failed: {str(e)}",
                    error=traceback.format_exc()
                )


        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()

        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": "Graph build task started, query progress via /task/{task_id}"
            }
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    task = TaskManager().get_task(task_id)

    if not task:
        return jsonify({
            "success": False,
            "error": f"Task not found: {task_id}"
        }), 404

    return jsonify({
        "success": True,
        "data": task.to_dict()
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    tasks = TaskManager().list_tasks()

    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY is not configured"
            }), 500

        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        graph_data = builder.get_graph_data(graph_id)

        return jsonify({
            "success": True,
            "data": graph_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/delete/<graph_id>', methods=['DELETE'])
def delete_graph(graph_id: str):
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY is not configured"
            }), 500

        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)

        return jsonify({
            "success": True,
            "message": f"Graph deleted: {graph_id}"
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
