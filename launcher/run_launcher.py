import json
import sys
from pathlib import Path


def main():
    assets=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets'
    if '--self-test' in sys.argv:
        from bc2launcher import VERSION
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes((assets/'public-key.bin').read_bytes())
        for name in ['valparaiso-original.png','Oswald.ttf','Manrope.ttf']:
            if not (assets/name).is_file():raise RuntimeError('Missing resource: '+name)
        result=dict(version=VERSION,resources_ok=True)
        if '--report' in sys.argv:Path(sys.argv[sys.argv.index('--report')+1]).write_text(json.dumps(result),encoding='utf-8')
        if sys.stdout: print(json.dumps(result))
        return 0
    from bc2launcher.ui import run
    return run(assets)


if __name__=='__main__': raise SystemExit(main())
