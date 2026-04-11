"""backup.py — Backup service for PGSM game server containers.

Provides two public functions:

    backup_server(server, backup_dir)  — tar the /PGSM directory on the
        container and pull the archive down to the NFS share via SFTP.

    list_backups(server, backup_dir)   — return metadata for all existing
        backup archives belonging to a given server.

Backup filenames follow the pattern:
    {safe_server_name}_{YYYY-MM-DD_HHMMSS}.tar.gz

where safe_server_name is the server's name with spaces and '/' replaced by '_'.
"""

import os
import glob
from datetime import datetime, timezone

from app.services.ssh import SSHManager

_ssh_mgr = SSHManager()


def _safe_name(server_name: str) -> str:
    """Returns a filesystem-safe version of the server name.

    Replaces spaces and forward-slashes with underscores so the name
    can be used directly as part of a filename.

    Args:
        server_name: The raw ``GameServer.name`` string.

    Returns:
        A sanitised string suitable for use in a filename.
    """
    return server_name.replace(' ', '_').replace('/', '_')


def backup_server(server, backup_dir: str) -> str:
    """Creates a compressed backup of /PGSM on the container and downloads it.

    Workflow:
        1. Build a timestamped filename and a corresponding remote temp path.
        2. Run ``tar -czf`` on the container (timeout=600 s — large worlds can
           take several minutes to compress).
        3. Download the resulting archive to ``backup_dir`` via SFTP.
        4. Best-effort removal of the temp file from the container.

    Args:
        server:     A ``GameServer`` model instance with ``name`` and
                    ``ip_address`` attributes.
        backup_dir: Absolute path on the PGSM host where the archive is saved.
                    Created automatically if it does not exist.

    Returns:
        The filename (not full path) of the newly created backup archive.

    Raises:
        Exception: Propagates any SSH or SFTP error so the caller can
                   surface it in the API response.
    """
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    safe = _safe_name(server.name)
    filename = f'{safe}_{timestamp}.tar.gz'

    # Remote path for the temporary archive on the container.
    # Using /tmp keeps it off the /PGSM volume and avoids including the archive
    # itself in the backup if the operator ever runs this twice simultaneously.
    remote_path = f'/tmp/pgsm_backup_{timestamp}.tar.gz'

    # Ensure the local NFS destination exists before we try to write to it
    os.makedirs(backup_dir, exist_ok=True)
    local_path = os.path.join(backup_dir, filename)

    # Step 1: Create the archive on the container.
    # -C / means paths inside the archive are relative to /, so the top-level
    # entry is PGSM/ — this makes extraction predictable.
    tar_cmd = f'tar -czf {remote_path} -C / PGSM'
    stdout, stderr = _ssh_mgr.exec(server.ip_address, tar_cmd, timeout=600)

    # Step 2: Download the archive from the container to the NFS share.
    ssh_client, sftp = _ssh_mgr.get_sftp(server.ip_address)
    try:
        sftp.get(remote_path, local_path)
    finally:
        sftp.close()
        ssh_client.close()

    # Step 3: Best-effort cleanup of the temp file on the container.
    # We deliberately swallow errors here — a leftover temp file is annoying
    # but should never cause the backup operation itself to be reported as failed.
    try:
        _ssh_mgr.exec(server.ip_address, f'rm -f {remote_path}', timeout=15)
    except Exception:
        pass

    return filename


def list_backups(server, backup_dir: str) -> list[dict]:
    """Returns metadata for all existing backups belonging to ``server``.

    Files are matched by the glob pattern ``{safe_server_name}_*.tar.gz``
    inside ``backup_dir``.  Results are sorted newest-first by file mtime.

    Args:
        server:     A ``GameServer`` model instance with a ``name`` attribute.
        backup_dir: Absolute path on the PGSM host to scan for archives.

    Returns:
        A list of dicts, each containing:
            - ``filename`` (str)  — bare filename (no directory component).
            - ``size_mb``  (float) — file size in megabytes, rounded to 1 dp.
            - ``created``  (str)   — ISO-8601 timestamp derived from file mtime.
        Returns an empty list if the directory does not exist or contains no
        matching files.
    """
    if not os.path.isdir(backup_dir):
        return []

    safe = _safe_name(server.name)
    pattern = os.path.join(backup_dir, f'{safe}_*.tar.gz')
    matches = glob.glob(pattern)

    if not matches:
        return []

    results = []
    for path in matches:
        try:
            stat = os.stat(path)
            size_mb = round(stat.st_size / (1024 * 1024), 1)
            # Convert mtime (seconds since epoch) to an ISO-8601 UTC string
            created = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat()
            results.append({
                'filename': os.path.basename(path),
                'size_mb': size_mb,
                'created': created,
            })
        except OSError:
            # Race condition: file was deleted between glob and stat — skip it
            continue

    # Sort by mtime descending (newest first) using the already-computed
    # 'created' ISO string — ISO-8601 sorts lexicographically
    results.sort(key=lambda d: d['created'], reverse=True)
    return results
