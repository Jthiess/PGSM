import os
from flask import Flask
from app.extensions import db, socketio
from app.config import Config


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # Ensure instance folder exists
    os.makedirs(app.instance_path, exist_ok=True)

    # Init extensions
    db.init_app(app)
    socketio.init_app(app, async_mode='eventlet', cors_allowed_origins='*')

    # Register blueprints
    from app.blueprints.dashboard import bp as dashboard_bp
    from app.blueprints.servers import bp as servers_bp
    from app.blueprints.console import bp as console_bp
    from app.blueprints.files import bp as files_bp
    from app.blueprints.api import bp as api_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(servers_bp, url_prefix='/servers')
    app.register_blueprint(console_bp, url_prefix='/console')
    app.register_blueprint(files_bp, url_prefix='/files')
    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        db.create_all()
        _apply_migrations(db)

    return app


def _apply_migrations(db):
    """Applies lightweight schema migrations for columns added after initial release.

    Uses SQLite's ALTER TABLE ADD COLUMN. Safe to run on every startup — the
    INSERT OR IGNORE pattern means already-applied changes are skipped.
    """
    migrations = [
        # v2: extra_ports column for multi-port support
        "ALTER TABLE game_servers ADD COLUMN extra_ports JSON",
    ]

    with db.engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(db.text(stmt))
                conn.commit()
            except Exception:
                # Column likely already exists; ignore and continue
                pass
