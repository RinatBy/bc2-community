import contextlib
import json
from pathlib import Path
from ..manifest import UpdateError, _json
from ..transaction import atomic_write
from .paths import inside, reject_links, validate_version
from .policy import _digest


class UpdateStore:
    def __init__(self, root):
        self.root = reject_links(root)

    def read_json(self, name, limit=16384):
        path = inside(self.root, name)
        if not path.exists(): return None
        if path.stat().st_size > limit: raise UpdateError('Application state is too large.')
        try: return _json(path.read_bytes())
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise UpdateError('Application update state is damaged.') from exc

    def write_json(self, name, value):
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write(inside(self.root, name), json.dumps(value, ensure_ascii=True).encode())

    @contextlib.contextmanager
    def locked(self, name='update.lock'):
        if name not in ('update.lock', 'client.lock'): raise ValueError('Invalid lock')
        self.root.mkdir(parents=True, exist_ok=True)
        path = inside(self.root, name)
        with path.open('a+b') as stream:
            stream.seek(0, 2)
            if not stream.tell(): stream.write(b'0'); stream.flush()
            stream.seek(0)
            try:
                import os
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc: raise UpdateError('Another launcher is updating this installation.') from exc
            try: yield
            finally:
                if os.name == 'nt': stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else: fcntl.flock(stream, fcntl.LOCK_UN)

    def load(self):
        p = self.read_json('update-state.json')
        if p is None: return dict(schema=1, highest_revision=0, payload_sha256='', failed=[])
        try:
            if (not isinstance(p, dict) or set(p) != {'schema','highest_revision','payload_sha256','failed'}
                    or type(p['schema']) is not int or p['schema'] != 1
                    or type(p['highest_revision']) is not int or not 0 <= p['highest_revision'] <= 2**53): raise ValueError()
            if p['highest_revision']: _digest(p['payload_sha256'])
            elif p['payload_sha256'] != '': raise ValueError()
            if not isinstance(p['failed'], list) or len(p['failed']) > 8: raise ValueError()
            for digest in p['failed']: _digest(digest)
            return p
        except (ValueError, TypeError, KeyError) as exc: raise UpdateError('Invalid application policy state.') from exc

    def accept(self, policy):
        with self.locked():
            p = self.load()
            if (policy.revision < p['highest_revision'] or (policy.revision == p['highest_revision']
                    and policy.payload_sha256 != p['payload_sha256'])):
                raise UpdateError('Launcher policy revision has been replayed or changed.')
            p.update(highest_revision=policy.revision, payload_sha256=policy.payload_sha256)
            self.write_json('update-state.json', p)

    def mark_failed(self, digest):
        _digest(digest)
        p = self.load(); p['failed'] = [f for f in p['failed'] if f != digest][-7:] + [digest]
        self.write_json('update-state.json', p)

    def active(self):
        p = self.read_json('active.json')
        if (not isinstance(p, dict) or set(p) != {'schema','version'}
                or type(p['schema']) is not int or p['schema'] != 1):
            raise UpdateError('Invalid active application version. Reinstall the launcher.')
        return validate_version(p['version'])

    def set_active(self, version):
        self.write_json('active.json', dict(schema=1, version=validate_version(version)))
