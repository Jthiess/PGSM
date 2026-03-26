# ============================================================
# app/services/panel_db.py — Game-Panel PostgreSQL Service
# All database operations for the public-facing game panel.
# Uses the 'servers' schema for active/archive tables and the
# 'public' schema for whitelist and pgsm_servers tables.
# ============================================================

import os
import random
import logging
from datetime import date, datetime
from uuid import UUID

import requests

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False

from flask import current_app

log = logging.getLogger(__name__)


# ============================================================
# Connection helpers
# ============================================================

def get_db_connection():
    """Open a psycopg2 connection scoped to the public schema.

    Reads all credentials from current_app.config['PANEL_DB_*'].
    Returns a psycopg2 connection object with search_path set to
    the configured public schema.

    Raises RuntimeError if psycopg2 is not installed.
    """
    if not _PSYCOPG2_AVAILABLE:
        raise RuntimeError(
            "psycopg2-binary is not installed. "
            "Run: pip install psycopg2-binary"
        )

    cfg = current_app.config
    conn = psycopg2.connect(
        host=cfg['PANEL_DB_HOST'],
        port=cfg['PANEL_DB_PORT'],
        dbname=cfg['PANEL_DB_NAME'],
        user=cfg['PANEL_DB_USER'],
        password=cfg['PANEL_DB_PASSWORD'],
        connect_timeout=5,
    )

    # Operate within the public schema by default
    schema = cfg['PANEL_DB_SCHEMA']
    with conn.cursor() as cur:
        cur.execute("SET search_path TO %s", (schema,))
    conn.commit()

    return conn


def _get_servers_db_connection():
    """Open a psycopg2 connection scoped to the servers schema.

    Used for active/archive server card tables.
    Returns a psycopg2 connection with search_path set to the
    configured servers schema.
    """
    if not _PSYCOPG2_AVAILABLE:
        raise RuntimeError(
            "psycopg2-binary is not installed. "
            "Run: pip install psycopg2-binary"
        )

    cfg = current_app.config
    conn = psycopg2.connect(
        host=cfg['PANEL_DB_HOST'],
        port=cfg['PANEL_DB_PORT'],
        dbname=cfg['PANEL_DB_NAME'],
        user=cfg['PANEL_DB_USER'],
        password=cfg['PANEL_DB_PASSWORD'],
        connect_timeout=5,
    )

    # Ensure servers schema exists before setting search path
    servers_schema = cfg['PANEL_DB_SERVERS_SCHEMA']
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {servers_schema}")
        cur.execute(f"SET search_path TO {servers_schema}")
    conn.commit()

    return conn


# ============================================================
# Schema / table initialisation
# ============================================================

