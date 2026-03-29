# ============================================================
# app/services/ldap_service.py — LDAPS Authentication Service
# Provides AD/LDAP user authentication and attribute lookup
# using the ldap3 library (pure Python, cross-platform).
#
# All connections use LDAPS (TLS on port 636 by default).
# A service account is used for user searches; the service
# account credentials are never exposed to callers.
# ============================================================

import ssl
import logging

from flask import current_app

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful import — the module is importable even if ldap3 is not installed.
# Functions will return an error dict if ldap3 is missing at call time.
# ---------------------------------------------------------------------------
try:
    import ldap3
    import ldap3.core.exceptions
    import ldap3.utils.dn
    _LDAP3_AVAILABLE = True
except ImportError:
    _LDAP3_AVAILABLE = False


# ============================================================
# OID constant for AD transitive/nested group membership checks
# ============================================================

_MATCHING_RULE_IN_CHAIN = '1.2.840.113556.1.4.1941'

# Attributes to retrieve for every user search
_USER_ATTRIBUTES = [
    'distinguishedName',
    'sAMAccountName',
    'displayName',
    'mail',
    'memberOf',
]


# ============================================================
# Internal helpers
# ============================================================

def _build_server() -> 'ldap3.Server':
    """Construct and return an ldap3.Server object from app config.

    Returns:
        An ldap3.Server instance configured for LDAPS with TLS settings
        derived from LDAP_TLS_VALIDATE and LDAP_CA_CERT_FILE config vars.
    """
    cfg = current_app.config

    # --- TLS configuration ---
    validate_mode = ssl.CERT_REQUIRED if cfg.get('LDAP_TLS_VALIDATE') else ssl.CERT_NONE
    ca_certs_file = cfg.get('LDAP_CA_CERT_FILE') or None

    tls = ldap3.Tls(
        validate=validate_mode,
        ca_certs_file=ca_certs_file,
        version=ssl.PROTOCOL_TLS_CLIENT if validate_mode == ssl.CERT_REQUIRED else ssl.PROTOCOL_TLS,
    )

    return ldap3.Server(
        host=cfg['LDAP_HOST'],
        port=cfg.get('LDAP_PORT', 636),
        use_ssl=cfg.get('LDAP_USE_SSL', True),
        tls=tls,
        get_info=ldap3.NONE,  # don't fetch schema info; faster and avoids anonymous info leak
        connect_timeout=5,
    )


def _bind_service_account(server: 'ldap3.Server') -> 'ldap3.Connection':
    """Open and bind a connection using the configured service account.

    Args:
        server: An ldap3.Server instance to connect to.

    Returns:
        A bound ldap3.Connection.

    Raises:
        ldap3.core.exceptions.LDAPException: If the bind fails.
    """
    cfg = current_app.config
    conn = ldap3.Connection(
        server,
        user=cfg['LDAP_BIND_DN'],
        password=cfg['LDAP_BIND_PASSWORD'],
        auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if not cfg.get('LDAP_USE_SSL', True) else ldap3.AUTO_BIND_NO_TLS,
        raise_exceptions=True,
    )
    conn.bind()
    return conn


