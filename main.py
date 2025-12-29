import os
import flask
from proxmoxer import ProxmoxAPI
import dotenv

dotenv.load_dotenv()
FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
CACHE_TTL = int(os.getenv('CACHE_TTL', 30))
PROXMOX_USERNAME = os.getenv('Proxmox_Username')
PROXMOX_PASSWORD = os.getenv('Proxmox_Password')
PROXMOX_HOST = os.getenv('Proxmox_Host')
PROXMOX_PORT = os.getenv('Proxmox_Port')
