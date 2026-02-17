# PGSM - Developer Reference for Future Claude Sessions

This document explains the architecture, conventions, and critical invariants of the PGSM codebase.
Read this before making any changes.

---

## Architecture Overview

PGSM is a Flask web application that manages game server LXC containers on Proxmox nodes.

```
Browser → Flask (app/) → Services → Proxmox API / SSH / nginx
                       ↕
                   SQLite DB (instance/pgsm.db)
```

The controller node runs:
- The Flask app (`main.py` via `socketio.run()`)
- nginx (for TCP port proxying of game servers)

Game server nodes run:
- LXC containers (Debian 12)
- Each container runs exactly one game server
- The game server runs in a tmux session named `PGSM` inside a systemd unit also named `PGSM`
- All game server files live in `/PGSM/` on the container
- A dedicated `PGSM` user (no home directory) runs the server process

---

## File Structure

```
app/
├── __init__.py           # create_app() factory — registers blueprints, inits db
├── config.py             # Config class — all .env vars in one place
├── extensions.py         # db, socketio singletons (no circular import)
├── models/
│   ├── server.py         # GameServer — the main DB model
│   └── node.py           # ProxmoxNode — cached node info (rarely used)
├── blueprints/
│   ├── dashboard/        # GET / → dashboard
│   ├── servers/          # /servers/ CRUD + start/stop/restart/delete
│   ├── console/          # /console/<id> + SocketIO handlers
│   ├── files/            # /files/<id> SFTP browser
│   └── api/              # /api/ JSON endpoints (nodes, versions, status)
├── services/
│   ├── proxmox.py        # ProxmoxService — create/query LXC containers
│   ├── ssh.py            # SSHManager — keypair + exec + SFTP
│   ├── nginx.py          # NginxService — write TCP stream conf files
│   ├── minecraft.py      # MinecraftService — Mojang API + install args
│   └── server_lifecycle.py  # provision/start/stop/restart/status
├── templates/            # Jinja2 templates (extends base.html)
└── static/
    ├── css/pgsm.css      # All styles — dark theme, card layout
    └── js/
        ├── console.js    # xterm.js + SocketIO wiring
        └── wizard.js     # Create server 3-step wizard navigation
```

---

## Critical Invariants

These things MUST remain consistent or servers will break:

### 1. tmux session name: `PGSM`
All install scripts create a tmux session named `PGSM`. The console blueprint attaches to this session:
```bash
tmux attach -t PGSM
```
The send_console_command function in `server_lifecycle.py` also sends to `PGSM`:
```bash
tmux send-keys -t PGSM '<command>' Enter
```
If you change the session name, change it in ALL install scripts AND `server_lifecycle.py`.

### 2. Systemd unit name: `PGSM`
All install scripts register a systemd unit named `PGSM`. Lifecycle commands use this:
```bash
systemctl start PGSM
systemctl stop PGSM
systemctl is-active PGSM
```
Defined in `server_lifecycle.py` as `SYSTEMD_UNIT = 'PGSM'`.

### 3. Game server directory: `/PGSM/`
All server files, including `server.jar`, `server.properties`, `eula.txt`, worlds, plugins, mods,
live in `/PGSM/` on the container. The SFTP browser defaults to `/PGSM/` as root.

### 4. PGSM user on containers
Each container has a `PGSM` user (created by `useradd -M`) that owns `/PGSM/`.
The systemd service runs as `User=PGSM`. Do not change this without updating all install scripts.

### 5. SSH keypair location
The keypair lives at `keys/pgsm_rsa` (relative to project root) by default. Configured by
`SSH_Key_Path` in `.env`. It is added as `ssh_public_keys` during LXC creation, granting root
access to containers without a password.

### 6. CT ID range: 500+
LXC containers are assigned IDs starting at 500 (`get_next_ct_id()` in `proxmox.py`).
IDs below 500 are reserved to avoid conflicts with user-created VMs/containers.

