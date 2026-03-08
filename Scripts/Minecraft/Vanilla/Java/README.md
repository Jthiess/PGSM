# Minecraft Java — Vanilla Install Script

**Script**: `install-mcjava.sh`
**Server type**: `vanilla`
**Game code**: `MCJAV`

---

## What It Does

1. Updates and upgrades the container (`apt update && apt upgrade -y`)
2. Downloads Java 8, 16, 17, 21, and 25 (Eclipse Temurin JREs) to `/opt/java/`
3. Extracts and renames each Java version (`java8`, `java16`, `java17`, `java21`, `java25`)
4. Downloads the Minecraft server JAR from the Mojang CDN to `/PGSM/server.jar`
5. Creates the `PGSM` system user (`useradd -M`), sets ownership, and symlinks the selected Java to `/usr/local/bin/java`
6. Writes `eula=true` to `/PGSM/eula.txt`
7. Installs tmux
8. Writes and enables the `PGSM` systemd service (Type=forking, starts `server.jar` in a tmux session named `PGSM`)

---

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `serverfilelink` | No | URL to the Minecraft server JAR. Defaults to whatever PGSM resolves. |
| `java_version` | No | Java major version to use: `8`, `16`, `17`, `21`, or `25`. Defaults to `21`. |
| `startup_command` | No | Override the full startup command. Default: `$JAVA_BIN -jar server.jar` |
| `type` | No | Server type string (always `vanilla` for this script) |

---

## Default Startup Command

```
/opt/java/java<version>/bin/java -jar server.jar
```

---

## Notes

- The script downloads all five Java versions regardless of which is selected. This is intentional — it avoids re-downloading Java if the version is changed later.
- `server.properties` is written separately by PGSM via SFTP after the script completes.
