import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bc2launcher.manifest import UpdateError
from bc2launcher.game_install import GameInstallService, InstallPaths, InstallProfile, InstallProgress, run_uninstall


def entry(name, data):
    return dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())


class GameInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.library = root / 'Игры тест'
        self.library.mkdir()
        assets = root / 'assets'
        assets.mkdir()
        (assets / 'source.torrent').write_bytes(b'fixture')
        self.setup = b'fake installer'
        self.game = {'BFBC2Game.exe': b'MZfixture', 'Package/level.bin': b'level bytes'}
        data = dict(schema=1, torrent_sha256=hashlib.sha256(b'fixture').hexdigest(),
                    info_hash='0' * 40, setup='Package Source/setup.exe',
                    package=[entry('Package Source/setup.exe', self.setup)],
                    game=[entry(name, value) for name, value in self.game.items()],
                    extra_space=1024)
        (assets / 'profile.json').write_text(json.dumps(data), encoding='utf-8')
        self.profile = InstallProfile.load(assets)
        self.paths = InstallPaths.from_library(self.library)
        self.executions = []

    def download(self, profile, paths, *, progress, cancelled):
        path = paths.payload / 'Package Source/setup.exe'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.setup)

    def setup_ok(self, exe, dest, log, *, on_tick):
        self.executions.append(exe)
        for name, data in self.game.items():
            file = dest / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
            on_tick()

    def service(self, setup=None):
        return GameInstallService(self.profile, download=self.download, setup=setup or self.setup_ok)

    def test_uninstall_uses_the_selected_games_native_wizard(self):
        folder = self.paths.game / 'Uninstall'
        folder.mkdir(parents=True)
        (self.paths.game / 'BFBC2Game.exe').write_bytes(self.game['BFBC2Game.exe'])
        exe = folder / 'unins000.exe'
        exe.write_bytes(b'MZfixture')
        exe.with_suffix('.dat').write_bytes(b'fixture')
        with patch('bc2launcher.game_install.ensure_game_closed') as closed, \
             patch('bc2launcher.game_install.subprocess.run') as start:
            start.return_value.returncode = 0
            self.assertTrue(run_uninstall(self.paths.game))
            closed.assert_called_once_with()
            start.assert_called_once_with([str(exe)], cwd=folder, shell=False, check=False)
            closed.side_effect = UpdateError('Game is running')
            start.reset_mock()
            with self.assertRaises(UpdateError):
                run_uninstall(self.paths.game)
            start.assert_not_called()

    def test_install_uses_exact_verified_setup_and_cleans_only_own_cache(self):
        unrelated = self.library / 'keep.txt'
        unrelated.write_text('keep')
        service = self.service()
        progress = []
        service.progress = progress.append
        result = service.install(self.library)
        self.assertEqual(self.executions, [self.paths.payload / 'Package Source/setup.exe'])
        self.assertEqual(result.game_dir, self.paths.game)
        self.assertIn(InstallProgress('SETUP', len(self.game['BFBC2Game.exe']), sum(map(len,self.game.values()))), progress)
        self.assertEqual(progress[-1].phase, 'VERIFY_GAME')
        self.assertTrue(self.paths.cache.is_dir())
        service.cleanup(result)
        self.assertFalse(self.paths.cache.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual((self.paths.game / 'BFBC2Game.exe').read_bytes(), self.game['BFBC2Game.exe'])

    def test_bad_package_does_not_launch_setup(self):
        service = self.service()
        self.setup = b'X' * len(self.setup)
        with self.assertRaises(UpdateError):
            service.install(self.library)
        self.assertEqual(self.executions, [])
        self.assertFalse(self.paths.game.exists())

    def test_reinstall_reuses_verified_cache_and_only_requires_space_for_game(self):
        service = self.service()
        result = service.install(self.library)
        for name in self.game:
            (self.paths.game / name).unlink()
        (self.paths.game / 'Package').rmdir()
        self.paths.game.rmdir()
        self.assertTrue((self.paths.cache / 'installed.json').is_file())
        with patch.object(service, 'download') as download, patch(
                'bc2launcher.game_install.shutil.disk_usage', return_value=(0, 0, self.profile.game_space)):
            second = service.install(self.library)
        download.assert_not_called()
        self.assertEqual(second.game_dir, result.game_dir)
        self.assertEqual(len(self.executions), 2)
        self.assertTrue(self.paths.cache.is_dir())
        service.cleanup(second)
        self.assertFalse(self.paths.cache.exists())

    def test_reinstall_repairs_damaged_cache_before_setup(self):
        service = self.service()
        service.install(self.library)
        for name in self.game:
            (self.paths.game / name).unlink()
        (self.paths.game / 'Package').rmdir()
        self.paths.game.rmdir()
        payload = self.paths.payload / 'Package Source/setup.exe'
        payload.write_bytes(b'X' * len(self.setup))
        with patch.object(service, 'download', wraps=self.download) as download:
            service.install(self.library)
        download.assert_called_once()
        self.assertEqual(payload.read_bytes(), self.setup)
        self.assertEqual(len(self.executions), 2)

    def test_failed_result_preserves_cache_and_cannot_clean(self):
        service = self.service(lambda exe, dest, log, **kwargs: None)
        with self.assertRaises(UpdateError):
            service.install(self.library)
        self.assertTrue(self.paths.cache.is_dir())
        self.assertFalse((self.paths.cache / 'installed.json').exists())

    def test_refuses_unowned_cache_and_occupied_game(self):
        self.paths.cache.mkdir(parents=True)
        with self.assertRaises(UpdateError):
            self.service().install(self.library)
        self.paths.cache.rmdir()
        self.paths.game.mkdir()
        (self.paths.game / 'keep.txt').write_text('keep')
        with self.assertRaises(UpdateError):
            self.service().install(self.library)
        self.assertFalse(self.paths.cache.exists())

    def test_refuses_game_library_inside_launcher_installation(self):
        launcher = self.library / 'BC2Launcher'
        client = launcher / 'versions' / '0.2.5'
        client.mkdir(parents=True)
        (launcher / 'BC2Launcher.exe').touch()
        (launcher / 'installation.json').write_text('{"schema":1,"product":"BC2Launcher"}')
        for path in (launcher, client):
            with self.subTest(path=path), self.assertRaisesRegex(UpdateError, 'папку лаунчера'):
                InstallPaths.from_library(path)

    def test_not_enough_space_leaves_no_job(self):
        with patch('bc2launcher.game_install.shutil.disk_usage', return_value=(100, 100, 0)):
            with self.assertRaises(UpdateError):
                self.service().install(self.library)
        self.assertFalse(self.paths.cache.exists())

    def test_cleanup_refuses_unexpected_file_or_changed_game(self):
        service = self.service()
        result = service.install(self.library)
        extra = self.paths.cache / 'my-files.txt'
        extra.write_text('mine')
        with self.assertRaises(UpdateError):
            service.cleanup(result)
        self.assertTrue(extra.exists())
        extra.unlink()
        (self.paths.game / 'Package/level.bin').write_bytes(b'x' * len(self.game['Package/level.bin']))
        with self.assertRaises(UpdateError):
            service.cleanup(result)
        self.assertTrue(self.paths.cache.exists())

    def test_cancel_preserves_owned_cache_for_retry(self):
        service = self.service()
        def download(*args, **kwargs):
            self.download(*args, **kwargs)
            service.cancel.set()
        service.download = download
        with self.assertRaises(UpdateError):
            service.install(self.library)
        self.assertTrue(self.paths.cache.is_dir())
        self.assertEqual(self.executions, [])
        service.cancel.clear()
        service.download = self.download
        self.assertEqual(service.install(self.library).game_dir, self.paths.game)
