"""Verify portable startup/update without shadowing the unittest test_portable module."""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'launcher'), str(ROOT / 'tools')]
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.package import verify_installed
from bc2launcher.selfupdate.service import SelfUpdateService
from bc2launcher.selfupdate.store import UpdateStore
from bc2launcher.selfupdate.policy import verify_policy
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
    raw = (build / 'launcher-stable.json').read_bytes()
    policy = verify_policy(raw, public, datetime.now(timezone.utc), 0)
    settings = case / 'user-data' / 'UPLAY2' / 'BC2Launcher' / 'settings.json'
    settings.parent.mkdir(parents=True, exist_ok=True)
    game = case / 'existing-game'
    game.mkdir()
    (game / 'BFBC2Game.exe').write_bytes(b'MZexisting-game-fixture')
    original_settings = json.dumps(dict(highest_revision=2, game_dir=str(game))).encode()
    settings.write_bytes(original_settings)
    def download(url, path, limit, **kwargs):
        shutil.copyfile(archive, path)
    service = SelfUpdateService(old, public, version=old_version,
                               fetch=lambda *a: raw, download=download)
    if service.check().play_allowed:
        raise UpdateError('Old launcher should require the mandatory update.')
    result = service.prepare(manual=True)
    if not result.restart_ready:
        raise UpdateError('Portable update failed to stage: ' + result.error)
    handoff_report = case / 'restart-method.json'
    restart = subprocess.run(
        [str(old / 'versions' / old_version / 'BC2Client.exe'), '--self-test-restart',
         '--smoke-startup', '--report', str(handoff_report)], cwd=old, timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=dict(os.environ, HTTPS_PROXY='http://127.0.0.1:1', NO_PROXY=''))
    if restart.returncode:
        raise UpdateError('Old client restart failed: ' + handoff_report.read_text())
    deadline = time.monotonic() + 90
    while UpdateStore(old).active() != version or (old / 'activation.json').exists():
        if time.monotonic() >= deadline:
            raise UpdateError('Old client did not activate the published version.')
        time.sleep(.1)
    wait_closed(old)
    if UpdateStore(old).active() != version:
        raise UpdateError('Portable version did not activate.')
    if hashlib.sha256((old / 'BC2Launcher.exe').read_bytes()).hexdigest() != original_bootstrap:
        raise UpdateError('Portable update changed its fixed entry.')
    if settings.read_bytes() != original_settings or (game / 'BFBC2Game.exe').read_bytes() != b'MZexisting-game-fixture':
        raise UpdateError('Update changed the existing game selection or game files.')
    if (old / 'versions' / version / '_internal' / 'assets' / 'install-preview.flag').exists():
        raise UpdateError('Public release contains the local preview flag.')
    report = dict(ok=True, portable_without_installer=True, actual_qt_startup=True,
                  transition=old_version + ' -> ' + version, bootstrap_unchanged=True,
                  highest_revision=UpdateStore(old).load()['highest_revision'], case=str(case),
                  signed_public_policy=policy.revision, original_client_restart=True,
                  settings_preserved=True, game_files_preserved=True, public_mode=True)
    (case / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
