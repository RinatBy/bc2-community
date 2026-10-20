"""Offline app packaging/signing. Never prints or packages private keys."""
import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.paths import inside, package_path, validate_version
from bc2launcher.selfupdate.policy import verify_inventory, verify_policy, INVENTORY_NAME, INVENTORY_LIMIT
from bc2launcher.selfupdate.package import file_hash
from release import _sign


def package_launcher(folder, version, output, key):
    folder = Path(folder).absolute(); validate_version(version)
    files = []
    for path in sorted(folder.rglob('*'), key=lambda p: p.relative_to(folder).as_posix()):
        inside(folder, path.relative_to(folder))
        if not path.is_file(): continue
        name = path.relative_to(folder).as_posix()
        if name == INVENTORY_NAME: continue
        if path.suffix.lower() in {'.key', '.pem', '.p12', '.pfx', '.db'} or path.name.lower() == 'settings.json':
            raise UpdateError('Private/runtime state file in application build.')
        files.append(dict(path=package_path(name), size=path.stat().st_size, sha256=file_hash(path)))
    raw = _sign(dict(purpose='bc2-launcher-package', schema=1, version=version, files=files), key)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    inv = verify_inventory(raw, public)
    meta = folder / INVENTORY_NAME
    if meta.exists():
        old = verify_inventory(meta.read_bytes(), public)
        if old.payload_sha256 != inv.payload_sha256: raise UpdateError('Refusing different contents for the same application build.')
    meta.write_bytes(raw)
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=False) as archive:
        for entry in [INVENTORY_NAME, *[f['path'] for f in files]]:
            info = zipfile.ZipInfo(entry, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            with (folder / entry).open('rb') as source, archive.open(info, 'w') as target:
                for chunk in iter(lambda: source.read(65536), b''): target.write(chunk)
    return output


def sign_launcher_policy(archive, version, url, revision, key, now, *, minimum=None, bootstrap='1.0.0'):
    archive = Path(archive)
    p = dict(purpose='bc2-launcher-update', schema=1, revision=revision,
             expires_at=(now + timedelta(days=90)).isoformat(), version=version,
             minimum_launcher_version=minimum or version, minimum_bootstrap_version=bootstrap,
             artifact=dict(url=url, size=archive.stat().st_size, sha256=file_hash(archive)))
    raw = _sign(p, key)
    verify_policy(raw, key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), now, 0)
    return raw


def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    package=sub.add_parser('package');package.add_argument('--folder',required=True)
    policy=sub.add_parser('policy');policy.add_argument('--archive',required=True);policy.add_argument('--url',required=True)
    policy.add_argument('--revision',required=True,type=int);policy.add_argument('--minimum');policy.add_argument('--bootstrap',default='1.0.0')
    for command in (package,policy):
        command.add_argument('--version',required=True);command.add_argument('--private',required=True);command.add_argument('--output',required=True)
    a=p.parse_args();key=load_pem_private_key(Path(a.private).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey):p.error('Expected Ed25519 key')
    if a.command=='package':package_launcher(a.folder,a.version,a.output,key)
    else:Path(a.output).write_bytes(sign_launcher_policy(a.archive,a.version,a.url,a.revision,key,datetime.now(timezone.utc),minimum=a.minimum,bootstrap=a.bootstrap))
    print('Signed launcher',a.command,'created for',a.version)


if __name__=='__main__':main()
