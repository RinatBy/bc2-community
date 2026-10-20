import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from bc2launcher.manifest import UpdateError
from bc2launcher.network import download_file


class Response(io.BytesIO):
    def geturl(self):return 'https://github.com/a'


class DownloadTests(unittest.TestCase):
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
