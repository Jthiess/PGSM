#!/bin/bash
#########################################
#      Proxmox Game Server Manager      #
#         Controller Setup Script       #
#########################################
# Run this on a fresh Debian 12 LXC to set up the PGSM controller node.
# The controller needs two network interfaces:
#   eth0 → your main LAN (so you can reach the web UI)
#   eth1 → PGSM VLAN (so it can SSH into game server containers)
#
# Usage:
#   bash setup-controller.sh
#
# What this does:
#   1. Installs system packages (Python, nginx, git)
#   2. Clones/copies PGSM to /opt/pgsm
#   3. Creates a Python venv and installs requirements
#   4. Prompts you to configure .env
#   5. Patches nginx.conf to add TCP stream proxying
#   6. Creates a systemd service so PGSM starts on boot
#   7. Starts PGSM

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PGSM_DIR="/opt/pgsm"
PGSM_USER="pgsm-ctrl"
SERVICE_NAME="pgsm"

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}${BOLD}║    Proxmox Game Server Manager Setup     ║${NC}"
    echo -e "${CYAN}${BOLD}║           Controller Node                ║${NC}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    echo -e "\n${CYAN}${BOLD}──────────────────────────────────────${NC}"
    echo -e "${CYAN}${BOLD}  $1${NC}"
    echo -e "${CYAN}${BOLD}──────────────────────────────────────${NC}"
}

print_ok() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warn() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_err() {
    echo -e "${RED}✗ $1${NC}"
}

prompt() {
    local var_name="$1"
    local prompt_text="$2"
    local default="$3"
    local secret="$4"
    local required="$5"   # pass "required" to reject blank input
    local input=""

    if [ -n "$default" ]; then
        prompt_text="$prompt_text [${default}]"
    fi

    while true; do
        if [ "$secret" = "true" ]; then
            read -rsp "  ${prompt_text}: " input
            echo ""
        else
            read -rp "  ${prompt_text}: " input
        fi

        # Apply default if blank
        if [ -z "$input" ] && [ -n "$default" ]; then
            input="$default"
        fi

        # Reject blank if required
        if [ -z "$input" ] && [ "$required" = "required" ]; then
            print_err "  This field is required — please enter a value."
            continue
        fi

        break
    done

    eval "$var_name='$input'"
}

# ── Preflight checks ──────────────────────────────────────────────────────────

print_header

if [ "$(id -u)" != "0" ]; then
    print_err "This script must be run as root."
    exit 1
fi

if ! grep -q 'ID=debian\|ID=ubuntu' /etc/os-release 2>/dev/null; then
    print_warn "This script is designed for Debian/Ubuntu. Proceeding anyway..."
fi

# ── Step 1: System packages ───────────────────────────────────────────────────

print_step "Step 1: Installing system packages"

echo "  Updating package lists..."
apt-get update -qq

echo "  Upgrading existing packages..."
apt-get upgrade -y -qq

echo "  Installing required packages..."
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    nginx \
    libnginx-mod-stream \
    git \
    curl \
    wget \
    openssh-client \
    sudo \
    rsync

print_ok "System packages installed"

# ── Step 2: Set up PGSM directory ────────────────────────────────────────────

print_step "Step 2: Setting up PGSM application"

# Determine source: are we running from inside the repo, or do we need to clone?
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$REPO_ROOT/main.py" ] && [ -f "$REPO_ROOT/requirements.txt" ]; then
    echo "  Detected PGSM source at: $REPO_ROOT"
    echo "  Copying to $PGSM_DIR..."
    rsync -a --exclude='.venv' --exclude='instance' --exclude='keys' \
          --exclude='__pycache__' --exclude='*.pyc' \
          "$REPO_ROOT/" "$PGSM_DIR/"
    print_ok "Copied PGSM to $PGSM_DIR"
else
    echo "  Source not found locally."
    prompt REPO_URL "Git repository URL (or 'skip' to copy files manually)" ""
    if [ "$REPO_URL" != "skip" ] && [ -n "$REPO_URL" ]; then
        git clone "$REPO_URL" "$PGSM_DIR"
        print_ok "Cloned repository to $PGSM_DIR"
    else
        print_warn "Skipping clone. Copy your PGSM files to $PGSM_DIR manually, then re-run."
        exit 0
    fi
fi

# ── Step 3: Create service user ───────────────────────────────────────────────

print_step "Step 3: Creating service user"

if ! id "$PGSM_USER" &>/dev/null; then
    useradd -r -s /bin/bash -d "$PGSM_DIR" "$PGSM_USER"
    print_ok "Created user: $PGSM_USER"
