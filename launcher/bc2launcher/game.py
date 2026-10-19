import configparser
import ctypes
from ctypes import wintypes
import io
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from .manifest import UpdateError, HOST


@dataclass(frozen=True)
class GameInstallation:
    root: Path
    executable: Path


def safe_path(root: Path, path: Path) -> Path:
    root, path = Path(os.path.abspath(root)), Path(os.path.abspath(path))
    if not path.is_relative_to(root): raise UpdateError("Путь выходит за пределы папки игры.")
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise UpdateError("Ссылки и перенаправленные папки не поддерживаются. Выберите обычную папку игры.")
    return path


def validate_game_dir(path: Path) -> GameInstallation:
    root = Path(os.path.abspath(path.expanduser()))
    safe_path(root, root)
    exe = safe_path(root, root/'BFBC2Game.exe')
    if not root.is_dir() or not exe.is_file():
        raise UpdateError("Выберите папку игры с файлом BFBC2Game.exe.")
    with exe.open('rb') as stream:
        if stream.read(2) != b'MZ': raise UpdateError("BFBC2Game.exe не является Windows-программой.")
    return GameInstallation(root, exe)


def _decode(data):
    for encoding in ['utf-8-sig', 'cp1251']:
        try:
            text = data.decode(encoding)
            if '\0' in text: raise UpdateError("INI содержит недопустимые данные.")
            return text, ('utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else
                          'utf-8' if encoding == 'utf-8-sig' else encoding)
        except UnicodeDecodeError: pass
    raise UpdateError("Не удалось прочитать bfbc2.ini.")


def _parse(text):
    parser = configparser.RawConfigParser(strict=True)
    try: parser.read_string(text)
    except configparser.Error as exc: raise UpdateError("Исправьте повреждённый bfbc2.ini или восстановите резервную копию.") from exc
    if parser.defaults(): raise UpdateError("Раздел DEFAULT в bfbc2.ini не поддерживается.")
    return parser


def read_managed_ini(data: bytes):
    p = _parse(_decode(data)[0])
    return p.get('info','host',fallback=''), p.get('info','connect_to_retail',fallback='')


def merge_connection_ini(original: bytes | None, template: bytes, host: str) -> bytes:
    if host != HOST: raise UpdateError("Неверный адрес мастера.")
    text, encoding = _decode(template if original is None else original)
    p = _parse(text)
    newline = '\r\n' if '\r\n' in text else '\n'
    if not p.has_section('info'):
        text += newline + '[info]' + newline
    lines = text.splitlines(keepends=True)
    values = {'host': host, 'connect_to_retail': '0'}
    result, section, seen = [], None, set()
    def add_missing():
        if result and not result[-1].endswith(('\n','\r')): result[-1] += newline
        for key, value in values.items():
            if key not in seen: result.append(key + '=' + value + newline)
    for line in lines:
        header = re.match(r'^\s*\[([^]]+)\]', line)
        if header:
            if section == 'info': add_missing()
            section = header[1]
        match = re.match(r'^(\s*)(host|connect_to_retail)\s*[=:].*$', line, re.I)
        if section == 'info' and match:
            key = match[2].lower(); seen.add(key)
            line = match[1] + key + '=' + values[key] + newline
        result.append(line)
    if section == 'info': add_missing()
    output = ''.join(result).encode(encoding)
    if read_managed_ini(output) != (HOST, '0'): raise UpdateError("Не удалось обновить настройки подключения.")
    return output


def ensure_game_closed():
    if os.name != 'nt': return
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
                    ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
                    ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
                    ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
                    ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == wintypes.HANDLE(-1).value: raise UpdateError("Не удалось проверить, закрыта ли игра.")
    try:
        entry=Entry(); entry.dwSize=ctypes.sizeof(entry)
        ok=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == 'bfbc2game.exe': raise UpdateError("Закройте игру перед изменением файлов.")
            ok=kernel.Process32NextW(handle,ctypes.byref(entry))
        if ctypes.get_last_error() not in (0,18): raise UpdateError("Не удалось завершить проверку процессов.")
    finally: kernel.CloseHandle(handle)