def init_db_tables():
    """Create all required schemas and tables if they do not already exist.

    Safe to call on every startup — all statements use IF NOT EXISTS.
    Also applies lightweight migrations for columns added after the
    initial schema (client_ip, sequence fixes, ptero_servers rename).
    """
    if not _PSYCOPG2_AVAILABLE:
        raise RuntimeError("psycopg2 is not installed; panel DB unavailable")
    cfg = current_app.config
    public_schema = cfg['PANEL_DB_SCHEMA']
    servers_schema = cfg['PANEL_DB_SERVERS_SCHEMA']

    conn = None
    try:
        # Use a direct connection (no schema pre-set) so we can create schemas
        conn = psycopg2.connect(
            host=cfg['PANEL_DB_HOST'],
            port=cfg['PANEL_DB_PORT'],
            dbname=cfg['PANEL_DB_NAME'],
            user=cfg['PANEL_DB_USER'],
            password=cfg['PANEL_DB_PASSWORD'],
            connect_timeout=5,
        )

        with conn.cursor() as cur:
            # --------------------------------------------------
            # Create schemas
            # --------------------------------------------------
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {public_schema}")
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {servers_schema}")

            # --------------------------------------------------
            # Public schema tables: whitelist, pgsm_servers
            # --------------------------------------------------
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {public_schema}.whitelist (
                    id              SERIAL PRIMARY KEY,
                    username        TEXT NOT NULL,
                    player_uuid     TEXT NOT NULL,
                    discord_username TEXT NOT NULL,
                    approved        BOOLEAN NOT NULL DEFAULT FALSE,
                    client_ip       TEXT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {public_schema}.pgsm_servers (
                    id        SERIAL PRIMARY KEY,
                    name      TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    enabled   BOOLEAN NOT NULL DEFAULT TRUE
                )
                """
            )

            # --------------------------------------------------
            # Servers schema tables: active, archive
            # --------------------------------------------------
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {servers_schema}.active (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    game        TEXT,
                    description TEXT,
                    ip          TEXT,
                    version     TEXT,
                    motd        TEXT DEFAULT '',
                    online      BOOLEAN NOT NULL DEFAULT FALSE,
                    playing_now INTEGER DEFAULT 0,
                    playing_max INTEGER DEFAULT 0,
                    modded      BOOLEAN NOT NULL DEFAULT FALSE,
                    pack_name   TEXT,
                    pack_link   TEXT,
                    pack_desc   TEXT,
                    pack_img_id TEXT,
                    pack_version TEXT
                )
                """
            )

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {servers_schema}.archive (
                    id              SERIAL PRIMARY KEY,
                    name            TEXT NOT NULL,
                    game            TEXT,
                    description     TEXT,
                    motd            TEXT,
                    version         TEXT,
                    file_size       TEXT,
                    retirement_date DATE,
                    world_link      TEXT,
                    modded          BOOLEAN NOT NULL DEFAULT FALSE,
                    pack_name       TEXT,
                    pack_link       TEXT,
                    pack_desc       TEXT,
                    pack_img_id     TEXT,
                    pack_version    TEXT
                )
                """
            )

            # --------------------------------------------------
            # Lightweight migrations
            # --------------------------------------------------

            # Ensure client_ip column exists (older deployments may be missing it)
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'whitelist'
                """,
                (public_schema,),
            )
            existing_cols = [row[0] for row in cur.fetchall()]
            if 'client_ip' not in existing_cols:
                cur.execute(
                    f"ALTER TABLE {public_schema}.whitelist ADD COLUMN client_ip TEXT"
                )

            # Migrate ptero_servers -> pgsm_servers if legacy table still exists
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = %s AND table_name = 'ptero_servers'
                """,
                (public_schema,),
            )
            if cur.fetchone():
                cur.execute(
                    f"""
                    INSERT INTO {public_schema}.pgsm_servers (name, server_id, enabled)
                    SELECT name, server_id, enabled FROM {public_schema}.ptero_servers
                    ON CONFLICT DO NOTHING
                    """
                )
                cur.execute(f"DROP TABLE {public_schema}.ptero_servers")

            # Fix whitelist sequence to match current max id
            cur.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{public_schema}.whitelist', 'id'),
                    COALESCE((SELECT MAX(id) FROM {public_schema}.whitelist), 0) + 1,
                    false
                )
                """
            )

        conn.commit()
        log.info("Panel DB tables initialised successfully.")

    except Exception:
        log.exception("panel_db.init_db_tables failed")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


# ============================================================
# Active server helpers
# ============================================================

def _format_date(d):
    """Format a date/datetime as M/D/YYYY string; return as-is if already a string."""
    try:
        if d is None:
            return None
        if isinstance(d, str):
            return d
        try:
            return d.strftime('%-m/%-d/%Y')
        except Exception:
            return d.strftime('%m/%d/%Y')
    except Exception:
        return str(d) if d is not None else None


def _row_to_active_card(row: dict) -> dict:
    """Map a DB row from active to the template's expected card dict."""
    card = {
        'id': row.get('id'),
        'name': row.get('name'),
        'motd': row.get('motd'),
        'online': row.get('online', False),
        'game': row.get('game'),
        'playing_now': row.get('playing_now'),
        'playing_max': row.get('playing_max'),
        'version': row.get('version'),
        'description': row.get('description'),
        'ip': row.get('ip'),
        'modded': row.get('modded', False),
        # Hyphenated keys expected by template JS
        'pack-name': row.get('pack_name'),
        'pack-link': row.get('pack_link'),
        'pack-desc': row.get('pack_desc'),
        'pack-img-id': row.get('pack_img_id'),
        'pack-version': row.get('pack_version'),
    }
    card['image'] = _get_card_image(card.get('game', '')).lower()
    return card


