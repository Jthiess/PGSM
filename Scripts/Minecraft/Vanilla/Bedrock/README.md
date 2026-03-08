# Minecraft Bedrock — Install Script

**Script**: `install-mcbedr.sh`
**Server type**: `bedrock`
**Game code**: `MCBED`

---

## What It Does

1. Updates and upgrades the container (`apt update && apt upgrade -y`)
2. Installs dependencies: `curl unzip libcurl4 libssl-dev tmux`
3. Downloads the Bedrock server `.zip` from `serverfilelink` using `curl`
4. Unzips the archive into `/PGSM/` and marks `bedrock_server` as executable
5. Creates the `PGSM` system user (`useradd -M`) and sets ownership of `/PGSM/`
6. Writes and enables the `PGSM` systemd service (Type=forking, runs `./bedrock_server` in a tmux session named `PGSM`)

---

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `serverfilelink` | **Yes** | URL to the Bedrock server `.zip` from the Microsoft API. Script exits with an error if omitted. |
| `type` | No | Server type string (always `bedrock` for this script) |

---

## Notes

- Bedrock does not use Java. No JRE is downloaded or installed.
- The Bedrock server binary is `bedrock_server` (not a JAR).
- Obtaining a valid `serverfilelink` from the Microsoft/Mojang Bedrock API is not yet automated in PGSM. This is a known limitation — see `Development Docs/READ THIS PLEASE DEVELOPERS.md`.
- There is no `eula.txt` step for Bedrock; the EULA is accepted implicitly by running the server.
