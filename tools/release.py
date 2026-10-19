"""Offline signing; private keys are never sent to GitHub or printed."""
import argparse
import base64
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'launcher'))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PrivateFormat,PublicFormat,NoEncryption,load_pem_private_key
from bc2launcher.manifest import HOST, LIMITS, verify_manifest


def _sign(payload,key):
    raw=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    return json.dumps(dict(payload=base64.b64encode(raw).decode(),signature=base64.b64encode(key.sign(raw)).decode()),indent=2).encode()


def sign_package(folder,base_url,revision,package_id,key,now):
    assets=[]
    for name in LIMITS:
        data=(Path(folder)/name).read_bytes()
        assets.append(dict(name=name,url=base_url.rstrip('/')+'/'+name,size=len(data),sha256=hashlib.sha256(data).hexdigest()))
    p=dict(schema=1,revision=revision,package_id=package_id,minimum_launcher_version='0.1.0',
           expires_at=(now+timedelta(days=90)).isoformat(),master_host=HOST,assets=assets)
    encoded=_sign(p,key)
    verify_manifest(encoded,key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw),now,0)
    return encoded


def rollback_payload(release,revision,key,now):
    if revision<=release.revision: raise ValueError('Rollback must use a NEW revision')
    return _sign(dict(schema=1,revision=revision,package_id=release.package_id,
                      minimum_launcher_version=release.minimum_launcher_version,
                      expires_at=(now+timedelta(days=90)).isoformat(),master_host=HOST,
                      assets=[asdict(a) for a in release.assets]),key)


def main():
    parser=argparse.ArgumentParser(description='BC2 release signing (offline private key)')
    sub=parser.add_subparsers(dest='command',required=True)
    keygen=sub.add_parser('keygen'); keygen.add_argument('--private',required=True); keygen.add_argument('--public',required=True)
    package=sub.add_parser('package'); package.add_argument('--folder',required=True); package.add_argument('--base-url',required=True); package.add_argument('--package-id',required=True)
    rollback=sub.add_parser('rollback'); rollback.add_argument('--manifest',required=True)
    for p in [package,rollback]:
        p.add_argument('--private',required=True); p.add_argument('--revision',required=True,type=int); p.add_argument('--output',required=True)
    a=parser.parse_args(); now=datetime.now(timezone.utc)
    if a.command=='keygen':
        private=Path(a.private); public=Path(a.public)
        if private.exists() or public.exists(): parser.error('Refusing to overwrite an existing key')
        key=Ed25519PrivateKey.generate(); private.parent.mkdir(parents=True,exist_ok=True); public.parent.mkdir(parents=True,exist_ok=True)
        with private.open('xb') as stream:stream.write(key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,NoEncryption()))
        public.write_bytes(key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))
        print('Created private key at requested private path and public verification key. Keep private key offline.')
        return
    key=load_pem_private_key(Path(a.private).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey): parser.error('Expected Ed25519 key')
    if a.command=='package': result=sign_package(a.folder,a.base_url,a.revision,a.package_id,key,now)
    else:
        old=verify_manifest(Path(a.manifest).read_bytes(),key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw),now,0)
        result=rollback_payload(old,a.revision,key,now)
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(result)
    print('Signed manifest written; revision',a.revision)


if __name__=='__main__': main()
