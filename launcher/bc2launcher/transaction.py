import base64
import contextlib
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .game import safe_path, validate_game_dir, ensure_game_closed
from .manifest import LIMITS, UpdateError


def atomic_write(path: Path, data: bytes):
    fd, name = tempfile.mkstemp(prefix='.bc2-write-', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def state_dir(root):
    path=safe_path(root,root/'.bc2-launcher'); path.mkdir(exist_ok=True)
    return path


@contextlib.contextmanager
def game_lock(root):
    root=validate_game_dir(Path(root)).root
    state=state_dir(root)
    lock=safe_path(root,state/'operation.lock')
    with lock.open('a+b') as stream:
        stream.seek(0,2)
        if not stream.tell(): stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc: raise UpdateError("Другой экземпляр лаунчера изменяет эту игру.") from exc
        try:
            ensure_game_closed()
            yield root
        finally:
            if os.name=='nt':
                stream.seek(0); msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(stream,fcntl.LOCK_UN)


def _replace_target(path, data):
    safe_path(path.parent,path)
    if data is None:
        if path.exists(): path.unlink()
    else: atomic_write(path,data)


def _checkpoint(index):
    pass  # Fault-injection boundary; no effect in the application.


def _backup_path(root, ident):
    if not re.fullmatch(r'[0-9a-f]{32}',ident): raise UpdateError("Неверная резервная копия.")
    return safe_path(root,state_dir(root)/'backups'/ident)


def _read_backup(root,ident):
    folder=_backup_path(root,ident)
    meta_path=safe_path(root,folder/'record.json')
    if meta_path.stat().st_size>16384: raise UpdateError("Повреждена резервная копия.")
    meta=json.loads(meta_path.read_bytes())
    if set(meta['files']) != set(LIMITS): raise UpdateError("Повреждена резервная копия.")
    result={}
    for name, digest in meta['files'].items():
        if digest is None: result[name]=None; continue
        p=safe_path(root,folder/name)
        if p.stat().st_size>LIMITS[name]: raise UpdateError("Резервный файл слишком большой.")
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=digest: raise UpdateError("Повреждена резервная копия. Файлы не изменены.")
        result[name]=data
    return result


def _journal(root,ident):
    atomic_write(safe_path(root,state_dir(root)/'journal.json'),json.dumps({'backup':ident}).encode())


def _clear(root):
    p=safe_path(root,state_dir(root)/'journal.json')
    if p.exists(): p.unlink()


def _recover(root):
    p=safe_path(root,state_dir(root)/'journal.json')
    if not p.exists(): return
    if p.stat().st_size>1024: raise UpdateError("Журнал восстановления повреждён.")
    ident=json.loads(p.read_bytes())['backup']
    data=_read_backup(root,ident)
    for name,contents in data.items(): _replace_target(safe_path(root,root/name),contents)
    _clear(root)


def recover_interrupted(game_dir: Path):
    try:
        with game_lock(game_dir) as root: _recover(root)
    except UpdateError: raise
    except (OSError,ValueError,KeyError,TypeError) as exc: raise UpdateError("Не удалось восстановить прерванное обновление. Сохраните резервные копии.") from exc


def _install_locked(root, files, package):
    if set(files)!=set(LIMITS): raise UpdateError("Неожиданный набор файлов.")
    for name,data in files.items():
        if data is not None and (not isinstance(data,bytes) or len(data)>LIMITS[name]): raise UpdateError("Недопустимый размер файла.")
        target=safe_path(root,root/name)
        if target.exists() and target.stat().st_size>LIMITS[name]: raise UpdateError("Существующий файл слишком большой для безопасного обновления.")
    _recover(root)
    ident=uuid.uuid4().hex; folder=_backup_path(root,ident)
    safe_path(root,folder.parent).mkdir(exist_ok=True); folder.mkdir()
    old={n: (root/n).read_bytes() if (root/n).exists() else None for n in LIMITS}
    metadata={'package':package,'created':datetime.now(timezone.utc).isoformat(),'files':{}}
    for name,data in old.items():
        metadata['files'][name]=hashlib.sha256(data).hexdigest() if data is not None else None
        if data is not None: atomic_write(folder/name,data)
    atomic_write(folder/'record.json',json.dumps(metadata).encode())
    _read_backup(root,ident)  # Validate all backups before touching either installed file.
    _journal(root,ident)
    try:
        _checkpoint(0)
        for index,(name,data) in enumerate(files.items(),1):
            _replace_target(safe_path(root,root/name),data); _checkpoint(index)
        _clear(root)
    except Exception:
        _recover(root)
        raise
    return ident


def install_bytes(game_dir: Path, files: dict, package: str):
    try:
        with game_lock(game_dir) as root: return _install_locked(root,files,package)
    except UpdateError: raise
    except (OSError,ValueError,KeyError,TypeError) as exc: raise UpdateError("Не удалось изменить файлы. Закройте игру, проверьте права папки и повторите попытку.") from exc


def restore_backup(game_dir: Path, backup_id: str):
    try:
        with game_lock(game_dir) as root:
            _recover(root)
            files=_read_backup(root,backup_id)
            return _install_locked(root,files,'local-rollback')
    except UpdateError: raise
    except (OSError,ValueError,KeyError,TypeError) as exc: raise UpdateError("Не удалось восстановить резервную копию.") from exc


def list_backups(game_dir: Path):
    root=Path(game_dir); folder=safe_path(root,root/'.bc2-launcher'/'backups')
    if not folder.exists(): return []
    result=[]
    for child in folder.iterdir():
        if not re.fullmatch('[0-9a-f]{32}',child.name): continue
        try:
            _read_backup(root,child.name)
            meta=json.loads(safe_path(root,child/'record.json').read_bytes())
            result.append((child.name,meta['created'],meta['package']))
        except (UpdateError,OSError,ValueError,KeyError,TypeError): continue
    return sorted(result,key=lambda x:x[1],reverse=True)
