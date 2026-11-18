"""Download one pinned torrent with piece verification and safe resume from disk."""
import ipaddress
import hashlib
import time
from urllib.parse import urlsplit

import libtorrent as lt

from .game_install import InstallProgress, relative_path
from .manifest import UpdateError
from .selfupdate.paths import inside


def session_settings():
    return {'listen_interfaces': '0.0.0.0:0', 'enable_dht': True, 'enable_lsd': False,
            'enable_upnp': False, 'enable_natpmp': False, 'connections_limit': 80}


def _tracker_allowed(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if parsed.scheme not in ('udp', 'https', 'http') or not host or '.' not in host:
            return False
        if parsed.username or parsed.password or host.endswith(('.local', '.localhost')):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def _read_info(profile, paths):
    try:
        torrent = inside(paths.cache, 'source.torrent')
        if not torrent.is_file() or torrent.stat().st_size > 2 * 1024**2:
            raise UpdateError('Не найден файл метаданных торрента.')
        raw = torrent.read_bytes()
        if hashlib.sha256(raw).hexdigest() != profile.torrent_sha256:
            raise UpdateError('Метаданные торрента изменились.')
        info = lt.torrent_info(raw)
        storage = info.files()
        expected = {record.path: record.size for record in profile.package}
        if str(info.info_hashes().v1) != profile.info_hash or storage.num_files() != len(expected):
            raise UpdateError('Идентификатор или состав торрента не совпадает с профилем.')
        for i in range(storage.num_files()):
            name = relative_path(storage.file_path(i).replace('\\', '/'))
            if storage.file_flags(i) or expected.pop(name, None) != storage.file_size(i):
                raise UpdateError('Торрент содержит неожиданный файл: ' + name)
            inside(paths.payload, *name.split('/'))
        return info
    except (OSError, RuntimeError) as exc:
        raise UpdateError('Не удалось прочитать проверенный торрент.') from exc


def download(profile, paths, *, progress, cancelled):
    if cancelled():
        raise UpdateError('Загрузка отменена. Кэш сохранён.')
    info = _read_info(profile, paths)
    session = lt.session(session_settings())
    params = lt.add_torrent_params()
    params.ti = info
    params.save_path = str(paths.payload)
    params.flags = ((params.flags | lt.torrent_flags.override_trackers | lt.torrent_flags.override_web_seeds)
                    & ~(lt.torrent_flags.auto_managed | lt.torrent_flags.paused | lt.torrent_flags.seed_mode))
    params.trackers = [entry.url for entry in info.trackers() if _tracker_allowed(entry.url)]
    handle = session.add_torrent(params)
    last_progress, previous = time.monotonic(), None
    try:
        while True:
            if cancelled():
                raise UpdateError('Загрузка отменена. Кэш сохранён.')
            status = handle.status()
            if status.errc.value():
                raise UpdateError('Ошибка торрента: ' + status.errc.message())
            checking = status.state in (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data)
            count = int(status.total_wanted_done)
            sample = (status.state, count, status.progress_ppm if checking else 0)
            if sample != previous:
                previous, last_progress = sample, time.monotonic()
            if time.monotonic() - last_progress > 300:
                raise UpdateError('Нет прогресса 5 минут. Кэш сохранён, загрузку можно продолжить.')
            progress(InstallProgress('CHECK_CACHE' if checking else 'DOWNLOAD', count,
                                     profile.download_size, int(status.download_payload_rate)))
            if status.is_seeding and count == profile.download_size:
                break
            time.sleep(.25)
        progress(InstallProgress('FINALIZE_DOWNLOAD'))
    finally:
        session.remove_torrent(handle)
        # The session destructor waits for disk I/O. The caller then hashes the files on disk.
        del session
