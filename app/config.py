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

    # Nginx
    NGINX_CONF_DIR = os.getenv('Nginx_Conf_Dir', '/etc/nginx/conf.d')

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
