#!/bin/bash
#########################################
#      Proxmox Game Server Manager      #
#            Install Script             #
#    Minecraft Java Edition - Paper     #
#########################################

# Variables
for arg in "$@"; do
  case $arg in
    serverfilelink=*) SERVERFILELINK="${arg#*=}" ;;
    type=*) TYPE="${arg#*=}" ;;
    java_version=*) JAVA_VERSION="${arg#*=}" ;;
    startup_command=*) STARTUP_COMMAND="${arg#*=}" ;;
  esac
done

if [ -z "$SERVERFILELINK" ]; then
    echo "ERROR: serverfilelink argument is required."
    exit 1
fi

JAVA25_URL="https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.2%2B10/OpenJDK25U-jre_x64_linux_hotspot_25.0.2_10.tar.gz"
JAVA21_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz"
JAVA17_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.17%2B10/OpenJDK17U-jre_x64_linux_hotspot_17.0.17_10.tar.gz"
JAVA16_URL="https://github.com/adoptium/temurin16-binaries/releases/download/jdk-16.0.2%2B7/OpenJDK16U-jdk_x64_linux_hotspot_16.0.2_7.tar.gz"
JAVA8_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u472-b08/OpenJDK8U-jre_x64_linux_hotspot_8u472b08.tar.gz"

# Resolve Java binary path based on version (default: 21)
case "${JAVA_VERSION:-21}" in
  8)  JAVA_BIN="/opt/java/java8/bin/java" ;;
  16) JAVA_BIN="/opt/java/java16/bin/java" ;;
  17) JAVA_BIN="/opt/java/java17/bin/java" ;;
  25) JAVA_BIN="/opt/java/java25/bin/java" ;;
  *)  JAVA_BIN="/opt/java/java21/bin/java" ;;
esac

# Use custom startup command if provided, else fall back to default
if [ -z "$STARTUP_COMMAND" ]; then
  STARTUP_COMMAND="$JAVA_BIN -Xms512M -Xmx2G -XX:+UseG1GC -jar server.jar --nogui"
fi

# Step 1: Update and Upgrade
echo "Running updates..."
apt update
apt upgrade -y

# Step 2: Install Java
echo "Installing Java..."
mkdir -p /opt/java
cd /opt/java
wget $JAVA25_URL
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
mv jdk-25* java25
mv jdk-21* java21
mv jdk-17* java17
mv jdk-16* java16
mv jdk8* java8

# Step 4: Download Paper server file
echo "Downloading Paper server file..."
mkdir -p /PGSM
cd /PGSM
wget "$SERVERFILELINK" -O server.jar
chmod +x server.jar

# Step 5: Create PGSM user
echo "Creating PGSM user..."
useradd -M -s /bin/bash PGSM
chown -R PGSM:PGSM /PGSM
chmod -R 755 /opt/java

# Step 6: Accept EULA
echo "Accepting EULA..."
echo "eula=true" > /PGSM/eula.txt

# Step 7: Install tmux
apt install tmux -y

# Step 8: Create systemd service
tee /etc/systemd/system/PGSM.service > /dev/null <<EOF
[Unit]
Description=Proxmox Game Server Manager - Paper
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

# Step 9: Enable and start
systemctl enable PGSM
systemctl start PGSM
