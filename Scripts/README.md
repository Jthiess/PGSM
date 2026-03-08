# PGSM Install Scripts

This directory contains all server install scripts used by PGSM. When a new game server is provisioned, PGSM uploads the appropriate script to `/tmp/install.sh` on the LXC container and runs it with `key=value` arguments.

---

## Directory Structure

```
Scripts/
├── Minecraft/
│   ├── Vanilla/
│   │   ├── Java/         # Minecraft Java Edition (vanilla)
│   │   └── Bedrock/      # Minecraft Bedrock Edition
│   ├── Modded/
│   │   ├── Paper/        # Paper (performance-optimized Java server)
│   │   ├── Fabric/       # Fabric mod loader
│   │   └── Forge/        # Forge mod loader
│   └── Import/           # Import an existing server archive
└── Counter Strike/       # (placeholder, not yet implemented)
```

---

## Script Conventions

All scripts must follow these conventions so PGSM can manage the server correctly:

- **tmux session**: Create and start the server in a tmux session named `PGSM`
- **systemd unit**: Register a systemd unit named `PGSM` (Type=forking, starts the tmux session)
- **Server directory**: All server files must live in `/PGSM/`
- **PGSM user**: Create a system user named `PGSM` via `useradd -M` (no home dir) and `chown -R PGSM:PGSM /PGSM`
- **Arguments**: Accept settings as `key=value` positional arguments (no dashes), parsed with a `case` loop

---

## Script Registration

Each script is registered in `app/services/minecraft.py` → `INSTALL_SCRIPTS`. The service also builds the argument string via `build_install_args()` from the `GameServer` model.

To add a new script, see the **Adding a New Server Type** section in `Development Docs/READ THIS PLEASE DEVELOPERS.md`.
