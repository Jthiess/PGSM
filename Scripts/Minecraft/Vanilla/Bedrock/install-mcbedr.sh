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

# Step 5: Create tmux systemd service
echo "Creating systemd service..."
tee /etc/systemd/system/PGSM.service > /dev/null <<EOF
[Unit]
Description=Proxmox Game Server Manager - Bedrock
After=network.target

[Service]
Type=forking
User=PGSM
Group=PGSM
WorkingDirectory=/PGSM
Environment=TERM=xterm-256color
Environment=TMUX_TMPDIR=/tmp
ExecStart=/usr/bin/tmux new-session -d -c /PGSM -s PGSM "./bedrock_server"
ExecStop=/usr/bin/tmux kill-session -t PGSM
Restart=on-failure
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Step 6: Enable and start
systemctl enable PGSM
systemctl start PGSM
