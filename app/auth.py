# ============================================================
# app/auth.py — Shared Authentication Helpers
# Provides session-based admin auth guards used by both the
# Game-Panel admin blueprint and all PGSM management routes.
# ============================================================

from functools import wraps

from flask import session, redirect, url_for, request


# ------------------------------------------------------------
# Session state helpers
# ------------------------------------------------------------

def is_admin() -> bool:
    """Return True if the current session has full admin privileges."""
    return bool(session.get('admin_auth'))


def is_messages_user() -> bool:
    """Return True if the current session has messages-only access."""
    return bool(session.get('messages_auth'))


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