def _row_to_archive_card(row: dict) -> dict:
    """Map a DB row from archive to the template's expected card dict."""
    card = {
        'id': row.get('id'),
        'name': row.get('name'),
        'motd': row.get('motd'),
        'game': row.get('game'),
        'version': row.get('version'),
        'description': row.get('description'),
        'file_size': row.get('file_size'),
        'retirement_date': _format_date(row.get('retirement_date')),
        'modded': row.get('modded', False),
        'pack-name': row.get('pack_name'),
        'pack-link': row.get('pack_link'),
        'pack-desc': row.get('pack_desc'),
        'pack-img-id': row.get('pack_img_id'),
        'pack-version': row.get('pack_version'),
        'world_link': row.get('world_link'),
    }
    card['image'] = _get_card_image(card.get('game', '')).lower()
    return card


def _get_card_image(name: str) -> str:
    """Resolve a game-type card image path, falling back to default.jpg."""
    image_name = name.lower().replace(' ', '-') + '.jpg'
    # Resolve relative to app static directory
    static_dir = os.path.join(current_app.root_path, 'static', 'images', 'cards')
    image_path = os.path.join(static_dir, image_name)
    if os.path.exists(image_path) and image_name.strip() != '.jpg':
        return f'/static/images/cards/{image_name}'
    return '/static/images/cards/default.jpg'


def get_active_servers() -> list:
    """Fetch all active server rows from servers.active, ordered by id ASC.

    Returns a list of dicts mapped through _row_to_active_card.
    Returns [] on any DB error.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, motd, online, game, playing_now, playing_max,
                       version, description, ip, modded,
                       pack_name, pack_link, pack_desc, pack_img_id, pack_version
                FROM active
                ORDER BY id ASC
                """
            )
            return [_row_to_active_card(dict(r)) for r in cur.fetchall()]
    except Exception:
        log.exception("panel_db.get_active_servers failed")
        return []
    finally:
        if conn:
            conn.close()


def get_archived_servers() -> list:
    """Fetch all archived server rows from servers.archive, newest first.

    Returns a list of dicts mapped through _row_to_archive_card.
    Returns [] on any DB error.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, motd, game, version, description, file_size,
                       retirement_date, modded,
                       pack_name, pack_link, pack_desc, pack_img_id, pack_version,
                       world_link
                FROM archive
                ORDER BY retirement_date DESC NULLS LAST, id DESC
                """
            )
            return [_row_to_archive_card(dict(r)) for r in cur.fetchall()]
    except Exception:
        log.exception("panel_db.get_archived_servers failed")
        return []
    finally:
        if conn:
            conn.close()


