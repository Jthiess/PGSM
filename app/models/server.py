import uuid
from datetime import datetime
from app.extensions import db


def _resolve_java_version(mc_version: str) -> int:
    """Maps a Minecraft version string to the required Java major version.

    Minecraft versions follow the pattern: 1.<minor>[.<patch>]
    Examples: '1.16.5', '1.17', '1.20.6', '1.21.4'
    """
    parts = mc_version.split('.')
    try:
        # Parts: ['1', '<minor>', '<patch>']  (patch is optional)
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return 21  # Safe default
    if minor < 17:
        return 8
    elif minor == 17:
        return 16
    elif minor < 20 or (minor == 20 and patch < 6):
        return 17
    else:
        return 21


class GameServer(db.Model):
    __tablename__ = 'game_servers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(128), nullable=False)

    # Identity
    game_code = db.Column(db.String(16), nullable=False)    # MCJAV, MCBED
    server_type = db.Column(db.String(32), nullable=False)  # vanilla, paper, fabric, forge, bedrock
    game_version = db.Column(db.String(32), nullable=False)

    # Proxmox / Container
    ct_id = db.Column(db.Integer, nullable=False, unique=True)
    proxmox_node = db.Column(db.String(64), nullable=False)
    hostname = db.Column(db.String(128), nullable=False)    # PGSM-MCJAV-<PARTIAL_UUID>
    ip_address = db.Column(db.String(45), nullable=False)   # IPv4

    # Resources
    disk_gb = db.Column(db.Integer, nullable=False)
    cores = db.Column(db.Integer, nullable=False)
    memory_mb = db.Column(db.Integer, nullable=False)

    # Networking
    game_port = db.Column(db.Integer, nullable=False, default=25565)

    # Minecraft settings
    motd = db.Column(db.String(256), nullable=True)
    render_distance = db.Column(db.Integer, default=10)
    spawn_protection = db.Column(db.Integer, default=0)
    difficulty = db.Column(db.String(16), default='normal')
    hardcore = db.Column(db.Boolean, default=False)

    # Lifecycle
    status = db.Column(db.String(32), default='creating')  # creating, stopped, running, error
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<GameServer {self.name} (CT {self.ct_id})>'

    @property
    def partial_uuid(self):
        return self.id[:8].upper()

    @property
    def java_version(self):
        """Required Java major version for Minecraft Java servers."""
        if self.game_code != 'MCJAV':
            return None
        return _resolve_java_version(self.game_version)

    @property
    def status_badge_class(self):
        return {
            'running': 'badge-running',
            'stopped': 'badge-stopped',
            'creating': 'badge-creating',
            'error': 'badge-error',
        }.get(self.status, 'badge-unknown')
