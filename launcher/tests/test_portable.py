import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from selfupdate_helpers import KEY, PUBLIC
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.package import verify_installed

ROOT = Path(__file__).resolve().parents[2]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PortableTests(unittest.TestCase):
    def seed(self, root):
        seed = root / 'seed'
        client = seed / 'versions' / '0.2.2'
        client.mkdir(parents=True)
        (client / 'BC2Client.exe').write_bytes(b'MZ fixture, never executed')
        load_tool('package_launcher').package_launcher(client, '0.2.2', root / 'app.zip', KEY)
        (seed / 'BC2Launcher.exe').write_bytes(b'MZ bootstrap fixture')
        (seed / 'installation.json').write_text('{"schema":1,"product":"BC2Launcher"}')
        return seed

    def test_portable_has_fixed_entry_and_verified_active_version_without_installer(self):
        portable = load_tool('package_portable')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed = self.seed(root)
            original = sorted(p.relative_to(seed).as_posix() for p in seed.rglob('*'))
            output = root / 'portable.zip'
            portable.package_portable(seed, '0.2.2', output, PUBLIC)
            with zipfile.ZipFile(output) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn('BC2Launcher/BC2Launcher.exe', archive.namelist())
                active = json.loads(archive.read('BC2Launcher/active.json'))
                self.assertEqual(active, {'schema': 1, 'version': '0.2.2'})
                self.assertNotIn('BC2Launcher/cache/client.lock', archive.namelist())
                archive.extractall(root / 'unpacked')
            verify_installed(root / 'unpacked' / 'BC2Launcher', '0.2.2', PUBLIC)
            self.assertEqual(original, sorted(p.relative_to(seed).as_posix() for p in seed.rglob('*')))

    def test_portable_refuses_unexpected_or_modified_seed_files(self):
        portable = load_tool('package_portable')
        for bad in ('settings.json', 'versions/0.2.2/BC2Client.exe'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                seed = self.seed(root)
                (seed / bad).write_text('private or modified')
                with self.assertRaises(UpdateError):
                    portable.package_portable(seed, '0.2.2', root / 'bad.zip', PUBLIC)
                self.assertFalse((root / 'bad.zip').exists())

    def test_existing_archive_is_not_deleted_or_overwritten(self):
        portable = load_tool('package_portable')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed = self.seed(root)
            output = root / 'existing.zip'
            output.write_bytes(b'previous download')
            with self.assertRaises((UpdateError, FileExistsError)):
                portable.package_portable(seed, '0.2.2', output, PUBLIC)
            self.assertEqual(output.read_bytes(), b'previous download')
