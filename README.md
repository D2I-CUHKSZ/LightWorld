<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&height=220&text=MicroWorld&fontAlign=50&fontAlignY=38&desc=Multi-modal%20event%20analysis%20and%20social%20simulation&descAlign=50&descAlignY=60&fontColor=ffffff&color=0:08111f,45:0f766e,100:38bdf8" width="100%" alt="MicroWorld banner" />

# MicroWorld

**A lightweight system for turning event materials into structured graphs, agent populations, and inspectable social simulations.**

[![Project Site](https://img.shields.io/badge/Project%20Site-GitHub%20Pages-0f766e?style=for-the-badge&logo=githubpages&logoColor=white)](https://d2i-cuhksz.github.io/MicroWorld/)
[![Python](https://img.shields.io/badge/Python-3.11%2B-2563eb?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/badge/License-AGPL--3.0-111827?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)

[Project Site](https://d2i-cuhksz.github.io/MicroWorld/) ·
[Architecture](https://d2i-cuhksz.github.io/MicroWorld/architecture.html) ·
[User Guide](https://d2i-cuhksz.github.io/MicroWorld/guide.html) ·
[Examples](https://d2i-cuhksz.github.io/MicroWorld/examples.html)

</div>

MicroWorld starts from raw event material: documents, images, videos, and graph-ready context. It builds an event graph, derives platform-facing agent profiles, runs a multi-agent discussion process, and keeps the intermediate artifacts available for inspection after the run.

It is built for cases where the final report is not enough on its own. The project keeps the graph, prompts, simulation inputs, action traces, memory states, and report outputs tied to the same run.

## System Architecture

<p align="center">
  <img src="Architecture.png" width="100%" alt="MicroWorld system architecture" />
</p>

MicroWorld is organized around four stages:

1. **Ingestion and graph build**: convert event materials into ontology, entities, and relations.
2. **Simulation preparation**: derive topic keywords, cluster topology, and generate platform profiles.
3. **Runtime execution**: run the topology-aware simulation with directional influence and lightweight memory.
4. **Reporting and inspection**: collect logs, traces, configs, and reports from the same run.

## Key Contributions

- **Multi-modal event ingestion** for text, image, and video inputs, without forcing the pipeline into a text-only workflow.
- **Two topology clustering modes**: a threshold-based mode and an LLM-keyword-driven mode.
- **PPR-guided directional influence** for agent activation and information flow.
- **Lightweight memory** that preserves useful state without requiring full-history replay.
- **Inspectable outputs** across graph building, simulation preparation, runtime traces, and reporting.

## Example: LK-99

The public example uses the LK-99 room-temperature-superconductor news cycle. It is a good fit for the project because it contains:

- mixed evidence types, including long-form text and videos,
- a clear shift from early excitement to later scrutiny,
- visible changes in narrative focus, participants, and discussion structure.

<p align="center">
  <img src="docs/assets/lk99/pic1.png" width="48%" alt="LK-99 demonstration clip" />
  <img src="docs/assets/lk99/pic3.png" width="48%" alt="LK-99 explanatory illustration" />
</p>
<p align="center">
  <img src="docs/assets/lk99/pic2.png" width="48%" alt="LK-99 annotated frame" />
  <img src="docs/assets/lk99/pic4.png" width="48%" alt="LK-99 materials figure strip" />
</p>

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/d2i-cuhksz/MicroWorld.git
cd MicroWorld
```

### 2. Prerequisites

Required:

- Python 3.11+
- `uv`

Recommended for video inputs:

- `ffmpeg`
- `ffprobe`

If `ffmpeg` and `ffprobe` are not on your `PATH`, set `MULTIMODAL_FFMPEG_PATH` and `MULTIMODAL_FFPROBE_PATH` in `.env`.

### 3. Configure environment variables

```bash
cp .env.example .env
```

Set at least:

```bash
LLM_API_KEY=your_key
ZEP_API_KEY=your_key
```

Common defaults:

```bash
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
MULTIMODAL_AUDIO_API_KEY=
MULTIMODAL_AUDIO_BASE_URL=
```

### 4. Install dependencies

```bash
uv sync
```

### 5. Start the API service

```bash
uv run microworld-api
```

The backend uses `FLASK_HOST`, `FLASK_PORT`, and `FLASK_DEBUG` from the environment. The default backend port is `5001`.

### 6. Create a run config

```bash
cp configs/full_run/full_run.template.json /tmp/microworld-run.json
```

Minimal example:

```json
{
  "project_name": "My MicroWorld Run",
  "graph_name": "My MicroWorld Graph",
  "simulation_requirement": "Build entities, relations, and a two-platform social simulation from the input materials.",
  "files": [
    "/abs/path/to/event.md",
    "/abs/path/to/video.mp4"
  ],
  "pipeline": {
    "chunk_size": 500,
    "chunk_overlap": 50,
    "batch_size": 3
  },
  "simulation": {
    "enable_twitter": true,
    "enable_reddit": true
  },
  "report": {
    "generate": false
  }
}
```

You can also leave `files` empty and provide `files_from`, with one local path per line.

### 7. Run the full pipeline

```bash
uv run microworld-full-run \
  --config /abs/path/to/microworld-run.json
```

To avoid the interactive clustering choice:

```bash
uv run microworld-full-run \
  --config /abs/path/to/microworld-run.json \
  --cluster-method threshold
```

Generated data is written under:

```text
data/generated/
output/simulations/
output/reports/
runs/
```

## Main Commands

```bash
uv run microworld-api
uv run microworld-local-pipeline --config /abs/path/to/local_pipeline.json
uv run microworld-parallel-sim --config /abs/path/to/simulation_config.json
uv run microworld-full-run --config /abs/path/to/microworld-run.json
```

## Outputs

A typical run exposes artifacts from several stages:

- **Project build**: extracted text, parsed multimodal content, source manifests, ontology output.
- **Simulation preparation**: entity prompts, graph snapshots, social relation graph, simulation config.
- **Runtime execution**: platform profiles, action logs, memory states, topology traces.
- **Reporting**: report outline, full report, agent logs, console logs.

## Repository Structure

```text
MicroWorld/
  pyproject.toml
  src/
    microworld/
      api/
      application/
      cli/
      config/
      domain/
      graph/
      ingestion/
      infrastructure/
      memory/
      reporting/
      simulation/
      storage/
      telemetry/
      tools/
  configs/
    full_run/
    simulation/
  data/
    generated/
  docs/
  tests/
```

## Development

```bash
uv sync --group dev
uv run pytest
```

## License

MicroWorld is released under the [GNU Affero General Public License v3.0](LICENSE).

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&height=120&section=footer&color=0:38bdf8,50:0f766e,100:08111f" width="100%" alt="MicroWorld footer" />

</div>
