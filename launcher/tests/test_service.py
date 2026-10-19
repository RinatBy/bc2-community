import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from helpers import KEY, PUBLIC, NOW, DLL, INI, payload, envelope
from bc2launcher.service import LauncherService
from bc2launcher.settings import Settings


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.game=self.root/'game'; self.game.mkdir()
        (self.game/'BFBC2Game.exe').write_bytes(b'MZ'+b'\0'*64)
        self.settings=Settings(self.root/'settings.json')
        self.policy=payload()
        self.launched=[]
        self.service=LauncherService(PUBLIC,self.settings,fetch=self.fetch,clock=lambda:NOW,
                                    launch=lambda p:self.launched.append(p))

    def fetch(self,url,limit):
        return envelope(self.policy) if 'stable.json' in url else DLL if url.endswith('.dll') else INI

    def test_update_then_launch(self):
        self.assertEqual(self.service.check(self.game).state,'UPDATE_REQUIRED')
        self.assertEqual(self.service.update(self.game).state,'READY')
        self.assertEqual(self.service.play(self.game).state,'READY')
        self.assertEqual(self.launched[0].root,self.game)

    def test_new_policy_at_click_blocks_launch(self):
        self.service.update(self.game)
        self.policy['revision']=2
        self.policy['assets'][0]['sha256']='0'*64
        self.assertEqual(self.service.play(self.game).state,'UPDATE_REQUIRED')
        self.assertFalse(self.launched)

    def test_replay_after_rollback(self):
        self.service.update(self.game)
        self.policy['revision']=2; self.service.check(self.game)
        self.service.rollback(self.game,self.service.backups(self.game)[0][0])
        self.policy['revision']=1
        self.assertEqual(self.service.play(self.game).state,'ERROR')
        self.assertEqual(self.settings.load()['highest_revision'],2)
        self.assertFalse(self.launched)

    def test_preserve_custom_ini_no_update_loop(self):
        self.service.update(self.game)
        with (self.game/'bfbc2.ini').open('ab') as f:f.write(b'\n[client]\nshow=custom\n')
        self.assertEqual(self.service.check(self.game).state,'READY')

    def test_corruption_network_and_tampering(self):
        self.service.update(self.game)
        (self.game/'dinput8.dll').write_bytes(b'bad')
        self.assertEqual(self.service.check(self.game).state,'UPDATE_REQUIRED')
        self.service.fetch=lambda *a: (_ for _ in ()).throw(OSError('offline'))
        self.assertEqual(self.service.play(self.game).state,'ERROR')
        self.assertFalse(self.launched)

    def test_cancel_before_commit_changes_nothing(self):
        self.service.cancel.set()
        self.assertEqual(self.service.update(self.game).state,'ERROR')
        self.assertFalse((self.game/'dinput8.dll').exists())

    def test_same_revision_different_payload_is_rejected(self):
        self.service.check(self.game)
        self.policy['package_id']='changed-same-revision'
        self.assertEqual(self.service.check(self.game).state,'ERROR')

    def test_signed_fallback_when_site_is_unavailable(self):
        original=self.service.fetch
        def fallback(url,limit):
            if url.startswith('https://bc2.uplay2.ru/'):raise OSError('site not connected yet')
            return original(url,limit)
        self.service.fetch=fallback
        self.assertEqual(self.service.update(self.game).state,'READY')

    def test_bad_signature_does_not_fall_back(self):
        calls=[]
        def bad(url,limit):calls.append(url);return b'{}'
        self.service.fetch=bad
        self.assertEqual(self.service.check(self.game).state,'ERROR')
        self.assertEqual(len(calls),1)

    def test_unsupported_new_policy_still_advances_replay_guard(self):
        self.service.update(self.game)
        self.policy['revision']=2; self.policy['minimum_launcher_version']='9.0.0'
        self.assertEqual(self.service.check(self.game).state,'ERROR')
        self.assertEqual(self.settings.load()['highest_revision'],2)
        self.policy=payload(1)
        self.assertEqual(self.service.play(self.game).state,'ERROR')
        self.assertFalse(self.launched)

    def test_launch_holds_game_operation_lock(self):
        from bc2launcher.transaction import game_lock
        from bc2launcher.manifest import UpdateError
        self.service.update(self.game)
        def launch(game):
            with self.assertRaises(UpdateError):
                with game_lock(game.root): pass
        self.service.launch=launch
        self.assertEqual(self.service.play(self.game).state,'READY')

    def test_concurrent_new_policy_cannot_be_overwritten(self):
        from bc2launcher.manifest import verify_manifest
        newer=verify_manifest(envelope(payload(2)),PUBLIC,NOW,0)
        original=self.service.fetch
        def accept_other_process_policy(url,limit):
            self.settings.accept_policy(newer)
            return original(url,limit)
        self.service.fetch=accept_other_process_policy
        self.assertEqual(self.service.check(self.game).state,'ERROR')
        self.assertEqual(self.settings.load()['highest_revision'],2)
