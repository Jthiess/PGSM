# Counter-Strike Install Scripts

> **Status: Not yet implemented.**

This directory is a placeholder for future Counter-Strike (CS2 / CS:GO) server support.

---

## Planned Implementation

A Counter-Strike server install script would need to:

1. Install SteamCMD on the container
2. Use SteamCMD to download the CS2/CS:GO dedicated server files (App ID 730 / 740)
3. Create a `PGSM` user and set up `/PGSM/` as the server directory
4. Create a tmux session named `PGSM` and a systemd unit named `PGSM` that starts it
5. Register a new game code (e.g., `CS2`) in `app/services/minecraft.py`

See `Development Docs/READ THIS PLEASE DEVELOPERS.md` → **Adding a New Server Type** for the full checklist.
