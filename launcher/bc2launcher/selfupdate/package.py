import hashlib
import os
import stat
import struct
import tempfile
import zipfile
import zlib
from pathlib import Path
from ..manifest import UpdateError
from .paths import inside, package_path, version_dir
from .policy import (INVENTORY_NAME, INVENTORY_LIMIT, COUNT_LIMIT, TOTAL_LIMIT,
                     verify_inventory)
from .store import UpdateStore


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''): digest.update(chunk)
    return digest.hexdigest()


def _archive_header(path):
    """Bound the central directory before ZipFile allocates a ZipInfo per entry."""
    with path.open('rb') as stream:
        stream.seek(0, 2); size = stream.tell()
        stream.seek(max(0, size - 65557)); tail = stream.read()
    index = tail.rfind(b'PK\x05\x06')
    if index < 0 or len(tail) - index < 22: raise UpdateError('Invalid ZIP directory.')
    _, disk, first, local_count, total, length, offset, comment = struct.unpack_from('<4s4H2IH', tail, index)
    eocd_offset = size - len(tail) + index
    if (disk or first or local_count != total or not 1 <= total <= COUNT_LIMIT + 1
            or total == 65535 or length > 4 * 1024**2 or offset + length != eocd_offset
            or index + 22 + comment != len(tail)):
        raise UpdateError('Unsupported or excessive ZIP directory.')
    return total


def _members(archive, count):
    entries = archive.infolist()
    if len(entries) != count: raise UpdateError('ZIP directory count mismatch.')
    result = {}
    for info in entries:
        name = package_path(info.filename)
        # ZipInfo truncates at a NUL; inspect the original name as well.
        if info.orig_filename != name: raise UpdateError('Invalid ZIP name.')
        folded = name.casefold()
        mode = info.external_attr >> 16
        if (folded in result or info.is_dir() or info.flag_bits & 1
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or info.external_attr & 0x400 or info.extract_version >= 45):
            raise UpdateError('Unsafe ZIP entry.')
        result[folded] = info
    return result


def _inventory_from_zip(archive, members, policy, public_key):
    meta = members.get(INVENTORY_NAME.casefold())
    if meta is None or meta.filename != INVENTORY_NAME or meta.file_size > INVENTORY_LIMIT:
        raise UpdateError('Missing or excessive package inventory.')
    raw = archive.read(meta)
    inv = verify_inventory(raw, public_key)
    if inv.version != policy.version: raise UpdateError('Package version mismatch.')
    expected = {f.path.casefold(): f for f in inv.files}
    if set(members) != set(expected) | {INVENTORY_NAME.casefold()}:
        raise UpdateError('Package contains missing or unexpected files.')
    total = 0
    for name, entry in expected.items():
        info = members[name]
        if info.filename != entry.path or info.file_size != entry.size:
            raise UpdateError('Package file name or size mismatch.')
        total += entry.size
        if total > TOTAL_LIMIT: raise UpdateError('Unpacked package exceeds size limit.')
    return inv, raw


def verify_installed(root, version, public_key):
    path = version_dir(root, version)
    metadata = inside(path, INVENTORY_NAME)
    if not metadata.is_file() or metadata.stat().st_size > INVENTORY_LIMIT:
        raise UpdateError('Missing installed package inventory.')
    inv = verify_inventory(metadata.read_bytes(), public_key)
    if inv.version != version: raise UpdateError('Installed version mismatch.')
    expected = {f.path: f for f in inv.files}
    directories = {'/'.join(f.path.split('/')[:i]) for f in inv.files for i in range(1, len(f.path.split('/')))}
    actual = set()
    for current, dirs, files in os.walk(path, followlinks=False):
        for name in dirs:
            child = inside(path, Path(current).relative_to(path), name)
            if child.relative_to(path).as_posix() not in directories: raise UpdateError('Unexpected installed directory.')
        for name in files:
            child = inside(path, Path(current).relative_to(path), name)
            relative = child.relative_to(path).as_posix()
            if relative == INVENTORY_NAME: continue
            entry = expected.get(relative)
            if entry is None or child.stat().st_size != entry.size or file_hash(child) != entry.sha256:
                raise UpdateError('Installed application file failed verification.')
            actual.add(relative)
    if actual != set(expected): raise UpdateError('Installed application files are missing.')
    return inv


def _remember_prepared(root, policy, inventory):
    cache = inside(root, 'cache')
    UpdateStore(cache).write_json('prepared-' + policy.version + '.json',
        dict(schema=1, version=policy.version, artifact_sha256=policy.artifact.sha256,
             inventory_sha256=inventory.payload_sha256))


def verify_prepared(root, policy, public_key):
    receipt = UpdateStore(inside(root, 'cache')).read_json('prepared-' + policy.version + '.json')
    if (not isinstance(receipt, dict)
            or set(receipt) != {'schema', 'version', 'artifact_sha256', 'inventory_sha256'}
            or type(receipt['schema']) is not int or receipt['schema'] != 1
            or receipt['version'] != policy.version or receipt['artifact_sha256'] != policy.artifact.sha256):
        raise UpdateError('Prepared version does not match the accepted archive.')
    inventory = verify_installed(root, policy.version, public_key)
    if inventory.payload_sha256 != receipt['inventory_sha256']:
        raise UpdateError('Prepared inventory has changed.')
    return inventory


def stage_package(archive, policy, root, public_key, *, cancelled=lambda: False):
    try:
        archive = Path(archive)
        if cancelled(): raise UpdateError('Update cancelled.')
        if archive.stat().st_size != policy.artifact.size or file_hash(archive) != policy.artifact.sha256:
            raise UpdateError('Launcher archive size or checksum mismatch.')
        count = _archive_header(archive)
        with UpdateStore(root).locked():
            versions = inside(root, 'versions'); versions.mkdir(exist_ok=True)
            destination = version_dir(root, policy.version)
            with zipfile.ZipFile(archive) as source:
                members = _members(source, count)
                inv, raw = _inventory_from_zip(source, members, policy, public_key)
                if destination.exists():
                    existing = verify_installed(root, policy.version, public_key)
                    if existing.payload_sha256 != inv.payload_sha256:
                        raise UpdateError('A version cannot be reused with different contents.')
                    _remember_prepared(root, policy, inv)
                    return destination
                with tempfile.TemporaryDirectory(prefix='.stage-', dir=versions) as scratch:
                    stage = Path(scratch) / 'content'; stage.mkdir()
                    for entry in inv.files:
                        if cancelled(): raise UpdateError('Update cancelled.')
                        target = inside(stage, *entry.path.split('/')); target.parent.mkdir(parents=True, exist_ok=True)
                        written, digest = 0, hashlib.sha256()
                        with source.open(members[entry.path.casefold()]) as stream, target.open('xb') as output:
                            while True:
                                if cancelled(): raise UpdateError('Update cancelled.')
                                chunk = stream.read(min(65536, entry.size + 1 - written))
                                if not chunk: break
                                written += len(chunk)
                                if written > entry.size: raise UpdateError('Extracted file exceeds signed size.')
                                digest.update(chunk); output.write(chunk)
                            output.flush(); os.fsync(output.fileno())
                        if written != entry.size or digest.hexdigest() != entry.sha256:
                            raise UpdateError('Extracted file failed checksum verification.')
                    (stage / INVENTORY_NAME).write_bytes(raw)
                    if cancelled(): raise UpdateError('Update cancelled.')
                    inside(root, 'versions', policy.version)
                    os.replace(stage, destination)
                    _remember_prepared(root, policy, inv)
                    return destination
    except UpdateError: raise
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise UpdateError('Unable to prepare verified launcher package.') from exc