def get_server_by_id(server_id: int) -> dict | None:
    """Fetch a single active server row by id.

    Args:
        server_id: The integer primary key.

    Returns:
        A dict of raw column values, or None if not found.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, game, description, ip, version, modded,
                       pack_name, pack_link, pack_desc, pack_img_id, pack_version,
                       motd, online, playing_now, playing_max
                FROM active
                WHERE id = %s
                """,
                (server_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        log.exception("panel_db.get_server_by_id failed")
        return None
    finally:
        if conn:
            conn.close()


def get_archived_server_by_id(server_id: int) -> dict | None:
    """Fetch a single archived server row by id.

    Args:
        server_id: The integer primary key.

    Returns:
        A dict of raw column values with retirement_date formatted for a
        date input (YYYY-MM-DD), or None if not found.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, motd, game, description, version, file_size,
                       retirement_date, world_link, modded,
                       pack_name, pack_link, pack_desc, pack_img_id, pack_version
                FROM archive
                WHERE id = %s
                """,
                (server_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            server = dict(row)
            # Format date for HTML date input (expects YYYY-MM-DD)
            if server.get('retirement_date') and isinstance(server['retirement_date'], date):
                server['retirement_date'] = server['retirement_date'].strftime('%Y-%m-%d')
            return server
    except Exception:
        log.exception("panel_db.get_archived_server_by_id failed")
        return None
    finally:
        if conn:
            conn.close()


def create_server(data: dict) -> None:
    """Insert a new row into servers.active.

    Args:
        data: Dict with keys: name, game, description, ip, version, modded,
              pack_name, pack_link, pack_desc, pack_img_id, pack_version.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO active
                    (name, game, description, ip, version, modded,
                     pack_name, pack_link, pack_desc, pack_img_id, pack_version,
                     motd, online, playing_now, playing_max)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    data.get('name'), data.get('game'), data.get('description'),
                    data.get('ip'), data.get('version'), data.get('modded', False),
                    data.get('pack_name'), data.get('pack_link'), data.get('pack_desc'),
                    data.get('pack_img_id'), data.get('pack_version'),
                    '', False, 0, 0,
                ),
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.create_server failed")
        raise
    finally:
        if conn:
            conn.close()


def update_server(server_id: int, data: dict) -> None:
    """Update an existing row in servers.active.

    Args:
        server_id: The integer primary key to update.
        data: Dict with keys: name, game, description, ip, version, modded,
              pack_name, pack_link, pack_desc, pack_img_id, pack_version.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE active
                SET name = %s, game = %s, description = %s, ip = %s, version = %s,
                    modded = %s, pack_name = %s, pack_link = %s, pack_desc = %s,
                    pack_img_id = %s, pack_version = %s
                WHERE id = %s
                """,
                (
                    data.get('name'), data.get('game'), data.get('description'),
                    data.get('ip'), data.get('version'), data.get('modded', False),
                    data.get('pack_name'), data.get('pack_link'), data.get('pack_desc'),
                    data.get('pack_img_id'), data.get('pack_version'),
                    server_id,
                ),
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.update_server failed")
        raise
    finally:
        if conn:
            conn.close()


def delete_server(server_id: int) -> None:
    """Delete an active server row by id.

    Args:
        server_id: The integer primary key to delete.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM active WHERE id = %s", (server_id,))
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.delete_server failed")
        raise
    finally:
        if conn:
            conn.close()


# ============================================================
# Archived server helpers
# ============================================================

def _parse_retirement_date(date_input: str):
    """Parse a retirement date string into a date object.

    Accepts 'now' (returns today), 'YYYY-MM-DD', or None for empty input.
    """
    if not date_input:
        return None
    if date_input.lower() == 'now':
        return date.today()
    return datetime.strptime(date_input, '%Y-%m-%d').date()


def create_archived_server(data: dict) -> None:
    """Insert a new row into servers.archive.

    Args:
        data: Dict with keys: name, motd, game, description, version, file_size,
              retirement_date (str or date), world_link, modded,
              pack_name, pack_link, pack_desc, pack_img_id, pack_version.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        retirement_date = data.get('retirement_date')
        if isinstance(retirement_date, str):
            retirement_date = _parse_retirement_date(retirement_date)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO archive
                    (name, motd, game, description, version, file_size,
                     retirement_date, world_link, modded,
                     pack_name, pack_link, pack_desc, pack_img_id, pack_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    data.get('name'), data.get('motd'), data.get('game'),
                    data.get('description'), data.get('version'), data.get('file_size'),
                    retirement_date, data.get('world_link'), data.get('modded', False),
                    data.get('pack_name'), data.get('pack_link'), data.get('pack_desc'),
                    data.get('pack_img_id'), data.get('pack_version'),
                ),
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.create_archived_server failed")
        raise
    finally:
        if conn:
            conn.close()


def update_archived_server(server_id: int, data: dict) -> None:
    """Update an existing row in servers.archive.

    Args:
        server_id: The integer primary key to update.
        data: Same shape as create_archived_server data dict.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        retirement_date = data.get('retirement_date')
        if isinstance(retirement_date, str):
            retirement_date = _parse_retirement_date(retirement_date)

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE archive
                SET name = %s, motd = %s, game = %s, description = %s, version = %s,
                    file_size = %s, retirement_date = %s, world_link = %s,
                    modded = %s, pack_name = %s, pack_link = %s, pack_desc = %s,
                    pack_img_id = %s, pack_version = %s
                WHERE id = %s
                """,
                (
                    data.get('name'), data.get('motd'), data.get('game'),
                    data.get('description'), data.get('version'), data.get('file_size'),
                    retirement_date, data.get('world_link'), data.get('modded', False),
                    data.get('pack_name'), data.get('pack_link'), data.get('pack_desc'),
                    data.get('pack_img_id'), data.get('pack_version'),
                    server_id,
                ),
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.update_archived_server failed")
        raise
    finally:
        if conn:
            conn.close()


def delete_archived_server(server_id: int) -> None:
    """Delete an archived server row by id.

    Args:
        server_id: The integer primary key to delete.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM archive WHERE id = %s", (server_id,))
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.delete_archived_server failed")
        raise
    finally:
        if conn:
            conn.close()


# ============================================================
# Whitelist helpers
# ============================================================

def get_whitelist_entries() -> list:
    """Fetch all whitelist entries ordered by created_at DESC.

    Returns a list of dicts with all whitelist columns.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, username, player_uuid, discord_username,
                       client_ip, approved, created_at
                FROM whitelist
                ORDER BY created_at DESC
                """
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        log.exception("panel_db.get_whitelist_entries failed")
        return []
    finally:
        if conn:
            conn.close()


def get_approved_whitelist_entries() -> list:
    """Fetch only approved whitelist entries.

    Returns a list of dicts with username and player_uuid fields,
    formatted for use in Minecraft whitelist.json.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT username, player_uuid FROM whitelist WHERE approved = TRUE"
            )
            entries = []
            for row in cur.fetchall():
                raw_uuid = row['player_uuid']
                try:
                    formatted_uuid = str(UUID(raw_uuid))
                except Exception:
                    formatted_uuid = raw_uuid
                entries.append({'name': row['username'], 'uuid': formatted_uuid})
            return entries
    except Exception:
        log.exception("panel_db.get_approved_whitelist_entries failed")
        return []
    finally:
        if conn:
            conn.close()


def get_whitelist_entry_by_id(entry_id: int) -> dict | None:
    """Fetch a single whitelist entry by id.

    Args:
        entry_id: The integer primary key.

    Returns:
        A dict of all whitelist columns, or None if not found.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM whitelist WHERE id = %s", (entry_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        log.exception("panel_db.get_whitelist_entry_by_id failed")
        return None
    finally:
        if conn:
            conn.close()


def create_whitelist_entry(data: dict) -> None:
    """Insert a new whitelist request with approved=False.

    Args:
        data: Dict with keys: username, player_uuid, discord_username, client_ip.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO whitelist
                    (username, player_uuid, discord_username, approved, client_ip)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    data['username'],
                    data['player_uuid'],
                    data['discord_username'],
                    False,
                    data.get('client_ip'),
                ),
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.create_whitelist_entry failed")
        raise
    finally:
        if conn:
            conn.close()


def toggle_whitelist_approval(entry_id: int) -> bool:
    """Toggle the approved boolean for a whitelist entry.

    Args:
        entry_id: The integer primary key.

    Returns:
        The new approved state (True or False).
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE whitelist SET approved = NOT approved WHERE id = %s RETURNING approved",
                (entry_id,),
            )
            result = cur.fetchone()
        conn.commit()
        return bool(result[0]) if result else False
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.toggle_whitelist_approval failed")
        raise
    finally:
        if conn:
            conn.close()


def delete_whitelist_entry(entry_id: int) -> None:
    """Delete a whitelist entry by id.

    Args:
        entry_id: The integer primary key to delete.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM whitelist WHERE id = %s", (entry_id,))
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.delete_whitelist_entry failed")
        raise
    finally:
        if conn:
            conn.close()


def count_whitelist_requests_by_discord(discord_username: str) -> int:
    """Count existing whitelist requests from a given Discord username.

    Comparison is case-insensitive.

    Args:
        discord_username: The Discord username to check.

    Returns:
        Integer count of matching whitelist rows.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM whitelist WHERE LOWER(discord_username) = LOWER(%s)",
                (discord_username,),
            )
            result = cur.fetchone()
            return result[0] if result else 0
    except Exception:
        log.exception("panel_db.count_whitelist_requests_by_discord failed")
        return 0
    finally:
        if conn:
            conn.close()


