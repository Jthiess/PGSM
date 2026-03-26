# ============================================================
# app/blueprints/admin_panel/routes.py — Admin Panel
# Session-based admin authentication and management routes
# for the public game panel (servers, messages, rules).
# All routes except /login and /logout require admin auth.
# ============================================================

import os

from flask import (
    current_app, flash, redirect, render_template,
    request, session, url_for,
)
from werkzeug.utils import secure_filename

from app.auth import is_admin, require_admin, require_messages_access
from app.blueprints.admin_panel import bp
from app.services import panel_db

# Allowed extensions for pack icon uploads
_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


# ------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------

def _allowed_file(filename: str) -> bool:
    """Return True if filename has an allowed image extension."""
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in _ALLOWED_EXTENSIONS
    )


def _pack_icons_dir() -> str:
    """Resolve the absolute path to the pack icons upload directory."""
    icons_dir = current_app.config.get('PANEL_PACK_ICONS_DIR', 'app/static/images/packicons')
    if os.path.isabs(icons_dir):
        return icons_dir
    # Resolve relative to project root (one level above app/)
    return os.path.join(current_app.root_path, '..', icons_dir)


def _save_pack_icon(file, label: str) -> str | None:
    """Save an uploaded pack icon file and return its filename.

    Args:
        file: Werkzeug FileStorage object from request.files.
        label: Base name to use for the saved file (e.g. pack_name or server name).

    Returns:
        The saved filename (e.g. 'my-pack.png'), or None if no file was provided
        or the extension is not allowed.
    """
    if not (file and file.filename and _allowed_file(file.filename)):
        return None
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{secure_filename(label)}.{ext}"
    upload_dir = _pack_icons_dir()
    os.makedirs(upload_dir, exist_ok=True)
    file.save(os.path.join(upload_dir, filename))
    return filename


