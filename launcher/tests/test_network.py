import io
import unittest
from unittest.mock import patch
from bc2launcher.network import validate_url, fetch_bytes, SafeRedirect
from bc2launcher.manifest import UpdateError


class Response(io.BytesIO):
    def geturl(self): return 'https://bc2.uplay2.ru/test'


class NetworkTests(unittest.TestCase):
    def test_url_policy(self):
        validate_url('https://github.com/RinatBy/x')
        for u in ['http://github.com/x', 'https://github.com.evil.test/x',
                  'https://user:pass@github.com/x', 'file:///tmp/x',
                  'https://github.com:444/x', 'https://github.com/x#secret']:
            with self.subTest(u=u), self.assertRaises(UpdateError): validate_url(u)

    def test_redirect_rejected_before_follow(self):
        with self.assertRaises(UpdateError):
            SafeRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test/x')

    def test_actual_size_not_header(self):
        with patch('bc2launcher.network.OPENER.open', return_value=Response(b'123456')):
            with self.assertRaises(UpdateError): fetch_bytes('https://bc2.uplay2.ru/test', 5)

    def test_fetch_success(self):
        with patch('bc2launcher.network.OPENER.open', return_value=Response(b'123')):
            self.assertEqual(fetch_bytes('https://bc2.uplay2.ru/test', 5), b'123')

    def test_network_failure(self):
        with patch('bc2launcher.network.OPENER.open', side_effect=TimeoutError):
            with self.assertRaises(UpdateError): fetch_bytes('https://bc2.uplay2.ru/test', 5)
