import uuid
from datetime import datetime
from app.extensions import db


class ServerPermission(db.Model):
    __tablename__ = 'server_permissions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    server_id = db.Column(db.String(36), db.ForeignKey('game_servers.id', ondelete='CASCADE'), nullable=False)
    username = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('server_id', 'username', name='uq_server_permission'),)

    server = db.relationship(
        'GameServer',
        backref=db.backref('permissions', lazy='dynamic', cascade='all, delete-orphan'),
    )
