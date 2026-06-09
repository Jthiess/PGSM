# ============================================================
# app/blueprints/panel/routes.py — Public-Facing Game Panel
# Serves the main entry point: server cards, rules page, and
# the JSON API used by the frontend card renderer.
# ============================================================

import logging
import re

from markupsafe import escape
from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.blueprints.panel import bp
from app.services import panel_db

log = logging.getLogger(__name__)

_MC_USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{3,16}$')


# ------------------------------------------------------------
# Public routes
# ------------------------------------------------------------

@bp.route('/')
def index():
    """Homepage: renders active and archived server cards.

    Loads server data from PostgreSQL via panel_db and selects
    a random rotating message from messages.txt.

    If authenticated via Authentik, the corresponding game account
    entry is fetched and passed to the template so the profile panel
    can be pre-loaded.

    Returns:
        Rendered panel/index.html template.
    """
    active_servers = panel_db.get_active_servers()
    archived_servers = panel_db.get_archived_servers()
    random_message = panel_db.get_random_message()

    authentik_username = session.get('ldap_raw_username')
    logged_in = bool(
        session.get('admin_auth')
        or session.get('messages_auth')
        or session.get('user_auth')
        or session.get('server_user')
    )
    display_name = session.get('ldap_username') or authentik_username
    current_user_profile = None

    if authentik_username:
        entry = panel_db.get_whitelist_entry_by_authentik_username(authentik_username)
        if entry:
            current_user_profile = {
                'username': entry['username'],
                'player_uuid': entry['player_uuid'],
                'approved': entry['approved'],
                'strikes': entry.get('strikes', 0),
            }

    return render_template(
        'panel/index.html',
        servers=active_servers,
        archived=archived_servers,
        message=random_message,
        logged_in=logged_in,
        display_name=display_name,
        current_user_profile=current_user_profile,
    )


@bp.route('/link-game', methods=['POST'])
def link_game():
    """Link a Minecraft account to the authenticated user's Authentik profile.

    Validates the Minecraft username, looks up the UUID via Mojang API,
    and creates a pending whitelist entry tied to the user's Authentik account.

    Returns:
        Redirect to panel.index with a flash message.
    """
    authentik_username = session.get('ldap_raw_username')
    if not authentik_username:
        flash('You must be logged in to link a game account.', 'error')
        return redirect(url_for('panel.index'))

    username = (request.form.get('mc_username') or '').strip()
    if not username or not _MC_USERNAME_RE.match(username):
        flash('Please enter a valid Minecraft username (3–16 letters, digits, or underscores).', 'error')
        return redirect(url_for('panel.index'))

    existing = panel_db.get_whitelist_entry_by_authentik_username(authentik_username)
    if existing:
        flash('You already have a Minecraft account linked.', 'error')
        return redirect(url_for('panel.index'))

    player_uuid = panel_db.lookup_minecraft_uuid(username)
    if not player_uuid:
        flash(
            f"Minecraft user '{username}' was not found. "
            "Make sure it's a valid Java Edition account.",
            'error',
        )
        return redirect(url_for('panel.index'))

    try:
        panel_db.create_whitelist_entry({
            'username': username,
            'player_uuid': player_uuid,
            'authentik_username': authentik_username,
            'client_ip': request.remote_addr,
        })
    except Exception:
        log.exception("Failed to create whitelist entry for %s", authentik_username)
        flash('Failed to link account. Please try again later.', 'error')
        return redirect(url_for('panel.index'))

    log.info("New game account link: %s linked %s (%s)", authentik_username, username, player_uuid)

    ntfy_topic = current_app.config.get('NTFY_TOPIC')
    if ntfy_topic:
        try:
            import requests as _req
            _req.post(
                f'https://ntfy.sh/{ntfy_topic}',
                data=f'New account link request: {username} ({authentik_username})'.encode('utf-8'),
                timeout=3,
            )
        except Exception:
            log.exception("ntfy notification failed")

    flash("Your Minecraft account has been linked! An admin will review your request.", 'success')
    return redirect(url_for('panel.index'))


@bp.route('/rules')
def rules():
    """Server rules page: reads rules.md and renders it as HTML.

    Converts the Markdown source to HTML using the `markdown`
    library (extensions: extra, nl2br). Falls back to a plain
    <pre> block if the library is unavailable.

    Returns:
        Rendered panel/rules.html template with rules_html string.
    """
    rules_content = panel_db.get_rules_markdown()
    rules_html = ''

    if rules_content:
        try:
            import markdown as md_lib
            raw_html = md_lib.markdown(rules_content, extensions=['extra', 'nl2br'])
            # Sanitise: python-markdown passes raw HTML through, and rules.md is
            # editable by the lower-privilege "messages" tier — without this a
            # <script> in the source would be stored XSS on this public page.
            try:
                import bleach
                allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS) | {
                    'p', 'pre', 'span', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                    'br', 'hr', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
                }
                allowed_attrs = {
                    '*': ['class'],
                    'a': ['href', 'title', 'rel'],
                    'img': ['src', 'alt', 'title'],
                }
                rules_html = bleach.clean(
                    raw_html, tags=allowed_tags, attributes=allowed_attrs,
                    protocols=['http', 'https', 'mailto'], strip=True,
                )
            except ImportError:
                # bleach not installed — fail safe by escaping instead of
                # serving unsanitised HTML.
                rules_html = f'<pre>{escape(rules_content)}</pre>'
        except ImportError:
            # Graceful fallback when markdown library is not installed
            rules_html = f'<pre>{escape(rules_content)}</pre>'
    else:
        rules_html = '<p>Rules file not found. Please contact an administrator.</p>'

    return render_template('panel/rules.html', rules_html=rules_html)


@bp.route('/api/cards')
def cards_api():
    """JSON API: return active and archived server card data.

    Used by the frontend JS card renderer to refresh without a
    full page reload.

    Returns:
        JSON object: { "active": [...], "archived": [...] }
    """
    return jsonify({
        'active': panel_db.get_active_servers(),
        'archived': panel_db.get_archived_servers(),
    })


@bp.route('/api/user/<username>')
def user_profile(username: str):
    """Public endpoint to look up a user's whitelist status and profile.

    Performs a case-insensitive username lookup. Returns a minimal
    public profile — no client_ip or internal fields are exposed.

    Args:
        username: The Minecraft username to look up.

    Returns:
        404 JSON if not found; 200 JSON with profile fields if found.
        Shape: { found, username, player_uuid, discord_username,
                 discord_avatar_url, approved, strikes }
    """
    entry = panel_db.get_whitelist_entry_by_username(username)
    if not entry:
        return jsonify({'found': False}), 404

    return jsonify({
        'found': True,
        'username': entry['username'],
        'player_uuid': entry['player_uuid'],
        'discord_username': entry['discord_username'],
        'discord_avatar_url': entry.get('discord_avatar_url'),
        'approved': entry['approved'],
        'strikes': entry.get('strikes', 0),
    })
