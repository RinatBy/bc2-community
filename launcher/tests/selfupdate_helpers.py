import base64
import hashlib
import io
import json
import zipfile
import warnings
from datetime import timedelta
from helpers import KEY, PUBLIC, NOW


def signed(payload):
    raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return json.dumps({'payload': base64.b64encode(raw).decode(),
                       'signature': base64.b64encode(KEY.sign(raw)).decode()}).encode()


def policy_payload(revision=1, version='0.2.1', archive=b'zip'):
    return dict(purpose='bc2-launcher-update', schema=1, revision=revision,
                expires_at=(NOW + timedelta(days=30)).isoformat(), version=version,
                minimum_launcher_version='0.2.0', minimum_bootstrap_version='1.0.0',
                artifact=dict(url='https://github.com/RinatBy/bc2-community/releases/download/test/app.zip',
                              size=len(archive), sha256=hashlib.sha256(archive).hexdigest()))


def inventory_payload(files=None, version='0.2.1'):
    files = files if files is not None else {'BC2Client.exe': b'MZtest', '_internal/lib.dll': b'library'}
    return dict(purpose='bc2-launcher-package', schema=1, version=version,
                files=[dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
                       for name, data in sorted(files.items())])


def make_archive(files=None, version='0.2.1', extra=None, inventory=None):
    files = files if files is not None else {'BC2Client.exe': b'MZtest', '_internal/lib.dll': b'library'}
    stream = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        warnings.filterwarnings('ignore',message='Duplicate name:',category=UserWarning,module='zipfile')
        z.writestr('.launcher-package.json', signed(inventory or inventory_payload(files, version)))
        for name, data in files.items(): z.writestr(name, data)
        for name, data in extra or []: z.writestr(name, data)
    return stream.getvalue()
