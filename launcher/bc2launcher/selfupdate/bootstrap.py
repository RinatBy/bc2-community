from dataclasses import dataclass
from datetime import datetime, timezone
from ..manifest import UpdateError
from .paths import inside, validate_version, version_dir
from .policy import verify_policy, _digest
from .package import verify_installed, verify_prepared
from .process import probe_version, launch_verified, wait_for_old_process
from .store import UpdateStore


@dataclass(frozen=True)
class ActivationResult:
    version: str
    recovered: bool = False


def _checkpoint(name):
    pass


def _journal(store):
    p = store.read_json('activation.json')
    if p is None: return None
    try:
        if (not isinstance(p, dict) or set(p) != {'schema','previous','target','phase','digest'}
                or type(p['schema']) is not int or p['schema'] != 1 or p['phase'] not in ('pending','confirmed')):
            raise ValueError()
        validate_version(p['previous']); validate_version(p['target']); _digest(p['digest'])
        return p
    except (ValueError, TypeError, KeyError) as exc: raise UpdateError('Invalid activation journal. Reinstall launcher.') from exc


def _recover(store, public_key):
    journal = _journal(store)
    if journal is not None:
        version = journal['target'] if journal['phase'] == 'confirmed' else journal['previous']
        verify_installed(store.root, version, public_key)
        if journal['phase'] == 'pending': store.mark_failed(journal['digest'])
        else: store.write_json('previous.json', dict(schema=1, version=journal['previous']))
        store.set_active(version)
        inside(store.root, 'activation.json').unlink()
    active = store.active()
    verify_installed(store.root, active, public_key)
    return active


def recover_activation(root, public_key):
    store = UpdateStore(root)
    with store.locked():
        with store.locked('client.lock'): return _recover(store, public_key)


def _target_policy(store, version, key, now):
    path = inside(store.root, 'launcher-policy.json')
    if not path.is_file() or path.stat().st_size > 262144: raise UpdateError('No verified launcher policy to activate.')
    saved = store.load()
    p = verify_policy(path.read_bytes(), key, now, saved['highest_revision'])
    if p.payload_sha256 != saved['payload_sha256'] or p.version != version:
        raise UpdateError('Activation does not match accepted policy.')
    return p


def _start_and_confirm(root, version, key, smoke):
    child = launch_verified(root, version, key, smoke=smoke)
    try: child.wait_ready()
    except Exception: child.stop(); raise
    finally: child.close()


def activate(root, version, *, wait_pid=None, public_key, now=None, on_handoff=lambda: None, smoke=False):
    validate_version(version)
    now = now or datetime.now(timezone.utc)
    store = UpdateStore(root)
    with store.locked():
        if _journal(store) is not None: raise UpdateError('Recover the previous activation before updating.')
        previous = store.active()
        policy = _target_policy(store, version, public_key, now)
        verify_prepared(root, policy, public_key)
        if previous == version: raise UpdateError('Target launcher is already active.')
        probe_version(root, version, public_key)
        if wait_pid is not None:
            wait_for_old_process(wait_pid, version_dir(root, previous) / 'BC2Client.exe', on_open=on_handoff)
        else: on_handoff()
        with store.locked('client.lock'): pass
        journal = dict(schema=1, previous=previous, target=version, phase='pending', digest=policy.payload_sha256)
        store.write_json('activation.json', journal); _checkpoint('journal')
        store.set_active(version); _checkpoint('pointer')
        child = None
        try:
            child = launch_verified(root, version, public_key, smoke=smoke); _checkpoint('spawn')
            child.wait_ready(); _checkpoint('ready')
            journal['phase'] = 'confirmed'; store.write_json('activation.json', journal); _checkpoint('confirmed')
        except Exception:
            if child is not None: child.stop()
            _recover(store, public_key)
            _start_and_confirm(root, previous, public_key, smoke)
            return ActivationResult(previous, True)
        finally:
            if child is not None: child.close()
        store.write_json('previous.json', dict(schema=1, version=previous))
        inside(root, 'activation.json').unlink(); _checkpoint('cleanup')
        return ActivationResult(version)


def start_active(root, public_key, *, smoke=False):
    store = UpdateStore(root)
    with store.locked():
        with store.locked('client.lock'): pass
        version = _recover(store, public_key) if _journal(store) is not None else store.active()
        try:
            verify_installed(root, version, public_key)
            _start_and_confirm(root, version, public_key, smoke)
            return ActivationResult(version)
        except (UpdateError, OSError):
            previous = store.read_json('previous.json')
            if (not isinstance(previous, dict) or set(previous) != {'schema','version'}
                    or type(previous['schema']) is not int or previous['schema'] != 1): raise
            fallback = validate_version(previous['version'])
            if fallback == version: raise UpdateError('No previous working launcher is available.')
            verify_installed(root, fallback, public_key)
            state = store.load()
            if state['payload_sha256']: store.mark_failed(state['payload_sha256'])
            store.set_active(fallback)
            _start_and_confirm(root, fallback, public_key, smoke)
            return ActivationResult(fallback, True)


def install_seed(root, version, public_key):
    store = UpdateStore(root)
    with store.locked():
        verify_installed(root, version, public_key)
        store.write_json('installation.json', dict(schema=1, product='BC2Launcher'))
        if inside(root, 'active.json').exists():
            _recover(store, public_key)
        else: store.set_active(version)
    # A signed seed policy enables local testing before a public channel exists.
    seed = inside(root, 'seed-policy.json')
    if seed.is_file() and seed.stat().st_size <= 262144:
        try:p = verify_policy(seed.read_bytes(), public_key, datetime.now(timezone.utc), 0)
        except UpdateError:
            # The signed package remains usable; Play still needs a fresh valid policy.
            return
        if p.version != version: raise UpdateError('Seed policy version mismatch.')
        state = store.load()
        if p.revision > state['highest_revision']:
            store.accept(p)
            from ..transaction import atomic_write
            with store.locked():atomic_write(inside(root, 'launcher-policy.json'), seed.read_bytes())
