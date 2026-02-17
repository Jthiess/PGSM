#!/bin/bash
# Run script for Minecraft Java Edition - Paper
# Typically invoked by the systemd PGSM service via tmux.
# Run manually: bash run-mcpape.sh

JAVA_BIN="/opt/java/java21/bin/java"
cd /PGSM
$JAVA_BIN -Xms512M -Xmx2G -XX:+UseG1GC -jar server.jar --nogui
