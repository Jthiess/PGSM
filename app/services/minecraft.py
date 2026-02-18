import os

import requests
from flask import current_app

# Maps server_type → game code
GAME_CODES = {
    'vanilla': 'MCJAV',
    'paper':   'MCJAV',
    'fabric':  'MCJAV',
    'forge':   'MCJAV',
    'bedrock': 'MCBED',
}

# Maps server_type → install script path (relative to project root)
INSTALL_SCRIPTS = {
    'vanilla': 'Scripts/Minecraft/Vanilla/Java/install-mcjava.sh',
    'bedrock': 'Scripts/Minecraft/Vanilla/Bedrock/install-mcbedr.sh',
    'paper':   'Scripts/Minecraft/Modded/Paper/install-mcpape.sh',
    'fabric':  'Scripts/Minecraft/Modded/Fabric/install-mcfabr.sh',
    'forge':   'Scripts/Minecraft/Modded/Forge/install-mcforg.sh',
}

# Maps server_type → display name
SERVER_TYPE_NAMES = {
    'vanilla': 'Minecraft Java - Vanilla',
    'paper':   'Minecraft Java - Paper',
    'fabric':  'Minecraft Java - Fabric',
    'forge':   'Minecraft Java - Forge',
    'bedrock': 'Minecraft Bedrock',
}


class MinecraftService:

    def get_vanilla_jar_url(self, version: str, snapshot: bool = False) -> str:
        """Resolves a Minecraft version string to its server JAR download URL via Mojang API.
        Directly absorbs the logic from the original Minecraft.py JavaManifester()."""
        manifest_url = current_app.config['MINECRAFT_MANIFEST_URL']
        response = requests.get(manifest_url, timeout=10).json()

        if version == 'latest':
            version_id = (
                response['latest']['snapshot'] if snapshot
                else response['latest']['release']
            )
        else:
            version_id = version

        version_entry = next(
            (v for v in response['versions'] if v['id'] == version_id),
            None,
        )
        if not version_entry:
            raise ValueError(f"Minecraft version '{version_id}' not found in Mojang manifest.")

        version_page = requests.get(version_entry['url'], timeout=10).json()
        return version_page['downloads']['server']['url']

    def get_available_versions(self, include_snapshots: bool = False) -> list[dict]:
        """Returns a list of available Minecraft versions from the Mojang manifest."""
        manifest_url = current_app.config['MINECRAFT_MANIFEST_URL']
        response = requests.get(manifest_url, timeout=10).json()
        versions = response['versions']
        if not include_snapshots:
            versions = [v for v in versions if v['type'] == 'release']
        return versions

    def get_script_path(self, server_type: str) -> str:
        """Returns the absolute path to the install script for a given server type."""
        relative = INSTALL_SCRIPTS.get(server_type)
        if not relative:
            raise ValueError(f"Unknown server type: {server_type}")
        # Resolve relative to project root (two levels up from this file's package)
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(project_root, relative)

    def build_install_args(self, server) -> str:
        """Builds the argument string for the install script from a GameServer instance."""
        import shlex
        jar_url = self.get_vanilla_jar_url(server.game_version)
        args = [f'serverfilelink={jar_url}', f'type={server.server_type}']
        if server.java_version_override:
            args.append(f'java_version={server.java_version_override}')
        if server.custom_startup_command:
            # Use shlex.quote on the value portion only; the key= prefix has no spaces
            args.append(f'startup_command={shlex.quote(server.custom_startup_command)}')
        return ' '.join(args)

    def generate_server_properties(self, server) -> str:
        """Generates the content of server.properties for a Minecraft Java server."""
        lines = [
            f"server-port={server.game_port}",
            f"motd={server.motd or 'A PGSM Minecraft Server'}",
            f"view-distance={server.render_distance}",
            f"spawn-protection={server.spawn_protection}",
            f"difficulty={server.difficulty}",
            f"hardcore={'true' if server.hardcore else 'false'}",
            "online-mode=true",
            "max-players=20",
            "enable-rcon=false",
            "white-list=false",
            "enable-query=true",
            f"query.port={server.game_port}",
        ]
        return "\n".join(lines) + "\n"
