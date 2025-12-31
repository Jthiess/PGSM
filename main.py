import os
import flask
from proxmoxer import ProxmoxAPI
import dotenv
import requests

dotenv.load_dotenv()
FLASK_PORT = int(os.getenv('Flask_Port', 5000))
PROXMOX_USERNAME = os.getenv('Proxmox_Username')
PROXMOX_PASSWORD = os.getenv('Proxmox_Password')
PROXMOX_HOST = os.getenv('Proxmox_Host')
PROXMOX_PORT = int(os.getenv('Proxmox_Port', 8006))
MINECRAFT_MANIFEST_URL = os.getenv('Minecraft_Manifest_Url', 'https://piston-meta.mojang.com/mc/game/version_manifest.json')


