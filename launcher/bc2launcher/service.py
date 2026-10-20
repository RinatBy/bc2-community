import hashlib
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from . import VERSION
from .manifest import verify_manifest, MANIFEST_LIMIT, LIMITS, UpdateError, version_tuple
from .network import fetch_bytes
from .game import validate_game_dir, safe_path, read_managed_ini, merge_connection_ini, ensure_game_closed
from .transaction import install_bytes, recover_interrupted, restore_backup, list_backups, game_lock, _recover

FEED = 'https://bc2.uplay2.ru/updates/stable.json'
FALLBACK_FEED = 'https://raw.githubusercontent.com/RinatBy/bc2-community/main/website/updates/stable.json'


@dataclass(frozen=True)
class CheckResult:
    state: str
    message: str
    release: object = None

    @property
    def allowed(self): return self.state == 'READY'


def start_game(installation):
    subprocess.Popen([str(installation.executable)],cwd=installation.root,shell=False)


class LauncherService:
    def __init__(self,public_key,settings,fetch=fetch_bytes,clock=None,launch=start_game,progress=None,before_play=None):
        self.public_key=public_key; self.settings=settings; self.fetch=fetch
        self.clock=clock or (lambda:datetime.now(timezone.utc)); self.launch=launch
        self.progress=progress or (lambda message:None); self.cancel=threading.Event()
        self.before_play=before_play or (lambda:None)

    def _policy(self):
        saved=self.settings.load()
        try: raw=self.fetch(FEED,MANIFEST_LIMIT)
        except (UpdateError,OSError): raw=self.fetch(FALLBACK_FEED,MANIFEST_LIMIT)
        r=verify_manifest(raw,self.public_key,self.clock(),saved['highest_revision'])
        if r.revision==saved['highest_revision'] and saved.get('payload_sha256')!=r.payload_sha256:
            raise UpdateError("Содержимое выпуска изменено без новой ревизии. Обратитесь к администратору.")
        self.settings.accept_policy(r)
        if version_tuple(r.minimum_launcher_version)>version_tuple(VERSION):
            raise UpdateError("Нужна новая версия лаунчера. Скачайте её с bc2.uplay2.ru.")
        return r

    def _cancelled(self):
        if self.cancel.is_set(): raise UpdateError("Операция отменена. Файлы игры сохранены.")

    def _check(self,folder,recover=True):
        game=validate_game_dir(Path(folder))
        if recover: recover_interrupted(game.root)
        r=self._policy()
        for asset in r.assets:
            p=safe_path(game.root,game.root/asset.name)
            if not p.is_file() or p.stat().st_size>LIMITS[asset.name]:
                return CheckResult('UPDATE_REQUIRED','Установите обязательное обновление.',r)
            data=p.read_bytes()
            good=(hashlib.sha256(data).hexdigest()==asset.sha256 and len(data)==asset.size) if asset.name=='dinput8.dll' else read_managed_ini(data)==(r.master_host,'0')
            if not good: return CheckResult('UPDATE_REQUIRED','Доступно обязательное обновление файлов подключения.',r)
        return CheckResult('READY','Файлы проверены.',r)

    def _run(self,action):
        try: return action()
        except UpdateError as exc: return CheckResult('ERROR',str(exc))
        except Exception: return CheckResult('ERROR','Операция не завершена. Проверьте сеть, папку игры и права доступа.')

    def check(self,game_dir): return self._run(lambda:self._check(game_dir))

    def update(self,game_dir):
        def action():
            self._cancelled()
            game=validate_game_dir(Path(game_dir)); recover_interrupted(game.root)
            r=self._policy(); files={}
            for asset in r.assets:
                self._cancelled(); self.progress('Загрузка '+asset.name)
                data=self.fetch(asset.url,LIMITS[asset.name])
                if len(data)!=asset.size or hashlib.sha256(data).hexdigest()!=asset.sha256:
                    raise UpdateError("Не совпадает контрольная сумма "+asset.name+". Установка отменена.")
                files[asset.name]=data
            ini=safe_path(game.root,game.root/'bfbc2.ini')
            if ini.exists() and ini.stat().st_size>LIMITS['bfbc2.ini']: raise UpdateError("INI слишком большой.")
            original=ini.read_bytes() if ini.exists() else None
            files['bfbc2.ini']=merge_connection_ini(original,files['bfbc2.ini'],r.master_host)
            self._cancelled(); self.progress('Сохранение резервной копии и установка…')
            install_bytes(game.root,files,r.package_id,expected_ini=original)
            self.settings.update_fields(game_dir=str(game.root),installed_package=r.package_id)
            return self._check(game.root)
        return self._run(action)

    def backups(self,game_dir): return list_backups(Path(game_dir))

    def rollback(self,game_dir,backup_id):
        def action():
            restore_backup(Path(game_dir),backup_id)
            return CheckResult('UPDATE_REQUIRED','Резервная копия восстановлена. Проверьте обязательную версию перед запуском.')
        return self._run(action)

    def prepare_launch(self,game_dir): return self.check(game_dir)

    def play(self,game_dir):
        def action():
            with game_lock(Path(game_dir)) as root:
                _recover(root)
                result=self._check(root,recover=False)
                if result.allowed:
                    self.before_play()
                    self._cancelled(); ensure_game_closed()
                    self.launch(validate_game_dir(root))
                return result
        return self._run(action)