def _search_user(conn: 'ldap3.Connection', username: str) -> tuple[str | None, dict | None]:
    """Search for a user by sAMAccountName and return their DN and attributes.

    Uses the configured LDAP_USER_SEARCH_BASE and LDAP_USER_SEARCH_FILTER.
    The username is escaped using ldap3.utils.dn.escape_rdn to prevent
    LDAP injection.

    Args:
        conn: A bound ldap3.Connection (service account).
        username: The sAMAccountName to search for.

    Returns:
        A (dn, attributes_dict) tuple, or (None, None) if not found.
    """
    cfg = current_app.config
    search_base = cfg.get('LDAP_USER_SEARCH_BASE') or cfg.get('LDAP_BASE_DN')
    raw_filter = cfg.get('LDAP_USER_SEARCH_FILTER', '(sAMAccountName={username})')

    # Escape the username value to prevent LDAP injection
    safe_username = ldap3.utils.dn.escape_rdn(username)
    search_filter = raw_filter.format(username=safe_username)

    # Build the full attribute list, including any custom UUID attributes
    attr_discord = cfg.get('LDAP_ATTR_DISCORD_UUID', 'extensionAttribute1')
    attr_mc = cfg.get('LDAP_ATTR_MINECRAFT_UUID', 'extensionAttribute2')
    attributes = list(set(_USER_ATTRIBUTES + [attr_discord, attr_mc]))

    conn.search(
        search_base=search_base,
        search_filter=search_filter,
        search_scope=ldap3.SUBTREE,
        attributes=attributes,
    )

    if not conn.entries:
        return None, None

    entry = conn.entries[0]
    dn = entry.entry_dn

    # Build a clean attributes dict; ldap3 entry attributes support .value
    raw = entry.entry_attributes_as_dict
    attrs = {}
    for key, val_list in raw.items():
        attrs[key] = val_list[0] if len(val_list) == 1 else val_list

    return dn, attrs


def _get_access_level(
    conn: 'ldap3.Connection',
    user_dn: str,
) -> tuple[str | None, list[str]]:
    """Determine access level for a user via AD transitive group membership.

    Uses the LDAP_MATCHING_RULE_IN_CHAIN OID (1.2.840.113556.1.4.1941) to
    traverse nested group membership. This single-query approach lets AD do
    the transitive walk server-side.

    Precedence:
      1. Member of LDAP_GROUP_ADMIN  → 'admin'
      2. Member of LDAP_GROUP_MESSAGES → 'messages'
      3. Neither → None

    Args:
        conn: A bound ldap3.Connection (service account).
        user_dn: The distinguishedName of the user to check.

    Returns:
        A (access_level, direct_group_cns) tuple where access_level is
        'admin', 'messages', or None, and direct_group_cns is a list of
        CN strings from the user's direct memberOf attribute.
    """
    cfg = current_app.config
    admin_group_dn = cfg.get('LDAP_GROUP_ADMIN')
    messages_group_dn = cfg.get('LDAP_GROUP_MESSAGES')
    search_base = cfg.get('LDAP_USER_SEARCH_BASE') or cfg.get('LDAP_BASE_DN')

    # --- Retrieve direct group CNs for display purposes ---
    direct_cns: list[str] = []
    conn.search(
        search_base=search_base,
        search_filter=f'(distinguishedName={ldap3.utils.dn.escape_rdn(user_dn)})',
        search_scope=ldap3.SUBTREE,
        attributes=['memberOf'],
    )
    if conn.entries:
        member_of = conn.entries[0].entry_attributes_as_dict.get('memberOf', [])
        for group_dn_entry in member_of:
            # Extract just the CN= component from the full DN
            parts = ldap3.utils.dn.parse_dn(group_dn_entry)
            if parts and parts[0][0].upper() == 'CN':
                direct_cns.append(parts[0][1])

    # --- Check admin group membership (transitive) ---
    if admin_group_dn:
        escaped_user_dn = ldap3.utils.dn.escape_rdn(user_dn)
        escaped_group_dn = ldap3.utils.dn.escape_rdn(admin_group_dn)
        admin_filter = (
            f'(&(distinguishedName={escaped_user_dn})'
            f'(memberOf:{_MATCHING_RULE_IN_CHAIN}:={escaped_group_dn}))'
        )
        conn.search(
            search_base=search_base,
            search_filter=admin_filter,
            search_scope=ldap3.SUBTREE,
            attributes=['distinguishedName'],
        )
        if conn.entries:
            return 'admin', direct_cns

    # --- Check messages group membership (transitive) ---
    if messages_group_dn:
        escaped_user_dn = ldap3.utils.dn.escape_rdn(user_dn)
        escaped_group_dn = ldap3.utils.dn.escape_rdn(messages_group_dn)
        messages_filter = (
            f'(&(distinguishedName={escaped_user_dn})'
            f'(memberOf:{_MATCHING_RULE_IN_CHAIN}:={escaped_group_dn}))'
        )
        conn.search(
            search_base=search_base,
            search_filter=messages_filter,
            search_scope=ldap3.SUBTREE,
            attributes=['distinguishedName'],
        )
        if conn.entries:
            return 'messages', direct_cns

    return None, direct_cns


