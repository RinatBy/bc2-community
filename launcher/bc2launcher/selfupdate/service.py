import os
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from .. import VERSION
from ..manifest import UpdateError, version_tuple, _json
from ..network import fetch_bytes, download_file
from . import BOOTSTRAP_VERSION
from .paths import inside, version_dir
from .policy import POLICY_LIMIT, verify_policy
from .package import stage_package, verify_installed, verify_prepared
from .process import probe_version
from .store import UpdateStore

FEED = 'https://bc2.uplay2.ru/updates/launcher-stable.json'
FALLBACK_FEED = 'https://raw.githubusercontent.com/RinatBy/bc2-community/main/website/updates/launcher-stable.json'


@dataclass(frozen=True)
class AppUpdateStatus:
    state: str
    play_allowed: bool
    restart_ready: bool
    error: str = ''


class SelfUpdateService:
    def __init__(self, root, public_key, *, version=VERSION, fetch=fetch_bytes,
                 download=download_file, clock=None, probe=probe_version, progress=None):
        self.root = inside(root); self.store = UpdateStore(root); self.public_key = public_key
        self.version = version; self.fetch = fetch; self.download = download
        self.clock = clock or (lambda: datetime.now(timezone.utc)); self.probe = probe
        self.progress = progress or (lambda message: None)
        self.cancel = threading.Event(); self.policy = None; self.prepared_version = None
        self.status = AppUpdateStatus('UNKNOWN', False, False)
        self.bootstrap_process = None

    def _get_policy(self):
        saved = self.store.load()
        try: raw = self.fetch(FEED, POLICY_LIMIT)
        except (UpdateError, OSError):
            try: raw = self.fetch(FALLBACK_FEED, POLICY_LIMIT)
            except (UpdateError, OSError):
                cached = inside(self.root, 'launcher-policy.json')
                if not cached.is_file() or cached.stat().st_size > POLICY_LIMIT: raise
                raw = cached.read_bytes()
        policy = verify_policy(raw, self.public_key, self.clock(), saved['highest_revision'])
        self.store.accept(policy)
        with self.store.locked():
            # Never overwrite a newer policy accepted by another instance.
            state = self.store.load()
            if policy.payload_sha256 != state['payload_sha256']: raise UpdateError('Launcher policy changed concurrently.')
            from ..transaction import atomic_write
            atomic_write(inside(self.root, 'launcher-policy.json'), raw)
        self.policy = policy
        return policy

    def check(self):
        try:
            p = self._get_policy()
            if version_tuple(p.minimum_bootstrap_version) > version_tuple(BOOTSTRAP_VERSION):
                self.status = AppUpdateStatus('INSTALLER_REQUIRED', False, False)
            else:
                allowed = version_tuple(self.version) >= version_tuple(p.minimum_launcher_version)
                if p.version == self.version: state = 'CURRENT'
                elif p.payload_sha256 in self.store.load()['failed']: state = 'FAILED'
                else: state = 'AVAILABLE' if allowed else 'REQUIRED'
                ready = self.prepared_version == p.version and p.version != self.version
                if ready: verify_prepared(self.root, p, self.public_key)
                self.status = AppUpdateStatus('STAGED' if ready else state, allowed, ready)
        except Exception as exc:
            self.policy = None
            self.status = AppUpdateStatus('ERROR', False, False, str(exc))
        return self.status

    def prepare(self, *, manual=False):
        status = self.check()
        if self.cancel.is_set():
            self.status = AppUpdateStatus('CANCELLED', status.play_allowed, False)
            return self.status
        if status.state in ('CURRENT', 'ERROR', 'INSTALLER_REQUIRED') or (status.state == 'FAILED' and not manual):
            return status
        archive = None
        try:
            p = self.policy
            cache = inside(self.root, 'cache'); cache.mkdir(exist_ok=True)
            archive = inside(cache, 'download-' + secrets.token_hex(12) + '.zip')
            try: verify_prepared(self.root, p, self.public_key)
            except (UpdateError, OSError):
                self.progress('DOWNLOAD')
                self.download(p.artifact.url, archive, p.artifact.size,
                              cancelled=self.cancel.is_set, progress=lambda n: None)
                stage_package(archive, p, self.root, self.public_key, cancelled=self.cancel.is_set)
            if self.cancel.is_set(): raise UpdateError('Update cancelled.')
            self.progress('PROBE')
            self.probe(self.root, p.version, self.public_key)
            if self.cancel.is_set(): raise UpdateError('Update cancelled.')
            self.prepared_version = p.version
            self.status = AppUpdateStatus('STAGED', status.play_allowed, True)
        except Exception as exc:
            cancelled = self.cancel.is_set()
            if not cancelled and self.policy:
                with self.store.locked(): self.store.mark_failed(self.policy.payload_sha256)
            self.status = AppUpdateStatus('CANCELLED' if cancelled else 'ERROR', status.play_allowed, False, str(exc))
        finally:
            if archive is not None: archive.unlink(missing_ok=True)
        return self.status

    def check_and_prepare(self):
        status = self.check()
        return self.prepare() if status.state in ('AVAILABLE', 'REQUIRED') else status

    def require_play_allowed(self):
        status = self.check()
        if not status.play_allowed:
            raise UpdateError('\u041f\u0435\u0440\u0435\u0434 \u0438\u0433\u0440\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0438 \u043e\u0431\u043d\u043e\u0432\u0438\u0442\u0435 \u0441\u0430\u043c \u043b\u0430\u0443\u043d\u0447\u0435\u0440.')

    def request_restart(self):
        status = self.check()
        if not status.restart_ready or not self.policy: raise UpdateError('Launcher update is not ready.')
        version = self.policy.version
        verify_installed(self.root, version, self.public_key)
        current_exe = version_dir(self.root, self.version) / 'BC2Client.exe'
        import sys
        if os.path.normcase(str(current_exe)) != os.path.normcase(os.path.abspath(sys.executable)):
            raise UpdateError('Restart must originate from the installed launcher.')
        token = secrets.token_hex(32)
        ack = inside(self.root, 'cache', 'handoff-' + token + '.json')
        command = [str(inside(self.root, 'BC2Launcher.exe')), '--apply', version,
                   '--wait-pid', str(os.getpid()), '--handoff-token', token]
        if '--smoke-startup' in sys.argv: command.append('--smoke-startup')
        self.bootstrap_process = subprocess.Popen(command, cwd=self.root, shell=False,
                                                 creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 90
        try:
            while time.monotonic() < deadline:
                if self.bootstrap_process.poll() is not None: raise UpdateError('Bootstrap did not accept restart.')
                if ack.is_file():
                    if ack.stat().st_size > 4096: raise UpdateError('Invalid restart acknowledgement.')
                    p = _json(ack.read_bytes())
                    if p != {'ready': True, 'nonce': token}: raise UpdateError('Invalid restart acknowledgement.')
                    self.status = AppUpdateStatus('RESTARTING', False, False)
                    return self.status
                time.sleep(.05)
            raise UpdateError('Bootstrap restart timed out. The current launcher remains open.')
        finally: ack.unlink(missing_ok=True)
