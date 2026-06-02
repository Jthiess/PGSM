import io
import logging
import posixpath
import stat

from flask import render_template, request, redirect, url_for, send_file, flash, jsonify, abort
from werkzeug.exceptions import HTTPException

from app.auth import require_server_access
from app.blueprints.files import bp
from app.models.server import GameServer
from app.services.ssh import SSHManager

logger = logging.getLogger(__name__)

ssh_mgr = SSHManager()

_ALLOWED_BASE = '/PGSM'

# Cap for in-browser downloads (buffered in memory). Larger files must be
# fetched over SFTP directly.
_DOWNLOAD_SIZE_LIMIT = 512 * 1024 * 1024  # 512 MB


def _safe_path(user_path: str) -> str:
    normalized = posixpath.normpath('/' + user_path.lstrip('/'))
    if not (normalized == _ALLOWED_BASE or normalized.startswith(_ALLOWED_BASE + '/')):
        abort(403)
    return normalized


def _within_base(p: str) -> bool:
    return p == _ALLOWED_BASE or p.startswith(_ALLOWED_BASE + '/')


def _resolve_within_base(sftp, remote_path: str) -> str:
    """Resolves remote_path server-side (following symlinks) and enforces that
    the *real* target stays within _ALLOWED_BASE, then returns the canonical
    path.

    The lexical `_safe_path` check only inspects the string; because all file
    operations run as root over SFTP, a symlink that lives under /PGSM but
    points outside it would otherwise be followed (arbitrary read/write/delete).
    `sftp.normalize()` issues SSH_FXP_REALPATH so the server resolves every
    symlink. For paths that do not exist yet (new uploads/saves) the parent
    directory is resolved instead and the leaf re-attached. Aborts 403 on any
    escape.
    """
    try:
        real = sftp.normalize(remote_path)
    except IOError:
        # Target doesn't exist yet — resolve the (existing) parent directory.
        parent = posixpath.dirname(remote_path.rstrip('/')) or '/'
        leaf = posixpath.basename(remote_path.rstrip('/'))
        real_parent = sftp.normalize(parent)
        if not _within_base(real_parent):
            abort(403)
        real = posixpath.join(real_parent, leaf)
    if not _within_base(real):
        abort(403)
    return real


@bp.route('/<server_id>')
@bp.route('/<server_id>/<path:remote_path>')
@require_server_access
def browse(server_id, remote_path='/PGSM'):
    server = GameServer.query.get_or_404(server_id)
    remote_path = _safe_path(remote_path)

    # Build breadcrumb parts
    parts = [p for p in remote_path.split('/') if p]
    breadcrumbs = []
    for i, part in enumerate(parts):
        breadcrumbs.append({
            'name': part,
            'path': '/' + '/'.join(parts[:i + 1]),
        })

    # Page renders immediately; file list is fetched via AJAX
    return render_template(
        'files/browser.html',
        server=server,
        entries=None,
        current_path=remote_path,
        breadcrumbs=breadcrumbs,
    )


@bp.route('/<server_id>/list')
@bp.route('/<server_id>/list/<path:remote_path>')
@require_server_access
def list_files(server_id, remote_path='/PGSM'):
    """JSON API: returns directory listing for the file browser."""
    server = GameServer.query.get_or_404(server_id)
    remote_path = _safe_path(remote_path)

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            remote_path = _resolve_within_base(sftp, remote_path)
            entries = []
            for attr in sftp.listdir_attr(remote_path):
                entries.append({
                    'name': attr.filename,
                    'is_dir': stat.S_ISDIR(attr.st_mode),
                    'size': attr.st_size,
                    'path': (remote_path.rstrip('/') + '/' + attr.filename),
                })
            entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
        finally:
            sftp.close()
            client.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('list_files failed for server=%s: %s', server_id, e)
        return jsonify({'error': 'Could not list directory'}), 502

    return jsonify({'entries': entries})


