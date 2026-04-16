import logging
import os

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Maps server_type → game code
GAME_CODES = {
    'vanilla': 'MCJAV',
    'paper':   'MCJAV',
    'fabric':  'MCJAV',
    'forge':   'MCJAV',
    'bedrock': 'MCBED',
    'import':  'MCJAV',
}

# Maps server_type → install script path (relative to project root)
INSTALL_SCRIPTS = {
    'vanilla': 'Scripts/Minecraft/Vanilla/Java/install-mcjava.sh',
    'bedrock': 'Scripts/Minecraft/Vanilla/Bedrock/install-mcbedr.sh',
    'paper':   'Scripts/Minecraft/Modded/Paper/install-mcpape.sh',
    'fabric':  'Scripts/Minecraft/Modded/Fabric/install-mcfabr.sh',
    'forge':   'Scripts/Minecraft/Modded/Forge/install-mcforg.sh',
    'import':  'Scripts/Minecraft/Import/install-import.sh',
}

# Maps server_type → display name
SERVER_TYPE_NAMES = {
    'vanilla': 'Minecraft Java - Vanilla',
    'paper':   'Minecraft Java - Paper',
    'fabric':  'Minecraft Java - Fabric',
    'forge':   'Minecraft Java - Forge',
    'bedrock': 'Minecraft Bedrock',
    'import':  'Minecraft - Import',
}

_FORGE_PROMOS_URL = 'https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json'
_FORGE_INSTALLER_URL = 'https://maven.minecraftforge.net/net/minecraftforge/forge/{mc}-{forge}/forge-{mc}-{forge}-installer.jar'
_FABRIC_LOADER_URL = 'https://meta.fabricmc.net/v2/versions/loader'
_FABRIC_INSTALLER_URL = 'https://meta.fabricmc.net/v2/versions/installer'
_PAPER_API_URL = 'https://api.papermc.io/v2/projects/paper'


