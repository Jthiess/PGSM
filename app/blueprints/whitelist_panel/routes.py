# ============================================================
# app/blueprints/whitelist_panel/routes.py — Whitelist System
# Public whitelist submission form and admin management UI.
# Syncs approved entries to enabled PGSM servers via the
# internal PGSM API after any approval change.
# ============================================================

import logging

import requests
from flask import (
    current_app, flash, redirect, render_template,
    request, url_for,
)

from app.auth import is_admin
from app.blueprints.whitelist_panel import bp
from app.services import panel_db

log = logging.getLogger(__name__)


# ------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------

def _pgsm_api_base() -> str:
    """Return the base URL for the internal PGSM API.

    Uses FLASK_PORT from config to build localhost URL so the
    whitelist sync reaches the running PGSM instance directly.
    """
    port = current_app.config.get('FLASK_PORT', 5000)
    return f'http://localhost:{port}'


def _sync_whitelist_to_pgsm_servers() -> None:
    """Push all approved whitelist entries to every enabled PGSM server.

    Fetches approved entries from panel_db, fetches enabled server IDs,
    then POSTs the whitelist JSON to /api/servers/{id}/whitelist for each.
    Errors per-server are logged but do not abort the remaining syncs.
    """
    entries = panel_db.get_approved_whitelist_entries()
    pgsm_servers = panel_db.get_pgsm_servers()
    enabled_servers = [s for s in pgsm_servers if s.get('enabled')]

    base_url = _pgsm_api_base()
    for server in enabled_servers:
        sid = server.get('server_id')
        try:
            resp = requests.post(
                f'{base_url}/api/servers/{sid}/whitelist',
                json=entries,
                timeout=15,
            )
            if resp.status_code != 200:
                log.error(
                    "Whitelist sync failed for server %s: %s %s",
                    sid, resp.status_code, resp.text[:200],
                )
        except Exception:
            log.exception("Whitelist sync request failed for server %s", sid)


# ------------------------------------------------------------
# Public routes
# ------------------------------------------------------------

@bp.route('/', methods=['GET', 'POST'])
def index():
    """Public whitelist submission form.

    GET:  Render the submission form.
    POST: Validate Minecraft username (UUID lookup via Mojang API),
          check Discord guild membership, enforce per-Discord request
          limit, insert pending entry, and send ntfy notification if
          configured.

    Flash messages:
        success — request submitted successfully.
        error   — validation failure or DB error.

    Returns:
        Redirect to /whitelist/ on POST; rendered whitelist_panel/index.html on GET.
    """
    if request.method == 'POST':
        username = (
            request.form.get('username')
            or request.form.get('mc_username')
            or ''
        ).strip()
        discord_username = (request.form.get('discord_username') or '').strip()

        if not username or not discord_username:
            flash('Both fields are required.', 'error')
            return redirect(url_for('whitelist_panel.index'))

        # --------------------------------------------------
        # Discord guild membership check
        # --------------------------------------------------
        if not panel_db.check_discord_guild_membership(discord_username):
            flash(
                "You don't appear to be in the server. "
                "Please make sure your Discord Username is correct.",
                'error',
            )
            return redirect(url_for('whitelist_panel.index'))

        # --------------------------------------------------
        # Per-Discord request limit
        # --------------------------------------------------
        max_per = current_app.config.get('MAX_REQUESTS_PER_DISCORD', 1)
        existing_count = panel_db.count_whitelist_requests_by_discord(discord_username)

        if existing_count >= max_per:
            if max_per == 1:
                flash(
                    'Sorry, you have already submitted a whitelist request. '
                    'You cannot submit another one.',
                    'error',
                )
            else:
                flash(
                    f'This Discord username has reached the limit of {max_per} whitelist requests.',
                    'error',
                )
            return redirect(url_for('whitelist_panel.index'))

        # --------------------------------------------------
        # Minecraft UUID lookup
        # --------------------------------------------------
        player_uuid = panel_db.lookup_minecraft_uuid(username)
        if not player_uuid:
            flash(f"Minecraft user '{username}' not found.", 'error')
            return redirect(url_for('whitelist_panel.index'))

        # --------------------------------------------------
        # Persist entry
        # --------------------------------------------------
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        try:
            panel_db.create_whitelist_entry({
                'username': username,
                'player_uuid': player_uuid,
                'discord_username': discord_username,
                'client_ip': client_ip,
            })
        except Exception:
            log.exception("Failed to insert whitelist entry")
            flash('Failed to submit request. Please try again later.', 'error')
            return redirect(url_for('whitelist_panel.index'))

        log.info("New whitelist request: %s (%s) from %s", username, player_uuid, client_ip)

        # --------------------------------------------------
        # Optional ntfy.sh notification
        # --------------------------------------------------
        ntfy_topic = current_app.config.get('NTFY_TOPIC')
        if ntfy_topic:
            try:
                requests.post(
                    f'https://ntfy.sh/{ntfy_topic}',
                    data=f'New Whitelist Request: {username}'.encode('utf-8'),
                    timeout=3,
                )
            except Exception:
                log.exception("ntfy notification failed")

        flash('Your request has been submitted for approval.', 'success')
        return redirect(url_for('whitelist_panel.index'))

    return render_template('whitelist_panel/index.html')