# ============================================================
# PGSM servers helpers
# ============================================================

def get_pgsm_servers() -> list:
    """Fetch all rows from pgsm_servers.

    Returns a list of dicts with id, name, server_id, enabled columns.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, name, server_id, enabled FROM pgsm_servers")
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        log.exception("panel_db.get_pgsm_servers failed")
        return []
    finally:
        if conn:
            conn.close()


def create_pgsm_server(name: str, server_id: str, enabled: bool = False) -> None:
    """Insert a new pgsm_server row.

    Args:
        name: Human-readable server name.
        server_id: The PGSM server UUID string.
        enabled: Whether whitelist sync is enabled; defaults to False.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pgsm_servers (name, server_id, enabled) VALUES (%s, %s, %s)",
                (name, server_id, enabled),
            )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.create_pgsm_server failed")
        raise
    finally:
        if conn:
            conn.close()


def toggle_pgsm_server(server_db_id: int) -> bool:
    """Toggle the enabled boolean for a pgsm_server row.

    Args:
        server_db_id: The integer primary key in pgsm_servers.

    Returns:
        The new enabled state (True or False).
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE pgsm_servers SET enabled = NOT enabled WHERE id = %s RETURNING enabled",
                (server_db_id,),
            )
            result = cur.fetchone()
        conn.commit()
        return bool(result[0]) if result else False
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.toggle_pgsm_server failed")
        raise
    finally:
        if conn:
            conn.close()


def delete_pgsm_server(server_db_id: int) -> None:
    """Delete a pgsm_server row by primary key.

    Args:
        server_db_id: The integer primary key in pgsm_servers.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pgsm_servers WHERE id = %s", (server_db_id,))
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.delete_pgsm_server failed")
        raise
    finally:
        if conn:
            conn.close()


