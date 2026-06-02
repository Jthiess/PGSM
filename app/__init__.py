import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from app.extensions import db, socketio, csrf
from app.config import Config

# Module-level OAuth instance; registered routes use oauth.authentik.*
oauth = OAuth()


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Configure application-wide logging before anything else so that all
    # subsequent startup steps (migrations, scheduler, etc.) are captured.
    _configure_logging(app)

    # Ensure instance folder and static image dirs exist
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'images', 'packicons'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'images', 'cards'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'images', 'headers'), exist_ok=True)

    # Init extensions
    db.init_app(app)
    csrf.init_app(app)

    # SocketIO CORS: never allow the wildcard '*' for authenticated, cookie-based
    # socket sessions. An empty list means same-origin only (the safe default).
    _cors_env = os.getenv('CORS_ORIGINS', '').strip()
    if _cors_env == '*':
        app.logger.warning("CORS_ORIGINS='*' is unsafe for cookie-auth sockets; falling back to same-origin only")
        _cors_origins = []
    else:
        _cors_origins = [o.strip() for o in _cors_env.split(',') if o.strip()]
    socketio.init_app(
        app,
        async_mode='eventlet',
        cors_allowed_origins=_cors_origins,
    )

    # Init OAuth (Authentik OIDC)
    oauth.init_app(app)
    if app.config.get('AUTHENTIK_CLIENT_ID'):
        _slug = app.config.get('AUTHENTIK_APP_SLUG', 'pgsm')
        _base = (app.config.get('AUTHENTIK_SERVER_URL') or '').rstrip('/')
        oauth.register(
            name='authentik',
            client_id=app.config['AUTHENTIK_CLIENT_ID'],
            client_secret=app.config['AUTHENTIK_CLIENT_SECRET'],
            server_metadata_url=f'{_base}/application/o/{_slug}/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid profile email'},
        )

    # Register PGSM management blueprints (all require admin auth)
    from app.blueprints.dashboard import bp as dashboard_bp
    from app.blueprints.servers import bp as servers_bp
    from app.blueprints.console import bp as console_bp
    from app.blueprints.files import bp as files_bp
    from app.blueprints.api import bp as api_bp

    app.register_blueprint(dashboard_bp, url_prefix='/manage')
    app.register_blueprint(servers_bp, url_prefix='/manage/servers')
    app.register_blueprint(console_bp, url_prefix='/manage/console')
    app.register_blueprint(files_bp, url_prefix='/manage/files')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Register public-facing Game Panel blueprints
    from app.blueprints.panel.routes import bp as panel_bp
    from app.blueprints.admin_panel.routes import bp as admin_panel_bp
    from app.blueprints.whitelist_panel.routes import bp as whitelist_panel_bp

    app.register_blueprint(panel_bp)
    app.register_blueprint(admin_panel_bp, url_prefix='/admin')
    app.register_blueprint(whitelist_panel_bp, url_prefix='/whitelist')

    with app.app_context():
        from app.models import GameServer, ServerPermission  # noqa: F401 — ensure tables are registered
        db.create_all()
        _apply_migrations(db)
        _migrate_extra_ports_format()

    # Initialize panel PostgreSQL tables (graceful — app works without panel DB)
    try:
        with app.app_context():
            from app.services.panel_db import init_db_tables
            init_db_tables()
    except Exception as e:
        app.logger.warning("Panel DB init skipped (PostgreSQL may not be configured): %s", e)

    # Jinja2 global: resolve card/header image path with PNG support
    _IMAGE_EXTS = ('png', 'jpg', 'jpeg', 'webp')

    def _resolve_static_image(subdir: str, name: str) -> str:
        base = os.path.join(app.root_path, 'static', 'images', subdir)
        for ext in _IMAGE_EXTS:
            if os.path.exists(os.path.join(base, f'{name}.{ext}')):
                return f'images/{subdir}/{name}.{ext}'
        return f'images/{subdir}/default.jpg'

    app.jinja_env.globals['card_image_path'] = lambda game: _resolve_static_image('cards', game)
    app.jinja_env.globals['header_image_path'] = lambda game: _resolve_static_image('headers', game)
    app.jinja_env.globals['authentik_enabled'] = bool(app.config.get('AUTHENTIK_CLIENT_ID'))

    _register_security_headers(app)

    # Start background scheduler for panel jobs
    _start_scheduler(app)

    return app


def _register_security_headers(app: Flask) -> None:
    """Adds baseline security response headers to every response.

    CSP is intentionally limited to `frame-ancestors 'none'` (clickjacking
    protection) so it does not break the app's existing inline scripts/styles;
    tighten `Content-Security-Policy` further once inline JS is externalised.
    HSTS is only emitted when the session cookie is marked Secure (i.e. the app
    is served over HTTPS) to avoid breaking plain-HTTP local development.
    """
    hsts_enabled = bool(app.config.get('SESSION_COOKIE_SECURE'))

    @app.after_request
    def _set_security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Content-Security-Policy', "frame-ancestors 'none'")
        if hsts_enabled:
            response.headers.setdefault(
                'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
            )
        return response


