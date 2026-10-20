import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from selfupdate_helpers import KEY,PUBLIC,NOW
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.policy import verify_inventory,verify_policy

tool_path=Path(__file__).resolve().parents[2]/'tools'/'package_launcher.py'
spec=importlib.util.spec_from_file_location('package_launcher',tool_path)
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)


class PackagingTests(unittest.TestCase):
    def test_package_is_signed_complete_deterministic_and_separate_from_game(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);client=root/'client';client.mkdir()
            (client/'BC2Client.exe').write_bytes(b'MZnot executed')
            (client/'_internal').mkdir();(client/'_internal'/'runtime.dll').write_bytes(b'library')
            first=root/'a.zip';second=root/'b.zip'
            tool.package_launcher(client,'0.2.0',first,KEY)
            tool.package_launcher(client,'0.2.0',second,KEY)
            self.assertEqual(first.read_bytes(),second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                inv=verify_inventory(archive.read('.launcher-package.json'),PUBLIC)
                self.assertEqual({f.path for f in inv.files},{'BC2Client.exe','_internal/runtime.dll'})
                self.assertIsNone(archive.testzip())
            policy=tool.sign_launcher_policy(first,'0.2.0','https://github.com/RinatBy/bc2-community/releases/download/test/app.zip',
                                             1,KEY,NOW,minimum='0.2.0')
            self.assertEqual(verify_policy(policy,PUBLIC,NOW,0).artifact.size,first.stat().st_size)

    def test_private_keys_settings_and_reused_version_are_rejected(self):
        for secret in ('secret.key','settings.json','database.db'):
            with self.subTest(secret=secret),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'BC2Client.exe').write_bytes(b'MZ');(root/secret).write_bytes(b'private')
                with self.assertRaises(UpdateError):tool.package_launcher(root,'0.2.0',root.parent/'never.zip',KEY)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);client=root/'client';client.mkdir();(client/'BC2Client.exe').write_bytes(b'MZ')
            tool.package_launcher(client,'0.2.0',root/'a.zip',KEY)
            (client/'BC2Client.exe').write_bytes(b'changed')
            with self.assertRaises(UpdateError):tool.package_launcher(client,'0.2.0',root/'b.zip',KEY)
