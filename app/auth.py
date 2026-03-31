# ============================================================
# app/auth.py — Shared Authentication Helpers
# ============================================================

from functools import wraps

from flask import session, redirect, url_for, request


# ------------------------------------------------------------
# Session state helpers
# ------------------------------------------------------------

def is_admin() -> bool:
    """Return True if the current session has full admin privileges."""
    return bool(session.get('admin_auth'))


def is_server_user() -> bool:
    """Return True if the session is a server-scoped user (no full admin)."""
    return bool(session.get('server_user'))


def is_messages_user() -> bool:
    """Return True if the current session has messages-only access."""
    return bool(session.get('messages_auth'))


def get_current_username() -> str | None:
    """Return the username used for permission matching (raw login name), or None.

    Prefers ldap_raw_username (SAMAccountName / preferred_username) which is what
    admins enter when granting permissions. Falls back to ldap_username (display name)
    for legacy sessions.
    """
    return session.get('ldap_raw_username') or session.get('ldap_username')


def has_server_access(server_id: str) -> bool:
    """Return True if the current user has access to the given server.

    Full admins always have access. Server users must have an explicit
    ServerPermission row for this server, matched by raw login name or display name.
    """
    if is_admin():
        return True
    if not is_server_user():
        return False
    raw = session.get('ldap_raw_username')
    display = session.get('ldap_username')
    if not raw and not display:
        return False
    from app.models.server_permission import ServerPermission
    from sqlalchemy import or_
    conditions = []
    if raw:
        conditions.append(ServerPermission.username == raw)
    if display and display != raw:
        conditions.append(ServerPermission.username == display)
    return (
        ServerPermission.query.filter(
            ServerPermission.server_id == server_id,
            or_(*conditions),
        ).first() is not None
    )


# ------------------------------------------------------------
# Route decorators
# ------------------------------------------------------------

def require_admin(f):
    """Decorator: redirect to login if the request is not from an admin session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            return redirect(url_for('admin_panel.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def require_messages_access(f):
    """Decorator: allow access for full admin or messages-only sessions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (is_admin() or is_messages_user()):
            return redirect(url_for('admin_panel.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def require_management_access(f):
    """Decorator: allow access for full admin or server_user sessions."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (is_admin() or is_server_user()):
            return redirect(url_for('admin_panel.login', next=request.path))
        return f(*args, **kwargs)
    return decorated


def require_server_access(f):
    """Decorator: allow admin, or server_user who has a permission for this server.

    Reads `server_id` from the URL kwargs.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if is_admin():
            return f(*args, **kwargs)
        server_id = kwargs.get('server_id')
        if server_id and is_server_user() and has_server_access(server_id):
            return f(*args, **kwargs)
        return redirect(url_for('admin_panel.login', next=request.path))
    return decorated
