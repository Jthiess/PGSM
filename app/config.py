import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv('Secret_Key', os.urandom(24).hex())
    FLASK_PORT = int(os.getenv('Flask_Port', 5000))

    # Proxmox
    PROXMOX_HOST = os.getenv('Proxmox_Host')
    PROXMOX_PORT = int(os.getenv('Proxmox_Port', 8006))
    PROXMOX_USERNAME = os.getenv('Proxmox_Username')
    PROXMOX_PASSWORD = os.getenv('Proxmox_Password')

    # Database
    SQLALCHEMY_DATABASE_URI = 'sqlite:///pgsm.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

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
    # ----------------------------------------------------------
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')
    MESSAGES_PASSWORD = os.getenv('MESSAGES_PASSWORD')

    # ----------------------------------------------------------
    # LDAP / LDAPS Authentication
    # Set LDAP_HOST to enable LDAP auth; leave unset to fall back
    # to password-only login (ADMIN_PASSWORD / MESSAGES_PASSWORD).
    # ----------------------------------------------------------
    LDAP_HOST = os.getenv('LDAP_HOST')                          # None = LDAP disabled
    LDAP_PORT = int(os.getenv('LDAP_PORT', 636))
    LDAP_USE_SSL = os.getenv('LDAP_USE_SSL', 'true').lower() == 'true'
    LDAP_TLS_VALIDATE = os.getenv('LDAP_TLS_VALIDATE', 'false').lower() == 'true'  # false = accept self-signed
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
