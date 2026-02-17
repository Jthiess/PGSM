from datetime import datetime
from app.extensions import db


class ProxmoxNode(db.Model):
    __tablename__ = 'proxmox_nodes'

    name = db.Column(db.String(64), primary_key=True)
    ip_address = db.Column(db.String(45), nullable=True)
    status = db.Column(db.String(16), default='unknown')  # online, offline, unknown
    last_seen = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<ProxmoxNode {self.name} ({self.status})>'
