import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ..manifest import UpdateError, _json, version_tuple
from ..network import validate_url
from .paths import package_path, validate_version

POLICY_LIMIT = 256 * 1024
INVENTORY_LIMIT = 2 * 1024**2
ARCHIVE_LIMIT = 512 * 1024**2
FILE_LIMIT = 512 * 1024**2
TOTAL_LIMIT = 1536 * 1024**2
COUNT_LIMIT = 8192
INVENTORY_NAME = '.launcher-package.json'


@dataclass(frozen=True)
class Artifact:
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class LauncherPolicy:
    revision: int
    expires_at: datetime
    version: str
    minimum_launcher_version: str
    minimum_bootstrap_version: str
    artifact: Artifact
    payload_sha256: str


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Inventory:
    version: str
    files: tuple[FileEntry, ...]
    payload_sha256: str


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ValueError('Unexpected fields')


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('Invalid digest')
    return value


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper: raise ValueError('Invalid integer')
    return value


def _verified(raw, key, limit, purpose, fields):
    if not isinstance(raw, bytes) or len(raw) > limit: raise ValueError('Metadata too large')
    env = _json(raw)
    _fields(env, 'payload signature')
    payload = base64.b64decode(env['payload'], validate=True)
    Ed25519PublicKey.from_public_bytes(key).verify(base64.b64decode(env['signature'], validate=True), payload)
    p = _json(payload)
    _fields(p, 'schema purpose ' + fields)
    if type(p['schema']) is not int or p['schema'] != 1 or p['purpose'] != purpose:
        raise ValueError('Wrong metadata purpose')
    return p, hashlib.sha256(payload).hexdigest()


BAD_FORMAT = (ValueError, TypeError, KeyError, AttributeError, InvalidSignature,
              binascii.Error, UnicodeError, RecursionError, OverflowError)


def verify_policy(raw, public_key, now, highest_revision):
    try:
        p, digest = _verified(raw, public_key, POLICY_LIMIT, 'bc2-launcher-update',
                             'revision expires_at version minimum_launcher_version minimum_bootstrap_version artifact')
        revision = _integer(p['revision'], 1, 2**53)
        if revision < highest_revision: raise UpdateError('Obsolete launcher policy.')
        expires = datetime.fromisoformat(p['expires_at'].replace('Z', '+00:00'))
        if expires.utcoffset() is None or expires <= now: raise UpdateError('Launcher policy has expired.')
        for name in ('version', 'minimum_launcher_version', 'minimum_bootstrap_version'):
            validate_version(p[name])
        if version_tuple(p['minimum_launcher_version']) > version_tuple(p['version']): raise ValueError()
        a = p['artifact']; _fields(a, 'url size sha256')
        validate_url(a['url']); _integer(a['size'], 1, ARCHIVE_LIMIT); _digest(a['sha256'])
        return LauncherPolicy(revision, expires, p['version'], p['minimum_launcher_version'],
                              p['minimum_bootstrap_version'], Artifact(**a), digest)
    except UpdateError: raise
    except BAD_FORMAT as exc: raise UpdateError('Invalid launcher policy signature or format.') from exc


def verify_inventory(raw, public_key):
    try:
        p, digest = _verified(raw, public_key, INVENTORY_LIMIT, 'bc2-launcher-package', 'version files')
        validate_version(p['version'])
        if not isinstance(p['files'], list) or not 1 <= len(p['files']) <= COUNT_LIMIT: raise ValueError()
        files, seen, total = [], set(), 0
        for item in p['files']:
            _fields(item, 'path size sha256')
            name = package_path(item['path']); folded = name.casefold()
            if folded in seen or folded == INVENTORY_NAME.casefold(): raise ValueError('Duplicate file')
            seen.add(folded)
            size = _integer(item['size'], 0, FILE_LIMIT); total += size
            if total > TOTAL_LIMIT: raise ValueError('Unpacked size too large')
            files.append(FileEntry(name, size, _digest(item['sha256'])))
        if 'BC2Client.exe' not in {f.path for f in files}: raise ValueError('Missing client')
        for name in seen:
            if any('/'.join(name.split('/')[:i]) in seen for i in range(1, len(name.split('/')))):
                raise ValueError('File/directory collision')
        return Inventory(p['version'], tuple(files), digest)
    except UpdateError: raise
    except BAD_FORMAT as exc: raise UpdateError('Invalid launcher package signature or inventory.') from exc
