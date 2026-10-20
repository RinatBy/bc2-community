import os
import re
import stat
import unicodedata
from pathlib import Path
from ..manifest import UpdateError


def validate_version(value):
    number = r'(?:0|[1-9][0-9]{0,3})'
    if not isinstance(value, str) or not re.fullmatch(rf'{number}\.{number}\.{number}', value):
        raise UpdateError('Invalid application version.')
    return value


def package_path(value):
    if not isinstance(value, str) or not value or not value.isascii() or len(value) > 220:
        raise UpdateError('Invalid package path.')
    if value != unicodedata.normalize('NFC', value):
        raise UpdateError('Noncanonical package path.')
    parts = value.split('/')
    for part in parts:
        if (not part or part in ('.', '..') or len(part) > 128 or part[-1] in ' .'
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in part)
                or re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part, re.I)):
            raise UpdateError('Unsafe Windows package path.')
    return value


def reject_links(path):
    path = Path(path).absolute()
    for part in [*reversed(path.parents), path]:
        try: info = part.lstat()
        except FileNotFoundError: continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise UpdateError('Links and reparse points are not allowed in the installation.')
    return path


def inside(root, *parts):
    root = reject_links(root)
    path = root.joinpath(*parts).absolute()
    try: path.relative_to(root)
    except ValueError as exc: raise UpdateError('Path outside installation.') from exc
    if '..' in path.parts: raise UpdateError('Parent traversal is not allowed.')
    return reject_links(path)


def version_dir(root, version):
    return inside(root, 'versions', validate_version(version))
