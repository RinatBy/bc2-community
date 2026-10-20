import json
import tempfile
import unittest
from pathlib import Path
from selfupdate_helpers import PUBLIC, NOW, signed, policy_payload
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.policy import verify_policy
from bc2launcher.selfupdate.store import UpdateStore


class StoreTests(unittest.TestCase):
    def test_accept_is_independent_of_game_settings_and_survives_version_rollback(self):
        with tempfile.TemporaryDirectory(prefix='тест ') as folder:
            root=Path(folder); settings=root/'settings.json'; original=b'{"game_dir":"E:/game","highest_revision":47}'
            settings.write_bytes(original); store=UpdateStore(root)
            p=verify_policy(signed(policy_payload(3)),PUBLIC,NOW,0)
            store.accept(p)
            self.assertEqual(UpdateStore(root).load()['highest_revision'],3)
            self.assertEqual(settings.read_bytes(),original)
            for data in (policy_payload(2),policy_payload(3,version='0.2.2')):
                with self.assertRaises(UpdateError): store.accept(verify_policy(signed(data),PUBLIC,NOW,0))
            self.assertEqual(store.load()['highest_revision'],3)

    def test_competing_writer_and_malformed_state_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            store=UpdateStore(Path(folder))
            with store.locked():
                with self.assertRaises(UpdateError):
                    with UpdateStore(Path(folder)).locked(): pass
            (Path(folder)/'update-state.json').write_text('{"highest_revision":true}')
            with self.assertRaises(UpdateError):store.load()

    def test_active_pointer_only_accepts_version_not_path(self):
        with tempfile.TemporaryDirectory() as folder:
            store=UpdateStore(Path(folder)); store.set_active('0.2.0')
            self.assertEqual(store.active(),'0.2.0')
            (Path(folder)/'active.json').write_text(json.dumps({'schema':1,'version':'../elsewhere'}))
            with self.assertRaises(UpdateError):store.active()


if __name__=='__main__':unittest.main()
