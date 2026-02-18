# PGSM — Developer Reference

This document is the definitive technical reference for the PGSM codebase. Read this before making any changes. It covers architecture, conventions, critical invariants, data flow, and known limitations.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [File Structure](#file-structure)
- [Database Model](#database-model)
- [Critical Invariants](#critical-invariants)
- [Server Lifecycle Flow](#server-lifecycle-flow)
- [LXC Container Configuration](#lxc-container-configuration)
- [High Availability Integration](#high-availability-integration)
- [Proxmox Tagging](#proxmox-tagging)
- [Game Codes](#game-codes)
- [Java Version Matrix](#java-version-matrix)
- [Nginx TCP Proxying](#nginx-tcp-proxying)
- [Console Connection Model](#console-connection-model)
- [API Endpoints](#api-endpoints)
- [Database Migrations](#database-migrations)
- [Adding a New Server Type](#adding-a-new-server-type)
- [Known Limitations and Future Work](#known-limitations-and-future-work)

---

## Architecture Overview

PGSM is a Flask web application that manages game server LXC containers on Proxmox nodes.

```
Browser → Flask (app/) → Services → Proxmox API / SSH / nginx
                       ↕
                   SQLite DB (instance/pgsm.db)
```

**Controller node** runs:
- The Flask app (`main.py` via `socketio.run()`)
- nginx (for TCP port proxying of game traffic to containers)

**Game server nodes** run:
- LXC containers (Debian 13), one per game server
- Each container runs its game server in a tmux session named `PGSM`
- A systemd unit named `PGSM` manages the process
- All game server files live in `/PGSM/` on the container
- A dedicated `PGSM` user (no home directory) owns `/PGSM/` and runs the server process

**Communication** between Flask and containers is via SSH using a keypair at `keys/pgsm_rsa` (relative to project root). The public key is injected into each container at LXC creation time.

---

## File Structure

```
app/
├── __init__.py           # create_app() factory — registers blueprints, inits db, runs migrations
├── config.py             # Config class — all .env vars loaded here, nowhere else
├── extensions.py         # db, socketio singletons (avoids circular imports)
├── models/
│   ├── server.py         # GameServer — the primary DB model
│   └── node.py           # ProxmoxNode — cached node info (rarely used)
├── blueprints/
│   ├── dashboard/        # GET / → dashboard with stats and server list
│   ├── servers/          # /servers/ — CRUD, start/stop/restart/delete, settings
│   ├── console/          # /console/<id> — xterm.js terminal + SocketIO handlers
│   ├── files/            # /files/<id> — SFTP file browser + inline editor
│   └── api/              # /api/ — JSON endpoints for status, metrics, versions, ports
├── services/
│   ├── proxmox.py        # ProxmoxService — create/delete/start/stop LXC, HA registration
│   ├── ssh.py            # SSHManager — keypair management, exec, SFTP
│   ├── nginx.py          # NginxService — write/reload/remove nginx stream conf files
│   ├── minecraft.py      # MinecraftService — Mojang version API + install script args
│   └── server_lifecycle.py  # provision/start/stop/restart/status — orchestrates all services
├── templates/            # Jinja2 templates, all extend base.html
│   ├── base.html         # Navbar, flash messages, script loading
│   ├── dashboard/        # index.html — stats cards + server list
│   ├── servers/          # create.html (wizard), list.html, detail.html
│   ├── console/          # index.html — xterm.js terminal
│   └── files/            # browser.html (SFTP listing), editor.html (CodeMirror)
└── static/
    ├── css/
    │   ├── theme.css     # CSS custom properties (colors, spacing) — loaded first
    │   └── pgsm.css      # All component styles — dark theme, card layout
    └── js/
        ├── console.js    # xterm.js init + SocketIO event wiring
        └── wizard.js     # Create server 3-step wizard navigation logic

Scripts/                  # Install scripts uploaded to containers during provisioning
├── Minecraft/
│   ├── Vanilla/
│   │   ├── Java/         # install-mcjava.sh
│   │   └── Bedrock/      # install-mcbedr.sh
│   └── Modded/
│       ├── Paper/        # install-paper.sh
│       ├── Fabric/       # install-fabric.sh
│       └── Forge/        # install-forge.sh
└── Counter Strike/       # (placeholder, not yet implemented)

Development Docs/         # Developer documentation (this file + FUTURE_CLAUDE.md)
keys/                     # SSH keypair (auto-generated, gitignored)
instance/                 # SQLite database (auto-generated, gitignored)
main.py                   # Entry point: calls create_app() and runs socketio
requirements.txt
.env                      # Local config (gitignored)
```

---

## Database Model

The `GameServer` model in `app/models/server.py` is the core of the application. Every field:

| Column | Type | Description |
|--------|------|-------------|
| `id` | String(36) | UUID primary key |
| `name` | String(128) | Human-readable display name |
| `game_code` | String(16) | `MCJAV` or `MCBED` — identifies the game family |
| `server_type` | String(32) | `vanilla`, `paper`, `fabric`, `forge`, `bedrock` |
| `game_version` | String(32) | Minecraft version string, e.g. `1.21.4` |
| `ct_id` | Integer (unique) | Proxmox CT ID (500+) |
| `proxmox_node` | String(64) | Name of the Proxmox node the CT lives on |
| `hostname` | String(128) | `PGSM-<GAMECODE>-<PARTIAL_UUID>` |
| `ip_address` | String(45) | IPv4 on the PGSM VLAN |
| `ha_enabled` | Boolean | Whether Proxmox HA is registered for this CT |
| `disk_gb` | Integer | Root disk size in GB |
| `cores` | Integer | CPU core count |
| `memory_mb` | Integer | RAM in MB |
| `game_port` | Integer | Primary game port (default 25565) |
| `extra_ports` | JSON | List of additional proxied ports, e.g. `[25575, 19132]` |
| `motd` | String(256) | Server description |
| `render_distance` | Integer | Minecraft chunk render distance |
| `spawn_protection` | Integer | Spawn protection radius |
| `difficulty` | String(16) | `peaceful`, `easy`, `normal`, `hard` |
| `hardcore` | Boolean | Hardcore mode on/off |
| `status` | String(32) | `creating`, `running`, `stopped`, `error` |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last update timestamp |

**Computed properties** (not DB columns):
- `all_ports` — `[game_port] + extra_ports`, deduped and sorted
- `partial_uuid` — first 8 chars of UUID, uppercased; used in hostname
- `java_version` — required Java version for MCJAV servers (from `_resolve_java_version()`)
- `status_badge_class` — CSS class string for status badge rendering

---

## Critical Invariants

These things MUST remain consistent across the codebase or servers will break. If you change any of them, update every reference.

### 1. tmux session name: `PGSM`

All install scripts create a tmux session named `PGSM`. The console blueprint attaches to this session and all commands are sent to it:

```python
# server_lifecycle.py
ssh.exec(f"tmux send-keys -t PGSM '{command}' Enter")
```

```bash
# console/routes.py — terminal attachment
ssh_channel.send("tmux attach -t PGSM\n")
```

If you rename the session, update every install script AND `server_lifecycle.py`.

### 2. Systemd unit name: `PGSM`

All install scripts register a systemd unit named `PGSM`. Lifecycle commands use this name:

```python
SYSTEMD_UNIT = 'PGSM'  # in server_lifecycle.py
ssh.exec(f"systemctl start {SYSTEMD_UNIT}")
ssh.exec(f"systemctl is-active {SYSTEMD_UNIT}")
```

### 3. Game server directory: `/PGSM/`

All server files (JAR, `server.properties`, `eula.txt`, worlds, plugins/mods) live in `/PGSM/` on the container. The SFTP browser defaults to `/PGSM/` as its root. Do not scatter files elsewhere.

### 4. PGSM user on containers

Each container has a `PGSM` user created via `useradd -M` (no home directory). This user owns `/PGSM/` and runs the game server via systemd:

```ini
[Service]
User=PGSM
WorkingDirectory=/PGSM
```

Do not change this without updating all install scripts.

### 5. SSH keypair location

Default: `keys/pgsm_rsa` (relative to project root). Configured by `SSH_Key_Path` in `.env`. The public key is injected as `ssh-public-keys` during LXC creation, granting passwordless root access to containers. **This keypair must be kept secret.**

### 6. CT ID range: 500+

`get_next_ct_id()` in `proxmox.py` starts scanning at 500. IDs below 500 are reserved to avoid conflicts with user-created VMs and containers in Proxmox.

### 7. nginx — stream blocks only

Game servers use raw TCP. nginx must use a `stream {}` context (not `http {}`). PGSM writes files like `pgsm-<ct_id>.conf` to `Nginx_Conf_Dir` (default `/etc/nginx/conf.d/`). The main `nginx.conf` must include:

```nginx
stream {
    include /etc/nginx/conf.d/*.conf;
}
```

This is a **one-time manual setup step**. PGSM cannot modify `nginx.conf`.

### 8. Flask `<path:>` route parameter quirk

Flask's `<path:remote_path>` parameter strips the leading `/`. Always re-add it in the route handler:

```python
# files/routes.py
@bp.route('/<server_id>/browse/<path:remote_path>')
def browse(server_id, remote_path):
    remote_path = '/' + remote_path  # re-add the leading slash
```

When building URLs with `url_for()` for path parameters, strip the leading `/` first (Flask will add it back in the URL):

```python
url_for('files.browse', server_id=server.id, remote_path=path.lstrip('/'))
```

---

## Server Lifecycle Flow

### Creation

1. User submits the create wizard → `POST /servers/create`
2. Route allocates CT ID (`get_next_ct_id()`) and IP (`get_next_ip()`)
3. `GameServer` record created in DB with `status='creating'`
4. `proxmox.create_lxc()` called — creates and starts the LXC container (with `pgsm` tag)
5. If `ha_enabled`, `proxmox.enable_ha(ct_id)` registers the CT with Proxmox HA
6. Background thread calls `server_lifecycle.provision_server(server_id)`:
   - Waits for SSH to become available (polls with retries)
   - Uploads the appropriate install script to `/tmp/install.sh` on the container
   - Runs the script with game-specific arguments (version, type, ports, settings)
   - Writes `server.properties` via SFTP
   - Writes the nginx stream conf and reloads nginx
   - Starts the systemd `PGSM` service
   - Updates `server.status` to `'running'`
7. UI polls `/api/servers/<id>/status` every 5 seconds until status leaves `'creating'`

### Start / Stop / Restart

These operate on the **game server process** inside an already-running container (not the container itself):

- **Start**: `systemctl start PGSM` via SSH
- **Stop**: `systemctl stop PGSM` via SSH
- **Restart**: `systemctl restart PGSM` via SSH

The LXC container itself stays running. Proxmox-level container start/stop is only done during provisioning and deletion.

### Deletion

1. `server_lifecycle.stop_server(server)` — stops the game server process
2. `proxmox.disable_ha(ct_id)` — removes CT from Proxmox HA (if `ha_enabled`)
3. `proxmox.stop_ct(node, ct_id)` — stops the LXC container
4. `proxmox.delete_ct(node, ct_id)` — permanently deletes the LXC container
5. `NginxService.remove_server(server)` — deletes nginx conf and reloads
6. DB record deleted

All steps after step 1 are wrapped in `try/except` and silently ignore failures — the container or nginx conf may not exist if provisioning failed partway through.

---

## LXC Container Configuration

Every container PGSM creates has this fixed configuration (see `proxmox.py` → `create_lxc()`):

| LXC Parameter | Value | Source |
|--------------|-------|--------|
| `vmid` | 500+ (auto) | `get_next_ct_id()` |
| `ostemplate` | Debian 13 | `PGSM_LXC_Template` in `.env` |
| `hostname` | `PGSM-<GAMECODE>-<UUID8>` | Computed in route |
| `unprivileged` | `1` (always) | Hardcoded — security |
| `cores` | User-specified | Wizard form |
| `memory` | User-specified MB | Wizard form |
| `rootfs` | `kestrel:<disk_gb>` | User-specified; storage name `kestrel` is hardcoded |
| `net0` | `name=eth0,bridge=PGSM,ip=<ip>/24,gw=<gateway>` | Auto-assigned IP + config |
| `nameserver` | `1.1.1.1` | Hardcoded |
| `searchdomain` | `PGSM.lan` | Hardcoded |
| `ssh-public-keys` | PGSM RSA public key | `SSHManager.ensure_keypair()` |
| `features` | `nesting=1` | Hardcoded — required for some server types |
| `tags` | `pgsm` | Hardcoded — identifies PGSM-managed containers in Proxmox |
| `start` | `1` | Hardcoded — container starts immediately |

**Note on storage name**: The `rootfs` parameter currently hardcodes the storage name `kestrel`. If your Proxmox storage is named differently, this will fail. This should be made configurable (see Known Limitations).

---

## High Availability Integration

Proxmox HA is registered/deregistered via the Proxmox cluster API. PGSM uses the proxmoxer library to call these endpoints.

### Enabling HA (`proxmox.enable_ha(ct_id)`)

Called in `servers/routes.py` → `create_server()` after `create_lxc()` succeeds:

```python
# Proxmox API: POST /cluster/ha/resources
api.cluster.ha.resources.post(sid=f'lxc:{ct_id}', state='started')
```

- `sid` format: `lxc:<vmid>` — identifies the resource type and ID
- `state='started'` — Proxmox HA will try to keep the container running
- No HA group is specified — uses Proxmox's default HA behavior
- Failure is non-fatal: a warning flash is shown, the server continues to be created

### Disabling HA (`proxmox.disable_ha(ct_id)`)

Called in `servers/routes.py` → `delete()` before stopping/deleting the CT:

```python
# Proxmox API: DELETE /cluster/ha/resources/lxc:<ct_id>
api.cluster.ha.resources(f'lxc:{ct_id}').delete()
```

- Failure is silently ignored — the HA entry may not exist if HA registration originally failed
- This must be called **before** `stop_ct()` and `delete_ct()`, because Proxmox HA will fight you if you try to stop/delete a container it's managing

### `ha_enabled` DB field

Stored on `GameServer.ha_enabled` (Boolean, default `False`). This is the source of truth for whether PGSM should call `disable_ha()` on deletion. It reflects intent at creation time — if HA registration fails silently in a future code path, this field will still be `True`, so `disable_ha()` will still be attempted on delete (which is safe — it silently ignores 404 errors).

---

## Proxmox Tagging

Every LXC container created by PGSM is tagged with `pgsm` in Proxmox. This is done by passing `'tags': 'pgsm'` to the `api.nodes(node).lxc.post()` call in `proxmox.create_lxc()`.

This allows operators to easily identify PGSM-managed containers in the Proxmox UI. Multiple tags can be added in the future by semicolon-separating them (e.g., `'tags': 'pgsm;production'`).

---

## Game Codes

Game codes are short identifiers for the game family a server runs.

| Code | Meaning |
|------|---------|
| `MCJAV` | Minecraft Java Edition (Vanilla, Paper, Fabric, Forge) |
| `MCBED` | Minecraft Bedrock Edition |

The `game_code` is derived from `server_type` in the create route:

```python
game_code = 'MCBED' if server_type == 'bedrock' else 'MCJAV'
```

The `server_type` column distinguishes variants within MCJAV (vanilla/paper/fabric/forge). Game codes appear in:
- Container hostname: `PGSM-MCJAV-A1B2C3D4`
- Install script selection (`minecraft.py` → `INSTALL_SCRIPTS` dict)
- Java version resolution

---

## Java Version Matrix

Minecraft Java Edition requires specific Java versions. PGSM automatically selects the right one:

| Minecraft Version | Java Required |
|-------------------|---------------|
| < 1.17 | Java 8 |
| 1.17.x | Java 16 |
| 1.17.1 – 1.20.5 | Java 17 |
| ≥ 1.20.6 | Java 21 |

Logic lives in `app/models/server.py` → `_resolve_java_version()`. Install scripts download all four Java versions to `/opt/java/` regardless of the Minecraft version; the correct one is selected by the `STARTUP_COMMAND` variable within each script.

---

## Nginx TCP Proxying

`app/services/nginx.py` writes per-server nginx `stream {}` config files to `Nginx_Conf_Dir`. Each port a server uses gets its own upstream and server block:

```nginx
# /etc/nginx/conf.d/pgsm-500.conf (example)
upstream pgsm_500_25565 {
    server 172.16.0.10:25565;
}
server {
    listen 25565;
    proxy_pass pgsm_500_25565;
}
```

After writing or removing a conf file, PGSM calls `systemctl reload nginx` via `subprocess.run()` on the controller node (no SSH needed since Flask runs there).

**Adding ports**: Extra ports from `server.extra_ports` each get their own upstream/server block in the same conf file.

---

## Console Connection Model

The console gives users a live terminal into the game server's tmux session.

1. HTTP route at `/console/<id>` renders the xterm.js terminal page
2. Browser connects via SocketIO → emits `join_console` event with `server_id`
3. Server-side (in `console/routes.py`):
   - Opens an SSH `invoke_shell()` channel to the container
   - Sends `tmux attach -t PGSM\n` to attach to the game server's session
   - Background thread reads output from the SSH channel and emits `console_output` SocketIO events
4. User input comes in via `console_input` SocketIO events → `send_console_command()` → `tmux send-keys -t PGSM '<cmd>' Enter`
5. Only one streaming thread per server (tracked by `_active_sessions` dict)
6. Thread exits when all viewers disconnect (empty set in `_active_sessions`)

The xterm.js terminal is fixed at 220×50 columns/rows. A proper PTY resize would require sending dimensions via SocketIO and resizing the Paramiko channel.

---

## API Endpoints

All API endpoints are in `app/blueprints/api/routes.py` and return JSON.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/nodes` | List online Proxmox nodes (`[{node, status, ...}]`) |
| `GET` | `/api/minecraft/versions` | Available Minecraft versions from Mojang. Add `?snapshots=true` to include snapshots. |
| `GET` | `/api/servers/<id>/status` | `{db_status, ct_status}` — PGSM DB status + live Proxmox CT status |
| `GET` | `/api/servers/<id>/metrics` | `{cpu_percent, memory_used_mb, memory_total_mb, net_rx_bytes, net_tx_bytes, players_online, players_max}` |
| `POST` | `/api/servers/<id>/ports/add` | Add an extra port. Body: `{"port": 25575}`. Writes new nginx conf and reloads. |
| `POST` | `/api/servers/<id>/ports/remove` | Remove an extra port. Body: `{"port": 25575}`. Rewrites nginx conf and reloads. |

**Metrics source**: Live Proxmox API call to `nodes/<node>/lxc/<vmid>/status/current`. Player count comes from a Minecraft status ping (TCP port query) via `minecraft.py`.

---

## Database Migrations

PGSM uses lightweight inline migrations rather than Alembic. All migrations live in `app/__init__.py` → `_apply_migrations()`.

The function runs every startup. Each migration is an `ALTER TABLE ADD COLUMN` statement wrapped in a try/except — if the column already exists, SQLite raises an error which is silently ignored.

```python
migrations = [
    # v2: extra_ports column for multi-port support
    "ALTER TABLE game_servers ADD COLUMN extra_ports JSON",
    # v3: ha_enabled column for Proxmox HA registration
    "ALTER TABLE game_servers ADD COLUMN ha_enabled BOOLEAN DEFAULT 0",
]
```

**When adding a new column:**
1. Add the column to `GameServer` in `app/models/server.py`
2. Add the corresponding `ALTER TABLE` statement to the `migrations` list in `_apply_migrations()`
3. Add a comment with the version number

**Do not reorder or remove existing migrations.** SQLite has no way to detect which have been applied — they all run on every startup and silently skip already-applied ones.

---

## Adding a New Server Type

1. **Create an install script** in `Scripts/<GameType>/`:
   - Must create a tmux session named `PGSM`
   - Must create a systemd unit named `PGSM`
   - Must put all files in `/PGSM/`
   - Must create a `PGSM` user via `useradd -M` that owns `/PGSM/`
   - Accept version, port, and game-specific settings as script arguments

2. **Register in `app/services/minecraft.py`**:
   - Add an entry to `INSTALL_SCRIPTS` dict mapping `server_type` → script path
   - Add a game code mapping if this is a new game (not just a new Minecraft variant)

3. **Add to the wizard** in `app/templates/servers/create.html`:
   - Add an `<option>` to `<select name="server_type">`

4. **Update the route** in `app/blueprints/servers/routes.py` if the new type needs special handling (e.g., a different `game_code`)

5. **Update this document** with any new invariants, game codes, or version matrices

---

## Known Limitations and Future Work

### Hardcoded storage name
`create_lxc()` hardcodes the Proxmox storage name `kestrel` in the `rootfs` parameter: `f'kestrel:{disk_gb}'`. This should be a config variable like `PGSM_LXC_Storage`.

### Bedrock download URL
Bedrock server downloads require a URL from the Microsoft API that requires accepting Terms of Service. `MinecraftService` passes a `serverfilelink` argument to `install-mcbedr.sh`, but the URL resolution is not yet implemented. Needs a Bedrock URL resolver similar to `get_vanilla_jar_url()`.

### Paper/Fabric/Forge resolution
Currently falls back to the vanilla JAR URL for Paper/Fabric. Production use needs integration with:
- Paper API: `https://api.papermc.io/v2/projects/paper/`
- Fabric meta API: `https://meta.fabricmc.net/`
- Forge promotions API: `https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json`

### Port conflict detection
`get_next_ip()` finds the next free IP, but game port conflicts (two servers both using port 25565) are not detected at creation time. Add port conflict checking in the create route by querying existing `game_port` and `extra_ports` values.

### No authentication
The web UI has no login system. Any user with network access to port 5000 has full control. Add Flask-Login before exposing to anything other than a localhost or trusted LAN connection.

### Console terminal resize
xterm.js is fixed at 220×50. A proper resize requires:
1. Detecting terminal size changes in JS
2. Sending new dimensions via a SocketIO event
3. Resizing the Paramiko channel server-side via `channel.resize_pty()`

### High Availability — no group support
HA is currently registered without a specific HA group. If your cluster uses HA groups to control failover priorities, you'll need to add a `PROXMOX_HA_GROUP` config variable and pass it to `enable_ha()`.

### Minecraft.py at project root
The original `Minecraft.py` at the project root is superseded by `app/services/minecraft.py`. It can be removed once confirmed nothing imports from it.

### Single-threaded provisioning
Provisioning runs in a daemon thread. If PGSM restarts while a server is provisioning, the thread dies and the server stays stuck in `creating` status. A task queue (Celery/RQ) would make this more robust.
