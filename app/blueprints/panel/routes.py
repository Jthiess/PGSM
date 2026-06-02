# ============================================================
# app/blueprints/panel/routes.py — Public-Facing Game Panel
# Serves the main entry point: server cards, rules page, and
# the JSON API used by the frontend card renderer.
# No authentication required — all routes are public.
# ============================================================

from markupsafe import escape
from flask import jsonify, render_template, session

from app.blueprints.panel import bp
from app.services import panel_db


# ------------------------------------------------------------
# Public routes
# ------------------------------------------------------------

@bp.route('/')
def index():
    """Homepage: renders active and archived server cards.

    Loads server data from PostgreSQL via panel_db and selects
    a random rotating message from messages.txt.

    If a username is present in the session (set at login), the
    corresponding whitelist entry is fetched and passed to the
    template as `current_user_profile` so the profile panel can
    be pre-loaded without any client-side username input.

    Returns:
        Rendered panel/index.html template.
    """
    active_servers = panel_db.get_active_servers()
    archived_servers = panel_db.get_archived_servers()
    random_message = panel_db.get_random_message()

    # ----------------------------------------------------------
    # Resolve the logged-in user's whitelist profile, if any
    # ----------------------------------------------------------
    minecraft_uuid = session.get('minecraft_uuid')
    logged_in = bool(session.get('admin_auth') or session.get('messages_auth'))
    current_user_profile = None

    if minecraft_uuid:
        entry = panel_db.get_whitelist_entry_by_uuid(minecraft_uuid)
        if entry:
            avatar_url = entry.get('discord_avatar_url')
            # If the avatar URL was never stored, try to fetch it now and cache it
            if not avatar_url and entry.get('discord_username'):
                _, fetched_url = panel_db.check_discord_guild_membership(
                    entry['discord_username']
                )
                if fetched_url:
                    panel_db.update_discord_avatar_url(entry['id'], fetched_url)
                    avatar_url = fetched_url
            current_user_profile = {
                'username': entry['username'],
                'player_uuid': entry['player_uuid'],
                'discord_username': entry['discord_username'],
                'discord_avatar_url': avatar_url,
                'approved': entry['approved'],
                'strikes': entry.get('strikes', 0),
            }

    return render_template(
        'panel/index.html',
        servers=active_servers,
        archived=archived_servers,
        message=random_message,
        logged_in=logged_in,
        current_user_profile=current_user_profile,
    )


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
