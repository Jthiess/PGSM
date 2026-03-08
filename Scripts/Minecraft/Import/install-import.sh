#!/bin/bash
#########################################
#      Proxmox Game Server Manager      #
#            Install Script             #
#     Minecraft - Import Server         #
#########################################

# Variables
for arg in "$@"; do
  case $arg in
    archive_path=*) ARCHIVE_PATH="${arg#*=}" ;;
    java_version=*) JAVA_VERSION="${arg#*=}" ;;
    startup_command=*) STARTUP_COMMAND="${arg#*=}" ;;
  esac
done

if [ -z "$ARCHIVE_PATH" ]; then
    echo "ERROR: archive_path argument is required."
    exit 1
fi

if [ -z "$STARTUP_COMMAND" ]; then
    echo "ERROR: startup_command argument is required for imported servers."
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

# Step 4: Prepare server archive
echo "Preparing server archive..."
apt install -y file unzip
mkdir -p /PGSM
cp "$ARCHIVE_PATH" /PGSM/server-archive

# Step 5: Detect format and extract
echo "Extracting server archive..."
cd /PGSM
FILETYPE=$(file server-archive)
if echo "$FILETYPE" | grep -qi "Zip"; then
    unzip -o server-archive
elif echo "$FILETYPE" | grep -qi "gzip\|tar"; then
    tar -xzf server-archive
elif echo "$FILETYPE" | grep -qi "bzip2"; then
    tar -xjf server-archive
elif echo "$FILETYPE" | grep -qi "XZ"; then
    tar -xJf server-archive
else
    # Last-resort: try tar then unzip
    tar -xzf server-archive 2>/dev/null || unzip -o server-archive
fi
rm -f server-archive

# Step 6: If the archive extracted into a single subdirectory, flatten it into /PGSM
SUBDIRS=$(find /PGSM -mindepth 1 -maxdepth 1 -type d)
SUBDIR_COUNT=$(echo "$SUBDIRS" | grep -c .)
FILES=$(find /PGSM -mindepth 1 -maxdepth 1 -type f)
FILE_COUNT=$(echo "$FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$SUBDIR_COUNT" -eq 1 ] && [ "$FILE_COUNT" -eq 0 ]; then
    SUBDIR=$(echo "$SUBDIRS" | head -1)
    echo "Flattening extracted subdirectory: $SUBDIR"
    mv "$SUBDIR"/* /PGSM/ 2>/dev/null || true
    mv "$SUBDIR"/.[!.]* /PGSM/ 2>/dev/null || true
    rmdir "$SUBDIR" 2>/dev/null || true
fi

# Step 7: Create PGSM user
echo "Creating PGSM user..."
useradd -M -s /bin/bash PGSM
chown -R PGSM:PGSM /PGSM
chmod -R 755 /opt/java
ln -sf "$JAVA_BIN" /usr/local/bin/java

# Step 8: Accept EULA
echo "Accepting EULA..."
echo "eula=true" > /PGSM/eula.txt

# Step 9: Install tmux
apt install tmux -y

# Step 10: Create systemd service
tee /etc/systemd/system/PGSM.service > /dev/null <<EOF
[Unit]
Description=Proxmox Game Server Manager - Imported Server
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

# Step 11: Enable and start
systemctl enable PGSM
systemctl start PGSM
