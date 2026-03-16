#!/bin/bash
#########################################
#      Proxmox Game Server Manager      #
#            Install Script             #
#    Minecraft Bedrock Edition Server   #
#########################################

# Variables
for arg in "$@"; do
  case $arg in
    serverfilelink=*) SERVERFILELINK="${arg#*=}" ;;
    type=*) TYPE="${arg#*=}" ;;
  esac
done

if [ -z "$SERVERFILELINK" ]; then
    echo "ERROR: serverfilelink argument is required."
    exit 1
fi

# Step 1: Update and Upgrade
echo "Running updates..."
apt update
apt upgrade -y

# Step 2: Install dependencies for Bedrock server
echo "Installing dependencies..."
apt install -y curl unzip libcurl4 libssl-dev tmux

# Step 3: Download Bedrock Server
echo "Downloading Bedrock server..."
mkdir -p /PGSM
cd /PGSM
curl -L "$SERVERFILELINK" -o bedrock-server.zip
unzip -o bedrock-server.zip
rm bedrock-server.zip
chmod +x bedrock_server

# Step 4: Create PGSM user
echo "Creating PGSM user..."
useradd -M -s /bin/bash PGSM
chown -R PGSM:PGSM /PGSM

# Step 5: Create wrapper script that monitors the tmux session
echo "Creating wrapper script..."
mkdir -p /opt/pgsm
tee /opt/pgsm/run.sh > /dev/null <<'RUNEOF'
#!/bin/bash
# PGSM wrapper: starts the server in tmux and monitors it.
# Exits non-zero on crash (triggering systemd Restart=on-failure).
CLEAN_STOP=0
trap 'CLEAN_STOP=1' SIGTERM SIGINT

/usr/bin/tmux new-session -d -c /PGSM -s PGSM "$@"

while /usr/bin/tmux has-session -t PGSM 2>/dev/null; do
    sleep 2
done

[ "$CLEAN_STOP" -eq 1 ] && exit 0
exit 1
RUNEOF
chmod +x /opt/pgsm/run.sh

# Step 6: Create systemd service
echo "Creating systemd service..."
tee /etc/systemd/system/PGSM.service > /dev/null <<EOF
[Unit]
Description=Proxmox Game Server Manager - Bedrock
After=network.target
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
Type=simple
User=PGSM
Group=PGSM
Environment=TERM=xterm-256color
Environment=TMUX_TMPDIR=/tmp
ExecStart=/opt/pgsm/run.sh ./bedrock_server
ExecStop=/usr/bin/tmux kill-session -t PGSM
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Step 7: Enable and start
systemctl enable PGSM
systemctl start PGSM
