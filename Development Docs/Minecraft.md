# Minecraft Notes

## Java Version Matrix

Java versions are auto-selected based on the Minecraft version. Logic lives in `app/models/server.py` → `_resolve_java_version()`.

| Minecraft Version | Java Required |
|-------------------|---------------|
| < 1.17            | 8             |
| 1.17.x            | 16            |
| 1.17.1 – 1.20.5   | 17            |
| ≥ 1.20.6          | 21            |

All install scripts also download Java 25 (Eclipse Temurin), which is available as a manual override via `java_version_override` but not auto-selected by any current Minecraft version.

Java binaries are stored in `/opt/java/java<version>/` and the selected version is symlinked to `/usr/local/bin/java`.

---

## Install Script Process

All Minecraft Java install scripts follow the same structure:

1. `apt update && apt upgrade -y`
2. Download all Java versions (8, 16, 17, 21, 25) from Eclipse Temurin to `/opt/java/`
3. Extract and rename each version (`jdk-21*` → `java21`, etc.)
4. Download server files to `/PGSM/` (type-specific — see below)
5. Create `PGSM` user (`useradd -M`) and `chown -R PGSM:PGSM /PGSM`
6. Accept EULA (`echo "eula=true" > /PGSM/eula.txt`)
7. Install tmux (`apt install tmux -y`)
8. Write `/etc/systemd/system/PGSM.service` (Type=forking, runs tmux session)
9. `systemctl daemon-reload && systemctl enable PGSM && systemctl start PGSM`

### Type-Specific Steps

**Vanilla**: Downloads the Mojang server JAR and renames it to `server.jar`.

**Paper**: Downloads the Paper server JAR from the Paper API and renames it to `server.jar`. Uses G1GC startup flags.

**Fabric**: Downloads the Mojang server JAR, then downloads and runs the Fabric installer (`fabric-installer-latest.jar`) from `maven.fabricmc.net` to install the Fabric server launcher (`fabric-server-launch.jar`).

**Forge**: Downloads the Forge installer JAR and runs it with `--installServer`. Resolves the startup command from the generated `libraries/net/minecraftforge/forge/*/unix_args.txt`.

**Bedrock**: Downloads the Bedrock server `.zip` via `curl`, unzips it, and runs `./bedrock_server` directly (no Java required).

---

## User-Configurable Options

| Option | Description |
|--------|-------------|
| Version | Minecraft version (e.g. `1.21.4`) |
| Type | `vanilla`, `paper`, `fabric`, `forge`, `bedrock`, `import` |
| Render Distance | Chunk view distance |
| MOTD | Server description shown in the server list |
| Spawn Protection | Radius (in blocks) around spawn that only ops can modify |
| Difficulty | `peaceful`, `easy`, `normal`, `hard` |
| Hardcore | Whether the server runs in hardcore mode |
| Java Version Override | Force a specific Java version (8/16/17/21/25) |
| Custom Startup Command | Override the default server startup command |
| Fabric Loader Version | Pin a specific Fabric loader version (Fabric only) |
| Forge Version | Pin a specific Forge version, e.g. `47.3.12` (Forge only) |
