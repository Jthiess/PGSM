# ============================================================
# app/blueprints/panel/routes.py — Public-Facing Game Panel
# Serves the main entry point: server cards, rules page, and
# the JSON API used by the frontend card renderer.
# No authentication required — all routes are public.
# ============================================================

from flask import jsonify, render_template

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

    Returns:
        Rendered panel/index.html template.
    """
    active_servers = panel_db.get_active_servers()
    archived_servers = panel_db.get_archived_servers()
    random_message = panel_db.get_random_message()

    return render_template(
        'panel/index.html',
        servers=active_servers,
        archived=archived_servers,
        message=random_message,
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
            rules_html = md_lib.markdown(rules_content, extensions=['extra', 'nl2br'])
        except ImportError:
            # Graceful fallback when markdown library is not installed
            rules_html = f'<pre>{rules_content}</pre>'
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
