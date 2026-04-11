"""app/services/nfs.py — NFS mount management service.

Provides functions to list, mount, and unmount NFS filesystems. All
subprocess calls use list-form arguments (no shell=True) and all inputs
are validated with strict regex patterns before use to prevent command
injection.

The app runs as root on Linux, so mount/umount are available without
additional privilege escalation.
"""

import os
import re
import subprocess

# ---------------------------------------------------------------------------
# Input validation patterns
# These patterns are intentionally strict — only the characters that are
# genuinely needed for valid NFS paths/addresses are permitted.
# ---------------------------------------------------------------------------

# Hostnames, IPv4 addresses, and simple FQDNs (no slash, no spaces)
_RE_SERVER_ADDR = re.compile(r'^[a-zA-Z0-9._\-]+$')

# Absolute paths containing only safe filesystem characters
_RE_PATH = re.compile(r'^[a-zA-Z0-9/_.\-]+$')

# Mount options: comma-separated key or key=value pairs
_RE_OPTIONS = re.compile(r'^[a-zA-Z0-9,=._\-]+$')


def list_nfs_mounts() -> list[dict]:
    """Return all currently mounted NFS filesystems from /proc/mounts.

    Reads the kernel's live mount table and filters to entries whose
    filesystem type is ``nfs`` or ``nfs4``.

    Returns:
        A list of dicts, each with keys:
            - ``device``      (str): The NFS source, e.g. ``192.168.1.10:/exports/data``
            - ``mount_point`` (str): Local mount path, e.g. ``/mnt/backup``
            - ``fstype``      (str): ``nfs`` or ``nfs4``
            - ``options``     (str): Mount option string, e.g. ``rw,relatime``

        Returns an empty list if ``/proc/mounts`` is absent or cannot be parsed.
    """
    proc_mounts = '/proc/mounts'
    results = []
    try:
        with open(proc_mounts, 'r') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                # /proc/mounts fields: device mount_point fstype options dump pass
                parts = line.split()
                if len(parts) < 4:
                    continue
                device, mount_point, fstype, options = parts[0], parts[1], parts[2], parts[3]
                if fstype in ('nfs', 'nfs4'):
                    results.append({
                        'device': device,
                        'mount_point': mount_point,
                        'fstype': fstype,
                        'options': options,
                    })
    except (FileNotFoundError, OSError, ValueError):
        # Silently return empty list — caller decides how to surface this
        return []
    return results


def mount_nfs(server_addr: str, remote_path: str, mount_point: str, options: str = 'defaults') -> None:
    """Mount a remote NFS export at the given local path.

    Validates all inputs with strict regex before invoking ``mount`` to
    prevent command injection. Creates the mount-point directory if it
    does not already exist.

    Args:
        server_addr:  NFS server hostname or IP address (e.g. ``192.168.1.10``).
        remote_path:  Exported path on the NFS server (e.g. ``/exports/minecraft``).
                      Must be an absolute path.
        mount_point:  Local directory to mount onto (e.g. ``/mnt/minecraft``).
                      Must be an absolute path. Created if absent.
        options:      Mount option string passed to ``-o`` (default ``defaults``).

    Raises:
        ValueError:   If any argument fails input validation.
        RuntimeError: If the ``mount`` command exits with a non-zero return code.
                      The error message includes stderr from the subprocess.
    """
    # --- Input validation ---------------------------------------------------
    # Each pattern check also catches the absolute-path requirement because
    # _RE_PATH requires the string to start with '/' for path arguments.
    if not _RE_SERVER_ADDR.match(server_addr):
        raise ValueError(f'Invalid server_addr: {server_addr!r}')
    if not remote_path.startswith('/') or not _RE_PATH.match(remote_path):
        raise ValueError(f'Invalid remote_path: {remote_path!r}')
    if not mount_point.startswith('/') or not _RE_PATH.match(mount_point):
        raise ValueError(f'Invalid mount_point: {mount_point!r}')
    if not _RE_OPTIONS.match(options):
        raise ValueError(f'Invalid options: {options!r}')

    # --- Ensure local mount-point directory exists -------------------------
    os.makedirs(mount_point, exist_ok=True)

    # --- Run mount ----------------------------------------------------------
    # List-form subprocess call — never shell=True.
    # Timeout of 30 s guards against a hung NFS server blocking the request.
    nfs_source = f'{server_addr}:{remote_path}'
    result = subprocess.run(
        ['mount', '-t', 'nfs', nfs_source, mount_point, '-o', options],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f'mount failed: {result.stderr.strip()}')


def unmount_nfs(mount_point: str) -> None:
    """Unmount an NFS filesystem from the given local path.

    Validates the mount point with a strict regex before invoking ``umount``
    to prevent command injection.

    Args:
        mount_point: Local directory that is currently mounted (e.g. ``/mnt/minecraft``).
                     Must be an absolute path matching ``^[a-zA-Z0-9/_.\-]+$``.

    Raises:
        ValueError:   If ``mount_point`` fails input validation.
        RuntimeError: If the ``umount`` command exits with a non-zero return code.
                      The error message includes stderr from the subprocess.
    """
    # --- Input validation ---------------------------------------------------
    if not mount_point.startswith('/') or not _RE_PATH.match(mount_point):
        raise ValueError(f'Invalid mount_point: {mount_point!r}')

    # --- Run umount ---------------------------------------------------------
    result = subprocess.run(
        ['umount', mount_point],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f'umount failed: {result.stderr.strip()}')
