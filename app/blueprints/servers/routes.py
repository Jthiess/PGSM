from flask import render_template, request, redirect, url_for, flash, current_app
from app.blueprints.servers import bp
from app.models.server import GameServer
from app.extensions import db


@bp.route('/')
def list_servers():
    servers = GameServer.query.order_by(GameServer.created_at.desc()).all()
    return render_template('servers/list.html', servers=servers)


@bp.route('/create', methods=['GET', 'POST'])
def create_server():
    from app.services.proxmox import ProxmoxService
    from app.services.ssh import SSHManager
    from app.services.minecraft import MinecraftService
    import uuid, threading

    proxmox = ProxmoxService()
    ssh_mgr = SSHManager()
    mc_svc = MinecraftService()

    if request.method == 'GET':
        try:
            nodes = proxmox.get_nodes()
        except Exception as e:
            flash(f'Could not reach Proxmox: {e}', 'error')
            nodes = []
        try:
            versions = mc_svc.get_available_versions()
        except Exception as e:
            flash(f'Could not fetch Minecraft versions: {e}', 'error')
            versions = []
        return render_template('servers/create.html', nodes=nodes, versions=versions)

    # POST: validate and kick off provisioning
    form = request.form
    server_type = form.get('server_type', 'vanilla')
    game_code = 'MCBED' if server_type == 'bedrock' else 'MCJAV'
    server_id = str(uuid.uuid4())
    partial_uuid = server_id[:8].upper()
    hostname = f'PGSM-{game_code}-{partial_uuid}'

    try:
        ct_id = proxmox.get_next_ct_id()
        pubkey = ssh_mgr.ensure_keypair()
        used_ips = [s.ip_address for s in GameServer.query.all()]
        ip = proxmox.get_next_ip(used_ips)
    except Exception as e:
        flash(f'Setup error: {e}', 'error')
        return redirect(url_for('servers.create_server'))

    server = GameServer(
        id=server_id,
        name=form.get('name', hostname),
        game_code=game_code,
        server_type=server_type,
        game_version=form.get('game_version', 'latest'),
        ct_id=ct_id,
        proxmox_node=form.get('node'),
        hostname=hostname,
        ip_address=ip,
        disk_gb=int(form.get('disk_gb', 20)),
        cores=int(form.get('cores', 2)),
        memory_mb=int(form.get('memory_mb', 2048)),
        game_port=int(form.get('game_port', 25565)),
        motd=form.get('motd') or None,
        render_distance=int(form.get('render_distance', 10)),
        spawn_protection=int(form.get('spawn_protection', 16)),
        difficulty=form.get('difficulty', 'normal'),
        hardcore='hardcore' in form,
        status='creating',
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
        flash(f'LXC creation failed: {e}', 'error')
        return redirect(url_for('servers.detail', server_id=server.id))

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
def detail(server_id):
    server = GameServer.query.get_or_404(server_id)
    active_tab = request.args.get('tab', 'info')
    return render_template('servers/detail.html', server=server, active_tab=active_tab)


@bp.route('/<server_id>/start', methods=['POST'])
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
def stop(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services import server_lifecycle
    try:
        server_lifecycle.stop_server(server)
        flash('Server stopped.', 'success')
    except Exception as e:
        flash(f'Stop failed: {e}', 'error')
    return redirect(url_for('servers.detail', server_id=server_id))


@bp.route('/<server_id>/restart', methods=['POST'])
def restart(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services import server_lifecycle
    try:
        server_lifecycle.restart_server(server)
        flash('Server restarting.', 'success')
    except Exception as e:
        flash(f'Restart failed: {e}', 'error')
    return redirect(url_for('servers.detail', server_id=server_id))


@bp.route('/<server_id>/settings', methods=['POST'])
def update_settings(server_id):
    server = GameServer.query.get_or_404(server_id)
    form = request.form

    # Update DB fields
    server.motd = form.get('motd') or None
    server.render_distance = int(form.get('render_distance', server.render_distance))
    server.spawn_protection = int(form.get('spawn_protection', server.spawn_protection))
    server.difficulty = form.get('difficulty', server.difficulty)
    server.hardcore = 'hardcore' in form
    db.session.commit()

    # Write updated server.properties to the container
    try:
        from app.services.minecraft import MinecraftService
        from app.services.ssh import SSHManager
        props = MinecraftService().generate_server_properties(server)
        client, sftp = SSHManager().get_sftp(server.ip_address)
        try:
            with sftp.file('/PGSM/server.properties', 'w') as f:
                f.write(props)
        finally:
            sftp.close()
            client.close()
        flash('Settings saved. Restart the server for changes to take effect.', 'success')
    except Exception as e:
        flash(f'Settings saved to database but could not write server.properties: {e}', 'warning')

    return redirect(url_for('servers.detail', server_id=server_id, tab='game-settings'))


@bp.route('/<server_id>/delete', methods=['POST'])
def delete(server_id):
    server = GameServer.query.get_or_404(server_id)
    from app.services.proxmox import ProxmoxService
    from app.services.nginx import NginxService
    from app.services import server_lifecycle

    try:
        server_lifecycle.stop_server(server)
    except Exception:
        pass  # Server may already be stopped

    try:
        ProxmoxService().stop_ct(server.proxmox_node, server.ct_id)
    except Exception:
        pass

    try:
        NginxService().remove_server(server)
    except Exception:
        pass

    name = server.name
    db.session.delete(server)
    db.session.commit()
    flash(f'Server "{name}" has been deleted.', 'warning')
    return redirect(url_for('servers.list_servers'))
