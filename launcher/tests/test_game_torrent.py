import tempfile
import hashlib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import libtorrent as lt

from bc2launcher.game_install import FileRecord, InstallPaths
from bc2launcher.game_torrent import download
from bc2launcher.manifest import UpdateError


class TorrentTests(unittest.TestCase):
    def test_completed_transfer_does_not_depend_on_a_disk_alert(self):
        status = Mock(errc=Mock(value=Mock(return_value=0)), state=lt.torrent_status.seeding,
                      total_wanted_done=40000, is_seeding=True, download_payload_rate=0)
        handle = Mock(status=Mock(return_value=status))
        session = Mock(add_torrent=Mock(return_value=handle), pop_alerts=Mock(return_value=[]))
        profile = SimpleNamespace(download_size=40000)
        paths = SimpleNamespace(payload=Path('payload'))
        info = lt.torrent_info(lt.sha1_hash(b'0' * 20))
        events = []
        with patch('bc2launcher.game_torrent._read_info', return_value=info), \
             patch('bc2launcher.game_torrent.lt.session', return_value=session), \
             patch('bc2launcher.game_torrent.time.monotonic', side_effect=[0, 0, 0, 0, 31]):
            download(profile, paths, progress=events.append, cancelled=lambda: False)
        self.assertEqual(events[-1].phase, 'FINALIZE_DOWNLOAD')
        session.remove_torrent.assert_called_once_with(handle)

    def test_download_completes_partial_file_from_loopback_peer(self):
        settings = dict(listen_interfaces='127.0.0.1:0', enable_dht=False, enable_lsd=False,
                        enable_upnp=False, enable_natpmp=False,
                        alert_mask=int(lt.alert.category_t.storage_notification))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seed_path = root / 'seed'
            seed_path.mkdir()
            content = bytes(range(256)) * 300
            (seed_path / 'setup.exe').write_bytes(content)
            storage = lt.file_storage()
            storage.add_file('setup.exe', len(content))
            creator = lt.create_torrent(storage, 16384, lt.create_torrent.v1_only)
            lt.set_piece_hashes(creator, str(seed_path))
            raw = lt.bencode(creator.generate())
            info = lt.torrent_info(raw)
            paths = InstallPaths.from_library(root)
            paths.payload.mkdir(parents=True)
            (paths.payload / 'setup.exe').write_bytes(content[:16384])
            (paths.cache / 'source.torrent').write_bytes(raw)
            profile = SimpleNamespace(info_hash=str(info.info_hashes().v1),
                torrent_sha256=hashlib.sha256(raw).hexdigest(),
                package=(FileRecord('setup.exe', len(content), ''),), download_size=len(content))
            make_session = lt.session
            seed = make_session(settings)
            params = lt.add_torrent_params()
            params.ti = info
            params.save_path = str(seed_path)
            params.flags = ((params.flags | lt.torrent_flags.seed_mode)
                            & ~(lt.torrent_flags.auto_managed | lt.torrent_flags.paused))
            seed_handle = seed.add_torrent(params)
            class LocalSession:
                def __init__(self, options):
                    self.session = make_session(options)
                def add_torrent(self, args):
                    handle = self.session.add_torrent(args)
                    handle.connect_peer(('127.0.0.1', seed.listen_port()))
                    return handle
                def __getattr__(self, name):
                    return getattr(self.session, name)
            from time import monotonic
            deadline = monotonic() + 15
            progress = []
            try:
                with patch('bc2launcher.game_torrent.session_settings', return_value=settings), \
                     patch('bc2launcher.game_torrent.lt.session', LocalSession):
                    download(profile, paths, progress=progress.append, cancelled=lambda: monotonic() > deadline)
                self.assertEqual((paths.payload / 'setup.exe').read_bytes(), content)
                self.assertEqual(progress[-2].downloaded, len(content))
            finally:
                seed.remove_torrent(seed_handle)

    def test_rechecks_complete_payload_without_network_and_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = InstallPaths.from_library(Path(folder))
            paths.payload.mkdir(parents=True)
            (paths.payload / 'setup.exe').write_bytes(b'x' * 40000)
            storage = lt.file_storage()
            storage.add_file('setup.exe', 40000)
            creator = lt.create_torrent(storage, 16384, lt.create_torrent.v1_only)
            lt.set_piece_hashes(creator, str(paths.payload))
            raw = lt.bencode(creator.generate())
            (paths.cache / 'source.torrent').write_bytes(raw)
            info = lt.torrent_info(str(paths.cache / 'source.torrent'))
            profile = SimpleNamespace(info_hash=str(info.info_hashes().v1), torrent_sha256=hashlib.sha256(raw).hexdigest(),
                                      package=(FileRecord('setup.exe', 40000, ''),), download_size=40000)
            progress = []
            with patch('bc2launcher.game_torrent.session_settings', return_value={
                'listen_interfaces':'127.0.0.1:0', 'enable_dht':False, 'enable_lsd':False,
                'enable_upnp':False, 'enable_natpmp':False,
                'alert_mask':int(lt.alert.category_t.storage_notification)}):
                download(profile, paths, progress=progress.append, cancelled=lambda: False)
                with self.assertRaises(UpdateError):
                    download(profile, paths, progress=progress.append, cancelled=lambda: True)
            self.assertEqual(progress[-2].downloaded, 40000)
            self.assertEqual((paths.payload / 'setup.exe').stat().st_size, 40000)

    def test_rejects_mismatched_torrent_before_starting_session(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = InstallPaths.from_library(Path(folder))
            paths.cache.mkdir(parents=True)
            (paths.cache / 'source.torrent').write_bytes(b'invalid')
            with patch('bc2launcher.game_torrent.lt.session') as session:
                with self.assertRaises(UpdateError):
                    download(SimpleNamespace(torrent_sha256='0' * 64), paths, progress=lambda x:None, cancelled=lambda:False)
                session.assert_not_called()
