import tempfile
import unittest
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
from selfupdate_helpers import PUBLIC,NOW,signed,policy_payload,make_archive
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.service import SelfUpdateService


class ServiceTests(unittest.TestCase):
    def create(self,folder,minimum='0.2.0',revision=1):
        data=make_archive(); p=policy_payload(revision=revision,archive=data)
        p['minimum_launcher_version']=minimum
        def download(url,path,limit,**kwargs):Path(path).write_bytes(data)
        service=SelfUpdateService(Path(folder),PUBLIC,version='0.2.0',fetch=lambda *a:signed(p),
                                  download=download,clock=lambda:NOW,probe=lambda *a:None)
        return service,p

    def test_required_update_only_allows_play_after_new_version(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder,minimum='0.2.1')
            result=service.check();self.assertFalse(result.play_allowed)
            with self.assertRaises(UpdateError):service.require_play_allowed()
            result=service.prepare();self.assertTrue(result.restart_ready)
            self.assertFalse(result.play_allowed)
            self.assertTrue((Path(folder)/'versions'/'0.2.1'/'BC2Client.exe').is_file())
            service.version='0.2.1'
            self.assertTrue(service.check().play_allowed)

    def test_optional_update_can_stage_without_affecting_game_files(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder)
            settings=Path(folder)/'settings.json';settings.write_bytes(b'game path stays')
            self.assertTrue(service.check().play_allowed)
            self.assertTrue(service.prepare().restart_ready)
            self.assertEqual(settings.read_bytes(),b'game path stays')

    def test_recheck_before_play_prevents_new_minimum_bypass(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder);self.assertTrue(service.check().play_allowed)
            p.update(revision=2,minimum_launcher_version='0.2.1')
            with self.assertRaises(UpdateError):service.require_play_allowed()
            self.assertFalse(service.status.play_allowed)

    def test_offline_cache_requires_accepted_unexpired_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder);service.check()
            def offline(*a):raise UpdateError('offline')
            service.fetch=offline
            self.assertTrue(service.check().play_allowed)
            (Path(folder)/'launcher-policy.json').write_bytes(b'broken')
            self.assertFalse(service.check().play_allowed)

    def test_invalid_policy_and_new_bootstrap_requirement_disable_play(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder);service.fetch=lambda *a:b'invalid'
            self.assertFalse(service.check().play_allowed)
            p['minimum_bootstrap_version']='2.0.0';service.fetch=lambda *a:signed(p)
            result=service.check();self.assertEqual(result.state,'INSTALLER_REQUIRED')
            self.assertFalse(result.play_allowed);self.assertFalse(result.restart_ready)

    def test_failed_release_not_automatically_restarted_and_cancel_is_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder);service.check()
            with service.store.locked():service.store.mark_failed(service.policy.payload_sha256)
            self.assertEqual(service.prepare().state,'FAILED')
            self.assertTrue(service.prepare(manual=True).restart_ready)
            service.cancel.set()
            self.assertEqual(service.prepare(manual=True).state,'CANCELLED')
            self.assertFalse((Path(folder)/'active.json').exists())

    def test_restart_waits_for_bootstrap_handoff_and_preserves_diagnostic_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            service,p=self.create(folder);service.prepare();commands=[]
            def spawn(command,**kwargs):
                commands.append(command)
                token=command[command.index('--handoff-token')+1]
                ack=Path(folder)/'cache'/('handoff-'+token+'.json')
                ack.write_text(json.dumps(dict(ready=True,nonce=token)))
                class Waiting:
                    def poll(self):return None
                return Waiting()
            exe=str(Path(folder)/'versions'/'0.2.0'/'BC2Client.exe')
            with patch.object(sys,'executable',exe),patch.object(sys,'argv',['client','--smoke-startup']),patch('bc2launcher.selfupdate.service.subprocess.Popen',side_effect=spawn):
                result=service.request_restart()
            self.assertEqual(result.state,'RESTARTING')
            self.assertIn('--smoke-startup',commands[0])
            self.assertEqual(commands[0][commands[0].index('--wait-pid')+1],str(os.getpid()))
