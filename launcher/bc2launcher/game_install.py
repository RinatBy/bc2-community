"""Verified game installation, independent of Qt and launcher self-updates."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .game import ensure_game_closed, validate_game_dir
from .manifest import UpdateError, _json
from .selfupdate.paths import inside, reject_links
from .selfupdate.store import UpdateStore
from .transaction import atomic_write


def relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 220:
        raise UpdateError('Некорректный путь в пакете игры.')
    parts = value.split('/')
    if any(not p or p in ('.', '..') or p[-1] in ' .'
           or PureWindowsPath(p).is_reserved()
           or any(ord(c) < 32 or c in '\\:<>"|?*' for c in p) for p in parts):
        raise UpdateError('Недопустимый путь в пакете игры.')
    return value


def digest(value, length=64):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{%d}' % length, value):
        raise UpdateError('Некорректная контрольная сумма пакета.')
    return value


def read_json(path, maximum):
    if not path.is_file() or path.stat().st_size > maximum:
        raise UpdateError('Не найдено или повреждено описание установки.')
    try:
        return _json(path.read_bytes())
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise UpdateError('Повреждено описание установки.') from exc


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str


def records(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 10000:
        raise UpdateError('Пустой или слишком большой список файлов.')
    seen, directories, result = set(), set(), []
    for item in items:
        if not isinstance(item, dict) or set(item) != {'path', 'size', 'sha256'}:
            raise UpdateError('Некорректная запись о файле игры.')
        name = relative_path(item['path'])
        size = item['size']
        parts = name.casefold().split('/')
        parents = {'/'.join(parts[:i]) for i in range(1, len(parts))}
        if (name.casefold() in seen | directories or parents & seen
                or type(size) is not int or not 0 <= size <= 64 * 1024**3):
            raise UpdateError('Конфликт путей или размеров в пакете игры.')
        seen.add(name.casefold())
        directories.update(parents)
        result.append(FileRecord(name, size, digest(item['sha256'])))
    return tuple(result)


@dataclass(frozen=True)
class InstallProfile:
    torrent: Path
    torrent_sha256: str
    info_hash: str
    setup: str
    package: tuple[FileRecord, ...]
    game: tuple[FileRecord, ...]
    extra_space: int

    @property
    def download_size(self):
        return sum(f.size for f in self.package)

    @property
    def game_space(self):
        return sum(f.size for f in self.game) + self.extra_space

    @classmethod
    def load(cls, assets):
        root = reject_links(assets)
        data = read_json(inside(root, 'profile.json'), 4 * 1024**2)
        required = {'schema', 'torrent_sha256', 'info_hash', 'setup', 'package', 'game', 'extra_space'}
        if not isinstance(data, dict) or set(data) != required or type(data['schema']) is not int or data['schema'] != 1:
            raise UpdateError('Неизвестный формат профиля установки.')
        torrent = inside(root, 'source.torrent')
        checksum = digest(data['torrent_sha256'])
        if not torrent.is_file() or torrent.stat().st_size > 2 * 1024**2 or hashlib.sha256(torrent.read_bytes()).hexdigest() != checksum:
            raise UpdateError('Метаданные торрента не прошли проверку.')
        package, game = records(data['package']), records(data['game'])
        setup = relative_path(data['setup'])
        extra = data['extra_space']
        if (Path(setup).name.casefold() != 'setup.exe' or setup not in {f.path for f in package}
                or 'BFBC2Game.exe' not in {f.path for f in game}
                or type(extra) is not int or not 0 <= extra <= 32 * 1024**3):
            raise UpdateError('Профиль игры не содержит нужных файлов.')
        return cls(torrent, checksum, digest(data['info_hash'], 40), setup, package, game, extra)


@dataclass(frozen=True)
class InstallPaths:
    library: Path
    cache: Path
    payload: Path
    game: Path

    @classmethod
    def from_library(cls, library):
        root = reject_links(library)
        if (not root.is_dir() or root == Path(root.anchor)
                or any((parent / 'BFBC2Game.exe').exists() for parent in (root, *root.parents))):
            raise UpdateError('Выберите отдельную папку библиотеки, не корень диска или папку игры.')
        if any((parent / 'BC2Launcher.exe').is_file() and (parent / 'installation.json').is_file()
               for parent in (root, *root.parents)):
            raise UpdateError('Выберите отдельную папку библиотеки. Нельзя использовать папку лаунчера.')
        cache = inside(root, '_torrents', 'bf_bc2')
        return cls(root, cache, inside(cache, 'payload'), inside(root, 'Battlefield_BC2'))


@dataclass(frozen=True)
class InstallProgress:
    phase: str
    downloaded: int = 0
    total: int = 0
    speed: int = 0


@dataclass(frozen=True)
class InstallResult:
    paths: InstallPaths
    job_id: str

    @property
    def game_dir(self):
        return self.paths.game


class FileMismatch(UpdateError):
    pass


def check_files(root, files, cancelled):
    for record in files:
        path = inside(root, *record.path.split('/'))
        if not path.is_file() or path.stat().st_size != record.size:
            raise FileMismatch('Отсутствует файл или отличается его размер: ' + record.path)
        sha = hashlib.sha256()
        with path.open('rb') as source:
            while block := source.read(1024**2):
                if cancelled():
                    raise UpdateError('Операция отменена. Кэш сохранён.')
                sha.update(block)
        if sha.hexdigest() != record.sha256:
            raise FileMismatch('Не совпала контрольная сумма: ' + record.path)


def run_setup(exe, dest, log, *, on_tick):
    args = [str(exe), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/SP-', '/NORESTART',
            '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', f'/DIR={dest}', f'/LOG={log}']
    try:
        with subprocess.Popen(args, cwd=exe.parent, shell=False) as process:
            while True:
                try:
                    code = process.wait(timeout=.75)
                    break
                except subprocess.TimeoutExpired:
                    on_tick()
            if code:
                raise subprocess.CalledProcessError(code, args)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UpdateError('Установщик не завершился успешно. Кэш и журнал сохранены.') from exc


def find_uninstaller(game_dir):
    exe = inside(game_dir, 'Uninstall', 'unins000.exe')
    data = inside(game_dir, 'Uninstall', 'unins000.dat')
    if exe.is_file() and data.is_file():
        with exe.open('rb') as source:
            if source.read(2) == b'MZ':
                return exe
    return None


def run_uninstall(game_dir):
    game = validate_game_dir(game_dir)
    exe = find_uninstaller(game.root)
    if exe is None:
        raise UpdateError('Штатный деинсталлятор игры не найден.')
    ensure_game_closed()
    try:
        result = subprocess.run([str(exe)], cwd=exe.parent, shell=False, check=False)
    except OSError as exc:
        raise UpdateError(f'Не удалось запустить деинсталлятор: {exc}') from exc
    return result.returncode == 0


class GameInstallService:
    def __init__(self, profile, *, download=None, setup=run_setup):
        if download is None:
            from .game_torrent import download
        self.profile, self.download, self.setup = profile, download, setup
        self.progress = lambda event: None
        self.cancel = threading.Event()

    def _owner(self, paths):
        owner = read_json(inside(paths.cache, 'owner.json'), 4096)
        if (not isinstance(owner, dict) or set(owner) != {'library', 'torrent', 'job'}
                or owner['library'] != str(paths.library) or owner['torrent'] != self.profile.torrent_sha256):
            raise UpdateError('Папка кэша принадлежит другой загрузке.')
        return digest(owner['job'], 32)

    def _check_target(self, paths):
        dest = reject_links(paths.game)
        if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
            raise UpdateError('Папка Battlefield_BC2 занята. Выберите другую папку библиотеки.')

    def _space(self, paths, needed):
        if shutil.disk_usage(paths.library)[2] < needed:
            raise UpdateError(f'Недостаточно места. Требуется не менее {needed / 10**9:.1f} ГБ свободного места.')

    def _cancelled(self):
        if self.cancel.is_set():
            raise UpdateError('Операция отменена. Кэш сохранён.')

    def _cache_items(self, paths):
        """Check the entire tree before cleanup; never delete unknown files."""
        allowed = {'owner.json', 'installed.json', 'source.torrent', 'setup.log'}
        allowed.update('payload/' + record.path for record in self.profile.package)
        directories = {'payload'}
        for name in allowed:
            parts = name.split('/')
            directories.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        files, folders = [], []
        for base, dirs, names in os.walk(reject_links(paths.cache), followlinks=False):
            for name in dirs + names:
                item = reject_links(Path(base) / name)
                relative = item.relative_to(paths.cache).as_posix()
                if item.is_dir() and relative in directories:
                    folders.append(item)
                elif item.is_file() and relative in allowed and item.stat().st_nlink == 1:
                    files.append(item)
                else:
                    raise UpdateError('В папке кэша есть посторонние файлы. Очистка остановлена.')
        return files, folders

    def _download_or_reuse(self, paths, existing_cache):
        if existing_cache:
            self.progress(InstallProgress('VERIFY_CACHE'))
            try:
                check_files(paths.payload, self.profile.package, self.cancel.is_set)
            except FileMismatch:
                pass
            else:
                return

        self._cancelled()
        if existing_cache:
            # Keep the conservative allowance for an incomplete torrent.
            self._space(paths, self.profile.download_size + self.profile.game_space)
        paths.payload.mkdir(exist_ok=True)
        torrent = inside(paths.cache, 'source.torrent')
        raw = self.profile.torrent.read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.profile.torrent_sha256:
            raise UpdateError('Метаданные торрента изменились.')
        atomic_write(torrent, raw)
        self.download(self.profile, paths, progress=self.progress, cancelled=self.cancel.is_set)
        self._cancelled()
        self.progress(InstallProgress('VERIFY'))
        self._cache_items(paths)
        check_files(paths.payload, self.profile.package, self.cancel.is_set)

    def install(self, library):
        paths = InstallPaths.from_library(library)
        self._cancelled()
        self._check_target(paths)
        self._space(paths, self.profile.game_space)
        lock = UpdateStore(inside(paths.library, '_torrents', '.bc2-install-lock'))
        with lock.locked():
            self._check_target(paths)
            existing_cache = paths.cache.exists()
            if existing_cache:
                job = self._owner(paths)
                self._cache_items(paths)
                receipt = inside(paths.cache, 'installed.json')
                if receipt.exists() and read_json(receipt, 4096) != dict(job=job, game=str(paths.game)):
                    raise UpdateError('Отметка об установке не соответствует папке игры. Кэш сохранён.')
            else:
                self._space(paths, self.profile.download_size + self.profile.game_space)
                paths.cache.mkdir()
                job = uuid.uuid4().hex
                atomic_write(inside(paths.cache, 'owner.json'), json.dumps(dict(
                    library=str(paths.library), torrent=self.profile.torrent_sha256, job=job)).encode())
            self._download_or_reuse(paths, existing_cache)
            self._check_target(paths)
            self._space(paths, self.profile.game_space)
            self._cancelled()
            # From here on the receipt describes only the new Setup attempt.
            inside(paths.cache, 'installed.json').unlink(missing_ok=True)
            paths.game.mkdir(exist_ok=True)
            log = inside(paths.cache, 'setup.log')
            total = sum(record.size for record in self.profile.game)
            targets = tuple((paths.game.joinpath(*record.path.split('/')), record.size) for record in self.profile.game)
            def report_setup():
                written = 0
                for target, size in targets:
                    try:
                        if target.is_file():
                            written += min(target.stat().st_size, size)
                    except OSError:
                        continue
                self.progress(InstallProgress('SETUP', written, total))
            report_setup()
            self.setup(inside(paths.payload, *self.profile.setup.split('/')), paths.game, log, on_tick=report_setup)
            self.progress(InstallProgress('VERIFY_GAME'))
            validate_game_dir(paths.game)
            check_files(paths.game, self.profile.game, lambda: False)
            if log.is_file():
                with inside(paths.game, f'.bc2-install-{job}.log').open('xb') as target, log.open('rb') as source:
                    shutil.copyfileobj(source, target)
            atomic_write(inside(paths.cache, 'installed.json'), json.dumps(dict(job=job, game=str(paths.game))).encode())
            return InstallResult(paths, job)

    def cleanup(self, result):
        paths = InstallPaths.from_library(result.paths.library)
        if paths != result.paths:
            raise UpdateError('Пути установки изменились. Кэш сохранён.')
        with UpdateStore(inside(paths.library, '_torrents', '.bc2-install-lock')).locked():
            expected = dict(job=result.job_id, game=str(paths.game))
            if self._owner(paths) != result.job_id or read_json(inside(paths.cache, 'installed.json'), 4096) != expected:
                raise UpdateError('Нет подтверждения успешной установки. Кэш сохранён.')
            validate_game_dir(paths.game)
            check_files(paths.game, self.profile.game, self.cancel.is_set)
            files, dirs = self._cache_items(paths)
            self._cancelled()
            markers = {'owner.json', 'installed.json'}
            for item in sorted(files, key=lambda p: p.parent == paths.cache and p.name in markers):
                reject_links(item).unlink()
            for item in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
                reject_links(item).rmdir()
            reject_links(paths.cache).rmdir()
