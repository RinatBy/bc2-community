import json
import os
import contextlib
from pathlib import Path
from .manifest import UpdateError
from .transaction import atomic_write


class Settings:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'UPLAY2'/'BC2Launcher'/'settings.json'

    def load(self):
        if not self.path.exists(): return {'highest_revision':0,'game_dir':''}
        try:
            if self.path.stat().st_size>16384: raise ValueError()
            data=json.loads(self.path.read_bytes())
            if type(data.get('highest_revision')) is not int or data['highest_revision']<0: raise ValueError()
            return data
        except (ValueError,KeyError,TypeError,OSError) as exc:
            raise UpdateError("Повреждены настройки лаунчера. Сохраните settings.json и обратитесь к администратору.") from exc

    def _save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        atomic_write(self.path,json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8'))

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.lock').open('a+b') as f:
            f.seek(0,2)
            if not f.tell(): f.write(b'0'); f.flush()
            f.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc: raise UpdateError("Другой лаунчер сохраняет настройки. Повторите проверку.") from exc
            try: yield
            finally:
                if os.name=='nt': f.seek(0); msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else: fcntl.flock(f,fcntl.LOCK_UN)

    def accept_policy(self,release):
        with self._locked():
            data=self.load()
            if release.revision<data['highest_revision']:
                raise UpdateError("Получено устаревшее описание обновления.")
            if release.revision==data['highest_revision'] and data.get('payload_sha256')!=release.payload_sha256:
                raise UpdateError("Содержимое выпуска изменено без новой ревизии.")
            data.update(highest_revision=release.revision,payload_sha256=release.payload_sha256)
            self._save(data)

    def update_fields(self,**fields):
        if not set(fields)<= {'game_dir','installed_package'}: raise ValueError('Unexpected settings')
        with self._locked():
            data=self.load(); data.update(fields); self._save(data)

    def remember_folder(self,folder):
        self.update_fields(game_dir=str(folder))
