import hashlib
import io
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from selfupdate_helpers import make_archive, policy_payload, inventory_payload, signed, PUBLIC, NOW
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.policy import verify_policy
from bc2launcher.selfupdate.package import stage_package, verify_installed, verify_prepared


class PackageTests(unittest.TestCase):
    def stage(self, root, data, p=None, cancelled=lambda:False):
        archive=root/'download.zip'; archive.write_bytes(data)
        policy=verify_policy(signed(p or policy_payload(archive=data)),PUBLIC,NOW,0)
        return stage_package(archive,policy,root,PUBLIC,cancelled=cancelled)

    def test_verified_version_is_new_and_old_active_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='bc2 \u0442\u0435\u0441\u0442 ') as folder:
            root=Path(folder); (root/'active.json').write_bytes(b'old-pointer')
            target=self.stage(root,make_archive())
            self.assertEqual(target,root/'versions'/'0.2.1')
            self.assertEqual((target/'BC2Client.exe').read_bytes(),b'MZtest')
            self.assertEqual((root/'active.json').read_bytes(),b'old-pointer')
            self.assertEqual(verify_installed(root,'0.2.1',PUBLIC).version,'0.2.1')
            self.assertEqual(self.stage(root,make_archive()),target)
            (target/'BC2Client.exe').write_bytes(b'MZevil')
            with self.assertRaises(UpdateError):verify_installed(root,'0.2.1',PUBLIC)
            with self.assertRaises(UpdateError):self.stage(root,make_archive())

    def test_malicious_zip_names_never_write_outside_new_version(self):
        bad_names=['../outside','/absolute','C:/outside','\\\\server/share','dir\\escape',
                   'file:stream','CON','folder/NUL.txt','name.','name ','BC2CLIENT.exe',
                   '_internal/../escape','_internal/lib.dll']
        for name in bad_names:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                root=Path(folder); (root/'active.json').write_bytes(b'unchanged')
                with self.assertRaises(UpdateError):self.stage(root,make_archive(extra=[(name,b'evil')]))
                self.assertFalse((root/'versions'/'0.2.1').exists())
                self.assertEqual((root/'active.json').read_bytes(),b'unchanged')

    def test_invalid_inventory_hash_archive_hash_and_missing_files(self):
        wrong=inventory_payload(); wrong['files'][0]['sha256']='0'*64
        fixtures=[make_archive(inventory=wrong),make_archive(version='0.2.0'),
                  make_archive(extra=[('unexpected.dll',b'evil')])]
        for data in fixtures:
            with self.subTest(size=len(data)),tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(UpdateError):self.stage(Path(folder),data)
        with tempfile.TemporaryDirectory() as folder:
            p=policy_payload();p['artifact']['size']=len(make_archive())
            with self.assertRaises(UpdateError):self.stage(Path(folder),make_archive(),p)

    def test_zip_symlink_and_compression_limits_rejected(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            z.writestr('.launcher-package.json',signed(inventory_payload()))
            info=zipfile.ZipInfo('BC2Client.exe');info.create_system=3
            info.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(info,b'outside')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(UpdateError):self.stage(Path(folder),stream.getvalue())
        data=bytearray(make_archive()); offset=data.rfind(b'PK\x05\x06')
        struct.pack_into('<H',data,offset+10,9000)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(UpdateError):self.stage(Path(folder),bytes(data))

    def test_cancellation_write_failure_and_size_limit_leave_active_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'active.json').write_bytes(b'A')
            with self.assertRaises(UpdateError):self.stage(root,make_archive(),cancelled=lambda:True)
            with patch('bc2launcher.selfupdate.package.TOTAL_LIMIT',5):
                with self.assertRaises(UpdateError):self.stage(root,make_archive())
            with patch('bc2launcher.selfupdate.package.os.replace',side_effect=PermissionError('denied')):
                with self.assertRaises(UpdateError):self.stage(root,make_archive())
            self.assertEqual((root/'active.json').read_bytes(),b'A')
            self.assertFalse((root/'versions'/'0.2.1').exists())

    def test_existing_parent_reparse_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'versions').mkdir()
            target=root/'outside';target.mkdir()
            try:(root/'versions'/'0.2.1').symlink_to(target,target_is_directory=True)
            except OSError:self.skipTest('Windows symlink privilege unavailable')
            with self.assertRaises(UpdateError):self.stage(root,make_archive())
            self.assertEqual(list(target.iterdir()),[])

    def test_prepared_version_is_bound_to_the_verified_archive_not_only_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=make_archive();self.stage(root,data)
            policy=verify_policy(signed(policy_payload(archive=data)),PUBLIC,NOW,0)
            self.assertEqual(verify_prepared(root,policy,PUBLIC).version,'0.2.1')
            changed=policy_payload(revision=2,archive=b'different signed artifact')
            other=verify_policy(signed(changed),PUBLIC,NOW,0)
            with self.assertRaises(UpdateError):verify_prepared(root,other,PUBLIC)