# ------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Admin login — supports full admin and messages-only access.

    POST params:
        password (str): Checked against ADMIN_PASSWORD and MESSAGES_PASSWORD.
        next (query str): URL to redirect to after successful login.

    On full admin match: sets session['admin_auth'] = True, redirects to /admin/panel.
    On messages match:   sets session['messages_auth'] = True, redirects to /admin/messages.
    On failure:          flashes error and re-renders login form.

    Returns:
        Redirect on success; rendered admin_panel/login.html on GET or failure.
    """
    if request.method == 'POST':
        password = request.form.get('password', '')
        admin_pw = current_app.config.get('ADMIN_PASSWORD', 'admin')
        messages_pw = current_app.config.get('MESSAGES_PASSWORD')

        if password == admin_pw:
            session['admin_auth'] = True
            session.pop('messages_auth', None)
            next_url = request.args.get('next') or url_for('dashboard.index')
            flash('Logged in as admin.', 'success')
            return redirect(next_url)

        if messages_pw and password == messages_pw:
            session['messages_auth'] = True
            session.pop('admin_auth', None)
            flash('Logged in with messages access.', 'success')
            return redirect(url_for('admin_panel.messages'))

        flash('Invalid password.', 'error')

    return render_template('admin_panel/login.html')


@bp.route('/logout', methods=['POST'])
def logout():
    """Clear all auth session flags and redirect to homepage.

    Returns:
        Redirect to /.
    """
    session.pop('admin_auth', None)
    session.pop('messages_auth', None)
    flash('Logged out.', 'success')
    return redirect(url_for('panel.index'))


# ------------------------------------------------------------
# Admin hub
# ------------------------------------------------------------

@bp.route('/panel')
@require_admin
def panel():
    """Backwards-compatible redirect — old admin hub URL now forwards to the unified dashboard.

    Returns:
        Redirect to dashboard.index.
    """
    return redirect(url_for('dashboard.index'))


# ------------------------------------------------------------
# Messages & rules editing
# ------------------------------------------------------------

@bp.route('/messages', methods=['GET', 'POST'])
@require_messages_access
def messages():
    """Edit the rotating homepage messages file (messages.txt).

    GET:  Load current content and render editor.
    POST: Save submitted content via panel_db.save_messages().

    Returns:
        Rendered admin_panel/messages.html or redirect after save.
    """
    if request.method == 'POST':
        try:
            content = request.form.get('content', '')
            panel_db.save_messages(content)
            flash('messages.txt updated.', 'success')
        except Exception as exc:
            current_app.logger.exception("Failed to update messages.txt")
            flash(f'Failed to update: {exc}', 'error')
        return redirect(url_for('admin_panel.messages'))

    content = panel_db.get_random_message.__module__ and ''
    try:
        content = ''
        path = panel_db._panel_data_path('messages.txt')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
    except Exception:
        content = ''

    return render_template('admin_panel/messages.html', content=content)


@bp.route('/rules', methods=['GET', 'POST'])
@require_messages_access
def rules_edit():
    """Edit the server rules Markdown file (rules.md).

    GET:  Load current content and render editor.
    POST: Save submitted content via panel_db.save_rules().

    Returns:
        Rendered admin_panel/rules.html or redirect after save.
    """
    if request.method == 'POST':
        try:
            content = request.form.get('content', '')
            panel_db.save_rules(content)
            flash('rules.md updated.', 'success')
        except Exception as exc:
            current_app.logger.exception("Failed to update rules.md")
            flash(f'Failed to update: {exc}', 'error')
        return redirect(url_for('admin_panel.rules_edit'))

    content = panel_db.get_rules_markdown()
    return render_template('admin_panel/rules.html', content=content)


# ------------------------------------------------------------
# Active servers management
# ------------------------------------------------------------

@bp.route('/servers')
@require_admin
def servers():
    """List all active game server cards.

    Returns:
        Rendered admin_panel/servers.html with servers list.
    """
    try:
        all_servers = panel_db.get_active_servers()
    except Exception as exc:
        flash(f'Failed to load servers: {exc}', 'error')
        all_servers = []
    return render_template('admin_panel/servers.html', servers=all_servers)


@bp.route('/servers/new', methods=['GET', 'POST'])
@require_admin
def server_new():
    """Create a new active server card.

    GET:  Render the server creation form.
    POST: Validate input, handle pack icon upload, insert row via panel_db.

    Returns:
        Redirect to /admin/servers on success; re-renders form on error.
    """
    games = ['minecraft', 'terraria']

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            game = request.form.get('game', '').strip()

            if not name or not game:
                flash('Name and game are required.', 'error')
                return render_template('admin_panel/server_form.html',
                                       server=None, games=games)

            modded = request.form.get('modded') == 'on'
            pack_name = pack_link = pack_desc = pack_img_id = pack_version = None

            if modded:
                pack_name = request.form.get('pack_name', '').strip() or None
                pack_link = request.form.get('pack_link', '').strip() or None
                pack_desc = request.form.get('pack_desc', '').strip() or None
                pack_version = request.form.get('pack_version', '').strip() or None

                if 'pack_image' in request.files:
                    pack_img_id = _save_pack_icon(
                        request.files['pack_image'],
                        pack_name or name,
                    )

            panel_db.create_server({
                'name': name,
                'game': game,
                'description': request.form.get('description', '').strip() or None,
                'ip': request.form.get('ip', '').strip() or None,
                'version': request.form.get('version', '').strip() or None,
                'modded': modded,
                'pack_name': pack_name,
                'pack_link': pack_link,
                'pack_desc': pack_desc,
                'pack_img_id': pack_img_id,
                'pack_version': pack_version,
            })
            flash(f'Server "{name}" created successfully!', 'success')
            return redirect(url_for('admin_panel.servers'))

        except Exception as exc:
            flash(f'Failed to create server: {exc}', 'error')

    return render_template('admin_panel/server_form.html', server=None, games=games)


@bp.route('/servers/<int:id>/edit', methods=['GET', 'POST'])
@require_admin
def server_edit(id: int):
    """Edit an existing active server card.

    Args:
        id: The integer primary key of the server to edit.

    GET:  Load current server data and render form.
    POST: Validate, handle pack icon upload, update via panel_db.

    Returns:
        Redirect to /admin/servers on success; re-renders form on error.
    """
    games = ['minecraft', 'terraria']

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            game = request.form.get('game', '').strip()

            if not name or not game:
                flash('Name and game are required.', 'error')
                return redirect(url_for('admin_panel.server_edit', id=id))

            modded = request.form.get('modded') == 'on'

            # Load existing pack_img_id to preserve if no new file uploaded
            existing = panel_db.get_server_by_id(id) or {}
            pack_name = pack_link = pack_desc = pack_version = None
            pack_img_id = existing.get('pack_img_id')

            if modded:
                pack_name = request.form.get('pack_name', '').strip() or None
                pack_link = request.form.get('pack_link', '').strip() or None
                pack_desc = request.form.get('pack_desc', '').strip() or None
                pack_version = request.form.get('pack_version', '').strip() or None

                if 'pack_image' in request.files:
                    new_img = _save_pack_icon(
                        request.files['pack_image'],
                        pack_name or name,
                    )
                    if new_img:
                        pack_img_id = new_img

            panel_db.update_server(id, {
                'name': name,
                'game': game,
                'description': request.form.get('description', '').strip() or None,
                'ip': request.form.get('ip', '').strip() or None,
                'version': request.form.get('version', '').strip() or None,
                'modded': modded,
                'pack_name': pack_name,
                'pack_link': pack_link,
                'pack_desc': pack_desc,
                'pack_img_id': pack_img_id,
                'pack_version': pack_version,
            })
            flash(f'Server "{name}" updated successfully!', 'success')
            return redirect(url_for('admin_panel.servers'))

        except Exception as exc:
            flash(f'Failed to update server: {exc}', 'error')

    server = panel_db.get_server_by_id(id)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('admin_panel.servers'))

    return render_template('admin_panel/server_form.html', server=server, games=games)


@bp.route('/servers/<int:id>/delete', methods=['POST'])
@require_admin
def server_delete(id: int):
    """Delete an active server card and its pack icon file if present.

    Args:
        id: The integer primary key of the server to delete.

    Returns:
        Redirect to /admin/servers.
    """
    try:
        server = panel_db.get_server_by_id(id)
        if server and server.get('pack_img_id'):
            icon_path = os.path.join(_pack_icons_dir(), server['pack_img_id'])
            if os.path.exists(icon_path):
                os.remove(icon_path)
        panel_db.delete_server(id)
        flash('Server deleted successfully!', 'success')
    except Exception as exc:
        flash(f'Failed to delete server: {exc}', 'error')
    return redirect(url_for('admin_panel.servers'))


# ------------------------------------------------------------
# Archived servers management
# ------------------------------------------------------------

@bp.route('/archived-servers')
@require_admin
def archived_servers():
    """List all archived game server cards.

    Returns:
        Rendered admin_panel/archived_servers.html with servers list.
    """
    try:
        all_servers = panel_db.get_archived_servers()
    except Exception as exc:
        flash(f'Failed to load archived servers: {exc}', 'error')
        all_servers = []
    return render_template('admin_panel/archived_servers.html', servers=all_servers)


@bp.route('/archived-servers/new', methods=['GET', 'POST'])
@require_admin
def archived_server_new():
    """Create a new archived server card.

    GET:  Render the archive creation form.
    POST: Validate input, handle pack icon upload, insert via panel_db.

    Returns:
        Redirect to /admin/archived-servers on success; re-renders form on error.
    """
    games = ['minecraft', 'terraria']

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            game = request.form.get('game', '').strip()

            if not name or not game:
                flash('Name and game are required.', 'error')
                return render_template('admin_panel/archived_server_form.html',
                                       server=None, games=games)

            modded = request.form.get('modded') == 'on'
            pack_name = pack_link = pack_desc = pack_img_id = pack_version = None

            if modded:
                pack_name = request.form.get('pack_name', '').strip() or None
                pack_link = request.form.get('pack_link', '').strip() or None
                pack_desc = request.form.get('pack_desc', '').strip() or None
                pack_version = request.form.get('pack_version', '').strip() or None

                if 'pack_image' in request.files:
                    pack_img_id = _save_pack_icon(
                        request.files['pack_image'],
                        pack_name or name,
                    )

            panel_db.create_archived_server({
                'name': name,
                'motd': request.form.get('motd', '').strip() or None,
                'game': game,
                'description': request.form.get('description', '').strip() or None,
                'version': request.form.get('version', '').strip() or None,
                'file_size': request.form.get('file_size', '').strip() or None,
                'retirement_date': request.form.get('retirement_date', '').strip() or None,
                'world_link': request.form.get('world_link', '').strip() or None,
                'modded': modded,
                'pack_name': pack_name,
                'pack_link': pack_link,
                'pack_desc': pack_desc,
                'pack_img_id': pack_img_id,
                'pack_version': pack_version,
            })
            flash(f'Archived server "{name}" created successfully!', 'success')
            return redirect(url_for('admin_panel.archived_servers'))

        except Exception as exc:
            flash(f'Failed to create archived server: {exc}', 'error')

    return render_template('admin_panel/archived_server_form.html', server=None, games=games)


@bp.route('/archived-servers/<int:id>/edit', methods=['GET', 'POST'])
@require_admin
def archived_server_edit(id: int):
    """Edit an existing archived server card.

    Args:
        id: The integer primary key of the archived server to edit.

    GET:  Load current server data and render form.
    POST: Validate, handle pack icon upload, update via panel_db.

    Returns:
        Redirect to /admin/archived-servers on success; re-renders form on error.
    """
    games = ['minecraft', 'terraria']

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()
            game = request.form.get('game', '').strip()

            if not name or not game:
                flash('Name and game are required.', 'error')
                return redirect(url_for('admin_panel.archived_server_edit', id=id))

            modded = request.form.get('modded') == 'on'

            # Preserve existing pack_img_id unless a new file is uploaded
            existing = panel_db.get_archived_server_by_id(id) or {}
            pack_name = pack_link = pack_desc = pack_version = None
            pack_img_id = existing.get('pack_img_id')

            if modded:
                pack_name = request.form.get('pack_name', '').strip() or None
                pack_link = request.form.get('pack_link', '').strip() or None
                pack_desc = request.form.get('pack_desc', '').strip() or None
                pack_version = request.form.get('pack_version', '').strip() or None

                if 'pack_image' in request.files:
                    new_img = _save_pack_icon(
                        request.files['pack_image'],
                        pack_name or name,
                    )
                    if new_img:
                        pack_img_id = new_img

            panel_db.update_archived_server(id, {
                'name': name,
                'motd': request.form.get('motd', '').strip() or None,
                'game': game,
                'description': request.form.get('description', '').strip() or None,
                'version': request.form.get('version', '').strip() or None,
                'file_size': request.form.get('file_size', '').strip() or None,
                'retirement_date': request.form.get('retirement_date', '').strip() or None,
                'world_link': request.form.get('world_link', '').strip() or None,
                'modded': modded,
                'pack_name': pack_name,
                'pack_link': pack_link,
                'pack_desc': pack_desc,
                'pack_img_id': pack_img_id,
                'pack_version': pack_version,
            })
            flash(f'Archived server "{name}" updated successfully!', 'success')
            return redirect(url_for('admin_panel.archived_servers'))

        except Exception as exc:
            flash(f'Failed to update archived server: {exc}', 'error')

    server = panel_db.get_archived_server_by_id(id)
    if not server:
        flash('Archived server not found.', 'error')
        return redirect(url_for('admin_panel.archived_servers'))

    return render_template('admin_panel/archived_server_form.html', server=server, games=games)


@bp.route('/archived-servers/<int:id>/delete', methods=['POST'])
@require_admin
def archived_server_delete(id: int):
    """Delete an archived server card and its pack icon file if present.

    Args:
        id: The integer primary key of the archived server to delete.

    Returns:
        Redirect to /admin/archived-servers.
    """
    try:
        server = panel_db.get_archived_server_by_id(id)
        if server and server.get('pack_img_id'):
            icon_path = os.path.join(_pack_icons_dir(), server['pack_img_id'])
            if os.path.exists(icon_path):
                os.remove(icon_path)
        panel_db.delete_archived_server(id)
        flash('Archived server deleted successfully!', 'success')
    except Exception as exc:
        flash(f'Failed to delete archived server: {exc}', 'error')
    return redirect(url_for('admin_panel.archived_servers'))
