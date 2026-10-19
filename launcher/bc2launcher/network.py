import ssl
import time
import urllib.request
import urllib.parse
from .manifest import UpdateError

ALLOWED_HOSTS = frozenset({'bc2.uplay2.ru', 'github.com',
                          'raw.githubusercontent.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'})


def validate_url(url: str) -> None:
    try:
        if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url): raise ValueError()
        p = urllib.parse.urlsplit(url)
        if p.scheme != 'https' or p.hostname not in ALLOWED_HOSTS: raise ValueError()
        if p.username or p.password or p.fragment or p.port not in (None, 443): raise ValueError()
    except ValueError as exc:
        raise UpdateError("Обновление ссылается на недопустимый адрес загрузки.") from exc


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(SafeRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))


def fetch_bytes(url: str, max_bytes: int) -> bytes:
    validate_url(url)
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'BC2Launcher/0.1.0', 'Cache-Control': 'no-cache'})
        with OPENER.open(request, timeout=20) as response:
            validate_url(response.geturl())
            chunks, total, started = [], 0, time.monotonic()
            while True:
                if time.monotonic()-started>90: raise UpdateError("Загрузка занимает слишком много времени. Повторите попытку.")
                chunk = response.read(min(65536, max_bytes + 1 - total))
                if not chunk: break
                total += len(chunk)
                if total > max_bytes: raise UpdateError("Размер загрузки превышает допустимый.")
                chunks.append(chunk)
            return b''.join(chunks)
    except UpdateError:
        raise
    except Exception as exc:
        raise UpdateError("Не удалось загрузить обновление. Проверьте интернет и повторите попытку.") from exc
