import unittest
import json
from helpers import NOW, PUBLIC, payload, envelope
from bc2launcher.manifest import verify_manifest, UpdateError


class ManifestTests(unittest.TestCase):
    def check(self, data=None, raw=None, highest=0):
        return verify_manifest(envelope(data, raw), PUBLIC, NOW, highest)

    def test_valid(self):
        r = self.check()
        self.assertEqual(r.master_host, "master.bc2.uplay2.ru")
        self.assertEqual(len(r.assets), 2)

    def test_bad_signature(self):
        x = json.loads(envelope())
        x['signature'] = 'A' * 88
        with self.assertRaises(UpdateError):
            verify_manifest(json.dumps(x).encode(), PUBLIC, NOW, 0)

    def test_invalid_fields(self):
        for key, val in [('schema', 2), ('revision', True), ('revision', 0),
                         ('master_host', 'evil.test'), ('expires_at', '2020-01-01T00:00:00Z'),
                         ('expires_at', '2026-12-01'), ('minimum_launcher_version', 'garbage')]:
            with self.subTest(key=key, val=val), self.assertRaises(UpdateError):
                x = payload(); x[key] = val; self.check(x)

    def test_replay(self):
        with self.assertRaises(UpdateError): self.check(highest=2)

    def test_duplicate_json(self):
        with self.assertRaises(UpdateError): self.check(raw=b'{"schema":1,"schema":1}')

    def test_nan(self):
        with self.assertRaises(UpdateError): self.check(raw=b'{"schema":NaN}')

    def test_asset_validation(self):
        for key, val in [('name', '../dinput8.dll'), ('size', True), ('size', 0),
                         ('size', 17000000), ('sha256', 'xyz'),
                         ('url', 'http://github.com/x'), ('url', 'https://evil.test/x')]:
            with self.subTest(key=key), self.assertRaises(UpdateError):
                x = payload(); x['assets'][0][key] = val; self.check(x)

    def test_missing_or_duplicate_asset(self):
        for assets in [[], [payload()['assets'][0]] * 2]:
            x = payload(); x['assets'] = assets
            with self.assertRaises(UpdateError): self.check(x)

    def test_envelope_size(self):
        with self.assertRaises(UpdateError): verify_manifest(b' ' * 262145, PUBLIC, NOW, 0)
