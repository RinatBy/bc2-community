"""Install/reinstall/uninstall only a disposable case inside dist/selfupdate-e2e."""
import argparse
import ctypes
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_frozen_update import COMMUNITY,TEST_BASE,validate_test_root
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.store import UpdateStore


def snapshot(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def invoke(exe,*args):
    result=subprocess.run([str(exe),*args],creationflags=subprocess.CREATE_NO_WINDOW,timeout=90)
    if result.returncode:raise UpdateError('Installer diagnostic failed, code '+str(result.returncode))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--first',required=True);parser.add_argument('--second',required=True)
    a=parser.parse_args();case=validate_test_root(TEST_BASE/('installer-'+secrets.token_hex(5)));case.mkdir(parents=True)
    root=case/'\u041b\u0430\u0443\u043d\u0447\u0435\u0440 \u0442\u0435\u0441\u0442'
    first=Path(a.first).absolute();second=Path(a.second).absolute();setup=first/'BC2Launcher-Setup.exe'
    desktop=ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,desktop):raise UpdateError('Cannot locate desktop.')
    shortcut=Path(desktop.value)/'BC2 Launcher.lnk';before_icon=snapshot(shortcut)
    actual_settings=Path(os.environ['LOCALAPPDATA'])/'UPLAY2'/'BC2Launcher'/'settings.json'
    before_settings=snapshot(actual_settings)
    args=('/VERYSILENT','/SUPPRESSMSGBOXES','/SP-','/NORESTART','/NOICONS','/TASKS=',
          '/DIR='+str(root),'/GROUP=BC2 Test '+case.name,'/LOG='+str(case/'install.log'))
    invoke(setup,*args)
    store=UpdateStore(root)
    if store.active()!='0.2.0':raise UpdateError('Initial version mismatch.')
    shutil.copytree(second/'seed'/'versions'/'0.2.1',root/'versions'/'0.2.1')
    store.set_active('0.2.1')
    original=store.load();original['highest_revision']=9;original['payload_sha256']='a'*64
    store.write_json('update-state.json',original)
    invoke(setup,*args)
    if store.active()!='0.2.1' or store.load()['highest_revision']!=9:
        raise UpdateError('Reinstall reset active version or accepted revision.')
    if snapshot(shortcut)!=before_icon:raise UpdateError('Silent test changed the desktop shortcut.')
    invoke(root/'unins000.exe','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
    if (root/'versions').exists() or (root/'cache').exists():raise UpdateError('Managed app versions were not uninstalled.')
    if snapshot(actual_settings)!=before_settings:raise UpdateError('Installer changed real game-path settings.')
    report=dict(ok=True,unicode_path=True,reinstall_preserves_active_and_revision=True,
                uninstall_removes_managed_versions=True,real_settings_and_shortcut_unchanged=True,case=str(case))
    (case/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