else
    print_ok "User $PGSM_USER already exists"
fi

# ── Step 4: Python venv + dependencies ───────────────────────────────────────

print_step "Step 4: Installing Python dependencies"

python3 -m venv "$PGSM_DIR/.venv"
"$PGSM_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PGSM_DIR/.venv/bin/pip" install --quiet -r "$PGSM_DIR/requirements.txt"
print_ok "Python venv created and dependencies installed"

# ── Step 5: Configure .env ───────────────────────────────────────────────────

print_step "Step 5: Configure PGSM settings"

if [ -f "$PGSM_DIR/.env" ]; then
    print_warn ".env already exists at $PGSM_DIR/.env"
    read -rp "  Overwrite it? (y/N): " overwrite
    if [ "$overwrite" != "y" ] && [ "$overwrite" != "Y" ]; then
        print_ok "Keeping existing .env"
        SKIP_ENV=true
    fi
fi

if [ "$SKIP_ENV" != "true" ]; then
    echo ""
    echo -e "  ${BOLD}Proxmox API connection${NC}"
    prompt PROXMOX_HOST    "Proxmox host IP or hostname" "10.0.0.3"  ""  "required"
    prompt PROXMOX_PORT    "Proxmox API port"            "8006"
    prompt PROXMOX_USER    "Proxmox username (with realm)" "root@pam" "" "required"
    prompt PROXMOX_PASS    "Proxmox password"            ""           "true" "required"

    echo ""
    echo -e "  ${BOLD}PGSM VLAN network${NC}"
    echo "  (The subnet and gateway of the dedicated PGSM VLAN where game servers live)"
    prompt VLAN_SUBNET   "PGSM VLAN subnet (CIDR)" "172.16.0.0/24"
    prompt VLAN_GATEWAY  "PGSM VLAN gateway IP" "172.16.0.1"
    echo "  (First IP PGSM may assign — leave lower IPs free for Proxmox nodes, router, etc.)"
    prompt VLAN_IP_START "First assignable game server IP" "172.16.0.10"

    echo ""
    echo -e "  ${BOLD}Proxmox LXC template${NC}"
    echo "  (Run 'pveam list kestrel' on your Proxmox host to see available templates)"
    prompt LXC_TEMPLATE "LXC template" "kestrel:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst"

    echo ""
    echo -e "  ${BOLD}Web UI${NC}"
    prompt FLASK_PORT "Port for the PGSM web UI" "5000"

    # Generate a random secret key
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    cat > "$PGSM_DIR/.env" <<EOF
# Proxmox API
Proxmox_Username=${PROXMOX_USER}
Proxmox_Password=${PROXMOX_PASS}
Proxmox_Host=${PROXMOX_HOST}
Proxmox_Port=${PROXMOX_PORT}

# Flask
Flask_Port=${FLASK_PORT}
Secret_Key=${SECRET_KEY}

# Minecraft version manifest
Minecraft_Manifest_Url=https://piston-meta.mojang.com/mc/game/version_manifest.json

# SSH keypair (generated automatically by PGSM on first run)
SSH_Key_Path=keys/pgsm_rsa

# Nginx TCP stream config directory (separate dir to avoid mixing with http conf.d)
Nginx_Conf_Dir=/etc/nginx/pgsm-stream

# PGSM VLAN network
PGSM_VLAN_Subnet=${VLAN_SUBNET}
PGSM_VLAN_Gateway=${VLAN_GATEWAY}
# IPs below this are reserved for Proxmox nodes, router, controller, etc.
PGSM_VLAN_IP_Start=${VLAN_IP_START}

# Proxmox LXC template
PGSM_LXC_Template=${LXC_TEMPLATE}
EOF

    chmod 600 "$PGSM_DIR/.env"
    print_ok ".env written to $PGSM_DIR/.env"
fi

# ── Step 6: Create required directories ──────────────────────────────────────

print_step "Step 6: Creating runtime directories"

mkdir -p "$PGSM_DIR/keys"
mkdir -p "$PGSM_DIR/instance"
chown -R "$PGSM_USER:$PGSM_USER" "$PGSM_DIR"
chmod 700 "$PGSM_DIR/keys"
print_ok "Directories created and ownership set"

# ── Step 7: Configure nginx for TCP stream proxying ──────────────────────────

print_step "Step 7: Configuring nginx"

NGINX_CONF="/etc/nginx/nginx.conf"
# PGSM uses its own stream conf directory to avoid mixing with http conf.d files
PGSM_STREAM_DIR="/etc/nginx/pgsm-stream"
mkdir -p "$PGSM_STREAM_DIR"