# ------------------------------------------------------------
# Admin routes
# ------------------------------------------------------------

@bp.route('/admin')
def admin():
    """Whitelist admin — list all entries and PGSM server sync targets.

    Requires full admin session; redirects to login if absent.

    Returns:
        Rendered whitelist_panel/admin.html with entries and servers.
    """
    if not is_admin():
        return redirect(url_for('admin_panel.login', next=request.path))

    entries = panel_db.get_whitelist_entries()
    pgsm_servers = panel_db.get_pgsm_servers()

    return render_template(
        'whitelist_panel/admin.html',
        entries=entries,
        servers=pgsm_servers,
    )


@bp.route('/admin/toggle/<int:id>', methods=['POST'])
def toggle(id: int):
    """Toggle the approved state for a whitelist entry, then sync.

    Args:
        id: The whitelist entry primary key.

    Returns:
        Redirect to /whitelist/admin.
    """
    if not is_admin():
        return redirect(url_for('admin_panel.login', next=request.path))

    try:
        panel_db.toggle_whitelist_approval(id)
        _sync_whitelist_to_pgsm_servers()
    except Exception:
        log.exception("Failed to toggle whitelist entry %s", id)
        flash('Failed to update approval status.', 'error')

    return redirect(url_for('whitelist_panel.admin'))


@bp.route('/admin/delete/<int:id>', methods=['POST'])
def delete_entry(id: int):
    """Delete a whitelist entry, then sync.

    Args:
        id: The whitelist entry primary key.

    Returns:
        Redirect to /whitelist/admin.
    """
    if not is_admin():
        return redirect(url_for('admin_panel.login', next=request.path))

    try:
        panel_db.delete_whitelist_entry(id)
        _sync_whitelist_to_pgsm_servers()
        flash(f'Request #{id} deleted.', 'success')
    except Exception:
        log.exception("Failed to delete whitelist entry %s", id)
        flash('Failed to delete entry.', 'error')

    return redirect(url_for('whitelist_panel.admin'))


@bp.route('/admin/servers', methods=['POST'])
def add_server():
    """Add a PGSM server to the whitelist sync target list.

    POST params:
        name (str): Human-readable server name.
        server_id (str): PGSM server UUID.

    Returns:
        Redirect to /whitelist/admin.
    """
    if not is_admin():
        return redirect(url_for('admin_panel.login', next=request.path))

    name = (request.form.get('name') or '').strip()
    server_id = (request.form.get('server_id') or '').strip()

    if name and server_id:
        try:
            panel_db.create_pgsm_server(name, server_id)
            flash(f"Added server '{name}'.", 'success')
        except Exception:
            log.exception("Failed to add pgsm_server")
            flash('Failed to add server.', 'error')
    else:
        flash('Both name and server ID are required.', 'error')

    return redirect(url_for('whitelist_panel.admin'))


@bp.route('/admin/servers/toggle/<int:id>', methods=['POST'])
def toggle_server(id: int):
    """Toggle the enabled flag for a PGSM whitelist sync target.

    After toggling, triggers a whitelist sync so the change takes effect
    immediately on the affected servers.

    Args:
        id: The pgsm_servers primary key.

    Returns:
        Redirect to /whitelist/admin.
    """
    if not is_admin():
        return redirect(url_for('admin_panel.login', next=request.path))

    try:
        panel_db.toggle_pgsm_server(id)
        _sync_whitelist_to_pgsm_servers()
    except Exception:
        log.exception("Failed to toggle pgsm_server %s", id)
        flash('Failed to toggle server.', 'error')

    return redirect(url_for('whitelist_panel.admin'))
