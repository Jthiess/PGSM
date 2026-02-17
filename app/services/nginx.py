import os
import subprocess

from flask import current_app


class NginxService:
    """Manages nginx TCP stream proxy config files for game servers."""

    def _conf_path(self, server) -> str:
        conf_dir = current_app.config['NGINX_CONF_DIR']
        return os.path.join(conf_dir, f'pgsm-{server.ct_id}.conf')

    def _generate_stream_block(self, server) -> str:
        """Generates an nginx stream block to TCP-proxy a game server port.

        NOTE: Requires the controller's nginx.conf to have:
            stream {
                include /etc/nginx/conf.d/*.conf;
            }
        This is a one-time manual setup prerequisite.
        """
        return (
            f"# PGSM Auto-generated: {server.name} (CT {server.ct_id})\n"
            f"upstream pgsm_{server.ct_id} {{\n"
            f"    server {server.ip_address}:{server.game_port};\n"
            f"}}\n"
            f"server {{\n"
            f"    listen {server.game_port};\n"
            f"    proxy_pass pgsm_{server.ct_id};\n"
            f"}}\n"
        )

    def add_server(self, server) -> None:
        """Writes an nginx conf file for the server and reloads nginx."""
        path = self._conf_path(server)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(self._generate_stream_block(server))
        self._reload_nginx()

    def remove_server(self, server) -> None:
        """Removes the nginx conf file for the server and reloads nginx."""
        path = self._conf_path(server)
        if os.path.exists(path):
            os.remove(path)
            self._reload_nginx()

    def _reload_nginx(self) -> None:
        # Try direct reload first (works when running as root).
        # Fall back to sudo, which the setup script grants via /etc/sudoers.d/pgsm-nginx.
        for cmd in (['nginx', '-s', 'reload'], ['sudo', 'nginx', '-s', 'reload']):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return
        raise RuntimeError(f'nginx reload failed: {result.stderr.strip()}')
