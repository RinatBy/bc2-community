import unittest
import tempfile
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from release import sign_package, rollback_payload
from bc2launcher.manifest import verify_manifest
from helpers import KEY,PUBLIC,NOW,DLL,INI


class ReleaseTests(unittest.TestCase):
    def test_sign_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'dinput8.dll').write_bytes(DLL); (p/'bfbc2.ini').write_bytes(INI)
            raw=sign_package(p,'https://github.com/RinatBy/bc2-community/releases/download/v0.1.0',1,'v0.1.0',KEY,NOW)
            original=verify_manifest(raw,PUBLIC,NOW,0)
            restored=rollback_payload(original,2,KEY,NOW)
            new=verify_manifest(restored,PUBLIC,NOW,1)
            self.assertEqual(new.package_id,original.package_id)
            self.assertEqual(new.assets,original.assets)
            self.assertEqual(new.revision,2)