# Verify the stream module is available (provided by libnginx-mod-stream)
# On Debian/Ubuntu it auto-installs a conf in /etc/nginx/modules-enabled/
if ! nginx -t 2>&1 | grep -q "unknown directive \"stream\""; then
    :  # stream module is loaded, nothing to do
fi

# Check if stream block already exists
if grep -q "^stream" "$NGINX_CONF" 2>/dev/null; then
    print_ok "nginx stream block already present in $NGINX_CONF"
else
    cat >> "$NGINX_CONF" <<NGINX_EOF

# PGSM - TCP stream proxy for game servers
# Added by setup-controller.sh
stream {
    include ${PGSM_STREAM_DIR}/*.conf;
}
NGINX_EOF
    print_ok "Added stream block to $NGINX_CONF"
fi

# Test and reload nginx
if nginx -t 2>/dev/null; then
    systemctl enable nginx
    systemctl reload nginx
    print_ok "nginx configured and reloaded"
else
    print_warn "nginx config test failed — check $NGINX_CONF manually"
    nginx -t
    print_warn "Common cause: libnginx-mod-stream not installed (should have been installed above)."
    print_warn "Try: apt-get install -y libnginx-mod-stream && nginx -t && systemctl reload nginx"
fi

# ── Step 7b: Grant pgsm-ctrl permission to manage nginx ──────────────────────

SUDOERS_FILE="/etc/sudoers.d/pgsm-nginx"
mkdir -p /etc/sudoers.d
if [ ! -f "$SUDOERS_FILE" ]; then
    echo "${PGSM_USER} ALL=(root) NOPASSWD: /usr/sbin/nginx -s reload, /usr/sbin/nginx -t" > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    print_ok "sudoers entry added for nginx reload"
else
    print_ok "sudoers entry already exists"
fi

# Grant pgsm-ctrl write access to the PGSM stream conf directory
chown root:"$PGSM_USER" "$PGSM_STREAM_DIR"
chmod 775 "$PGSM_STREAM_DIR"
print_ok "nginx stream conf dir write access granted to $PGSM_USER"

# Write the correct stream dir into .env so PGSM knows where to write confs
if grep -q "^Nginx_Conf_Dir=" "$PGSM_DIR/.env" 2>/dev/null; then
    sed -i "s|^Nginx_Conf_Dir=.*|Nginx_Conf_Dir=${PGSM_STREAM_DIR}|" "$PGSM_DIR/.env"
else
    echo "Nginx_Conf_Dir=${PGSM_STREAM_DIR}" >> "$PGSM_DIR/.env"
fi
print_ok "Nginx_Conf_Dir set to $PGSM_STREAM_DIR in .env"

# ── Step 8: Create systemd service ───────────────────────────────────────────

print_step "Step 8: Creating systemd service"

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Proxmox Game Server Manager
Documentation=file://${PGSM_DIR}/Development Docs/FUTURE_CLAUDE.md
After=network.target nginx.service

[Service]
Type=simple
User=${PGSM_USER}
Group=${PGSM_USER}
WorkingDirectory=${PGSM_DIR}
EnvironmentFile=${PGSM_DIR}/.env
ExecStart=${PGSM_DIR}/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
print_ok "systemd service created: $SERVICE_NAME"

# ── Step 9: Start PGSM ───────────────────────────────────────────────────────

print_step "Step 9: Starting PGSM"

systemctl start "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    print_ok "PGSM is running"
else
    print_err "PGSM failed to start. Check logs with: journalctl -u $SERVICE_NAME -n 50"
    systemctl status "$SERVICE_NAME" --no-pager
    exit 1
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║        Setup Complete!                   ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# Get the main LAN IP (first non-PGSM-VLAN IP)
MAIN_IP=$(hostname -I | awk '{print $1}')
FLASK_PORT_VAL=$(grep Flask_Port "$PGSM_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo "5000")

echo -e "  ${BOLD}Web UI:${NC}      http://${MAIN_IP}:${FLASK_PORT_VAL}"
echo ""
echo -e "  ${BOLD}Service commands:${NC}"
echo "    systemctl status $SERVICE_NAME"
echo "    systemctl restart $SERVICE_NAME"
echo "    journalctl -u $SERVICE_NAME -f"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo "  1. Open the web UI and verify the dashboard loads"
echo "  2. Click 'New Server' to create your first game server"
echo "  3. The SSH keypair will be generated automatically on first use"
echo ""
echo -e "  ${BOLD}Nginx prerequisite reminder:${NC}"
echo "  Game server ports are proxied via nginx TCP stream."
echo "  Verify nginx is running: systemctl status nginx"
echo ""
