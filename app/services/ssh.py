import os

import paramiko
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import current_app


class SSHManager:
    """Manages the PGSM SSH keypair and all SSH/SFTP operations against game nodes."""

    def ensure_keypair(self) -> str:
        """Generates a 4096-bit RSA keypair if one does not exist. Returns the public key string."""
        key_path = current_app.config['SSH_KEY_PATH']
        pub_path = key_path + '.pub'

        if not os.path.exists(key_path):
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

        with open(pub_path, 'r') as f:
            return f.read().strip()

    def get_client(self, ip: str, username: str = 'root') -> paramiko.SSHClient:
        """Returns a connected, authenticated Paramiko SSH client."""
        key_path = current_app.config['SSH_KEY_PATH']
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            ip,
            username=username,
            key_filename=key_path,
            timeout=15,
            banner_timeout=30,
        )
        return client

    def exec(self, ip: str, command: str, username: str = 'root', timeout: int = 60) -> tuple[str, str]:
        """Runs a command on a remote host. Returns (stdout, stderr) as strings.

        Args:
            timeout: Max seconds to wait for the command. Use a large value for
                     install scripts (e.g., 600 for 10-minute installs).
        """
        client = self.get_client(ip, username)
        try:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            return stdout.read().decode(), stderr.read().decode()
        finally:
            client.close()

    def upload_script(self, ip: str, local_path: str, remote_path: str) -> None:
        """Uploads a local file to the remote container via SFTP and makes it executable."""
        client = self.get_client(ip)
        try:
            sftp = client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.chmod(remote_path, 0o755)
            sftp.close()
        finally:
            client.close()

    def get_sftp(self, ip: str, username: str = 'root') -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """Returns (ssh_client, sftp_client). Caller is responsible for closing both."""
        client = self.get_client(ip, username)
        return client, client.open_sftp()
