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

    def ensure_keypair(self) -> str:
        """Generates a 4096-bit RSA keypair if one does not exist. Returns the public key string."""
        key_path = current_app.config['SSH_KEY_PATH']
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
        key_path = current_app.config['SSH_KEY_PATH']
        # Resolve relative paths against the Flask app root so this works
        # correctly from background threads regardless of working directory
        if not os.path.isabs(key_path):
            key_path = os.path.join(current_app.root_path, '..', key_path)
        key_path = os.path.normpath(key_path)

        if not os.path.exists(key_path):
            raise FileNotFoundError(
                f'SSH private key not found at {key_path}. '
                f'Has the keypair been generated? (SSH_Key_Path in .env)'
            )

        logger.debug('Opening SSH connection to %s@%s', username, ip)
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                ip,
                username=username,
                key_filename=key_path,
                timeout=5,
                banner_timeout=10,
            )
            return client
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

    def get_sftp(self, ip: str, username: str = 'root') -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """Returns (ssh_client, sftp_client). Caller is responsible for closing both."""
        logger.debug('Opening SFTP session to %s@%s', username, ip)
        client = self.get_client(ip, username)
        return client, client.open_sftp()
