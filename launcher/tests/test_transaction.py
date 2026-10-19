import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bc2launcher.transaction import install_bytes, restore_backup, recover_interrupted, list_backups
from bc2launcher.manifest import UpdateError


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'BFBC2Game.exe').write_bytes(b'MZ'+b'\0'*64)
        (self.root/'dinput8.dll').write_bytes(b'old')
        self.new = {'dinput8.dll':b'new', 'bfbc2.ini':b'new ini'}

    def test_install_and_rollback_absent_file(self):
        b = install_bytes(self.root, self.new, 'test')
        self.assertEqual((self.root/'dinput8.dll').read_bytes(), b'new')
        restore_backup(self.root, b)
        self.assertEqual((self.root/'dinput8.dll').read_bytes(), b'old')
        self.assertFalse((self.root/'bfbc2.ini').exists())

    def test_unsafe_names_and_symlinks(self):
        with self.assertRaises(UpdateError): install_bytes(self.root, {'../escape':b'x'}, 'x')
        target=self.root/'outside'; target.write_bytes(b'x')
        (self.root/'dinput8.dll').unlink()
        try: (self.root/'dinput8.dll').symlink_to(target)
        except OSError: self.skipTest('Windows symlink privilege unavailable')
        with self.assertRaises(UpdateError): install_bytes(self.root,self.new,'test')

    def test_second_replace_failure_rolls_back(self):
        import bc2launcher.transaction as t
        original=t._replace_target
        def fail(path,data):
            if path.name=='bfbc2.ini' and data==b'new ini': raise OSError('locked')
            original(path,data)
        with patch.object(t,'_replace_target',side_effect=fail):
            with self.assertRaises(UpdateError): install_bytes(self.root,self.new,'test')
        self.assertEqual((self.root/'dinput8.dll').read_bytes(),b'old')
        self.assertFalse((self.root/'bfbc2.ini').exists())

    def test_interrupt_each_commit_phase(self):
        import bc2launcher.transaction as t
        for count in [0,1,2]:
            with self.subTest(count=count):
                if (self.root/'bfbc2.ini').exists(): (self.root/'bfbc2.ini').unlink()
                (self.root/'dinput8.dll').write_bytes(b'old')
                def phase(n):
                    if n==count: raise KeyboardInterrupt()
                with patch.object(t,'_checkpoint',side_effect=phase):
                    with self.assertRaises(KeyboardInterrupt): install_bytes(self.root,self.new,'test')
                recover_interrupted(self.root)
                recover_interrupted(self.root)
                self.assertEqual((self.root/'dinput8.dll').read_bytes(),b'old')
                self.assertFalse((self.root/'bfbc2.ini').exists())

    def test_corrupt_backup_rejected_before_writes(self):
        b=install_bytes(self.root,self.new,'test')
        (self.root/'.bc2-launcher'/'backups'/b/'dinput8.dll').write_bytes(b'bad')
        with self.assertRaises(UpdateError): restore_backup(self.root,b)
        self.assertEqual((self.root/'dinput8.dll').read_bytes(),b'new')

    def test_parallel_operation_is_blocked(self):
        from bc2launcher.transaction import game_lock
        with game_lock(self.root):
            with self.assertRaises(UpdateError):
                install_bytes(self.root,self.new,'parallel')

    def test_game_running_blocks_write(self):
        with patch('bc2launcher.transaction.ensure_game_closed',side_effect=UpdateError('game running')):
            with self.assertRaises(UpdateError): install_bytes(self.root,self.new,'x')
        self.assertEqual((self.root/'dinput8.dll').read_bytes(),b'old')
