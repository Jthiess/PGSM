#!/bin/bash
#########################################
#      Proxmox Game Server Manager      #
#            Install Script             #
#    Minecraft Java Edition - Forge     #
#########################################

# Variables
for arg in "$@"; do
  case $arg in
    serverfilelink=*) SERVERFILELINK="${arg#*=}" ;;
    forge_url=*) FORGE_URL="${arg#*=}" ;;
    type=*) TYPE="${arg#*=}" ;;
  esac
done

if [ -z "$SERVERFILELINK" ]; then
    echo "ERROR: serverfilelink argument is required."
    exit 1
fi

JAVA21_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz"
JAVA17_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.17%2B10/OpenJDK17U-jre_x64_linux_hotspot_17.0.17_10.tar.gz"
JAVA16_URL="https://github.com/adoptium/temurin16-binaries/releases/download/jdk-16.0.2%2B7/OpenJDK16U-jdk_x64_linux_hotspot_16.0.2_7.tar.gz"
JAVA8_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u472-b08/OpenJDK8U-jre_x64_linux_hotspot_8u472b08.tar.gz"
STARTUP_COMMAND="/opt/java/java21/bin/java -Xms512M -Xmx2G -XX:+UseG1GC @libraries/net/minecraftforge/forge/*/unix_args.txt nogui"

# Step 1: Update and Upgrade
echo "Running updates..."
apt update
apt upgrade -y

# Step 2: Install Java
echo "Installing Java..."
mkdir -p /opt/java
cd /opt/java
wget $JAVA21_URL
wget $JAVA17_URL
wget $JAVA16_URL
wget $JAVA8_URL

# Step 3: Extract Java
echo "Extracting Java files..."
for f in *.tar.gz; do
    tar -xzf "$f"
done
rm *.tar.gz
mv jdk-21* java21
mv jdk-17* java17
mv jdk-16* java16
mv jdk8* java8

# Step 4: Download Forge installer
echo "Downloading Forge installer..."
mkdir -p /PGSM
cd /PGSM
if [ -n "$FORGE_URL" ]; then
    wget "$FORGE_URL" -O forge-installer.jar
else
    echo "WARNING: No forge_url provided. Using serverfilelink as Forge installer."
    wget "$SERVERFILELINK" -O forge-installer.jar
fi

# Step 5: Run Forge installer
echo "Running Forge installer..."
/opt/java/java21/bin/java -jar forge-installer.jar --installServer
rm forge-installer.jar

# Step 6: Create PGSM user
echo "Creating PGSM user..."
useradd -M -s /bin/bash PGSM
chown -R PGSM:PGSM /PGSM
chmod -R 755 /opt/java

# Step 7: Accept EULA
echo "Accepting EULA..."
echo "eula=true" > /PGSM/eula.txt

# Step 8: Install tmux
apt install tmux -y

# Step 9: Create systemd service
tee /etc/systemd/system/PGSM.service > /dev/null <<EOF
[Unit]
Description=Proxmox Game Server Manager - Forge
After=network.target

[Service]
Type=forking
User=PGSM
Group=PGSM
Environment=TERM=xterm-256color
Environment=TMUX_TMPDIR=/tmp
ExecStart=/usr/bin/tmux new-session -d -c /PGSM -s PGSM "$STARTUP_COMMAND"
ExecStop=/usr/bin/tmux kill-session -t PGSM
Restart=on-failure
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Step 10: Enable and start
systemctl enable PGSM
systemctl start PGSM
