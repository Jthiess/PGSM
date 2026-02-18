# PGSM — Proxmox Game Server Manager

PGSM is a web application for deploying and managing game server LXC containers on a Proxmox cluster. It provides a clean UI to create servers, manage their lifecycle, monitor resource usage, access the in-game console, and browse/edit server files — all without needing to touch Proxmox directly.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Installation](#installation)
- [Configuration (.env)](#configuration-env)
- [First-Time Setup](#first-time-setup)
- [Using PGSM](#using-pgsm)
  - [Creating a Server](#creating-a-server)
  - [Managing a Server](#managing-a-server)
  - [Console](#console)
  - [File Manager](#file-manager)
  - [Monitoring](#monitoring)
  - [Deleting a Server](#deleting-a-server)
- [High Availability](#high-availability)
- [Networking](#networking)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before running PGSM, you need:

- **Proxmox VE cluster** (single-node or multi-node) with API access
- **PGSM VLAN** configured on your Proxmox cluster — an isolated network for game server containers (see [Networking](#networking))
- **LXC template** available in Proxmox storage (default: `debian-13-standard_13.1-2_amd64.tar.zst`)
- **nginx** installed on the PGSM controller node with a `stream {}` block (see [Networking](#networking))
- **Python 3.11+** on the controller node
- **SSH keypair** — PGSM will generate one automatically on first use

For **High Availability**, your Proxmox cluster must have at least two nodes with the Proxmox HA manager configured and a corosync quorum established.

---

## Architecture Overview

```
Internet / LAN
      |
  Controller Node  ← runs Flask (PGSM) + nginx
      |         \
  PGSM VLAN      → TCP port proxy (nginx stream)
      |
 ┌────────────────────────┐
 │  Game Server Containers │  (LXC, one per game server)
 │  CT 500, 501, 502 ...  │  Each runs: tmux + systemd PGSM unit
 └────────────────────────┘
```

- **Controller node**: Runs the PGSM Flask app and nginx. nginx proxies raw TCP game traffic from the external network to the correct container on the PGSM VLAN.
- **Game server containers**: Isolated LXC containers (Debian 13). Each runs one game server in a tmux session named `PGSM`, managed by a systemd unit also named `PGSM`. All server files live in `/PGSM/` on the container.
- **Database**: SQLite at `instance/pgsm.db` — stores server metadata, not game data.
- **PGSM communicates** with containers via SSH using an automatically managed RSA keypair.

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd PGSM

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy the example environment file and fill it in
cp .env.example .env
# Edit .env — see Configuration section below
```

---

## Configuration (.env)

All configuration is done via environment variables in a `.env` file at the project root. Create this file before starting PGSM.

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `Proxmox_Host` | Hostname or IP of your Proxmox server | `192.168.1.10` |
| `Proxmox_Username` | Proxmox API user (format: `user@realm`) | `root@pam` |
| `Proxmox_Password` | Password for the Proxmox API user | `your-password` |

### Optional Settings (with defaults)

**Proxmox Connection**

| Variable | Default | Description |
|----------|---------|-------------|
| `Proxmox_Port` | `8006` | Proxmox web API port |

**Flask**

| Variable | Default | Description |
|----------|---------|-------------|
| `Flask_Port` | `5000` | Port PGSM listens on |
| `Secret_Key` | random | Flask session secret key — set a fixed value to keep sessions across restarts |

**PGSM VLAN Network**

| Variable | Default | Description |
|----------|---------|-------------|
| `PGSM_VLAN_Subnet` | `172.16.0.0/24` | The subnet for game server containers |
| `PGSM_VLAN_Gateway` | `172.16.0.1` | Gateway for the PGSM VLAN |
| `PGSM_VLAN_IP_Start` | `172.16.0.10` | First IP PGSM may assign to containers. IPs below this (e.g. `.1`–`.9`) are reserved for infrastructure. |

**LXC Template**

| Variable | Default | Description |
|----------|---------|-------------|
| `PGSM_LXC_Template` | `kestrel:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst` | Proxmox storage path to the LXC template. Must exist in Proxmox before creating servers. |

**SSH**

| Variable | Default | Description |
|----------|---------|-------------|
| `SSH_Key_Path` | `keys/pgsm_rsa` | Path to the RSA private key used to SSH into containers. PGSM generates this automatically if it doesn't exist. |

**nginx**

| Variable | Default | Description |
|----------|---------|-------------|
| `Nginx_Conf_Dir` | `/etc/nginx/conf.d` | Directory where PGSM writes per-server nginx TCP stream config files |

**Minecraft**

| Variable | Default | Description |
|----------|---------|-------------|
| `Minecraft_Manifest_Url` | Mojang's manifest URL | URL for fetching available Minecraft versions. Rarely needs changing. |

**Server Creation Defaults**

These values pre-fill the create server wizard. Override them to match your typical server size.

| Variable | Default | Description |
|----------|---------|-------------|
| `Server_Default_Disk_GB` | `20` | Default disk size in GB |
| `Server_Default_Cores` | `8` | Default CPU core count |
| `Server_Default_Memory_MB` | `4096` | Default RAM in MB |
| `Server_Default_Game_Port` | `25565` | Default Minecraft port |
| `Server_Default_Render_Distance` | `12` | Default chunk render distance |
| `Server_Default_Spawn_Protection` | `0` | Default spawn protection radius |
| `Server_Default_Difficulty` | `normal` | Default difficulty (peaceful/easy/normal/hard) |
| `Server_Default_Server_Type` | `vanilla` | Default server type |
| `Server_Default_HA_Enabled` | `false` | Whether HA is pre-checked in the wizard by default |

---

## First-Time Setup

### 1. Proxmox VLAN

Create a Linux bridge on each Proxmox node called `PGSM` attached to your VLAN. All game server containers use this bridge. The exact VLAN configuration (tagging, physical NIC assignment) depends on your network hardware.

### 2. LXC Template

Download the Debian 13 LXC template in Proxmox:

- Go to **Datacenter → Storage → your storage → CT Templates**
- Download `debian-13-standard_13.1-2_amd64.tar.zst`

Or update `PGSM_LXC_Template` in `.env` to point to a template you already have.

### 3. nginx Stream Block

On the controller node, ensure `/etc/nginx/nginx.conf` contains a `stream` block that includes the conf directory:

```nginx
stream {
    include /etc/nginx/conf.d/*.conf;
}
```

This is a **one-time manual step**. PGSM cannot modify `nginx.conf` itself. Restart nginx after making this change.

### 4. Start PGSM

```bash
source .venv/bin/activate
python main.py
```

PGSM will create the SQLite database and apply any schema migrations automatically on startup. Visit `http://<controller-ip>:5000` in your browser.

---

## Using PGSM

### Creating a Server

1. Click **Create Server** from the dashboard or navigation.
2. **Step 1 — Game Type & Version**: Choose a server type (Vanilla, Paper, Fabric, Forge, or Bedrock) and version. Toggle "Show snapshot versions" for unstable development builds.
3. **Step 2 — Resources & Node**: Choose a Proxmox node and set disk, CPU, and RAM. Enable **High Availability** here if you want Proxmox to automatically restart the container on a different node if the current node fails (requires HA-configured cluster).
4. **Step 3 — Game Settings**: Set the server name, port, MOTD, render distance, spawn protection, difficulty, and hardcore mode.
5. Click **Create Server**.

PGSM will:
- Assign the next available CT ID (500+) and IP address
- Create the LXC container in Proxmox with the `pgsm` tag
- Register the container with Proxmox HA (if enabled)
- Run the game-specific install script inside the container
- Configure nginx to proxy the game port
- Start the game server

This process typically takes 2–5 minutes. The detail page will show "creating" and refresh automatically when provisioning completes.

### Managing a Server

The server detail page shows all information about a server and provides controls to:

- **Start / Stop / Restart** the game server process (not the container itself)
- Open the **Console** for direct server interaction
- Browse **Files** via the built-in SFTP file manager
- View live **Monitoring** metrics (CPU, memory, network)
- Edit **Game Settings** (MOTD, difficulty, render distance, spawn protection, hardcore)
- Add/remove **Ports** for multi-port setups (e.g., separate RCON or Bedrock ports)

The **Info** tab shows a read-only summary including whether HA is enabled.

### Console

The console connects you directly to the game server's interactive session. It's equivalent to being logged into the tmux session named `PGSM` on the container.

- Type commands and press Enter to send them to the server (e.g., `list`, `say Hello`, `stop`)
- Output streams live — no need to refresh
- The server must be **running** for the console to accept input

### File Manager

The file manager lets you browse, edit, download, and upload files in the `/PGSM/` directory on the container (the directory where all game server files live).

- Click any file name to edit it in the built-in code editor
- Use the **Upload** button to send files from your computer
- Use **Download** to retrieve individual files
- You can delete files from the file listing (this is permanent)

The editor supports syntax highlighting for `.properties`, `.yml`, `.json`, `.sh`, and other common file types.

### Monitoring

Available on the **Monitoring** tab when the server is running. Shows:

- **CPU Usage** — percentage of allocated cores in use
- **Memory** — used vs. total allocated RAM
- **Network I/O** — receive and transmit rates (averaged over the last 10 seconds for stability)

Metrics update every 2 seconds.

### Deleting a Server

In the **Danger Zone** at the bottom of the detail page. Deleting a server:

1. Stops the game server process
2. Stops the LXC container
3. Removes the container from Proxmox HA (if HA was enabled)
4. Deletes the LXC container from Proxmox (all container data is permanently destroyed)
5. Removes the nginx port proxy config
6. Deletes the server record from the PGSM database

**This cannot be undone.** World data, configuration, and all files inside the container are permanently lost unless you have external backups.

---

## High Availability

Proxmox HA automatically restarts a container on a different cluster node if the node it's running on becomes unavailable. When HA is enabled on a PGSM server:

- Proxmox monitors the container's health
- If the node fails, the HA manager migrates and restarts the container on another available node
- The game server resumes (with the same IP, since the PGSM VLAN spans all nodes)

**Requirements:**
- Proxmox cluster with at least 2 nodes
- Corosync quorum established
- Proxmox HA manager active (Datacenter → HA)

**Important caveats:**
- HA does not protect against in-container failures (e.g., if the game server crashes, systemd will restart it — not HA)
- HA failover means the game server will experience downtime while the container migrates (typically 30–120 seconds)
- HA is registered without a specific HA group, using Proxmox's default behavior

If you enable HA on a server, PGSM will automatically deregister it from HA when you delete the server.

---

## Networking

PGSM uses an isolated VLAN for all game server containers. This design:

- Prevents game servers from directly accessing your main network
- Allows containers on different physical Proxmox nodes to communicate
- Routes all external traffic through the controller node's nginx TCP proxy

```
Player's Client
       |
    [Internet/LAN]
       |
  Controller Node (nginx)
  Port 25565 → CT 500 → 172.16.0.10:25565
  Port 25566 → CT 501 → 172.16.0.11:25565
       |
  [PGSM VLAN: 172.16.0.0/24]
       |
  ┌──────────────┬──────────────┐
  CT 500          CT 501          ...
  172.16.0.10     172.16.0.11
```

Each server gets:
- A unique IP in the PGSM VLAN subnet (auto-assigned, starting at `PGSM_VLAN_IP_Start`)
- One or more game ports proxied via nginx on the controller node
- DNS server: `1.1.1.1`, search domain: `PGSM.lan`

The VLAN requires a physical or virtual router/switch that supports VLAN tagging, configured separately from PGSM.

---

## Troubleshooting

### "Could not reach Proxmox"
- Verify `Proxmox_Host`, `Proxmox_Username`, and `Proxmox_Password` in `.env`
- Make sure the Proxmox API is accessible from the controller node: `curl -k https://<host>:8006`
- Check that the Proxmox user has sufficient privileges (root@pam or a custom role with VM.Allocate, VM.Config.*, etc.)

### Server stuck on "creating"
- Check the PGSM logs for errors (console output of `python main.py`)
- SSH into the container manually: `ssh -i keys/pgsm_rsa root@<container-ip>`
- Check if the install script ran: `ls /PGSM/`
- Check systemd: `systemctl status PGSM`

### nginx not proxying traffic
- Ensure `nginx.conf` has a `stream {}` block that includes `/etc/nginx/conf.d/*.conf`
- Check PGSM wrote the config: `ls /etc/nginx/conf.d/pgsm-*.conf`
- Test nginx config: `nginx -t`
- Reload nginx: `systemctl reload nginx`

### HA registration failed
- Verify your Proxmox cluster has HA enabled: Proxmox UI → Datacenter → HA
- The cluster must have quorum (at least half of nodes online)
- Check the Proxmox HA manager is running on all nodes

### Console shows no output / input not working
- The server must be in `running` status
- Check that the tmux session exists: SSH into the container and run `tmux list-sessions`
- If the session is named something other than `PGSM`, the install script may have failed midway
