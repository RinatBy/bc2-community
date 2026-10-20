import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from selfupdate_helpers import make_archive, policy_payload, signed, PUBLIC, NOW
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.store import UpdateStore
from bc2launcher.selfupdate.package import stage_package
from bc2launcher.selfupdate.policy import verify_policy
from bc2launcher.selfupdate.bootstrap import activate, recover_activation, start_active, install_seed


class Crash(BaseException): pass


class FakeChild:
    stopped=False
    def wait_ready(self,timeout=30):pass
    def stop(self):self.stopped=True
    def close(self):pass


class BootstrapTests(unittest.TestCase):
    def setup_root(self,folder):
        root=Path(folder);store=UpdateStore(root)
        for version in ('0.2.0','0.2.1'):
            data=make_archive(version=version);archive=root/'app.zip';archive.write_bytes(data)
            p=policy_payload(version=version,archive=data)
            p['minimum_launcher_version']='0.2.0'
            policy=verify_policy(signed(p),PUBLIC,NOW,0)
            stage_package(archive,policy,root,PUBLIC)
        store.set_active('0.2.0');store.accept(policy)
        (root/'launcher-policy.json').write_bytes(signed(p))
        return root,store

    def test_activation_confirms_new_version_and_keeps_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            with patch('bc2launcher.selfupdate.bootstrap.probe_version'),patch('bc2launcher.selfupdate.bootstrap.launch_verified',return_value=FakeChild()):
                result=activate(root,'0.2.1',public_key=PUBLIC,now=NOW)
            self.assertEqual(store.active(),'0.2.1');self.assertEqual(result.version,'0.2.1')
            self.assertFalse((root/'activation.json').exists())
            self.assertTrue((root/'versions'/'0.2.0'/'BC2Client.exe').is_file())

    def test_failed_probe_changes_no_pointer(self):
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            with patch('bc2launcher.selfupdate.bootstrap.probe_version',side_effect=UpdateError('probe')):
                with self.assertRaises(UpdateError):activate(root,'0.2.1',public_key=PUBLIC,now=NOW)
            self.assertEqual(store.active(),'0.2.0')

    def test_missing_ready_stops_own_child_before_single_fallback(self):
        class NoReady(FakeChild):
            def wait_ready(self,timeout=30):raise UpdateError('no ready')
        bad=NoReady(); fallback=FakeChild();calls=[]
        def launch(root,version,key,**kwargs):
            calls.append(version)
            if version=='0.2.0':self.assertTrue(bad.stopped)
            return bad if version=='0.2.1' else fallback
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            with patch('bc2launcher.selfupdate.bootstrap.probe_version'),patch('bc2launcher.selfupdate.bootstrap.launch_verified',side_effect=launch):
                result=activate(root,'0.2.1',public_key=PUBLIC,now=NOW)
            self.assertTrue(result.recovered);self.assertEqual(store.active(),'0.2.0')
            self.assertEqual(calls,['0.2.1','0.2.0']);self.assertEqual(len(store.load()['failed']),1)

    def test_interruption_at_every_activation_boundary_recovers_idempotently(self):
        for boundary in ('journal','pointer','spawn','ready','confirmed','cleanup'):
            with self.subTest(boundary=boundary),tempfile.TemporaryDirectory() as folder:
                root,store=self.setup_root(folder)
                def checkpoint(name):
                    if name==boundary:raise Crash()
                with patch('bc2launcher.selfupdate.bootstrap.probe_version'),patch('bc2launcher.selfupdate.bootstrap.launch_verified',return_value=FakeChild()),patch('bc2launcher.selfupdate.bootstrap._checkpoint',side_effect=checkpoint):
                    with self.assertRaises(Crash):activate(root,'0.2.1',public_key=PUBLIC,now=NOW)
                expected='0.2.1' if boundary in ('confirmed','cleanup') else '0.2.0'
                self.assertEqual(recover_activation(root,PUBLIC),expected)
                self.assertEqual(recover_activation(root,PUBLIC),expected)

    def test_replayed_target_and_corrupt_previous_are_not_executed(self):
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            with self.assertRaises(UpdateError):activate(root,'0.2.0',public_key=PUBLIC,now=NOW)
            (root/'versions'/'0.2.0'/'BC2Client.exe').write_bytes(b'evil')
            store.write_json('activation.json',dict(schema=1,previous='0.2.0',target='0.2.1',phase='pending',digest='0'*64))
            with self.assertRaises(UpdateError):recover_activation(root,PUBLIC)

    def test_later_startup_failure_also_returns_previous_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            with patch('bc2launcher.selfupdate.bootstrap.probe_version'),patch('bc2launcher.selfupdate.bootstrap.launch_verified',return_value=FakeChild()):
                activate(root,'0.2.1',public_key=PUBLIC,now=NOW)
            calls=[]
            def launch(root,version,key,**kwargs):
                calls.append(version)
                if version=='0.2.1':raise UpdateError('startup failed later')
                return FakeChild()
            with patch('bc2launcher.selfupdate.bootstrap.launch_verified',side_effect=launch):
                result=start_active(root,PUBLIC)
            self.assertEqual(result.version,'0.2.0');self.assertTrue(result.recovered)
            self.assertEqual(calls,['0.2.1','0.2.0'])

    def test_quarantined_active_file_returns_verified_previous(self):
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            with patch('bc2launcher.selfupdate.bootstrap.probe_version'),patch('bc2launcher.selfupdate.bootstrap.launch_verified',return_value=FakeChild()):
                activate(root,'0.2.1',public_key=PUBLIC,now=NOW)
            (root/'versions'/'0.2.1'/'BC2Client.exe').unlink()
            with patch('bc2launcher.selfupdate.bootstrap.launch_verified',return_value=FakeChild()):
                result=start_active(root,PUBLIC)
            self.assertEqual(result.version,'0.2.0');self.assertTrue(result.recovered)

    def test_expired_installer_seed_does_not_break_existing_active_version(self):
        with tempfile.TemporaryDirectory() as folder:
            root,store=self.setup_root(folder)
            expired=policy_payload(version='0.2.0');expired['expires_at']='2000-01-01T00:00:00+00:00'
            (root/'seed-policy.json').write_bytes(signed(expired))
            install_seed(root,'0.2.0',PUBLIC)
            self.assertEqual(store.active(),'0.2.0')
            self.assertEqual(store.load()['highest_revision'],1)
