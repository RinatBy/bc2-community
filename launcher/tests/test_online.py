import io
import socket
import struct
import unittest

from bc2launcher.online import fetch_online, OnlineError, OnlineStatus


def response(kind, text):
    body = text.encode('utf-8') + b'\0'
    return struct.pack('>4sII', kind, 0, len(body) + 12) + body


HELLO = response(b'CONN', 'TID=1\nPROT=2')


class FragmentedSocket:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.sent = []

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): pass
    def sendall(self, data): self.sent.append(data)
    def recv(self, count): return self.stream.read(min(count, 3))


class OnlineTests(unittest.TestCase):
    def fetch(self, data, **options):
        stream = FragmentedSocket(data)
        def connect(address, timeout):
            self.assertEqual(address, ('master.bc2.uplay2.ru', 18395))
            return stream
        result = fetch_online(connect=connect, **options)
        self.assertEqual([p[:4] for p in stream.sent], [b'CONN', b'GLST'])
        return result

    def test_sums_active_players_from_fragmented_catalog(self):
        data = HELLO + response(b'GLST', 'TID=2\nNUM-GAMES=2')
        data += response(b'GDAT', 'TID=2\nLID=1\nGID=8\nAP=8\nMP=32\nJP=3\nN="Test server"')
        data += response(b'GDAT', 'TID=2\nLID=1\nGID=9\nAP=12\nMP=16')
        self.assertEqual(self.fetch(data), OnlineStatus(players=20, servers=2))

    def test_empty_catalog_is_a_successful_zero(self):
        self.assertEqual(self.fetch(HELLO + response(b'GLST', 'TID=2\nNUM-GAMES=0')),
                         OnlineStatus(players=0, servers=0))

    def test_partial_catalog_never_returns_a_partial_count(self):
        data = HELLO + response(b'GLST', 'TID=2\nNUM-GAMES=2')
        data += response(b'GDAT', 'TID=2\nLID=1\nGID=8\nAP=8\nMP=32')
        with self.assertRaises(OnlineError): self.fetch(data)

    def test_duplicate_game_is_not_counted_twice(self):
        game = response(b'GDAT', 'TID=2\nLID=1\nGID=8\nAP=8\nMP=32')
        with self.assertRaises(OnlineError):
            self.fetch(HELLO + response(b'GLST', 'TID=2\nNUM-GAMES=2') + game * 2)

    def test_rejects_invalid_player_numbers(self):
        for values in ['AP=-1\nMP=32', 'AP=33\nMP=32', 'AP=oops\nMP=32', 'MP=32']:
            with self.subTest(values=values), self.assertRaises(OnlineError):
                self.fetch(HELLO + response(b'GLST', 'TID=2\nNUM-GAMES=1') +
                           response(b'GDAT', 'TID=2\nLID=1\nGID=8\n' + values))

    def test_rejects_wrong_transaction_and_duplicate_fields(self):
        for text in ['TID=99\nNUM-GAMES=0', 'TID=2\nNUM-GAMES=0\nNUM-GAMES=1',
                     'TID=2\nNUM-GAMES=1000000']:
            with self.subTest(text=text), self.assertRaises(OnlineError):
                self.fetch(HELLO + response(b'GLST', text))

    def test_oversized_frame_rejected_before_reading_payload(self):
        with self.assertRaises(OnlineError):
            self.fetch(HELLO + struct.pack('>4sII', b'GLST', 0, 2**30))

    def test_connection_failure_is_unavailable_not_zero(self):
        def offline(*args, **kwargs): raise OSError('offline')
        with self.assertRaises(OnlineError): fetch_online(connect=offline)

    def test_cancelled_request_does_not_connect(self):
        def unexpected(*args, **kwargs): self.fail('Cancelled request connected')
        with self.assertRaises(OnlineError):
            fetch_online(connect=unexpected, cancelled=lambda: True)

    def test_timeout_has_an_overall_deadline(self):
        class SlowSocket(FragmentedSocket):
            def recv(self, count): raise socket.timeout()
        stream = SlowSocket(b'')
        ticks = iter(range(100))
        with self.assertRaises(OnlineError):
            fetch_online(connect=lambda *args, **kwargs: stream,
                         clock=lambda: next(ticks))
