# Minecraft Modded Install Scripts

This directory contains install scripts for modded/enhanced Minecraft Java Edition servers.

| Subdirectory | Platform | Script |
|-------------|---------|--------|
| `Paper/` | Paper (performance-focused, Bukkit/Spigot plugin support) | `install-mcpape.sh` |
| `Fabric/` | Fabric (lightweight mod loader) | `install-mcfabr.sh` |
| `Forge/` | Forge (heavy mod loader, most mods target this) | `install-mcforg.sh` |

All three variants use the same Java installation process (Eclipse Temurin, Java 8/16/17/21/25 to `/opt/java/`) and the same systemd/tmux service structure as the vanilla Java script.

See each subdirectory's README for script-specific arguments and details.
