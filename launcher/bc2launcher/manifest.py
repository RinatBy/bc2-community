import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

HOST = "master.bc2.uplay2.ru"
LIMITS = {"dinput8.dll": 16 * 1024 * 1024, "bfbc2.ini": 64 * 1024}
MANIFEST_LIMIT = 256 * 1024


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    revision: int
    package_id: str
    minimum_launcher_version: str
    expires_at: datetime
    master_host: str
    assets: tuple[Asset, ...]
    payload_sha256: str


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', value):
        raise UpdateError("Неверная версия в описании обновления.")
    return tuple(map(int, value.split('.')))


def _pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result: raise UpdateError("Повторяющиеся поля обновления.")
        result[k] = v
    return result


def _json(raw):
    def invalid(value): raise UpdateError("Некорректное число JSON.")
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def verify_manifest(envelope: bytes, public_key: bytes, now: datetime, highest_revision: int) -> Release:
    from .network import validate_url
    import hashlib
    try:
        if len(envelope) > MANIFEST_LIMIT: raise UpdateError("Описание обновления слишком большое.")
        outer = _json(envelope)
        if set(outer) != {'payload', 'signature'}: raise ValueError()
        raw = base64.b64decode(outer['payload'], validate=True)
        signature = base64.b64decode(outer['signature'], validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, raw)
        p = _json(raw)
        required = {'schema', 'revision', 'package_id', 'minimum_launcher_version',
                    'expires_at', 'master_host', 'assets'}
        if not isinstance(p, dict) or set(p) != required: raise ValueError()
        if type(p['schema']) is not int or p['schema'] != 1: raise ValueError()
        if type(p['revision']) is not int or not 1 <= p['revision'] <= 2**53: raise ValueError()
        if p['revision'] < highest_revision: raise UpdateError("Получено устаревшее описание обновления.")
        if not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}', p['package_id']): raise ValueError()
        version_tuple(p['minimum_launcher_version'])
        expires = datetime.fromisoformat(p['expires_at'].replace('Z', '+00:00'))
        if expires.utcoffset() is None: raise ValueError()
        if expires <= now: raise UpdateError("Срок действия обновления истёк. Повторите проверку позже.")
        if p['master_host'] != HOST: raise UpdateError("Неожиданный адрес мастер-сервера.")
        if not isinstance(p['assets'], list) or len(p['assets']) != 2: raise ValueError()
        assets = []
        for item in p['assets']:
            if set(item) != {'name', 'url', 'size', 'sha256'}: raise ValueError()
            if item['name'] not in LIMITS: raise UpdateError("Недопустимый файл обновления.")
            if type(item['size']) is not int or not 0 < item['size'] <= LIMITS[item['name']]: raise ValueError()
            if not re.fullmatch(r'[0-9a-f]{64}', item['sha256']): raise ValueError()
            validate_url(item['url'])
            assets.append(Asset(**item))
        if {a.name for a in assets} != set(LIMITS): raise ValueError()
        return Release(p['revision'], p['package_id'], p['minimum_launcher_version'],
                       expires, HOST, tuple(assets), hashlib.sha256(raw).hexdigest())
    except UpdateError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, InvalidSignature, binascii.Error,
            UnicodeError, RecursionError) as exc:
        raise UpdateError("Не удалось проверить подпись или формат обновления.") from exc
