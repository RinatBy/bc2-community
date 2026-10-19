import base64
import json
import hashlib
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

KEY = Ed25519PrivateKey.generate()
PUBLIC = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
DLL = b"test DLL, never executed"
INI = b"[info]\nhost=master.bc2.uplay2.ru\nconnect_to_retail=0\n"


def payload(revision=1):
    return dict(schema=1, revision=revision, package_id="test-1",
                minimum_launcher_version="0.1.0", master_host="master.bc2.uplay2.ru",
                expires_at=(NOW + timedelta(days=30)).isoformat(),
                assets=[dict(name=n, size=len(b), sha256=hashlib.sha256(b).hexdigest(),
                             url="https://github.com/RinatBy/bc2-community/releases/download/test/" + n)
                        for n, b in [("dinput8.dll", DLL), ("bfbc2.ini", INI)]])


def envelope(data=None, raw=None):
    raw = raw if raw is not None else json.dumps(data or payload()).encode()
    return json.dumps(dict(payload=base64.b64encode(raw).decode(),
                           signature=base64.b64encode(KEY.sign(raw)).decode())).encode()
