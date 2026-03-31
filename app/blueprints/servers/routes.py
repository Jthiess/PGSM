import os

from flask import render_template, request, redirect, url_for, flash, current_app
from app.auth import require_admin, require_management_access, require_server_access, is_admin
from app.blueprints.servers import bp
from app.models.server import GameServer
from app.extensions import db


@bp.route('/')
@require_management_access
def list_servers():
    if is_admin():
        servers = GameServer.query.order_by(GameServer.created_at.desc()).all()
    else:
        from app.auth import get_current_username
        from app.models.server_permission import ServerPermission
        username = get_current_username()
        if username:
            perms = ServerPermission.query.filter_by(username=username).all()
            server_ids = [p.server_id for p in perms]
            servers = GameServer.query.filter(GameServer.id.in_(server_ids)).order_by(GameServer.created_at.desc()).all()
        else:
            servers = []
    return render_template('servers/list.html', servers=servers)


@bp.route('/create', methods=['GET', 'POST'])
@require_admin
def create_server():
    from app.services.proxmox import ProxmoxService
    from app.services.ssh import SSHManager
    from app.services.minecraft import MinecraftService
    import uuid, threading

    proxmox = ProxmoxService()
    ssh_mgr = SSHManager()
    mc_svc = MinecraftService()

    if request.method == 'GET':
        cfg = current_app.config
        defaults = {
            'disk_gb':        cfg['SERVER_DEFAULT_DISK_GB'],
            'cores':          cfg['SERVER_DEFAULT_CORES'],
            'memory_mb':      cfg['SERVER_DEFAULT_MEMORY_MB'],
            'game_port':      cfg['SERVER_DEFAULT_GAME_PORT'],
            'render_distance': cfg['SERVER_DEFAULT_RENDER_DIST'],
            'spawn_protection': cfg['SERVER_DEFAULT_SPAWN_PROT'],
            'difficulty':     cfg['SERVER_DEFAULT_DIFFICULTY'],
            'server_type':    cfg['SERVER_DEFAULT_SERVER_TYPE'],
            'ha_enabled':     cfg['SERVER_DEFAULT_HA_ENABLED'],
        }
        # Nodes and versions are loaded asynchronously by JS to avoid blocking the page render
        return render_template('servers/create.html', defaults=defaults)

    # POST: validate and kick off provisioning
    form = request.form
    server_type = form.get('server_type', 'vanilla')
    game_code = 'MCBED' if server_type == 'bedrock' else 'MCJAV'

    # Import type requires a startup command and a zip file
    if server_type == 'import':
        if not form.get('custom_startup_command', '').strip():
            flash('A startup command is required for imported servers.', 'error')
            return redirect(url_for('servers.create_server'))
        import_file = request.files.get('import_archive')
        if not import_file or not import_file.filename:
            flash('A .zip archive is required for imported servers.', 'error')
            return redirect(url_for('servers.create_server'))
        if not import_file.filename.lower().endswith('.zip'):
            flash('Only .zip archives are supported for import.', 'error')
            return redirect(url_for('servers.create_server'))

    server_id = str(uuid.uuid4())
    partial_uuid = server_id[:8].upper()
    hostname = f'PGSM-{game_code}-{partial_uuid}'
    ha_enabled = 'ha_enabled' in form

    # Save uploaded zip before any error that would redirect, so we have the path ready
    import_archive_path = None
    if server_type == 'import':
        uploads_dir = os.path.join(current_app.instance_path, 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        import_archive_path = os.path.join(uploads_dir, f'{server_id}.zip')
        import_file.save(import_archive_path)

    try:
        ct_id = proxmox.get_next_ct_id()
        pubkey = ssh_mgr.ensure_keypair()
        used_ips = [s.ip_address for s in GameServer.query.all()]
        ip = proxmox.get_next_ip(used_ips)
    except Exception as e:
        if import_archive_path and os.path.exists(import_archive_path):
            os.remove(import_archive_path)
        flash(f'Setup error: {e}', 'error')
        return redirect(url_for('servers.create_server'))

    cfg = current_app.config
    game_port = int(form.get('game_port', cfg['SERVER_DEFAULT_GAME_PORT']))
    port_conflict = GameServer.port_in_use_by(game_port)
    if port_conflict:
        if import_archive_path and os.path.exists(import_archive_path):
            os.remove(import_archive_path)
        flash(f'Port {game_port} is already in use by server "{port_conflict.name}".', 'error')
        return redirect(url_for('servers.create_server'))
    # Import servers don't have a meaningful MC version; use 'import' as sentinel
    game_version = 'import' if server_type == 'import' else form.get('game_version', 'latest')

    server = GameServer(
        id=server_id,
        name=form.get('name', hostname),
        game_code=game_code,
        server_type=server_type,
        game_version=game_version,
        ct_id=ct_id,
        proxmox_node=form.get('node'),
        hostname=hostname,
        ip_address=ip,
        disk_gb=int(form.get('disk_gb', cfg['SERVER_DEFAULT_DISK_GB'])),
        cores=int(form.get('cores', cfg['SERVER_DEFAULT_CORES'])),
        memory_mb=int(form.get('memory_mb', cfg['SERVER_DEFAULT_MEMORY_MB'])),
        game_port=game_port,
        motd=form.get('motd') or None,
        render_distance=int(form.get('render_distance', cfg['SERVER_DEFAULT_RENDER_DIST'])),
        spawn_protection=int(form.get('spawn_protection', cfg['SERVER_DEFAULT_SPAWN_PROT'])),
        difficulty=form.get('difficulty', cfg['SERVER_DEFAULT_DIFFICULTY']),
        hardcore='hardcore' in form,
        ha_enabled=ha_enabled,
        status='creating',
        # Modded / import fields
        fabric_loader_version=form.get('fabric_loader_version', '').strip() or None,
        forge_version=form.get('forge_version', '').strip() or None,
        import_archive_url=import_archive_path,  # local path to uploaded zip
        custom_startup_command=form.get('custom_startup_command', '').strip() or None,
    )
    db.session.add(server)
    db.session.commit()

    # Create LXC container
    try:
        proxmox.create_lxc(
            server.proxmox_node, ct_id, hostname, ip,
            server.disk_gb, server.cores, server.memory_mb, pubkey
        )
    except Exception as e:
        server.status = 'error'
        db.session.commit()
        if import_archive_path and os.path.exists(import_archive_path):
            os.remove(import_archive_path)
        flash(f'LXC creation failed: {e}', 'error')
        return redirect(url_for('servers.detail', server_id=server.id))

    # Register with Proxmox HA if requested
    if ha_enabled:
        try:
            proxmox.enable_ha(ct_id)
        except Exception as e:
            flash(f'HA registration failed (server still created): {e}', 'warning')

    # Provision in background thread
    # Must capture the app instance here — current_app proxy is invalid inside a new thread
    app = current_app._get_current_object()

    def _provision():
        with app.app_context():
            from app.services import server_lifecycle
            server_lifecycle.provision_server(server.id)

    threading.Thread(target=_provision, daemon=True).start()

    flash(f'Server "{server.name}" is being created. This may take several minutes.', 'info')
    return redirect(url_for('servers.detail', server_id=server.id))


@bp.route('/<server_id>')
@require_server_access
def detail(server_id):
    server = GameServer.query.get_or_404(server_id)
    active_tab = request.args.get('tab', 'info')
    permissions = []
    if is_admin():
        from app.models.server_permission import ServerPermission
        permissions = ServerPermission.query.filter_by(server_id=server_id).order_by(ServerPermission.created_at).all()
    return render_template('servers/detail.html', server=server, active_tab=active_tab, permissions=permissions)


@bp.route('/<server_id>/start', methods=['POST'])
@require_server_access
def start(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services import server_lifecycle
    try:
        server_lifecycle.start_server(server)
        flash('Server started.', 'success')
    except Exception as e:
        flash(f'Start failed: {e}', 'error')
    return redirect(url_for('servers.detail', server_id=server_id))


@bp.route('/<server_id>/stop', methods=['POST'])
@require_server_access
def stop(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services import server_lifecycle
    try:
        server_lifecycle.stop_server(server)
        flash('Server shut down.', 'success')
    except Exception as e:
        flash(f'Shutdown failed: {e}', 'error')
    return redirect(url_for('servers.detail', server_id=server_id))


@bp.route('/<server_id>/power_off', methods=['POST'])
@require_server_access
def power_off(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services import server_lifecycle
    try:
        server_lifecycle.power_off_server(server)
        flash('Container powered off.', 'success')
    except Exception as e:
        flash(f'Power off failed: {e}', 'error')
    return redirect(url_for('servers.detail', server_id=server_id))


@bp.route('/<server_id>/restart', methods=['POST'])
@require_server_access
def restart(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services import server_lifecycle
    try:
        server_lifecycle.restart_server(server)
        flash('Server restarting.', 'success')
    except Exception as e:
        flash(f'Restart failed: {e}', 'error')
    return redirect(url_for('servers.detail', server_id=server_id))


@bp.route('/<server_id>/resources', methods=['POST'])
@require_admin
def update_resources(server_id):
    server = GameServer.query.get_or_404(server_id)
    form = request.form

    # Validate cores
    try:
        cores = int(form.get('cores', server.cores))
    except (TypeError, ValueError):
        flash('Invalid CPU cores value.', 'error')
        return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))
    if cores < 1 or cores > 128:
        flash('CPU cores must be between 1 and 128.', 'error')
        return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))

    # Validate memory
    try:
        memory_mb = int(form.get('memory_mb', server.memory_mb))
    except (TypeError, ValueError):
        flash('Invalid memory value.', 'error')
        return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))
    if memory_mb < 128 or memory_mb > 1048576:
        flash('Memory must be between 128 MB and 1,048,576 MB (1 TB).', 'error')
        return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))

    # Skip if nothing changed
    if cores == server.cores and memory_mb == server.memory_mb:
        flash('No changes detected.', 'info')
        return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))

    # Apply to Proxmox CT
    from app.services.proxmox import ProxmoxService
    proxmox = ProxmoxService()
    try:
        proxmox.update_ct_resources(
            server.proxmox_node, server.ct_id,
            cores=cores if cores != server.cores else None,
            memory_mb=memory_mb if memory_mb != server.memory_mb else None,
        )
    except Exception as e:
        flash(f'Failed to update container resources: {e}', 'error')
        return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))

    # Update DB
    server.cores = cores
    server.memory_mb = memory_mb
    db.session.commit()

    flash('Resources updated successfully.', 'success')
    return redirect(url_for('servers.detail', server_id=server_id, tab='resources'))


