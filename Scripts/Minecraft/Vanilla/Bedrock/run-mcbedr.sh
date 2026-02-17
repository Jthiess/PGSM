#!/bin/bash
# Run script for Minecraft Bedrock Edition
# Typically invoked by the systemd PGSM service via tmux.
# Run manually: bash run-mcbedr.sh

cd /PGSM
./bedrock_server
