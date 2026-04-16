import logging
import os
import subprocess

from flask import current_app

logger = logging.getLogger(__name__)


class NginxService:
    """Manages nginx TCP stream proxy config files for game servers."""

    def _conf_path(self, server) -> str:
        conf_dir = current_app.config['NGINX_CONF_DIR']
        return os.path.join(conf_dir, f'pgsm-{server.ct_id}.conf')

    def _generate_stream_block(self, server) -> str:
        """Generates nginx stream blocks to TCP-proxy all of a server's ports.

        One upstream + server block is emitted per port (primary + extra).

        NOTE: Requires the controller's nginx.conf to have:
            stream {
                include /etc/nginx/stream.d/*.conf;
            }
        Use a dedicated stream.d directory (not conf.d) to avoid conflicts
        with the http {} block that typically includes conf.d.
        This is a one-time manual setup prerequisite.
        """
        lines = [f"# PGSM Auto-generated: {server.name} (CT {server.ct_id})\n"]
        for entry in server.all_ports_with_protocols:
            port = entry['port']
            protocol = entry.get('protocol', 'tcp')
            name = f"pgsm_{server.ct_id}_{port}"
            block = (
                f"upstream {name} {{\n"
                f"    server {server.ip_address}:{port};\n"
                f"}}\n"
            )
            if protocol in ('tcp', 'both'):
                block += (
                    f"server {{\n"
                    f"    listen {port};\n"
                    f"    proxy_pass {name};\n"
                    f"}}\n"
                )
            if protocol in ('udp', 'both'):
                block += (
                    f"server {{\n"
                    f"    listen {port} udp;\n"
                    f"    proxy_pass {name};\n"
                    f"}}\n"
                )
            lines.append(block)
        return '\n'.join(lines)

    def add_server(self, server) -> None:
        """Writes an nginx conf file for the server and reloads nginx."""
        path = self._conf_path(server)
        logger.info('Writing nginx conf for ct_id=%s → %s', server.ct_id, path)
        content = self._generate_stream_block(server)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                f.write(content)
            logger.info('nginx conf written for ct_id=%s', server.ct_id)
        except PermissionError:
            logger.debug('Direct write to %s denied — falling back to sudo tee', path)
            dir_path = os.path.dirname(path)
            if not os.path.isdir(dir_path):
                subprocess.run(['sudo', 'mkdir', '-p', dir_path], check=True, capture_output=True)
            subprocess.run(
                ['sudo', 'tee', path],
                input=content, text=True, check=True, capture_output=True,
            )
            logger.info('nginx conf written via sudo for ct_id=%s', server.ct_id)
        self._reload_nginx()

    def remove_server(self, server) -> None:
        """Removes the nginx conf file for the server and reloads nginx."""
        path = self._conf_path(server)
        if os.path.exists(path):
            logger.info('Removing nginx conf for ct_id=%s: %s', server.ct_id, path)
            try:
                os.remove(path)
            except PermissionError:
                logger.debug('Direct remove of %s denied — falling back to sudo rm', path)
                subprocess.run(['sudo', 'rm', path], check=True, capture_output=True)
            logger.info('nginx conf removed for ct_id=%s', server.ct_id)
            self._reload_nginx()
        else:
            logger.debug('nginx conf not found for ct_id=%s (already removed?): %s', server.ct_id, path)

    def _reload_nginx(self) -> None:
        # Test config first so errors are descriptive rather than silent.
        for cmd in (['nginx', '-t'], ['sudo', 'nginx', '-t']):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                break
        else:
            err_msg = result.stderr.strip() or result.stdout.strip()
            logger.error('nginx config test failed: %s', err_msg)
            raise RuntimeError(f'nginx config test failed: {err_msg}')

        # Reload — try direct first (works when running as root),
        # fall back to sudo granted via /etc/sudoers.d/pgsm-nginx.
        for cmd in (['nginx', '-s', 'reload'], ['sudo', 'nginx', '-s', 'reload']):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info('nginx reloaded successfully')
                return
        err_msg = result.stderr.strip()
        logger.error('nginx reload failed: %s', err_msg)
        raise RuntimeError(f'nginx reload failed: {err_msg}')
