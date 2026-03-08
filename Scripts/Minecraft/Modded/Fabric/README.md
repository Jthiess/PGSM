# Minecraft Java — Fabric Install Script

**Script**: `install-mcfabr.sh`
**Server type**: `fabric`
**Game code**: `MCJAV`

---

## What It Does

1. Updates and upgrades the container (`apt update && apt upgrade -y`)
2. Downloads Java 8, 16, 17, 21, and 25 (Eclipse Temurin JREs) to `/opt/java/`
3. Extracts and renames each Java version
4. Downloads the vanilla Minecraft server JAR to `/PGSM/server.jar` (required by the Fabric installer)
5. Downloads `fabric-installer-latest.jar` from `https://maven.fabricmc.net/net/fabricmc/fabric-installer/latest/fabric-installer-latest.jar`
6. Runs the Fabric installer: `java -jar fabric-installer.jar server -mcversion <MC_VERSION> -downloadMinecraft`
7. Creates the `PGSM` system user, sets ownership, and symlinks the selected Java to `/usr/local/bin/java`
8. Writes `eula=true` to `/PGSM/eula.txt`
9. Installs tmux
10. Writes and enables the `PGSM` systemd service (Type=forking, runs `server.jar` in a tmux session named `PGSM`)

---

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `serverfilelink` | **Yes** | URL to the vanilla Minecraft server JAR (used as a dependency by Fabric). |
| `mc_version` | No | Minecraft version passed to the Fabric installer. Defaults to `latest`. |
| `fabric_version` | No | Specific Fabric loader version. Omit to use the latest stable release. |
| `java_version` | No | Java major version: `8`, `16`, `17`, `21`, or `25`. Defaults to `21`. |
| `startup_command` | No | Override the full startup command. |
| `type` | No | Server type string (always `fabric` for this script) |

---

## Default Startup Command

```
/opt/java/java<version>/bin/java -Xms512M -Xmx2G -XX:+UseG1GC -jar server.jar --nogui
```

---

## Notes

- The Fabric installer runs using Java 21 regardless of the `java_version` argument — `java_version` only affects the startup command and the symlink at `/usr/local/bin/java`.
- The Fabric installer produces `fabric-server-launch.jar` which is what actually runs when the server starts.
- `server.properties` is written separately by PGSM via SFTP after the script completes.