def _configure_logging(app: Flask) -> None:
    """Configures Python's root logger for the PGSM application.

    Sets up two handlers:
      - StreamHandler (console): always active, useful for Docker / systemd logs.
      - RotatingFileHandler (file): writes to LOG_FILE; disabled when LOG_FILE is
        empty or falsy.

    Using the root logger (rather than app.logger alone) ensures that service
    modules using ``logging.getLogger(__name__)`` inherit the same level and
    handlers without needing a reference to the Flask app object.

    Config keys (from config.py / .env):
        LOG_LEVEL        — Python level name, e.g. 'DEBUG' or 'INFO' (default INFO).
        LOG_FILE         — Rotating log file path (default 'logs/pgsm.log').
        LOG_MAX_BYTES    — Max size per log file before rotation (default 10 MB).
        LOG_BACKUP_COUNT — Number of rotated files to retain (default 5).
    """
    log_level_name = app.config.get('LOG_LEVEL', 'INFO')
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Shared formatter: timestamp, level, module path, message
    fmt = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(log_level)

    handlers = [console_handler]

    # --- Rotating file handler (optional) ---
    log_file = app.config.get('LOG_FILE', 'logs/pgsm.log')
    if log_file:
        # Create the logs directory relative to the project root (one level up
        # from the app package) so the file ends up at <project>/logs/pgsm.log.
        if not os.path.isabs(log_file):
            project_root = os.path.dirname(app.root_path)
            log_file = os.path.join(project_root, log_file)
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=app.config.get('LOG_MAX_BYTES', 10 * 1024 * 1024),
            backupCount=app.config.get('LOG_BACKUP_COUNT', 5),
            encoding='utf-8',
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    # Apply to the root logger so all ``logging.getLogger(__name__)`` calls in
    # service modules inherit this configuration automatically.
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Remove any default handlers installed before our factory ran (e.g.
    # Werkzeug's default StreamHandler) to avoid duplicate log lines.
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)

    # Suppress noisy third-party loggers that flood the output at INFO level.
    logging.getLogger('paramiko.transport').setLevel(logging.WARNING)

    app.logger.info(
        'PGSM logging initialised — level=%s, file=%s',
        log_level_name,
        log_file if log_file else 'disabled',
    )


def _start_scheduler(app):
    """Start APScheduler for panel background jobs (server status updates)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        def _make_job(func, _app):
            def job():
                with _app.app_context():
                    func()
            return job

        scheduler = BackgroundScheduler(daemon=True)

        try:
            from app.services.panel_db import update_all_server_statuses
            scheduler.add_job(
                _make_job(update_all_server_statuses, app),
                'interval', minutes=10, id='panel_server_status',
            )
        except Exception as e:
            app.logger.warning("Could not add server status job: %s", e)

        scheduler.start()
    except Exception as e:
        app.logger.warning("APScheduler not started: %s", e)


def _migrate_extra_ports_format():
    """One-time data migration: convert extra_ports from [int, ...] to
    [{"port": int, "protocol": "tcp"}, ...] format.

    Safe to run every startup — already-migrated entries (dicts) are left alone.
    """
    from app.models.server import GameServer
    from sqlalchemy.orm.attributes import flag_modified

    changed = False
    for server in GameServer.query.all():
        if not server.extra_ports:
            continue
        new_ports = []
        needs_update = False
        for entry in server.extra_ports:
            if isinstance(entry, int):
                new_ports.append({'port': entry, 'protocol': 'tcp'})
                needs_update = True
            else:
                new_ports.append(entry)
        if needs_update:
            server.extra_ports = new_ports
            flag_modified(server, 'extra_ports')
            changed = True
    if changed:
        db.session.commit()


def _apply_migrations(db):
    """Applies lightweight schema migrations for columns added after initial release.

    Uses SQLite's ALTER TABLE ADD COLUMN. Safe to run on every startup — the
    INSERT OR IGNORE pattern means already-applied changes are skipped.
    """
    migrations = [
        # v2: extra_ports column for multi-port support
        "ALTER TABLE game_servers ADD COLUMN extra_ports JSON",
        # v3: ha_enabled column for Proxmox HA registration
        "ALTER TABLE game_servers ADD COLUMN ha_enabled BOOLEAN DEFAULT 0",
        # v4: java version override (NULL = auto)
        "ALTER TABLE game_servers ADD COLUMN java_version_override INTEGER",
        # v5: custom startup command override (NULL = use script default)
        "ALTER TABLE game_servers ADD COLUMN custom_startup_command VARCHAR(512)",
        # v6: Fabric loader version (NULL = latest)
        "ALTER TABLE game_servers ADD COLUMN fabric_loader_version VARCHAR(32)",
        # v7: Forge version (NULL = recommended for MC version)
        "ALTER TABLE game_servers ADD COLUMN forge_version VARCHAR(32)",
        # v8: Import archive URL (for import server type)
        "ALTER TABLE game_servers ADD COLUMN import_archive_url VARCHAR(512)",
        # v9: Provisioning log (stdout/stderr from install script; error details)
        "ALTER TABLE game_servers ADD COLUMN provision_log TEXT",
    ]

    with db.engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(db.text(stmt))
                conn.commit()
            except Exception:
                # Column likely already exists; ignore and continue
                pass
