import os
import shutil
from pathlib import Path
from ..manifest import UpdateError
from .paths import inside, reject_links, validate_version, version_dir
from .package import file_hash
from .policy import INVENTORY_NAME
from .store import UpdateStore


def check_destination(root, seed_version=None, seed_inventory_hash=None):
    root = reject_links(root)
    if root == Path(root.anchor) or root == Path.home().absolute(): raise UpdateError('Unsafe installation root.')
    if (root / 'BFBC2Game.exe').exists(): raise UpdateError('Do not install the launcher into the game folder.')
    if root.exists() and any(root.iterdir()):
        marker = UpdateStore(root).read_json('installation.json')
        if marker != dict(schema=1, product='BC2Launcher'):
            raise UpdateError('Choose an empty folder or an existing BC2 Launcher installation.')
        for current, dirs, files in os.walk(root, followlinks=False):
            for name in dirs + files: inside(root, Path(current).relative_to(root), name)
        with UpdateStore(root).locked():
            with UpdateStore(root).locked('client.lock'): pass
        if seed_version:
            seed = version_dir(root, seed_version)
            if seed.exists():
                meta = inside(seed, INVENTORY_NAME)
                if not meta.is_file() or file_hash(meta) != seed_inventory_hash:
                    raise UpdateError('This installed version has a different inventory; use a newer installer.')
    return root


def cleanup_versions(root):
    root = check_destination(root)
    if UpdateStore(root).read_json('installation.json') != dict(schema=1, product='BC2Launcher'):
        raise UpdateError('Missing installation marker; refusing cleanup.')
    with UpdateStore(root).locked():
        with UpdateStore(root).locked('client.lock'):
            versions = inside(root, 'versions')
            if versions.exists():
                for child in versions.iterdir():
                    if not child.name.startswith('.stage-'): validate_version(child.name)
                    inside(root, 'versions', child.name)
                shutil.rmtree(versions)
            cache = inside(root, 'cache')
            if cache.exists(): shutil.rmtree(cache)