@bp.route('/<server_id>/settings', methods=['POST'])
@require_server_access
def update_settings(server_id):
    server = GameServer.query.get_or_404(server_id)
    form = request.form

    # Update DB fields
    server.motd = form.get('motd') or None
    server.render_distance = int(form.get('render_distance', server.render_distance))
    server.spawn_protection = int(form.get('spawn_protection', server.spawn_protection))
    server.difficulty = form.get('difficulty', server.difficulty)
    server.hardcore = 'hardcore' in form

    # Java/startup settings (Java servers only)
    if server.game_code == 'MCJAV':
        jv_raw = form.get('java_version_override', '').strip()
        server.java_version_override = int(jv_raw) if jv_raw else None
        server.custom_startup_command = form.get('custom_startup_command', '').strip() or None

    db.session.commit()

    # Write updated server.properties to the container
    from app.services.minecraft import MinecraftService
    from app.services.ssh import SSHManager
    ssh_mgr = SSHManager()
    mc_svc = MinecraftService()
    warnings = []

    try:
        props = mc_svc.generate_server_properties(server)
        client, sftp = ssh_mgr.get_sftp(server.ip_address)
        try:
            with sftp.file('/PGSM/server.properties', 'w') as f:
                f.write(props)
        finally:
            sftp.close()
            client.close()
        # SFTP writes as root; restore PGSM ownership so the server can read/write the file
        ssh_mgr.exec(server.ip_address, 'chown PGSM:PGSM /PGSM/server.properties')
    except Exception as e:
        warnings.append(f'Could not write server.properties: {e}')

    # Rewrite systemd unit if Java version or startup command changed
    if server.game_code == 'MCJAV':
        try:
            _rewrite_systemd_unit(server, ssh_mgr)
        except Exception as e:
            warnings.append(f'Could not update systemd unit: {e}')

    if warnings:
        flash('Settings saved to database but: ' + '; '.join(warnings), 'warning')
    else:
        flash('Settings saved. Restart the server for changes to take effect.', 'success')

    return redirect(url_for('servers.detail', server_id=server_id, tab='game-settings'))


