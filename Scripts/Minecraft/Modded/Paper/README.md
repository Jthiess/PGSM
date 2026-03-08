# Minecraft Java — Paper Install Script

**Script**: `install-mcpape.sh`
**Server type**: `paper`
**Game code**: `MCJAV`

---

## What It Does

1. Updates and upgrades the container (`apt update && apt upgrade -y`)
2. Downloads Java 8, 16, 17, 21, and 25 (Eclipse Temurin JREs) to `/opt/java/`
3. Extracts and renames each Java version
4. Downloads the Paper server JAR from `serverfilelink` to `/PGSM/server.jar`
5. Creates the `PGSM` system user, sets ownership, and symlinks the selected Java to `/usr/local/bin/java`
6. Writes `eula=true` to `/PGSM/eula.txt`
7. Installs tmux
8. Writes and enables the `PGSM` systemd service (Type=forking, starts `server.jar` in a tmux session named `PGSM`)

---

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `serverfilelink` | **Yes** | URL to the Paper server JAR. Script exits with an error if omitted. |
| `java_version` | No | Java major version: `8`, `16`, `17`, `21`, or `25`. Defaults to `21`. |
| `startup_command` | No | Override the full startup command. |
| `type` | No | Server type string (always `paper` for this script) |

---

## Default Startup Command

```
/opt/java/java<version>/bin/java -Xms512M -Xmx2G -XX:+UseG1GC -jar server.jar --nogui
```

---

## Additional Scripts

`run-mcpape.sh` — Standalone helper to start the Paper server manually outside of systemd. Not used by PGSM directly.

---

## Notes

- Paper is API-compatible with Bukkit/Spigot plugins but delivers significantly better performance.
- The Paper JAR URL must come from the Paper API (`https://api.papermc.io/v2/projects/paper/`). PGSM currently passes the vanilla JAR URL here — proper Paper API integration is a known limitation.
- `server.properties` is written separately by PGSM via SFTP after the script completes.
