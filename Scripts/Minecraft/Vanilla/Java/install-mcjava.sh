#!/bin/bash
#########################################
#      Proxmox Game Server Manager      #
#            Install Script             #
# Minecraft Java Edition Vanilla Server #
#########################################


# Variables
for arg in "$@"; do
  case $arg in
    serverfilelink=*) SERVERFILELINK="${arg#*=}" ;;
    type=*) TYPE="${arg#*=}" ;;
  esac
done
JAVA21_URL="https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz"
JAVA17_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.17%2B10/OpenJDK17U-jre_x64_linux_hotspot_17.0.17_10.tar.gz"
JAVA16_URL="https://github.com/adoptium/temurin16-binaries/releases/download/jdk-16.0.2%2B7/OpenJDK16U-jdk_x64_linux_hotspot_16.0.2_7.tar.gz"
JAVA8_URL="https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u472-b08/OpenJDK8U-jre_x64_linux_hotspot_8u472b08.tar.gz"

# Step 1: Update and Upgrade
apt update
apt upgrade -y

# Step 2: Install Java
mkdir -p /opt/java
cd /opt/java
  wget $JAVA21_URL
  wget $JAVA17_URL
  wget $JAVA16_URL
  wget $JAVA8_URL

# Step 3: Extract Javas
for f in *.tar.gz; do
    tar -xzf "$f"
done
rm *.tar.gz
mv jdk-21* java21
mv jdk-17* java17
mv jdk-16* java16
mv jdk8* java8

# Step 4: Download Minecraft Server File
mkdir /PGSM
cd /PGSM
wget $SERVERFILELINK
mv *.jar server.jar
chmod +x server.jar

# Step 5: Create User for minecraft
useradd -M -s /bin/bash PGSM-User
chown -R PGSM-User:PGSM-User /PGSM
chmod -R 755 /opt/java

# Step 6: Accept EULA (For testing purposes only, of course.)
echo "eula=true" > /PGSM/eula.txt # This line of code should never be used in a production environment.