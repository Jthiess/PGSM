import io
import stat

from flask import render_template, request, redirect, url_for, send_file, flash

from app.blueprints.files import bp
from app.models.server import GameServer
from app.services.ssh import SSHManager

ssh_mgr = SSHManager()


@bp.route('/<server_id>')
@bp.route('/<server_id>/<path:remote_path>')
def browse(server_id, remote_path='/PGSM'):
    server = GameServer.query.get_or_404(server_id)
    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
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
    except Exception as e:
        flash(f'SFTP error: {e}', 'error')
        entries = []

    # Build breadcrumb parts
    parts = [p for p in remote_path.split('/') if p]
    breadcrumbs = []
    for i, part in enumerate(parts):
        breadcrumbs.append({
            'name': part,
            'path': '/' + '/'.join(parts[:i + 1]),
        })

    return render_template(
        'files/browser.html',
        server=server,
        entries=entries,
        current_path=remote_path,
        breadcrumbs=breadcrumbs,
    )


@bp.route('/<server_id>/download')
def download(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.args.get('path', '')
    if not remote_path:
        flash('No file path specified.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            buf = io.BytesIO()
            sftp.getfo(remote_path, buf)
            buf.seek(0)
        finally:
            sftp.close()
            client.close()
    except Exception as e:
        flash(f'Download failed: {e}', 'error')
        return redirect(url_for('files.browse', server_id=server_id))

    filename = remote_path.split('/')[-1]
    return send_file(buf, as_attachment=True, download_name=filename)


@bp.route('/<server_id>/upload', methods=['POST'])
def upload(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_dir = request.form.get('path', '/PGSM')
    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected.', 'error')
        return redirect(url_for('files.browse', server_id=server_id,
                                remote_path=remote_dir))

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            sftp.putfo(file.stream, f'{remote_dir.rstrip("/")}/{file.filename}')
        finally:
            sftp.close()
            client.close()
        flash(f'Uploaded {file.filename} successfully.', 'success')
    except Exception as e:
        flash(f'Upload failed: {e}', 'error')

    return redirect(url_for('files.browse', server_id=server_id,
                            remote_path=remote_dir))


@bp.route('/<server_id>/delete_file', methods=['POST'])
def delete_file(server_id):
    server = GameServer.query.get_or_404(server_id)
    remote_path = request.form.get('path', '')
    parent = '/'.join(remote_path.split('/')[:-1]) or '/PGSM'

    if not remote_path:
        flash('No path specified.', 'error')
        return redirect(url_for('files.browse', server_id=server_id))

    try:
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            sftp.remove(remote_path)
        finally:
            sftp.close()
            client.close()
        flash(f'Deleted {remote_path.split("/")[-1]}.', 'warning')
    except Exception as e:
        flash(f'Delete failed: {e}', 'error')

    return redirect(url_for('files.browse', server_id=server_id, remote_path=parent))