def _extract_str(value) -> str:
    """Safely coerce an LDAP attribute value to a string.

    ldap3 may return lists, bytes, or None depending on the attribute.

    Args:
        value: Raw attribute value from ldap3.

    Returns:
        A string, or empty string if the value is None or empty.
    """
    if value is None:
        return ''
    if isinstance(value, list):
        value = value[0] if value else ''
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value)


# ============================================================
# Public API
# ============================================================

def authenticate(username: str, password: str) -> dict:
    """Authenticate a user against the configured LDAP/AD server.

    Flow:
      1. Bind with the service account (LDAP_BIND_DN / LDAP_BIND_PASSWORD).
      2. Search for the user by sAMAccountName under LDAP_USER_SEARCH_BASE.
      3. If found, re-bind as the user with the supplied password.
      4. If the user bind succeeds, check group membership for access level.

    Passwords are never logged. All LDAP exceptions are caught and returned
    as error dicts so callers never see raw ldap3 exceptions.

    Args:
        username: The sAMAccountName (login name) to authenticate.
        password: The plaintext password supplied by the user.

    Returns:
        A dict with the following keys:
          success (bool): True if authentication and access check succeeded.
          error (str | None): Human-readable error message, or None.
          username (str): The sAMAccountName.
          display_name (str): The LDAP displayName attribute.
          email (str): The LDAP mail attribute.
          access_level (str | None): 'admin', 'messages', or None.
          groups (list[str]): Direct group CNs the user belongs to.
    """
    _base_result = {
        'success': False,
        'error': None,
        'username': username,
        'display_name': '',
        'email': '',
        'access_level': None,
        'groups': [],
    }

    if not _LDAP3_AVAILABLE:
        msg = 'ldap3 is not installed. Run: pip install ldap3'
        log.error(msg)
        return {**_base_result, 'error': msg}

    service_conn = None
    user_conn = None

    try:
        server = _build_server()

        # --- Step 1: bind with service account and find the user ---
        service_conn = _bind_service_account(server)
        user_dn, attrs = _search_user(service_conn, username)

        if user_dn is None:
            log.info('LDAP authenticate: user not found — %s', username)
            return {**_base_result, 'error': 'Invalid credentials.'}

        display_name = _extract_str(attrs.get('displayName', ''))
        email = _extract_str(attrs.get('mail', ''))

        # --- Step 2: bind as the user to validate their password ---
        try:
            user_conn = ldap3.Connection(
                server,
                user=user_dn,
                password=password,
                raise_exceptions=True,
            )
            user_conn.bind()
        except ldap3.core.exceptions.LDAPInvalidCredentialsResult:
            log.info('LDAP authenticate: invalid credentials for user %s', username)
            return {**_base_result, 'error': 'Invalid credentials.', 'display_name': display_name, 'email': email}
        except ldap3.core.exceptions.LDAPException as exc:
            log.warning('LDAP authenticate: user bind failed for %s — %s', username, exc)
            return {**_base_result, 'error': 'Authentication failed. Please try again.', 'display_name': display_name, 'email': email}

        # --- Step 3: determine access level via group membership ---
        access_level, groups = _get_access_level(service_conn, user_dn)

        log.info(
            'LDAP authenticate: success — user=%s display=%s access=%s',
            username, display_name, access_level,
        )

        return {
            'success': True,
            'error': None,
            'username': username,
            'display_name': display_name,
            'email': email,
            'access_level': access_level,
            'groups': groups,
        }

    except ldap3.core.exceptions.LDAPException as exc:
        log.exception('LDAP authenticate: unexpected LDAP error for user %s', username)
        return {**_base_result, 'error': 'LDAP connection error. Please try again.'}

    except Exception as exc:
        log.exception('LDAP authenticate: unexpected error for user %s', username)
        return {**_base_result, 'error': 'An unexpected error occurred. Please try again.'}

    finally:
        # Always unbind — never share or leak connections across requests
        if user_conn:
            try:
                user_conn.unbind()
            except Exception:
                pass
        if service_conn:
            try:
                service_conn.unbind()
            except Exception:
                pass


