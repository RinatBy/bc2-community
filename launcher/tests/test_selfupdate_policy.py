import base64
import json
import unittest
from datetime import timedelta
from helpers import payload as game_payload, KEY
from selfupdate_helpers import PUBLIC, NOW, signed, policy_payload, inventory_payload
from bc2launcher.manifest import UpdateError
from bc2launcher.selfupdate.policy import verify_policy, verify_inventory, validate_version


class PolicyTests(unittest.TestCase):
    def test_valid_policy_exposes_verified_version_and_artifact(self):
        p = verify_policy(signed(policy_payload()), PUBLIC, NOW, 0)
        self.assertEqual((p.version, p.revision, p.artifact.size), ('0.2.1', 1, 3))
        self.assertEqual(p.minimum_launcher_version, '0.2.0')

    def test_bad_signature_and_game_channel_cannot_install_program(self):
        for raw in (signed(game_payload()), signed(policy_payload()).replace(b'payload', b'payloae')):
            with self.subTest(raw=raw[:30]), self.assertRaises(UpdateError):
                verify_policy(raw, PUBLIC, NOW, 0)
        with self.assertRaises(UpdateError):
            verify_policy(signed(policy_payload()), bytes(32), NOW, 0)

    def test_expiry_revision_strict_schema_and_limits(self):
        mutations = [dict(expires_at=(NOW-timedelta(seconds=1)).isoformat()),
                     dict(revision=True), dict(revision=0), dict(revision=2**53+1),
                     dict(schema=True), dict(purpose='other'), dict(extra='ignored'),
                     dict(version='../evil'), dict(minimum_launcher_version='0.3.0'),
                     dict(artifact=dict(url='http://github.com/a',size=1,sha256='0'*64)),
                     dict(artifact=dict(url='https://github.com/a',size=512*1024**2+1,sha256='0'*64))]
        for update in mutations:
            p=policy_payload(); p.update(update)
            with self.subTest(update=update), self.assertRaises(UpdateError):
                verify_policy(signed(p), PUBLIC, NOW, 0)
        with self.assertRaises(UpdateError): verify_policy(signed(policy_payload()), PUBLIC, NOW, 2)
        with self.assertRaises(UpdateError): verify_policy(b' '*262145, PUBLIC, NOW, 0)

    def test_duplicate_json_fields_rejected_even_with_valid_signature(self):
        raw=json.dumps(policy_payload()).encode()[:-1]+b',"revision":2}'
        env=json.dumps(dict(payload=base64.b64encode(raw).decode(), signature=base64.b64encode(KEY.sign(raw)).decode())).encode()
        with self.assertRaises(UpdateError): verify_policy(env, PUBLIC, NOW, 0)

    def test_canonical_version_prevents_pointer_path_ambiguity(self):
        for bad in ('../1','01.2.0','0.2.0/','0.2.0 ','10000.0.0','0.2','0.2.0.exe',None):
            with self.subTest(bad=bad), self.assertRaises(UpdateError): validate_version(bad)

    def test_inventory_must_have_fixed_executable_and_unique_windows_paths(self):
        inv=verify_inventory(signed(inventory_payload()),PUBLIC)
        self.assertEqual(inv.version,'0.2.1')
        for files in ({'other.exe':b'x'}, {'BC2Client.exe':b'x','bc2client.EXE':b'y'},
                      {'BC2Client.exe':b'x','../outside':b'y'}, {'BC2Client.exe':b'x','_internal/CON.dll':b'y'}):
            with self.subTest(files=list(files)), self.assertRaises(UpdateError):
                verify_inventory(signed(inventory_payload(files)),PUBLIC)

    def test_windows_unicode_name_ambiguity_does_not_allow_two_package_paths(self):
        files={'BC2Client.exe':b'MZ','_internal/I.dll':b'a','_internal/\u0131.dll':b'b'}
        with self.assertRaises(UpdateError):verify_inventory(signed(inventory_payload(files)),PUBLIC)


if __name__=='__main__': unittest.main()
