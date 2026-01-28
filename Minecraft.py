from main import MINECRAFT_MANIFEST_URL, requests
def JavaManifester(version: str, snapshot:bool=False):
    response = requests.get(MINECRAFT_MANIFEST_URL, timeout=10).json()

    # Handle "latest" since its not actually a thing
    if version == 'latest':
        version_id = (
            response['latest']['snapshot']
            if snapshot
            else response['latest']['release']
        )
    else:
        version_id = version

    # Find the actual verison entry
    version_entry = next(
        (poop for poop in response['versions'] if poop['id'] == version_id),
        None
    )

    # Cry if it doesnt work
    if not version_entry:
        raise ValueError(f"Version '{version_id}' not found 😭")
    
    # Get the manifest for the specific version
    version_page = requests.get(version_entry['url'], timeout=10).json()

    # Get the damn info (downloads - server - url/sha1)
    return version_page['downloads']['server']['url']

if __name__ == "__main__":
    userinput = input("What version do you want: ")
    print(JavaManifester(userinput))