import argparse
import json
import re
import sys
from pathlib import Path


def main():
    from bc2launcher.selfupdate import BOOTSTRAP_VERSION
    from bc2launcher.manifest import UpdateError
    from bc2launcher.selfupdate.store import UpdateStore
    from bc2launcher.selfupdate.bootstrap import activate, start_active, install_seed
    from bc2launcher.selfupdate.paths import inside
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report')
    parser.add_argument('--apply')
    parser.add_argument('--install-seed')
    parser.add_argument('--wait-pid', type=int)
    parser.add_argument('--handoff-token')
    parser.add_argument('--smoke-startup', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--check-destination')
    parser.add_argument('--seed-version')
    parser.add_argument('--seed-inventory')
    parser.add_argument('--uninstall-data', action='store_true')
    args = parser.parse_args()
    assets = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'
    key = (assets / 'public-key.bin').read_bytes()
    Ed25519PublicKey.from_public_bytes(key)
    if args.self_test:
        result = dict(ok=True, bootstrap_version=BOOTSTRAP_VERSION, public_key_ok=True)
        if args.report: Path(args.report).write_text(json.dumps(result), encoding='utf-8')
        if sys.stdout: print(json.dumps(result))
        return 0
    if not getattr(sys, 'frozen', False):
        raise UpdateError('Use the packaged bootstrap for an installed launcher.')
    root = Path(sys.executable).absolute().parent
    if args.check_destination:
        from bc2launcher.selfupdate.install import check_destination
        check_destination(args.check_destination,args.seed_version,args.seed_inventory)
        return 0
    if args.uninstall_data:
        from bc2launcher.selfupdate.install import cleanup_versions
        cleanup_versions(root)
        return 0
    def handoff():
        token = args.handoff_token
        if token is not None:
            if not re.fullmatch('[0-9a-f]{64}', token): raise UpdateError('Invalid handoff token.')
            UpdateStore(inside(root, 'cache')).write_json('handoff-' + token + '.json', dict(ready=True, nonce=token))
    if args.install_seed:
        install_seed(root, args.install_seed, key)
    elif args.apply:
        activate(root, args.apply, wait_pid=args.wait_pid, public_key=key,
                 on_handoff=handoff, smoke=args.smoke_startup)
    else:
        if args.wait_pid or args.handoff_token: raise UpdateError('Unexpected bootstrap arguments.')
        start_active(root, key, smoke=args.smoke_startup)
    return 0


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as exc:
        # A failed bootstrap must remain usable without Qt or the GUI package.
        if '--smoke-startup' not in sys.argv and '--quiet' not in sys.argv and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                '\u041b\u0430\u0443\u043d\u0447\u0435\u0440 \u043d\u0435 \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u043b\u0441\u044f. \u0417\u0430\u043a\u0440\u043e\u0439\u0442\u0435 \u0434\u0440\u0443\u0433\u0438\u0435 \u043e\u043a\u043d\u0430 \u043b\u0430\u0443\u043d\u0447\u0435\u0440\u0430 \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0437\u0430\u043f\u0443\u0441\u043a.\n\n' + str(exc),
                'BC2 Launcher', 0x10)
        raise SystemExit(1)