def query_user(username: str) -> dict:
    """Look up a user's LDAP attributes using the service account only.

    No user authentication is performed — this is intended for the admin
    LDAP testing page where an admin wants to inspect what LDAP returns
    for a given account without knowing the user's password.

    Args:
        username: The sAMAccountName to look up.

    Returns:
        A dict with the following keys:
          found (bool): True if the user exists in the directory.
          error (str | None): Human-readable error message, or None.
          username (str): The sAMAccountName.
          display_name (str): The LDAP displayName attribute.
          email (str): The LDAP mail attribute.
          dn (str): The user's full distinguishedName.
          discord_uuid (str | None): Value of LDAP_ATTR_DISCORD_UUID attribute.
          minecraft_uuid (str | None): Value of LDAP_ATTR_MINECRAFT_UUID attribute.
          groups (list[str]): Direct group CNs the user belongs to.
          access_level (str | None): 'admin', 'messages', or None.
          raw_attributes (dict): All retrieved LDAP attributes for debugging.
    """
    _base_result = {
        'found': False,
        'error': None,
        'username': username,
        'display_name': '',
        'email': '',
        'dn': '',
        'discord_uuid': None,
        'minecraft_uuid': None,
        'groups': [],
        'access_level': None,
        'raw_attributes': {},
    }

    if not _LDAP3_AVAILABLE:
        msg = 'ldap3 is not installed. Run: pip install ldap3'
        log.error(msg)
        return {**_base_result, 'error': msg}

    service_conn = None

    try:
        cfg = current_app.config
        attr_discord = cfg.get('LDAP_ATTR_DISCORD_UUID', 'extensionAttribute1')
        attr_mc = cfg.get('LDAP_ATTR_MINECRAFT_UUID', 'extensionAttribute2')

        server = _build_server()
        service_conn = _bind_service_account(server)
        user_dn, attrs = _search_user(service_conn, username)

        if user_dn is None:
            log.info('LDAP query_user: user not found — %s', username)
            return {**_base_result, 'found': False}

        display_name = _extract_str(attrs.get('displayName', ''))
        email = _extract_str(attrs.get('mail', ''))

        # Retrieve optional UUID extension attributes
        raw_discord = attrs.get(attr_discord)
        raw_mc = attrs.get(attr_mc)
        discord_uuid = _extract_str(raw_discord) or None
        minecraft_uuid = _extract_str(raw_mc) or None

        # Determine access level and direct group CNs
        access_level, groups = _get_access_level(service_conn, user_dn)

        # Build serialisable raw_attributes dict (convert any bytes/lists)
        raw_serialisable = {}
        for key, val in attrs.items():
            if isinstance(val, list):
                raw_serialisable[key] = [
                    v.decode('utf-8', errors='replace') if isinstance(v, bytes) else str(v)
                    for v in val
                ]
            elif isinstance(val, bytes):
                raw_serialisable[key] = val.decode('utf-8', errors='replace')
            else:
                raw_serialisable[key] = str(val) if val is not None else None

        log.info('LDAP query_user: found — user=%s display=%s access=%s', username, display_name, access_level)

        return {
            'found': True,
            'error': None,
            'username': username,
            'display_name': display_name,
            'email': email,
            'dn': user_dn,
            'discord_uuid': discord_uuid,
            'minecraft_uuid': minecraft_uuid,
            'groups': groups,
            'access_level': access_level,
            'raw_attributes': raw_serialisable,
        }

    except ldap3.core.exceptions.LDAPException as exc:
        log.exception('LDAP query_user: LDAP error for user %s', username)
        return {**_base_result, 'error': 'LDAP connection error. Please try again.'}

    except Exception as exc:
        log.exception('LDAP query_user: unexpected error for user %s', username)
        return {**_base_result, 'error': 'An unexpected error occurred.'}

    finally:
        if service_conn:
            try:
                service_conn.unbind()
            except Exception:
                pass
