# Minecraft Install Scripts

This directory contains all install scripts for Minecraft server variants supported by PGSM.

---

## Variants

| Directory | Server Type | Script |
|-----------|-------------|--------|
| `Vanilla/Java/` | Minecraft Java — Vanilla | `install-mcjava.sh` |
| `Vanilla/Bedrock/` | Minecraft Bedrock | `install-mcbedr.sh` |
| `Modded/Paper/` | Minecraft Java — Paper | `install-mcpape.sh` |
| `Modded/Fabric/` | Minecraft Java — Fabric | `install-mcfabr.sh` |
| `Modded/Forge/` | Minecraft Java — Forge | `install-mcforg.sh` |
| `Import/` | Import existing archive | `install-import.sh` |

---

## Common Java Install Steps

All Java Edition scripts follow the same core steps:

1. `apt update && apt upgrade -y`
2. Download Java 8, 16, 17, 21, 25 (Eclipse Temurin) to `/opt/java/`
3. Extract and rename directories (`jdk-21*` → `java21`, etc.)
4. Download/install server files to `/PGSM/` (type-specific)
5. Create `PGSM` user, `chown` `/PGSM/`, symlink selected Java to `/usr/local/bin/java`
6. Write `eula=true` to `/PGSM/eula.txt`
7. Install tmux
8. Write and enable the `PGSM` systemd service

Bedrock does not use Java and skips steps 2–3 and 6.
