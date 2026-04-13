import ipaddress
import logging

from flask import current_app
from proxmoxer import ProxmoxAPI

logger = logging.getLogger(__name__)


class ProxmoxService:
    """Wraps proxmoxer to manage Proxmox nodes and LXC containers."""

    def __init__(self):
        self._api: ProxmoxAPI | None = None

    def _get_api(self) -> ProxmoxAPI:
        if self._api is None:
            cfg = current_app.config
            host = cfg.get('PROXMOX_HOST')
            user = cfg.get('PROXMOX_USERNAME')
            password = cfg.get('PROXMOX_PASSWORD')

            missing = [k for k, v in [('Proxmox_Host', host), ('Proxmox_Username', user), ('Proxmox_Password', password)] if not v]
            if missing:
                raise RuntimeError(
                    f"Proxmox connection not configured. Missing from .env: {', '.join(missing)}"
                )

            logger.info('Connecting to Proxmox API at %s (user=%s)', host, user)
            self._api = ProxmoxAPI(
                host,
                user=user,
                password=password,
                port=cfg['PROXMOX_PORT'],
                verify_ssl=False,
            )
        return self._api

    def get_nodes(self) -> list[dict]:
        """Returns list of online Proxmox nodes."""
        return [n for n in self._get_api().nodes.get() if n['status'] == 'online']

    def get_next_ct_id(self) -> int:
        """Returns the lowest available CT ID at or above 500."""
        api = self._get_api()
        existing_ids: set[int] = set()
        for node in api.nodes.get():
            for ct in api.nodes(node['node']).lxc.get():
                existing_ids.add(int(ct['vmid']))
        ct_id = 500
        while ct_id in existing_ids:
            ct_id += 1
        return ct_id

    def get_next_ip(self, used_ips: list[str]) -> str:
        """Returns the next available IP in the PGSM VLAN subnet.

        Skips everything below PGSM_VLAN_IP_Start (reserved for Proxmox nodes,
        router, controller, etc.) and anything already assigned to a server in the DB.
        """
        subnet = ipaddress.IPv4Network(current_app.config['PGSM_VLAN_SUBNET'])
        ip_start = ipaddress.IPv4Address(current_app.config['PGSM_VLAN_IP_START'])
        reserved = {ipaddress.IPv4Address(ip) for ip in used_ips if ip}
        for host in subnet.hosts():
            if host < ip_start:
                continue
            if host not in reserved:
                return str(host)
        raise RuntimeError('No available IPs in the PGSM VLAN subnet.')

    def create_lxc(
        self,
        node: str,
        ct_id: int,
        hostname: str,
        ip: str,
        disk_gb: int,
        cores: int,
        memory_mb: int,
        pubkey: str,
    ) -> None:
        """Creates an unprivileged LXC container with PGSM networking and starts it."""
        logger.info(
            'Creating LXC container ct_id=%s hostname=%s ip=%s node=%s '
            'disk=%dGB cores=%d memory=%dMB',
            ct_id, hostname, ip, node, disk_gb, cores, memory_mb,
        )
        api = self._get_api()
        cfg = current_app.config
        gateway = cfg['PGSM_VLAN_GATEWAY']
        template = cfg['PGSM_LXC_TEMPLATE']

        try:
            api.nodes(node).lxc.post(**{
                'vmid': ct_id,
                'ostemplate': template,
                'hostname': hostname,
                'unprivileged': 1,
                'cores': cores,
                'memory': memory_mb,
                'rootfs': f'kestrel:{disk_gb}',
                'net0': f'name=eth0,bridge=PGSM,ip={ip}/24,gw={gateway}',
                'nameserver': '1.1.1.1',
                'searchdomain': 'PGSM.lan',
                'ssh-public-keys': pubkey,
                'features': 'nesting=1',
                'tags': 'pgsm',
                'start': 1,
            })
            logger.info('LXC container ct_id=%s created and start signal sent', ct_id)
        except Exception as e:
            logger.error('Failed to create LXC container ct_id=%s: %s', ct_id, e, exc_info=True)
            raise

    def enable_ha(self, ct_id: int) -> None:
        """Registers an LXC container with Proxmox HA (no group, state=started).

        Requires the Proxmox cluster to have HA configured. If the cluster has
        no HA manager running, this will raise an exception.
        """
        logger.info('Enabling HA for ct_id=%s', ct_id)
        try:
            self._get_api().cluster.ha.resources.post(sid=f'lxc:{ct_id}', state='started')
            logger.info('HA enabled for ct_id=%s', ct_id)
        except Exception as e:
            logger.error('Failed to enable HA for ct_id=%s: %s', ct_id, e, exc_info=True)
            raise

    def disable_ha(self, ct_id: int) -> None:
        """Removes an LXC container from Proxmox HA management.

        Safe to call even if HA was never enabled — Proxmox returns 404 which
        callers should catch and ignore.
        """
        logger.info('Disabling HA for ct_id=%s', ct_id)
        try:
            self._get_api().cluster.ha.resources(f'lxc:{ct_id}').delete()
            logger.info('HA disabled for ct_id=%s', ct_id)
        except Exception as e:
            logger.error('Failed to disable HA for ct_id=%s: %s', ct_id, e, exc_info=True)
            raise

    def update_ct_resources(
        self,
        node: str,
        ct_id: int,
        cores: int | None = None,
        memory_mb: int | None = None,
    ) -> None:
        """Updates CPU and/or memory allocation on an existing LXC container.

        Proxmox applies CPU/memory changes immediately to running containers.
        """
        params: dict = {}
        if cores is not None:
            params['cores'] = cores
        if memory_mb is not None:
            params['memory'] = memory_mb
        if params:
            logger.info('Updating resources for ct_id=%s on node=%s: %s', ct_id, node, params)
            try:
                self._get_api().nodes(node).lxc(ct_id).config.put(**params)
                logger.info('Resources updated for ct_id=%s', ct_id)
            except Exception as e:
                logger.error('Failed to update resources for ct_id=%s: %s', ct_id, e, exc_info=True)
                raise

    def start_ct(self, node: str, ct_id: int) -> None:
        logger.info('Starting CT ct_id=%s on node=%s', ct_id, node)
        try:
            self._get_api().nodes(node).lxc(ct_id).status.start.post()
            logger.info('Start signal sent to ct_id=%s', ct_id)
        except Exception as e:
            logger.error('Failed to start ct_id=%s: %s', ct_id, e, exc_info=True)
            raise

    def stop_ct(self, node: str, ct_id: int, wait: bool = False, timeout: int = 60) -> None:
        """Sends a stop signal to an LXC container.

        If wait=True, blocks until the container reports 'stopped' status or
        timeout seconds elapse (raises RuntimeError on timeout).
        """
        import time
        logger.info('Stopping CT ct_id=%s on node=%s (wait=%s, timeout=%ds)', ct_id, node, wait, timeout)
        try:
            self._get_api().nodes(node).lxc(ct_id).status.stop.post()
            logger.info('Stop signal sent to ct_id=%s', ct_id)
        except Exception as e:
            logger.error('Failed to send stop signal to ct_id=%s: %s', ct_id, e, exc_info=True)
            raise
        if wait:
            deadline = time.time() + timeout
            while time.time() < deadline:
                time.sleep(2)
                try:
                    status = self._get_api().nodes(node).lxc(ct_id).status.current.get()
                    if status.get('status') == 'stopped':
                        logger.info('CT ct_id=%s confirmed stopped', ct_id)
                        return
                except Exception:
                    pass
            raise RuntimeError(f'CT {ct_id} did not stop within {timeout}s')

    def delete_ct(self, node: str, ct_id: int) -> None:
        """Permanently deletes an LXC container from Proxmox. Container must be stopped first."""
        logger.info('Deleting CT ct_id=%s on node=%s', ct_id, node)
        try:
            self._get_api().nodes(node).lxc(ct_id).delete()
            logger.info('CT ct_id=%s deleted', ct_id)
        except Exception as e:
            logger.error('Failed to delete ct_id=%s: %s', ct_id, e, exc_info=True)
            raise

    def get_ct_status(self, node: str, ct_id: int) -> dict:
        logger.debug('Querying status for ct_id=%s on node=%s', ct_id, node)
        try:
            status = self._get_api().nodes(node).lxc(ct_id).status.current.get()
            logger.debug('ct_id=%s status=%s', ct_id, status.get('status'))
            return status
        except Exception as e:
            logger.error('Failed to get status for ct_id=%s: %s', ct_id, e, exc_info=True)
            raise