class MinecraftService:

    def get_vanilla_jar_url(self, version: str, snapshot: bool = False) -> str:
        """Resolves a Minecraft version string to its server JAR download URL via Mojang API.
        Directly absorbs the logic from the original Minecraft.py JavaManifester()."""
        logger.info('Resolving vanilla JAR URL for version=%s (snapshot=%s)', version, snapshot)
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
            logger.error("Minecraft version '%s' not found in Mojang manifest", version_id)
            raise ValueError(f"Minecraft version '{version_id}' not found in Mojang manifest.")

        version_page = requests.get(version_entry['url'], timeout=10).json()
        jar_url = version_page['downloads']['server']['url']
        logger.info('Resolved vanilla JAR URL for %s: %s', version_id, jar_url)
        return jar_url

    def get_available_versions(self, include_snapshots: bool = False) -> list[dict]:
        """Returns a list of available Minecraft versions from the Mojang manifest."""
        manifest_url = current_app.config['MINECRAFT_MANIFEST_URL']
        response = requests.get(manifest_url, timeout=10).json()
        versions = response['versions']
        if not include_snapshots:
            versions = [v for v in versions if v['type'] == 'release']
        return versions

    def get_forge_versions(self, mc_version: str) -> dict:
        """Returns recommended and latest Forge versions for a given MC version.

        Returns a dict like:
            {'recommended': '47.3.12', 'latest': '47.3.12'}
        Either value may be None if not available for the given MC version.
        """
        promos = requests.get(_FORGE_PROMOS_URL, timeout=10).json().get('promos', {})
        return {
            'recommended': promos.get(f'{mc_version}-recommended'),
            'latest':      promos.get(f'{mc_version}-latest'),
        }

    def get_forge_installer_url(self, mc_version: str, forge_version: str | None = None) -> str:
        """Resolves a Forge installer JAR URL for a given MC + Forge version.

        If forge_version is None, uses the recommended version (falling back to latest).
        Raises ValueError if no Forge version is found for the given MC version.
        """
        logger.info('Resolving Forge installer URL for MC=%s, forge_version=%s', mc_version, forge_version or 'auto')
        if not forge_version:
            versions = self.get_forge_versions(mc_version)
            forge_version = versions['recommended'] or versions['latest']
            if not forge_version:
                logger.error('No Forge version found for Minecraft %s', mc_version)
                raise ValueError(f"No Forge version found for Minecraft {mc_version}")
            logger.info('Auto-resolved Forge version for MC=%s: %s', mc_version, forge_version)
        url = _FORGE_INSTALLER_URL.format(mc=mc_version, forge=forge_version)
        logger.info('Forge installer URL: %s', url)
        return url

    def get_paper_jar_url(self, mc_version: str) -> str:
        """Resolves the latest Paper build JAR download URL for a given Minecraft version."""
        logger.info('Resolving Paper JAR URL for MC version=%s', mc_version)
        # Get the latest build number for this MC version
        version_url = f'{_PAPER_API_URL}/versions/{mc_version}'
        version_data = requests.get(version_url, timeout=10)
        if version_data.status_code != 200:
            logger.error("Paper does not support Minecraft version '%s' (HTTP %s)", mc_version, version_data.status_code)
            raise ValueError(f"Paper does not support Minecraft version '{mc_version}'")
        builds = version_data.json().get('builds', [])
        if not builds:
            logger.error("No Paper builds found for Minecraft version '%s'", mc_version)
            raise ValueError(f"No Paper builds found for Minecraft version '{mc_version}'")
        latest_build = builds[-1]
        # Get the download filename for this build
        build_url = f'{_PAPER_API_URL}/versions/{mc_version}/builds/{latest_build}'
        build_data = requests.get(build_url, timeout=10).json()
        download_name = build_data['downloads']['application']['name']
        jar_url = f'{_PAPER_API_URL}/versions/{mc_version}/builds/{latest_build}/downloads/{download_name}'
        logger.info('Resolved Paper JAR URL for %s build %s: %s', mc_version, latest_build, jar_url)
        return jar_url

    def get_fabric_loader_versions(self) -> list[dict]:
        """Returns a list of available Fabric loader versions."""
        return requests.get(_FABRIC_LOADER_URL, timeout=10).json()

    def get_fabric_installer_url(self) -> str:
        """Resolves the latest stable Fabric installer JAR download URL."""
        logger.info('Resolving latest stable Fabric installer URL')
        installers = requests.get(_FABRIC_INSTALLER_URL, timeout=10).json()
        stable = [i for i in installers if i.get('stable')]
        if not stable:
            logger.error('No stable Fabric installer versions found')
            raise ValueError('No stable Fabric installer versions found')
        url = stable[0]['url']
        logger.info('Resolved Fabric installer URL: %s', url)
        return url

    def get_fabric_loader_version(self, loader_version: str | None = None) -> str:
        """Resolves a Fabric loader version. If None, returns the latest stable."""
        if loader_version:
            logger.info('Using specified Fabric loader version: %s', loader_version)
            return loader_version
        logger.info('Resolving latest stable Fabric loader version')
        loaders = self.get_fabric_loader_versions()
        stable = [l for l in loaders if l.get('stable')]
        if not stable:
            logger.error('No stable Fabric loader versions found')
            raise ValueError('No stable Fabric loader versions found')
        resolved = stable[0]['version']
        logger.info('Resolved latest stable Fabric loader version: %s', resolved)
        return resolved

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
        logger.info('Building install args for server_id=%s type=%s version=%s',
                    server.id, server.server_type, server.game_version)
        args = [f'type={server.server_type}']

        if server.server_type == 'import':
            if not server.import_archive_url:
                raise ValueError('import_archive_url is required for import server type')
            if not server.custom_startup_command:
                raise ValueError('custom_startup_command is required for import server type (e.g. "java -jar server.jar nogui")')
            # import_archive_url holds the local host path; the file will be
            # uploaded to /tmp/server-archive.zip on the container by provision_server()
            args.append('archive_path=/tmp/server-archive.zip')

        elif server.server_type == 'forge':
            forge_url = self.get_forge_installer_url(server.game_version, server.forge_version)
            # Forge script uses forge_url if set, serverfilelink as fallback — pass both
            args.append(f'serverfilelink={shlex.quote(forge_url)}')
            args.append(f'forge_url={shlex.quote(forge_url)}')

        elif server.server_type == 'paper':
            jar_url = self.get_paper_jar_url(server.game_version)
            args.append(f'serverfilelink={jar_url}')

        elif server.server_type == 'fabric':
            installer_url = self.get_fabric_installer_url()
            loader_version = self.get_fabric_loader_version(server.fabric_loader_version)
            args.append(f'fabric_installer_url={installer_url}')
            args.append(f'fabric_version={loader_version}')
            args.append(f'mc_version={server.game_version}')

        else:
            # vanilla
            jar_url = self.get_vanilla_jar_url(server.game_version)
            args.append(f'serverfilelink={jar_url}')

        if server.java_version:
            args.append(f'java_version={server.java_version}')
        if server.custom_startup_command:
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