def _rewrite_systemd_unit(server, ssh_mgr):
    """Rewrites /etc/systemd/system/PGSM.service on the container to reflect
    current java_version and custom_startup_command, then reloads systemd.
    Also ensures the run.sh wrapper script exists."""
    if server.custom_startup_command:
        startup_cmd = server.custom_startup_command
    else:
        java_dir = f'java{server.java_version}'
        startup_cmd = f'/opt/java/{java_dir}/bin/java -jar server.jar'

    # Ensure the crash-recovery wrapper script exists
    run_sh = (
        '#!/bin/bash\n'
        '# PGSM wrapper: starts the server in tmux and monitors it.\n'
        '# Exits non-zero on crash (triggering systemd Restart=on-failure).\n'
        'CLEAN_STOP=0\n'
        'trap \'CLEAN_STOP=1\' SIGTERM SIGINT\n'
        '\n'
        '/usr/bin/tmux new-session -d -c /PGSM -s PGSM "$@"\n'
        '\n'
        'while /usr/bin/tmux has-session -t PGSM 2>/dev/null; do\n'
        '    sleep 2\n'
        'done\n'
        '\n'
        '[ "$CLEAN_STOP" -eq 1 ] && exit 0\n'
        'exit 1\n'
    )
    ssh_mgr.exec(server.ip_address, 'mkdir -p /opt/pgsm')
    client, sftp = ssh_mgr.get_sftp(server.ip_address)
    try:
        with sftp.file('/opt/pgsm/run.sh', 'w') as f:
            f.write(run_sh)
    finally:
        sftp.close()
        client.close()
    ssh_mgr.exec(server.ip_address, 'chmod +x /opt/pgsm/run.sh')

    service_content = (
        '[Unit]\n'
        'Description=Proxmox Game Server Manager\n'
        'After=network.target\n'
        'StartLimitIntervalSec=120\n'
        'StartLimitBurst=3\n\n'
        '[Service]\n'
        'Type=simple\n'
        'User=PGSM\n'
        'Group=PGSM\n'
        'Environment=TERM=xterm-256color\n'
        'Environment=TMUX_TMPDIR=/tmp\n'
        f'ExecStart=/opt/pgsm/run.sh {startup_cmd}\n'
        'ExecStop=/usr/bin/tmux kill-session -t PGSM\n'
        'Restart=on-failure\n'
        'RestartSec=10\n\n'
        '[Install]\n'
        'WantedBy=multi-user.target\n'
    )
    client, sftp = ssh_mgr.get_sftp(server.ip_address)
    try:
        with sftp.file('/etc/systemd/system/PGSM.service', 'w') as f:
            f.write(service_content)
    finally:
        sftp.close()
        client.close()
    # Update /usr/local/bin/java symlink to match the active Java version
    java_dir = f'java{server.java_version}'
    ssh_mgr.exec(server.ip_address, f'ln -sf /opt/java/{java_dir}/bin/java /usr/local/bin/java')
    ssh_mgr.exec(server.ip_address, 'systemctl daemon-reload')


