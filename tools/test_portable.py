"""Verify portable startup and update in disposable copies; never run the game."""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'launcher'), str(ROOT / 'tools')]
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.package import verify_installed
from bc2launcher.selfupdate.service import SelfUpdateService
from bc2launcher.selfupdate.store import UpdateStore
from package_launcher import sign_launcher_policy
from test_frozen_update import TEST_BASE, validate_test_root, command, wait_closed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', required=True)
    parser.add_argument('--previous', required=True)
    args = parser.parse_args()
    build = Path(args.build).absolute()
    previous = Path(args.previous).absolute()
    version = json.loads((build / 'client-self-test.json').read_text())['version']
    old_version = json.loads((previous / 'client-self-test.json').read_text())['version']
    case = validate_test_root(TEST_BASE / ('portable-' + secrets.token_hex(5)))
    case.mkdir(parents=True)
    os.environ['LOCALAPPDATA'] = str(case / 'user-data')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    key = load_pem_private_key((ROOT / '.secrets' / 'release-signing.key').read_bytes(), None)
    public = (ROOT / 'launcher' / 'assets' / 'public-key.bin').read_bytes()
    with zipfile.ZipFile(build / ('BC2Launcher-' + version + '-portable.zip')) as archive:
        if archive.testzip() is not None:
            raise UpdateError('Portable ZIP CRC failed.')
        archive.extractall(case / 'unpacked')
    portable = case / 'unpacked' / 'BC2Launcher'
    verify_installed(portable, version, public)
    if UpdateStore(portable).active() != version:
        raise UpdateError('Portable ZIP has no active version.')
    command(portable, '--smoke-startup')
    wait_closed(portable)
    old = case / 'old-portable'
    shutil.copytree(previous / 'seed', old)
    command(old, '--install-seed', old_version)
    original_bootstrap = hashlib.sha256((old / 'BC2Launcher.exe').read_bytes()).hexdigest()
    archive = build / ('BC2Launcher-app-' + version + '.zip')
    raw = sign_launcher_policy(archive, version,
        'https://github.com/RinatBy/bc2-community/releases/download/test/app.zip',
        2, key, datetime.now(timezone.utc), minimum='0.2.0')
    def download(url, path, limit, **kwargs):
        shutil.copyfile(archive, path)
    service = SelfUpdateService(old, public, version=old_version,
                               fetch=lambda *a: raw, download=download)
    result = service.prepare(manual=True)
    if not result.restart_ready:
        raise UpdateError('Portable update failed to stage: ' + result.error)
    command(old, '--apply', version, '--smoke-startup')
    wait_closed(old)
    if UpdateStore(old).active() != version:
        raise UpdateError('Portable version did not activate.')
    if hashlib.sha256((old / 'BC2Launcher.exe').read_bytes()).hexdigest() != original_bootstrap:
        raise UpdateError('Portable update changed its fixed entry.')
    report = dict(ok=True, portable_without_installer=True, actual_qt_startup=True,
                  transition=old_version + ' -> ' + version, bootstrap_unchanged=True,
                  highest_revision=UpdateStore(old).load()['highest_revision'], case=str(case))
    (case / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
