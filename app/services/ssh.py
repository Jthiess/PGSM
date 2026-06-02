import logging
import os

import paramiko
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import current_app

logger = logging.getLogger(__name__)


class SSHManager:
    """Manages the PGSM SSH keypair and all SSH/SFTP operations against game nodes."""

    def _resolve_key_path(self) -> str:
        """Resolves SSH_KEY_PATH to an absolute path.

        Relative paths are resolved against the Flask app root (one level up
        from the app package) so the key is always found regardless of the
        working directory — including from background threads/greenlets.
        """
        key_path = current_app.config['SSH_KEY_PATH']
        if not os.path.isabs(key_path):
            key_path = os.path.join(current_app.root_path, '..', key_path)
        return os.path.normpath(key_path)

    def _known_hosts_path(self) -> str:
        """Path to PGSM's managed known_hosts file (created on first use).

        Stored under the Flask instance folder. The file is created empty if it
        does not exist so paramiko can both verify against and append to it.
        """
        path = os.path.join(current_app.instance_path, 'known_hosts')
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            # Create empty so paramiko.load_host_keys() can read it.
            open(path, 'a').close()
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return path

    def ensure_keypair(self) -> str:
        """Generates a 4096-bit RSA keypair if one does not exist. Returns the public key string."""
        key_path = self._resolve_key_path()
        pub_path = key_path + '.pub'

        if not os.path.exists(key_path):
            logger.info('SSH keypair not found at %s — generating new 4096-bit RSA keypair', key_path)
            os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=4096,
                backend=default_backend(),
            )
            with open(key_path, 'wb') as f:
                f.write(private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.OpenSSH,
                    serialization.NoEncryption(),
                ))
            os.chmod(key_path, 0o600)
            with open(pub_path, 'wb') as f:
                f.write(private_key.public_key().public_bytes(
                    serialization.Encoding.OpenSSH,
                    serialization.PublicFormat.OpenSSH,
                ))
            logger.info('SSH keypair generated and written to %s', key_path)

        with open(pub_path, 'r') as f:
            return f.read().strip()

    def get_client(self, ip: str, username: str = 'root') -> paramiko.SSHClient:
        """Returns a connected, authenticated Paramiko SSH client."""
        key_path = self._resolve_key_path()

        if not os.path.exists(key_path):
            raise FileNotFoundError(
                f'SSH private key not found at {key_path}. '
                f'Has the keypair been generated? (SSH_Key_Path in .env)'
            )

        logger.debug('Opening SSH connection to %s@%s', username, ip)
        try:
            client = paramiko.SSHClient()
            # Trust-on-first-use host-key pinning. paramiko verifies the
            # presented key against this file; a host already recorded with a
            # DIFFERENT key raises BadHostKeyException (blocks MITM/impersonation
            # after the first contact). AutoAddPolicy only fires for hosts not
            # yet seen, recording (pinning) their key to the file.
            client.load_host_keys(self._known_hosts_path())
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                ip,
                username=username,
                key_filename=key_path,
                timeout=5,
                banner_timeout=10,
            )
            return client
        except paramiko.BadHostKeyException as e:
            logger.error(
                'SSH host key mismatch for %s — refusing connection (possible MITM '
                'or the container was rebuilt). Remove the stale entry from '
                'instance/known_hosts if the rebuild was intentional. %s', ip, e,
            )
            raise
        except Exception as e:
            logger.error('SSH connection to %s@%s failed: %s', username, ip, e)
            raise

    def exec(self, ip: str, command: str, username: str = 'root', timeout: int = 60,
             check: bool = False) -> tuple[str, str]:
        """Runs a command on a remote host. Returns (stdout, stderr) as strings.

        Args:
            timeout: Max seconds to wait for the command. Use a large value for
                     install scripts (e.g., 600 for 10-minute installs).
            check:   If True, raises RuntimeError when the remote command exits non-zero.
        """
        # Log at DEBUG level — exec is called frequently (SSH health checks, status
        # polls) and logging every call at INFO would be too noisy in production.
        logger.debug('SSH exec %s: %s', ip, command)
        client = self.get_client(ip, username)
        try:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out, err = stdout.read().decode(), stderr.read().decode()
            exit_code = stdout.channel.recv_exit_status()
            if err and err.strip():
                logger.debug('SSH exec %s stderr: %s', ip, err.strip())
            if check and exit_code != 0:
                raise RuntimeError(
                    f'Remote command exited {exit_code}\n'
                    f'cmd: {command}\n'
                    f'stdout: {out.strip()}\n'
                    f'stderr: {err.strip()}'
                )
            return out, err
        except Exception as e:
            logger.error('SSH exec failed on %s (cmd=%r): %s', ip, command, e)
            raise
        finally:
            client.close()

    def upload_script(self, ip: str, local_path: str, remote_path: str) -> None:
        """Uploads a local file to the remote container via SFTP and makes it executable."""
        logger.debug('SFTP upload %s → %s:%s', local_path, ip, remote_path)
        client = self.get_client(ip)
        try:
            sftp = client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.chmod(remote_path, 0o755)
            sftp.close()
            logger.debug('SFTP upload complete: %s:%s', ip, remote_path)
        except Exception as e:
            logger.error('SFTP upload failed (%s → %s:%s): %s', local_path, ip, remote_path, e)
            raise
        finally:
            client.close()

    def forget_host(self, ip: str) -> None:
        """Removes any pinned host key(s) for an IP from known_hosts.

        Call this when a container is (re)provisioned or deleted so a fresh
        container reusing the same IP is pinned cleanly instead of tripping the
        BadHostKeyException guard.
        """
        try:
            path = self._known_hosts_path()
            host_keys = paramiko.HostKeys(path)
            if ip in host_keys:
                del host_keys[ip]
                host_keys.save(path)
                logger.info('Cleared pinned SSH host key for %s', ip)
        except Exception as e:
            logger.warning('Could not clear pinned host key for %s: %s', ip, e)

    def get_sftp(self, ip: str, username: str = 'root') -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """Returns (ssh_client, sftp_client). Caller is responsible for closing both."""
        logger.debug('Opening SFTP session to %s@%s', username, ip)
        client = self.get_client(ip, username)
        return client, client.open_sftp()
