
import os
import warnings


warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request
from flask_cors import CORS

from .config.settings import Config
from .telemetry.logging_config import setup_logger, get_logger


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)


    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False


    logger = setup_logger('lightworld')


    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process

    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MicroWorld Backend starting...")
        logger.info("=" * 50)


    CORS(app, resources={r"/api/*": {"origins": "*"}})


    from .simulation.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("Registered simulation process cleanup handler")


    @app.before_request
    def log_request():
        logger = get_logger('lightworld.request')
        logger.debug(f"Request: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"Request body: {request.get_json(silent=True)}")

    @app.after_request
    def log_response(response):
        logger = get_logger('lightworld.request')
        logger.debug(f"Response: {response.status_code}")
        return response


    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')


    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MicroWorld Backend'}

    if should_log_startup:
        logger.info("MicroWorld Backend startup complete")

    return app
