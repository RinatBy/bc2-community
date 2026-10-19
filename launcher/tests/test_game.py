import unittest
import tempfile
import stat
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from bc2launcher.game import validate_game_dir, merge_connection_ini, read_managed_ini
from bc2launcher.manifest import UpdateError, HOST
from helpers import INI


class GameTests(unittest.TestCase):
    def test_folder(self):
        with tempfile.TemporaryDirectory(prefix='BC2 тест ') as d:
            with self.assertRaises(UpdateError): validate_game_dir(Path(d))
            (Path(d)/'BFBC2Game.exe').write_bytes(b'MZ' + b'\0'*64)
            self.assertEqual(validate_game_dir(Path(d)).root, Path(d).resolve())

    def test_preserve_settings_crlf_and_comments(self):
        old = b'[info]\r\nhost=1.2.3.4\r\nconnect_to_retail=1\r\n; note\r\nshow_console=1\r\n[server]\r\nunlimited_ammo=0\r\n'
        new = merge_connection_ini(old, INI, HOST)
        self.assertIn(b'host=master.bc2.uplay2.ru\r\n', new)
        self.assertIn(b'; note\r\nshow_console=1', new)
        self.assertIn(b'unlimited_ammo=0', new)
        self.assertEqual(read_managed_ini(new), (HOST, '0'))

    def test_create_and_missing_section(self):
        self.assertEqual(read_managed_ini(merge_connection_ini(None, INI, HOST)), (HOST,'0'))
        self.assertEqual(read_managed_ini(merge_connection_ini(b'[client]\nfoo=bar\n', INI, HOST)),(HOST,'0'))

    def test_bad_ini(self):
        for b in [b'[info]\nhost=a\nhost=b\n', b'[info]\n[info]\n']:
            with self.assertRaises(UpdateError): merge_connection_ini(b, INI, HOST)

    def test_junction_attribute_is_rejected(self):
        from bc2launcher.game import safe_path
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); child=root/'state'; child.mkdir()
            original=Path.lstat
            def attributes(p,*a,**kw):
                if p==child:return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
                return original(p,*a,**kw)
            with patch.object(Path,'lstat',attributes):
                with self.assertRaises(UpdateError):safe_path(root,child/'file')
