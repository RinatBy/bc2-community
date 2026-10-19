"""Live HTTPS/signature/update smoke check using only a disposable fake game."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'launcher'))
from bc2launcher.service import LauncherService,FEED
from bc2launcher.settings import Settings
from bc2launcher.manifest import UpdateError,HOST
from bc2launcher.game import read_managed_ini
from bc2launcher.network import fetch_bytes


def main():
    urls=[]
    def fetch(url,limit):
        urls.append(url)
        if url==FEED:raise UpdateError('Site DNS deliberately deferred for this smoke check')
        return fetch_bytes(url,limit)
    with tempfile.TemporaryDirectory(prefix='bc2-public-check-') as directory:
        root=Path(directory);game=root/'fake-game';game.mkdir()
        exe=b'MZ'+b'\0'*64;ini=b'[info]\nhost=127.0.0.1\nconnect_to_retail=0\nshow_console=1\n'
        (game/'BFBC2Game.exe').write_bytes(exe)
        (game/'bfbc2.ini').write_bytes(ini)
        service=LauncherService((Path(__file__).resolve().parents[1]/'launcher/assets/public-key.bin').read_bytes(),
                                Settings(root/'settings.json'),fetch=fetch,
                                launch=lambda _: (_ for _ in ()).throw(AssertionError('Must not start any process')))
        result=service.update(game)
        if result.state!='READY':raise RuntimeError(result.message)
        assert read_managed_ini((game/'bfbc2.ini').read_bytes())==(HOST,'0')
        assert b'show_console=1' in (game/'bfbc2.ini').read_bytes()
        assert (game/'BFBC2Game.exe').read_bytes()==exe
        backup=service.backups(game)[0][0]
        restored=service.rollback(game,backup)
        assert restored.state=='UPDATE_REQUIRED'
        assert (game/'bfbc2.ini').read_bytes()==ini
        assert not (game/'dinput8.dll').exists()
        report=dict(revision=result.release.revision,package=result.release.package_id,
                    real_https_downloads=True,signature_verified=True,temporary_update=True,
                    rollback=True,game_started=False,gui_opened=False,network_requests=len(urls))
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
