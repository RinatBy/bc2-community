import io
import http.client
import socket
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bc2launcher.manifest import UpdateError
from bc2launcher.network import download_file


class Response(io.BytesIO):
    def geturl(self):return 'https://github.com/a'


class DownloadTests(unittest.TestCase):
    def test_slow_response_reports_first_bytes_before_the_rest_arrive_and_can_cancel(self):
        client, server = socket.socketpair()
        client.settimeout(2)
        server.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 10000\r\n\r\nabc')
        response = http.client.HTTPResponse(client)
        response.begin()
        response.geturl = lambda: 'https://github.com/a'
        seen = threading.Event()
        cancelled = threading.Event()
        errors = []
        def progress(n):
            if n:
                seen.set()
                cancelled.set()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.zip'
            def download():
                try:
                    download_file('https://github.com/a', path, 10000,
                                  cancelled=cancelled.is_set, progress=progress)
                except UpdateError as exc:
                    errors.append(str(exc))
            try:
                with patch('bc2launcher.network.OPENER.open', return_value=response):
                    worker = threading.Thread(target=download, daemon=True)
                    worker.start()
                    early_progress = seen.wait(1)
                    server.close()
                    worker.join(3)
                self.assertTrue(early_progress, 'Received bytes stayed buffered until the response ended.')
                self.assertFalse(worker.is_alive())
                self.assertTrue(errors)
                self.assertFalse(path.exists())
            finally:
                server.close()
                client.close()

    def test_total_timeout_is_checked_when_a_slow_read_returns_eof(self):
        clock = [0]
        class SlowResponse(Response):
            def read(self, n=-1):
                clock[0] = 601
                return b''
            read1 = read
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'app.zip'
            with patch('bc2launcher.network.OPENER.open', return_value=SlowResponse()), \
                    patch('bc2launcher.network.time.monotonic', side_effect=lambda:clock[0]), \
                    self.assertRaises(UpdateError):
                download_file('https://github.com/a', path, 100,
                              cancelled=lambda:False, progress=lambda n:None)
            self.assertFalse(path.exists())

    def test_streamed_file_complete_without_accumulating_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app.zip'
            with patch('bc2launcher.network.OPENER.open',return_value=Response(b'a'*140000)):
                download_file('https://github.com/a',path,140000,cancelled=lambda:False,progress=lambda n:None)
            self.assertEqual(path.stat().st_size,140000)

    def test_oversize_cancel_network_and_redirect_remove_partial(self):
        for kind in ('oversize','cancel','network','redirect'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'app.zip'; response=Response(b'a'*10)
                if kind=='redirect':response.geturl=lambda:'https://evil.example/a'
                kwargs={'return_value':response} if kind!='network' else {'side_effect':OSError('offline')}
                with patch('bc2launcher.network.OPENER.open',**kwargs),self.assertRaises(UpdateError):
                    download_file('https://github.com/a',path,5 if kind=='oversize' else 10,
                                  cancelled=lambda:kind=='cancel',progress=lambda n:None)
                self.assertFalse(path.exists())

    def test_existing_file_is_not_deleted_or_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'app.zip';path.write_bytes(b'keep')
            with patch('bc2launcher.network.OPENER.open',return_value=Response(b'new')),self.assertRaises(UpdateError):
                download_file('https://github.com/a',path,10,cancelled=lambda:False,progress=lambda n:None)
            self.assertEqual(path.read_bytes(),b'keep')