# ============================================================
# Data file helpers (messages.txt / rules.md)
# ============================================================

def _panel_data_path(filename: str) -> str:
    """Resolve an absolute path inside PANEL_DATA_DIR for the given filename."""
    data_dir = current_app.config.get('PANEL_DATA_DIR', 'Game-Panel/data')
    # If the path is relative, resolve from the working directory
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(os.getcwd(), data_dir)
    return os.path.join(data_dir, filename)


def get_random_message() -> str:
    """Read messages.txt and return a random line.

    Returns an empty string if the file does not exist or is empty.
    """
    path = _panel_data_path('messages.txt')
    try:
        if not os.path.exists(path):
            return ''
        with open(path, 'r', encoding='utf-8') as f:
            messages = [line for line in f.read().splitlines() if line.strip()]
        return random.choice(messages) if messages else ''
    except Exception:
        log.exception("panel_db.get_random_message failed")
        return ''


def get_rules_markdown() -> str:
    """Read rules.md and return its raw Markdown content.

    Returns an empty string if the file does not exist.
    """
    path = _panel_data_path('rules.md')
    try:
        if not os.path.exists(path):
            return ''
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        log.exception("panel_db.get_rules_markdown failed")
        return ''


def save_messages(content: str) -> None:
    """Write content to messages.txt, normalising line endings.

    Args:
        content: The full text to write (one message per line).
    """
    path = _panel_data_path('messages.txt')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalised = content.replace('\r\n', '\n').replace('\r', '\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(normalised)


def save_rules(content: str) -> None:
    """Write content to rules.md, normalising line endings.

    Args:
        content: The Markdown text to write.
    """
    path = _panel_data_path('rules.md')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalised = content.replace('\r\n', '\n').replace('\r', '\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(normalised)


# ============================================================
# Server status update (background job)
# ============================================================

def _minecraft_status(address: str) -> dict | None:
    """Query mcsrvstat.us API for a Minecraft server's live status.

    Args:
        address: The server IP or hostname (optionally with :port).

    Returns:
        Dict with keys online, players_online, players_max, motd on success;
        None on any error or non-200 response.
    """
    url = f'https://api.mcsrvstat.us/3/{address}'
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
        if raw.get('online'):
            return {
                'online': True,
                'players_online': raw.get('players', {}).get('online', 0),
                'players_max': raw.get('players', {}).get('max', 0),
                'motd': (raw.get('motd', {}).get('clean') or [''])[0],
            }
        return {
            'online': False,
            'players_online': 0,
            'players_max': 0,
            'motd': '',
        }
    except Exception:
        log.exception("panel_db._minecraft_status failed for %s", address)
        return None


def _terraria_status(address: str) -> dict:
    """Placeholder Terraria status — always returns online with 0/0 players.

    Args:
        address: The server IP or hostname (unused until implemented).

    Returns:
        Dict with online=True, 0/0 players, stub motd.
    """
    return {
        'online': True,
        'players_online': 0,
        'players_max': 0,
        'motd': 'Terraria status coming soon!',
    }


def update_server_status(server_id: int, online: bool, playing_now: int,
                         playing_max: int, motd: str) -> None:
    """Update the live status fields for a single active server.

    Args:
        server_id: The integer primary key in servers.active.
        online: Whether the server is currently reachable.
        playing_now: Current player count.
        playing_max: Maximum player capacity.
        motd: Server message of the day (empty string to keep existing).
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor() as cur:
            if motd:
                cur.execute(
                    """
                    UPDATE active
                    SET motd = %s, online = %s, playing_now = %s, playing_max = %s
                    WHERE id = %s
                    """,
                    (motd, online, playing_now, playing_max, server_id),
                )
            else:
                # Preserve existing motd when the new one is empty
                cur.execute(
                    """
                    UPDATE active
                    SET online = %s, playing_now = %s, playing_max = %s
                    WHERE id = %s
                    """,
                    (online, playing_now, playing_max, server_id),
                )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        log.exception("panel_db.update_server_status failed for server_id=%s", server_id)
    finally:
        if conn:
            conn.close()


def update_all_server_statuses() -> None:
    """Query every active server's live status and persist the results.

    Iterates active server rows, calls mcsrvstat.us for Minecraft servers
    and the Terraria stub for Terraria servers, then calls update_server_status.
    Should be called by the APScheduler background job.
    """
    conn = None
    try:
        conn = _get_servers_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, ip, game FROM active")
            servers = cur.fetchall()
    except Exception:
        log.exception("panel_db.update_all_server_statuses: failed to fetch servers")
        return
    finally:
        if conn:
            conn.close()

    updated = 0
    for server in servers:
        server_id = server['id']
        ip = server['ip'] or ''
        game = (server['game'] or '').lower()

        status = None
        if 'minecraft' in game:
            status = _minecraft_status(ip)
        elif 'terraria' in game:
            status = _terraria_status(ip)

        if status:
            update_server_status(
                server_id,
                status['online'],
                status['players_online'],
                status['players_max'],
                status['motd'],
            )
            updated += 1

    log.info("panel_db.update_all_server_statuses: updated %d servers", updated)


# ============================================================
# Discord guild membership check
# ============================================================

def check_discord_guild_membership(discord_username: str) -> bool:
    """Check whether a Discord username is a member of the configured guild.

    Requires DISCORD_GUILD_ID and DISCORD_BOT_TOKEN in config.
    Supports legacy username#discriminator format as well as modern
    display name / global name / server nickname matching.

    Args:
        discord_username: The user-provided Discord name string.

    Returns:
        True if the user appears to be in the guild, False otherwise.
        Returns False (not raises) on any API error or missing config.
    """
    guild_id = current_app.config.get('DISCORD_GUILD_ID')
    bot_token = current_app.config.get('DISCORD_BOT_TOKEN')
    name_input = (discord_username or '').strip()

    if not name_input:
        return False
    if not guild_id or not bot_token:
        log.error(
            "Discord verification not configured: "
            "missing DISCORD_GUILD_ID or DISCORD_BOT_TOKEN"
        )
        return False

    # Build search query using the base name before '#' if present
    base_query = name_input.split('#', 1)[0]
    try:
        resp = requests.get(
            f'https://discord.com/api/v10/guilds/{guild_id}/members/search',
            params={'query': base_query, 'limit': 1000},
            headers={'Authorization': f'Bot {bot_token}'},
            timeout=6,
        )
    except Exception:
        log.exception("panel_db.check_discord_guild_membership: API request failed")
        return False

    if resp.status_code != 200:
        log.error(
            "Discord API error %s: %s",
            resp.status_code,
            resp.text[:200],
        )
        return False

    has_discriminator = '#' in name_input
    name_part = name_input.split('#', 1)[0] if has_discriminator else name_input
    disc_part = name_input.split('#', 1)[1].strip() if has_discriminator else ''
    name_part_lower = name_part.lower()
    want_lower = name_input.lower()

    try:
        members = resp.json()
    except Exception:
        members = []

    for member in members:
        user = (member or {}).get('user', {})
        uname = (user.get('username') or '').strip()
        disc = (user.get('discriminator') or '').strip()
        gname = (user.get('global_name') or '').strip()
        nick = (member.get('nick') or '').strip()

        tag = f'{uname}#{disc}' if disc else uname

        candidates = {uname.lower(), gname.lower(), nick.lower(), tag.lower()}

        if has_discriminator:
            if uname.lower() == name_part_lower and disc == disc_part:
                return True
            if want_lower == tag.lower():
                return True
        else:
            if name_part_lower in candidates:
                return True

    return False


# ============================================================
# Minecraft UUID lookup
# ============================================================

def lookup_minecraft_uuid(username: str) -> str | None:
    """Look up a Minecraft player's UUID via the Mojang services API.

    Args:
        username: The Minecraft username to look up.

    Returns:
        The formatted UUID string (with hyphens), or None if not found
        or the API call failed.
    """
    try:
        resp = requests.get(
            f'https://api.minecraftservices.com/minecraft/profile/lookup/name/{username}',
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        raw_id = resp.json().get('id')
        if not raw_id:
            return None
        return str(UUID(raw_id))
    except Exception:
        log.exception(
            "panel_db.lookup_minecraft_uuid failed for username=%s", username
        )
        return None
