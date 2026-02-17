#!/bin/bash
# Run script for Minecraft Java Edition - Forge
# Typically invoked by the systemd PGSM service via tmux.
# Run manually: bash run-mcforg.sh

JAVA_BIN="/opt/java/java21/bin/java"
cd /PGSM
$JAVA_BIN -Xms512M -Xmx2G -XX:+UseG1GC @libraries/net/minecraftforge/forge/*/unix_args.txt nogui