@bp.route('/<server_id>/delete', methods=['POST'])
@require_admin
def delete(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services.proxmox import ProxmoxService
    from app.services.nginx import NginxService
    from app.services import server_lifecycle

    try:
        server_lifecycle.stop_server(server)
    except Exception:
        pass  # Server may already be stopped

    proxmox = ProxmoxService()

    # Remove from Proxmox HA before stopping/deleting the CT
    if server.ha_enabled:
        try:
            proxmox.disable_ha(server.ct_id)
        except Exception:
            pass  # HA entry may not exist

    try:
        proxmox.stop_ct(server.proxmox_node, server.ct_id, wait=True)
    except Exception:
        pass  # CT may already be stopped or Proxmox unreachable

    try:
        proxmox.delete_ct(server.proxmox_node, server.ct_id)
    except Exception:
        pass  # CT may not exist or Proxmox unreachable

    try:
        NginxService().remove_server(server)
    except Exception:
        pass

    name = server.name
    db.session.delete(server)
    db.session.commit()
    flash(f'Server "{name}" has been deleted.', 'warning')
    return redirect(url_for('servers.list_servers'))


@bp.route('/<server_id>/permissions/add', methods=['POST'])
@require_admin
def add_permission(server_id):
    server = GameServer.query.get_or_404(server_id)
    username = request.form.get('username', '').strip()
    if not username:
        flash('Username is required.', 'error')
        return redirect(url_for('servers.detail', server_id=server_id, tab='permissions'))
    from app.models.server_permission import ServerPermission
    existing = ServerPermission.query.filter_by(server_id=server_id, username=username).first()
    if existing:
        flash(f'"{username}" already has access to this server.', 'warning')
        return redirect(url_for('servers.detail', server_id=server_id, tab='permissions'))
    perm = ServerPermission(server_id=server_id, username=username)
    db.session.add(perm)
    db.session.commit()
    flash(f'Access granted to "{username}".', 'success')
    return redirect(url_for('servers.detail', server_id=server_id, tab='permissions'))


@bp.route('/<server_id>/permissions/<permission_id>/remove', methods=['POST'])
@require_admin
def remove_permission(server_id, permission_id):
    from app.models.server_permission import ServerPermission
    perm = ServerPermission.query.filter_by(id=permission_id, server_id=server_id).first_or_404()
    username = perm.username
    db.session.delete(perm)
    db.session.commit()
    flash(f'Access revoked for "{username}".', 'success')
    return redirect(url_for('servers.detail', server_id=server_id, tab='permissions'))
