import os
from dotenv import load_dotenv

load_dotenv()


def _stable_random_secret(filename: str, env_names: tuple[str, ...]) -> str:
    """Return a stable random secret, preferring an env var, else a persisted file.

    Accepts multiple env var names (the first non-empty wins) so both the
    conventional spelling and any legacy spelling are honoured. When no env var
    is set, a 32-byte random value is generated once and persisted under
    instance/ with owner-only permissions so it survives restarts/workers.
    """
    for name in env_names:
        value = os.getenv(name)
        if value:
            return value
    key_file = os.path.join(os.path.dirname(__file__), '..', 'instance', filename)
    key_file = os.path.abspath(key_file)
    try:
        with open(key_file, 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        pass
    value = os.urandom(32).hex()
    os.makedirs(os.path.dirname(key_file), exist_ok=True)
    with open(key_file, 'w') as f:
        f.write(value)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return value


def _stable_secret_key() -> str:
    # Accept the conventional SECRET_KEY spelling as well as the legacy
    # `Secret_Key` used by older .env files.
    return _stable_random_secret('.flask_secret', ('SECRET_KEY', 'Secret_Key'))


class Config:
    SECRET_KEY = _stable_secret_key()
    FLASK_PORT = int(os.getenv('Flask_Port', 5000))

    # ----------------------------------------------------------
    # Session / cookie hardening
    # SESSION_COOKIE_SECURE defaults ON; set SESSION_COOKIE_SECURE=false in .env
    # only for local plain-HTTP development.
    # ----------------------------------------------------------
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
    PERMANENT_SESSION_LIFETIME = int(os.getenv('SESSION_LIFETIME_SECONDS', 12 * 60 * 60))
    # Flask-WTF CSRF: tokens do not expire mid-session (avoids spurious failures
    # on long-lived admin pages); protection itself stays on.
    WTF_CSRF_TIME_LIMIT = None

    # Token guarding internal-only API endpoints (e.g. the whitelist push the
    # panel makes to itself over localhost). An INDEPENDENT random secret —
    # deliberately NOT derived from SECRET_KEY, so a SECRET_KEY disclosure does
    # not also hand an attacker the internal token. Stable across
    # restarts/workers via a persisted file; override via env if the panel and
    # PGSM API run as separate deployments.
    INTERNAL_API_TOKEN = _stable_random_secret('.internal_token', ('INTERNAL_API_TOKEN',))

    # Proxmox
    PROXMOX_HOST = os.getenv('Proxmox_Host')
    PROXMOX_PORT = int(os.getenv('Proxmox_Port', 8006))
    PROXMOX_USERNAME = os.getenv('Proxmox_Username')
    PROXMOX_PASSWORD = os.getenv('Proxmox_Password')
    # Optional API token auth (preferred over the root password). When both
    # token id and secret are set they take precedence over PROXMOX_PASSWORD.
    PROXMOX_TOKEN_NAME = os.getenv('Proxmox_Token_Name')
    PROXMOX_TOKEN_VALUE = os.getenv('Proxmox_Token_Value')
    # TLS verification ON by default; set Proxmox_Verify_SSL=false ONLY for a
    # self-signed cert on a trusted management network.
    PROXMOX_VERIFY_SSL = os.getenv('Proxmox_Verify_SSL', 'true').lower() == 'true'
    PROXMOX_TIMEOUT = int(os.getenv('Proxmox_Timeout', 30))

    # Database
    SQLALCHEMY_DATABASE_URI = 'sqlite:///pgsm.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_MB', 512)) * 1024 * 1024

    # Minecraft
    MINECRAFT_MANIFEST_URL = os.getenv(
        'Minecraft_Manifest_Url',
        'https://piston-meta.mojang.com/mc/game/version_manifest.json'
    )

    # SSH keypair
    SSH_KEY_PATH = os.getenv('SSH_Key_Path', 'keys/pgsm_rsa')

    # Nginx — must be included inside the stream {} block in nginx.conf:
    #   stream { include /etc/nginx/stream.d/*.conf; }
    NGINX_CONF_DIR = os.getenv('Nginx_Conf_Dir', '/etc/nginx/stream.d')

    # PGSM VLAN network
    PGSM_VLAN_SUBNET = os.getenv('PGSM_VLAN_Subnet', '172.16.0.0/24')
    PGSM_VLAN_GATEWAY = os.getenv('PGSM_VLAN_Gateway', '172.16.0.1')
    # First IP PGSM is allowed to assign to game server containers.
    # IPs below this (e.g. Proxmox nodes, router) are left alone.
    PGSM_VLAN_IP_START = os.getenv('PGSM_VLAN_IP_Start', '172.16.0.10')

    # Proxmox LXC template (must exist in Proxmox storage)
    PGSM_LXC_TEMPLATE = os.getenv(
        'PGSM_LXC_Template',
        'kestrel:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst'
    )

    # ----------------------------------------------------------
    # Game-Panel: Admin auth (password fallback)
    # Used only when LDAP_HOST is not configured.
    # NO DEFAULT: if neither LDAP/Authentik nor an explicit ADMIN_PASSWORD is
    # configured, password login is DISABLED (fail closed) rather than shipping
    # a guessable default credential.
    # ----------------------------------------------------------
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD') or None
    MESSAGES_PASSWORD = os.getenv('MESSAGES_PASSWORD') or None

    # ----------------------------------------------------------
    # LDAP / LDAPS Authentication
    # Set LDAP_HOST to enable LDAP auth; leave unset to fall back
    # to password-only login (ADMIN_PASSWORD / MESSAGES_PASSWORD).
    # ----------------------------------------------------------
    LDAP_HOST = os.getenv('LDAP_HOST')                          # None = LDAP disabled
    LDAP_PORT = int(os.getenv('LDAP_PORT', 636))
    LDAP_USE_SSL = os.getenv('LDAP_USE_SSL', 'true').lower() == 'true'
    LDAP_TLS_VALIDATE = os.getenv('LDAP_TLS_VALIDATE', 'true').lower() == 'true'  # set false ONLY to accept self-signed
    LDAP_CA_CERT_FILE = os.getenv('LDAP_CA_CERT_FILE')         # path to CA bundle, optional
    LDAP_BIND_DN = os.getenv('LDAP_BIND_DN')                   # service account DN
    LDAP_BIND_PASSWORD = os.getenv('LDAP_BIND_PASSWORD')       # service account password
    LDAP_BASE_DN = os.getenv('LDAP_BASE_DN')                   # e.g. dc=example,dc=com
    LDAP_USER_SEARCH_BASE = os.getenv('LDAP_USER_SEARCH_BASE') # e.g. ou=users,dc=example,dc=com
    LDAP_USER_SEARCH_FILTER = os.getenv('LDAP_USER_SEARCH_FILTER', '(sAMAccountName={username})')
    LDAP_GROUP_ADMIN = os.getenv('LDAP_GROUP_ADMIN')            # DN of admin group (AL-5)
    LDAP_GROUP_MESSAGES = os.getenv('LDAP_GROUP_MESSAGES')     # DN of messages group (AL-4)
    LDAP_ATTR_DISCORD_UUID = os.getenv('LDAP_ATTR_DISCORD_UUID', 'extensionAttribute1')
    LDAP_ATTR_MINECRAFT_UUID = os.getenv('LDAP_ATTR_MINECRAFT_UUID', 'extensionAttribute2')

    # ----------------------------------------------------------
    # Authentik OIDC Authentication
    # Set AUTHENTIK_CLIENT_ID to enable Authentik login.
    # When set, replaces direct LDAP login; LDAP is still used
    # for AD group lookup (query_user) if LDAP_HOST is set.
    # AUTHENTIK_APP_SLUG: the Authentik application slug (used
    # to build the OIDC metadata URL).
    # ----------------------------------------------------------
    AUTHENTIK_CLIENT_ID = os.getenv('AUTHENTIK_CLIENT_ID')
    AUTHENTIK_CLIENT_SECRET = os.getenv('AUTHENTIK_CLIENT_SECRET')
    AUTHENTIK_SERVER_URL = os.getenv('AUTHENTIK_SERVER_URL')   # e.g. https://auth.example.com
    AUTHENTIK_APP_SLUG = os.getenv('AUTHENTIK_APP_SLUG', 'pgsm')

    # ----------------------------------------------------------
    # Game-Panel: PostgreSQL (public panel DB)
    # ----------------------------------------------------------
    PANEL_DB_HOST = os.getenv('DB_HOST', 'localhost')
    PANEL_DB_PORT = int(os.getenv('DB_PORT', 5432))
    PANEL_DB_NAME = os.getenv('DB_NAME', 'gamepanel')
    PANEL_DB_USER = os.getenv('DB_USER', 'postgres')
    PANEL_DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    PANEL_DB_SCHEMA = os.getenv('DB_SCHEMA', 'public')
    PANEL_DB_SERVERS_SCHEMA = os.getenv('DB_SERVERS_SCHEMA', 'servers')

    # ----------------------------------------------------------
    # Game-Panel: Optional integrations
    # ----------------------------------------------------------
    NTFY_TOPIC = os.getenv('NTFY_TOPIC')
    DISCORD_GUILD_ID = os.getenv('DISCORD_GUILD_ID')
    DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    MAX_REQUESTS_PER_DISCORD = int(os.getenv('MAX_REQUESTS_PER_DISCORD', 1))

    # ----------------------------------------------------------
    # Game-Panel: Data file paths
    # ----------------------------------------------------------
    PANEL_DATA_DIR = os.getenv('PANEL_DATA_DIR', 'data')
    PANEL_PACK_ICONS_DIR = os.getenv('PANEL_PACK_ICONS_DIR', 'app/static/images/packicons')

    # ----------------------------------------------------------
    # Game-Panel: Whitelist sync interval (minutes)
    # ----------------------------------------------------------
    WHITELIST_SYNC_INTERVAL = int(os.getenv('WHITELIST_SYNC_INTERVAL', 60))

    # ── Server Creation Defaults ───────────────────────────────────────────
    # These values are pre-filled in the create server wizard.
    # Override any of them in your .env file.
    SERVER_DEFAULT_DISK_GB       = int(os.getenv('Server_Default_Disk_GB', 20))
    SERVER_DEFAULT_CORES         = int(os.getenv('Server_Default_Cores', 8))
    SERVER_DEFAULT_MEMORY_MB     = int(os.getenv('Server_Default_Memory_MB', 4096))
    SERVER_DEFAULT_GAME_PORT     = int(os.getenv('Server_Default_Game_Port', 25565))
    SERVER_DEFAULT_RENDER_DIST   = int(os.getenv('Server_Default_Render_Distance', 12))
    SERVER_DEFAULT_SPAWN_PROT    = int(os.getenv('Server_Default_Spawn_Protection', 0))
    SERVER_DEFAULT_DIFFICULTY    = os.getenv('Server_Default_Difficulty', 'normal')
    SERVER_DEFAULT_SERVER_TYPE   = os.getenv('Server_Default_Server_Type', 'vanilla')
    SERVER_DEFAULT_HA_ENABLED    = os.getenv('Server_Default_HA_Enabled', 'true').lower() == 'true'

    # ----------------------------------------------------------
    # Backups: local directory to store backup archives
    # ----------------------------------------------------------
    BACKUP_PATH = os.getenv('BACKUP_PATH', '/mnt/pgsm-backups')

    # ----------------------------------------------------------
    # Logging
    # LOG_LEVEL: Python logging level name (DEBUG, INFO, WARNING, ERROR).
    # LOG_FILE:  Path to the rotating log file. Set to empty string to
    #            disable file logging (console only).
    # LOG_MAX_BYTES / LOG_BACKUP_COUNT: RotatingFileHandler parameters.
    # ----------------------------------------------------------
    LOG_LEVEL        = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FILE         = os.getenv('LOG_FILE', 'logs/pgsm.log')
    LOG_MAX_BYTES    = int(os.getenv('LOG_MAX_BYTES', 10 * 1024 * 1024))  # 10 MB
    LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', 5))
