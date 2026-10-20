"""Local-only integration test. Never targets a user's installed launcher or game."""
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'launcher'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.paths import reject_links,inside
from bc2launcher.selfupdate.store import UpdateStore
from bc2launcher.selfupdate.service import SelfUpdateService
from bc2launcher.selfupdate.process import launch_verified
from package_launcher import package_launcher,sign_launcher_policy

COMMUNITY=Path(__file__).resolve().parents[1]
TEST_BASE=COMMUNITY/'dist'/'selfupdate-e2e'


def validate_test_root(path):
    path=Path(os.path.abspath(path))
    if '..' in Path(path).parts or path==TEST_BASE or not path.is_relative_to(TEST_BASE):
        raise UpdateError('Diagnostic output must be inside a new dist/selfupdate-e2e case.')
    return reject_links(path)


def command(root,*args):
    result=subprocess.run([str(root/'BC2Launcher.exe'),*args,'--quiet'],cwd=root,
                          creationflags=subprocess.CREATE_NO_WINDOW,timeout=120,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if result.returncode:raise UpdateError('Frozen bootstrap failed: '+str(args))


def wait_closed(root,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            with UpdateStore(root).locked('client.lock'):return
        except UpdateError:time.sleep(.05)
    raise UpdateError('Diagnostic client did not exit.')


def remove_closed_image(path, timeout=10):
    # The GUI lease closes before Windows finishes unloading the native image.
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.unlink()
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.05)


def prepare(root,archive,version,revision,key,public):
    raw=sign_launcher_policy(archive,version,'https://github.com/RinatBy/bc2-community/releases/download/test/app.zip',
                             revision,key,datetime.now(timezone.utc),minimum='0.2.0')
    def download(url,path,limit,**kwargs):shutil.copyfile(archive,path)
    service=SelfUpdateService(root,public,version=UpdateStore(root).active(),
                              fetch=lambda *a:raw,download=download)
    return service.prepare(manual=True)


def bad_fixture(source,folder,version,kind,key):
    shutil.copytree(source/'client'/'BC2Client',folder)
    (folder/'.launcher-package.json').unlink(missing_ok=True)
    (folder/'_internal'/'assets'/'build-version.txt').write_text(version,encoding='ascii')
    if kind=='probe':
        files=list(folder.rglob('QtCore.pyd'))
    else:files=list(folder.rglob('qoffscreen.dll'))
    if len(files)!=1:raise UpdateError('Expected a single failure fixture component: '+kind)
    files[0].unlink()
    archive=folder.parent/(version+'.zip')
    package_launcher(folder,version,archive,key)
    return archive


def main():
    p=argparse.ArgumentParser();p.add_argument('--first',required=True);p.add_argument('--second',required=True)
    p.add_argument('--private',default=str(COMMUNITY/'.secrets'/'release-signing.key'))
    p.add_argument('--root');a=p.parse_args()
    case=validate_test_root(a.root or TEST_BASE/('case-'+secrets.token_hex(5)))
    if case.exists():raise UpdateError('Refusing to reuse an existing diagnostic case.')
    case.mkdir(parents=True)
    root=case/'install'; first=Path(a.first).absolute();second=Path(a.second).absolute()
    shutil.copytree(first/'seed',root)
    key=load_pem_private_key(Path(a.private).read_bytes(),password=None)
    public=(COMMUNITY/'launcher'/'assets'/'public-key.bin').read_bytes()
    # Child processes inherit only this tool's isolated user-data location.
    os.environ['LOCALAPPDATA']=str(case/'localappdata')
    os.environ['QT_QPA_PLATFORM']='offscreen'
    settings=case/'localappdata'/'UPLAY2'/'BC2Launcher'/'settings.json'
    settings.parent.mkdir(parents=True)
    original=b'{"highest_revision":0,"game_dir":""}'
    settings.write_bytes(original)
    backup=case/'game-fixture'/'.bc2-launcher'/'backups'/'saved.bin'
    backup.parent.mkdir(parents=True);backup.write_bytes(b'unchanged game backup')
    command(root,'--install-seed','0.2.0')
    bootstrap_bytes=(root/'BC2Launcher.exe').read_bytes()
    command(root,'--smoke-startup');wait_closed(root)
    archive=second/'BC2Launcher-app-0.2.1.zip'
    status=prepare(root,archive,'0.2.1',2,key,public)
    if not status.restart_ready:raise UpdateError('New build did not stage: '+status.error)
    # Actual installed client invokes the same restart method as the GUI button.
    handoff_report=case/'restart-method.json'
    old=subprocess.run([str(root/'versions'/'0.2.0'/'BC2Client.exe'),'--self-test-restart','--smoke-startup',
                        '--report',str(handoff_report)],cwd=root,creationflags=subprocess.CREATE_NO_WINDOW,timeout=120)
    if old.returncode:raise UpdateError('Installed client restart method failed: '+handoff_report.read_text())
    deadline=time.monotonic()+90
    while (UpdateStore(root).active()!='0.2.1' or (root/'activation.json').exists()) and time.monotonic()<deadline:
        time.sleep(.05)
    wait_closed(root)
    if UpdateStore(root).active()!='0.2.1':raise UpdateError('New version not active.')
    # Signed but broken packages exercise actual native import and Qt startup failures.
    bad_probe=bad_fixture(second,case/'bad-probe','0.2.2','probe',key)
    failed=prepare(root,bad_probe,'0.2.2',3,key,public)
    if failed.restart_ready or UpdateStore(root).active()!='0.2.1':raise UpdateError('Bad self-test changed active version.')
    bad_gui=bad_fixture(second,case/'bad-gui','0.2.3','gui',key)
    status=prepare(root,bad_gui,'0.2.3',4,key,public)
    if not status.restart_ready:raise UpdateError('Qt failure fixture should pass import-only probe: '+status.error)
    failure_started=time.monotonic()
    command(root,'--apply','0.2.3','--smoke-startup');wait_closed(root)
    if time.monotonic()-failure_started >= 25:
        raise UpdateError('Diagnostic plugin failure stalled instead of exiting without a dialog.')
    if UpdateStore(root).active()!='0.2.1':raise UpdateError('Missing GUI ready did not restore previous version.')
    remove_closed_image(root/'versions'/'0.2.1'/'BC2Client.exe')
    command(root,'--smoke-startup');wait_closed(root)
    if UpdateStore(root).active()!='0.2.0':raise UpdateError('Quarantined active file did not restore previous version.')
    if (root/'BC2Launcher.exe').read_bytes()!=bootstrap_bytes:raise UpdateError('Permanent bootstrap was changed.')
    if settings.read_bytes()!=original or backup.read_bytes()!=b'unchanged game backup':raise UpdateError('User/game fixture changed.')
    report=dict(ok=True,transition='0.2.0 -> 0.2.1',specific_pid_handoff=True,failed_probe_preserves_active=True,
                launcher_restart_method=True,
                failed_qt_start_restores_previous=True,bootstrap_unchanged=True,settings_and_backups_unchanged=True,
                failed_qt_start_without_dialog=True,
                quarantined_active_file_restores_previous=True,
                highest_revision=UpdateStore(root).load()['highest_revision'],case=str(case))
    (case/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