@bp.route('/<server_id>/download')
@require_server_access
def download(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.args.get('path', '')
    if not remote_path:
        flash('No file path specified.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))
    remote_path = _safe_path(remote_path)

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            remote_path = _resolve_within_base(sftp, remote_path)
            st = sftp.stat(remote_path)
            if stat.S_ISDIR(st.st_mode):
                flash('Cannot download a directory.', 'error')
                return redirect(url_for('files.browse', server_id=server_id))
            # Reject oversized regular files (buffered in memory) and anything
            # that isn't a regular file (e.g. a device that would read forever).
            if not stat.S_ISREG(st.st_mode):
                flash('Only regular files can be downloaded.', 'error')
                return redirect(url_for('files.browse', server_id=server_id))
            if st.st_size > _DOWNLOAD_SIZE_LIMIT:
                flash(
                    f'File is too large to download from the browser '
                    f'({st.st_size // (1024 * 1024)} MB). Use SFTP instead.',
                    'error',
                )
                return redirect(url_for('files.browse', server_id=server_id))
            buf = io.BytesIO()
            sftp.getfo(remote_path, buf)
            buf.seek(0)
        finally:
            sftp.close()
            client.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('download failed for server=%s: %s', server_id, e)
        flash('Download failed.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))

    filename = posixpath.basename(remote_path)
    return send_file(buf, as_attachment=True, download_name=filename)


@bp.route('/<server_id>/upload', methods=['POST'])
@require_server_access
def upload(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_dir = _safe_path(request.form.get('path', '/PGSM'))
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('files.browse', server_id=server_id,
                                remote_path=remote_dir))

    from werkzeug.utils import secure_filename as _secure
    safe_name = _secure(file.filename)
    if not safe_name:
        flash('Invalid filename.', 'error')
        return redirect(url_for('files.browse', server_id=server_id,
                                remote_path=remote_dir))

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            real_dir = _resolve_within_base(sftp, remote_dir)
            dest = _resolve_within_base(sftp, f'{real_dir.rstrip("/")}/{safe_name}')
            sftp.putfo(file.stream, dest)
        finally:
            sftp.close()
            client.close()
        flash(f'Uploaded {safe_name} successfully.', 'success')
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('upload failed for server=%s: %s', server_id, e)
        flash('Upload failed.', 'error')

    return redirect(url_for('files.browse', server_id=server_id,
                            remote_path=remote_dir))


@bp.route('/<server_id>/delete_file', methods=['POST'])
@require_server_access
def delete_file(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.form.get('path', '')
    if not remote_path:
        flash('No path specified.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))
    remote_path = _safe_path(remote_path)
    parent = '/'.join(remote_path.split('/')[:-1]) or '/PGSM'

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            real_path = _resolve_within_base(sftp, remote_path)
            sftp.remove(real_path)
        finally:
            sftp.close()
            client.close()
        flash(f'Deleted {posixpath.basename(remote_path)}.', 'warning')
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('delete_file failed for server=%s: %s', server_id, e)
        flash('Delete failed.', 'error')

    return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))


@bp.route('/<server_id>/delete_dir', methods=['POST'])
@require_server_access
def delete_dir(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.form.get('path', '')

    if not remote_path:
        flash('No path specified.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))
    remote_path = _safe_path(remote_path)
    parent = '/'.join(remote_path.split('/')[:-1]) or '/PGSM'

    if remote_path == _ALLOWED_BASE:
        flash('Cannot delete the server root directory.', 'error')
        return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))

    try:
        import shlex
        # Resolve symlinks server-side and confirm containment before the
        # (root) rm -rf, so a symlink under /PGSM can't target an outside path.
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            real_path = _resolve_within_base(sftp, remote_path)
        finally:
            sftp.close()
            client.close()
        if real_path == _ALLOWED_BASE:
            flash('Cannot delete the server root directory.', 'error')
            return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))
        ssh_mgr.exec(server.ip_address, f'rm -rf {shlex.quote(real_path)}')
        flash(f'Deleted directory {posixpath.basename(remote_path)}.', 'warning')
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('delete_dir failed for server=%s: %s', server_id, e)
        flash('Delete failed.', 'error')

    return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))


_EDIT_SIZE_LIMIT = 512 * 1024  # 512 KB


@bp.route('/<server_id>/edit')
@require_server_access
def edit_file(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.args.get('path', '')
    if not remote_path:
        flash('No file path specified.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))
    remote_path = _safe_path(remote_path)
    parent = '/'.join(remote_path.split('/')[:-1]) or '/PGSM'

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            remote_path = _resolve_within_base(sftp, remote_path)
            file_stat = sftp.stat(remote_path)
            if file_stat.st_size > _EDIT_SIZE_LIMIT:
                flash(
                    f'File is too large to edit in browser ({file_stat.st_size // 1024} KB). '
                    'Download it instead.',
                    'error',
                )
                return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))

            with sftp.open(remote_path, 'r') as f:
                raw = f.read()
        finally:
            sftp.close()
            client.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('edit_file failed for server=%s: %s', server_id, e)
        flash('Could not open file.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))

    # Reject binary files (null bytes in first 8 KB)
    if b'\x00' in raw[:8192]:
        flash('This file appears to be binary and cannot be edited here.', 'error')
        return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))

    try:
        content = raw.decode('utf-8')
    except UnicodeDecodeError:
        flash('File is not valid UTF-8 and cannot be edited here.', 'error')
        return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))

    filename = remote_path.split('/')[-1]
    return render_template(
        'files/editor.html',
        server=server,
        remote_path=remote_path,
        filename=filename,
        content=content,
    )


@bp.route('/<server_id>/save', methods=['POST'])
@require_server_access
def save_file(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.form.get('path', '')
    content = request.form.get('content', '')

    if not remote_path:
        return jsonify({'error': 'No path specified'}), 400
    remote_path = _safe_path(remote_path)

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            real_path = _resolve_within_base(sftp, remote_path)
            with sftp.file(real_path, 'w') as f:
                f.write(content)
        finally:
            sftp.close()
            client.close()
    except HTTPException:
        raise
    except Exception as e:
        logger.warning('save_file failed for server=%s: %s', server_id, e)
        return jsonify({'error': 'Could not save file'}), 500

    return jsonify({'ok': True})
