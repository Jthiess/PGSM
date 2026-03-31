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
    """Return the display name stored in the session, or None."""
    return session.get('ldap_username')


def has_server_access(server_id: str) -> bool:
    """Return True if the current user has access to the given server.

    Full admins always have access. Server users must have an explicit
    ServerPermission row for this server.
    """
    if is_admin():
        return True
    if not is_server_user():
        return False
    username = get_current_username()
    if not username:
        return False
    from app.models.server_permission import ServerPermission
    return (
        ServerPermission.query.filter_by(server_id=server_id, username=username).first()
        is not None
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
