"""Package a fresh, verified launcher installation without Windows registration."""
import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.bootstrap import install_seed
from bc2launcher.selfupdate.package import verify_installed
from bc2launcher.selfupdate.paths import reject_links, validate_version


def package_portable(seed, version, output, public_key):
    seed = reject_links(Path(seed).absolute())
    output = reject_links(Path(output).absolute())
    validate_version(version)
    allowed = {'BC2Launcher.exe', 'installation.json', 'seed-policy.json', 'versions'}
    if any(path.name not in allowed for path in seed.iterdir()):
        raise UpdateError('Portable input must be a fresh build seed, without user files.')
    if set(path.name for path in (seed / 'versions').iterdir()) != {version}:
        raise UpdateError('Portable seed must contain exactly the requested version.')
    for path in seed.rglob('*'):
        reject_links(path)
    if not (seed / 'BC2Launcher.exe').is_file():
        raise UpdateError('Portable bootstrap is missing.')
    verify_installed(seed, version, public_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bc2-portable-') as folder:
        fresh = Path(folder) / 'BC2Launcher'
        shutil.copytree(seed, fresh)
        install_seed(fresh, version, public_key)
        files = sorted(path for path in fresh.rglob('*') if path.is_file() and path.suffix != '.lock')
        created = False
        try:
            stream = output.open('xb')
            created = True
            with stream, zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in files:
                    name = 'BC2Launcher/' + path.relative_to(fresh).as_posix()
                    info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, path.read_bytes(), compresslevel=9)
        except Exception:
            if created:
                output.unlink(missing_ok=True)
            raise
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    package_portable(args.seed, args.version, args.output,
                     (ROOT / 'launcher' / 'assets' / 'public-key.bin').read_bytes())
    print('Portable ZIP ready: ' + args.output)