### 7. Nginx stream blocks, not http blocks
Game servers use raw TCP. nginx must be configured with `stream {}` context.
The controller's `/etc/nginx/conf.d/` receives files like `pgsm-<ct_id>.conf` from NginxService.
The main `nginx.conf` must include:
```nginx
stream {
    include /etc/nginx/conf.d/*.conf;
}
```
This is a MANUAL one-time setup. PGSM cannot do this automatically.

---

## Server Lifecycle Flow

1. User fills create wizard → POST to `/servers/create`
2. `proxmox.create_lxc()` creates and starts the LXC container
3. Background thread calls `server_lifecycle.provision_server(server_id)`
4. Provision: wait for SSH → upload install script → run it → write server.properties → write nginx conf → start service
5. Status transitions: `creating` → `running` (or `error` if anything fails)
6. UI polls `/api/servers/<id>/status` every 5s until status leaves `creating`

---

## Game Codes

| Code  | Meaning                              |
|-------|--------------------------------------|
| MCJAV | All Minecraft Java variants (Vanilla, Paper, Fabric, Forge) |
| MCBED | Minecraft Bedrock Edition            |

The `server_type` column on `GameServer` distinguishes Vanilla/Paper/Fabric/Forge within MCJAV.

---

## Java Version Matrix (Minecraft)

| Minecraft Version | Java |
|-------------------|------|
| < 1.17            | 8    |
| 1.17              | 16   |
| > 1.17            | 17   |
| ≥ 1.20.6          | 21   |

Logic in `app/models/server.py` → `_resolve_java_version()`.
Install scripts download all four Java versions to `/opt/java/` regardless; the correct
one is selected by `STARTUP_COMMAND` in each script.

---

## Adding a New Server Type

1. Create a new install script in `Scripts/<GameType>/`
2. Add an entry to `INSTALL_SCRIPTS` in `app/services/minecraft.py`
3. Add a game code to `GAME_CODES` in `app/services/minecraft.py`
4. Add the option to the `<select name="server_type">` in `app/templates/servers/create.html`
5. Make sure the install script:
   - Creates tmux session named `PGSM`
   - Creates systemd unit named `PGSM`
   - Puts all files in `/PGSM/`
   - Creates a `PGSM` user (no home directory) that owns `/PGSM/`

---

## Console Connection Model

- HTTP route at `/console/<id>` renders the xterm.js terminal
- Browser connects via SocketIO → `join_console` event
- Server-side: background thread opens SSH `invoke_shell()` to the container, sends `tmux attach -t PGSM`
- Output streams back via `console_output` SocketIO events
- User input via `console_input` events → `send_console_command()` → `tmux send-keys -t PGSM`
- Only one streaming thread per server (tracked by `_active_sessions` dict in `console/routes.py`)
- Thread exits when all viewers leave (empty set in `_active_sessions`)

---

## Known Limitations and Future Work

- **Bedrock download URL**: Bedrock server downloads require a URL from the Microsoft API which
  requires accepting Terms of Service. The current implementation passes a `serverfilelink` arg
  to `install-mcbedr.sh` but the caller (MinecraftService) does not yet resolve Bedrock URLs
  automatically. This needs a Bedrock URL resolver similar to `get_vanilla_jar_url()`.

- **Paper/Fabric/Forge resolution**: Currently uses the vanilla JAR URL for Paper/Fabric and
  requires a separate `forge_url` for Forge. Production use should integrate the Paper API
  (`https://api.papermc.io/v2/projects/paper/`), Fabric meta API, and Forge promotions API.

- **Port conflicts**: `get_next_ip()` finds the next free IP, but game port conflicts (e.g., two
  servers both requesting port 25565) are not detected. Add port conflict checking in the create route.

- **Minecraft.py at root**: The original `Minecraft.py` file at the project root is now superseded
  by `app/services/minecraft.py`. It can be removed once nothing else imports from it.

- **Authentication**: The web UI has no login system. Add Flask-Login before exposing to a network.

- **Server console resize**: The xterm.js terminal is fixed at 220x50. A proper PTY resize would
  require sending the new dimensions via SocketIO and resizing the Paramiko channel.
