# ============================================================
# app/auth.py — Shared Authentication Helpers
# ============================================================

import hmac
from functools import wraps

from flask import session, redirect, url_for, request, current_app, jsonify


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
    names = _permission_match_names()
    if not names:
        return False
    from app.models.server_permission import ServerPermission
    return (
        ServerPermission.query.filter(
            ServerPermission.server_id == server_id,
            ServerPermission.username.in_(names),
        ).first() is not None
    )


def _permission_match_names() -> list[str]:
    """Usernames to match ServerPermission rows against.

    Permissions are granted by the immutable raw login name (sAMAccountName /
    preferred_username), so when that is present we match ONLY on it — display
    names are admin-editable and non-unique, so matching them would let one user
    inherit another's access via a colliding display name. The display name is
    used solely as a legacy fallback for sessions with no raw username.
    """
    raw = session.get('ldap_raw_username')
    display = session.get('ldap_username')
    if raw:
        return [raw]
    if display:
        return [display]
    return []


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


def get_permitted_server_ids() -> list[str]:
    from app.models.server_permission import ServerPermission
    names = _permission_match_names()
    if not names:
        return []
    perms = ServerPermission.query.filter(ServerPermission.username.in_(names)).all()
    return [p.server_id for p in perms]


def require_internal_token(f):
    """Decorator for internal-only API endpoints (e.g. the whitelist push).

    Authorizes ONLY when the request carries the correct internal token header —
    used by in-process server-to-self calls like the whitelist sync. There is
    deliberately no admin-session bypass: these endpoints are CSRF-exempt, so a
    cookie-based bypass would be forgeable cross-site. Returns 401 JSON
    otherwise.

    The token is compared in constant time and is never source-IP dependent,
    so it holds even though ProxyFix lets clients influence remote_addr.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = current_app.config.get('INTERNAL_API_TOKEN') or ''
        provided = request.headers.get('X-PGSM-Internal-Token', '')
        if expected and hmac.compare_digest(provided, expected):
            return f(*args, **kwargs)
        return jsonify({'error': 'Unauthorized'}), 401
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
