#!/bin/bash
# Run script for Minecraft Java Edition - Fabric
# Typically invoked by the systemd PGSM service via tmux.
# Run manually: bash run-mcfabr.sh

JAVA_BIN="/opt/java/java21/bin/java"
cd /PGSM
$JAVA_BIN -Xms512M -Xmx2G -XX:+UseG1GC -jar fabric-server-launch.jar --nogui
