import tempfile
import unittest
from pathlib import Path
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.install import check_destination,cleanup_versions
from bc2launcher.selfupdate.store import UpdateStore


class InstallTests(unittest.TestCase):
    def test_existing_game_or_unrelated_folder_is_never_install_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'BFBC2Game.exe').write_bytes(b'MZ')
            with self.assertRaises(UpdateError):check_destination(root)
            (root/'BFBC2Game.exe').unlink();(root/'personal.txt').write_bytes(b'keep')
            with self.assertRaises(UpdateError):check_destination(root)
            self.assertEqual((root/'personal.txt').read_bytes(),b'keep')

    def test_uninstall_only_removes_own_version_and_cache_preserves_external_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'app';root.mkdir()
            UpdateStore(root).write_json('installation.json',dict(schema=1,product='BC2Launcher'))
            (root/'versions'/'0.2.0').mkdir(parents=True);(root/'versions'/'0.2.0'/'BC2Client.exe').write_bytes(b'MZ')
            (root/'cache').mkdir();(root/'cache'/'download.tmp').write_bytes(b'cache')
            settings=base/'settings.json';settings.write_bytes(b'preserve game path')
            check_destination(root);cleanup_versions(root)
            self.assertFalse((root/'versions').exists());self.assertFalse((root/'cache').exists())
            self.assertEqual(settings.read_bytes(),b'preserve game path')
