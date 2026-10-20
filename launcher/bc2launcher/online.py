"""Read public Theater catalog counts without logging in or changing game state."""
from dataclasses import dataclass
import re
import socket
import struct
import time

from .manifest import HOST

PORT = 18395
MAX_GAMES = 1000
MAX_FRAME = 1024 * 1024
MAX_RESPONSE = 4 * 1024 * 1024


class OnlineError(Exception):
    pass


@dataclass(frozen=True)
class OnlineStatus:
    players: int
    servers: int


def _number(fields, key, maximum):
    value = fields.get(key, b'')
    if not re.fullmatch(rb'[0-9]{1,6}', value):
        raise OnlineError('Invalid catalog number')
    number = int(value)
    if number > maximum:
        raise OnlineError('Catalog number exceeds limit')
    return number


class _Reader:
    def __init__(self, stream, deadline, clock, cancelled):
        self.stream = stream
        self.deadline = deadline
        self.clock = clock
        self.cancelled = cancelled
        self.remaining = MAX_RESPONSE

    def exact(self, size):
        result = bytearray()
        while len(result) < size:
            if self.cancelled(): raise OnlineError('Cancelled')
            remaining = self.deadline - self.clock()
            if remaining <= 0: raise OnlineError('Catalog request timed out')
            self.stream.settimeout(min(.5, remaining))
            try:
                chunk = self.stream.recv(min(65536, size - len(result)))
            except socket.timeout:
                continue
            if not chunk: raise OnlineError('Incomplete catalog response')
            result.extend(chunk)
        return bytes(result)

    def packet(self, expected, tid):
        kind, flags, size = struct.unpack('>4sII', self.exact(12))
        if kind != expected or flags != 0 or not 12 <= size <= MAX_FRAME:
            raise OnlineError('Unexpected catalog frame')
        if size > self.remaining: raise OnlineError('Catalog response too large')
        self.remaining -= size
        body = self.exact(size - 12).rstrip(b'\0\n')
        fields = {}
        for line in body.split(b'\n'):
            if not line: continue
            key, separator, value = line.partition(b'=')
            if not separator or not key or key in fields:
                raise OnlineError('Invalid catalog fields')
            fields[key] = value[1:-1] if value.startswith(b'"') and value.endswith(b'"') else value
        if fields.get(b'TID') != str(tid).encode('ascii'):
            raise OnlineError('Unexpected catalog transaction')
        return fields


def _request(kind, text):
    body = text.encode('ascii') + b'\0'
    return struct.pack('>4sII', kind, 0x40000000, len(body) + 12) + body


def fetch_online(*, connect=None, clock=None, cancelled=None):
    """Count active players only; an unavailable/invalid snapshot raises OnlineError.

    The public plaintext catalog is informational, never update-policy input.
    No credentials, player names, server addresses or remote text enter the UI.
    """
    connect = connect or socket.create_connection
    clock = clock or time.monotonic
    cancelled = cancelled or (lambda: False)
    if cancelled(): raise OnlineError('Cancelled')
    deadline = clock() + 6
    try:
        with connect((HOST, PORT), timeout=3) as stream:
            reader = _Reader(stream, deadline, clock, cancelled)
            stream.sendall(_request(b'CONN', 'TID=1\nPROT=2'))
            reader.packet(b'CONN', 1)
            stream.sendall(_request(b'GLST', 'TID=2'))
            header = reader.packet(b'GLST', 2)
            count = _number(header, b'NUM-GAMES', MAX_GAMES)
            total, games = 0, set()
            for _ in range(count):
                game = reader.packet(b'GDAT', 2)
                key = (_number(game, b'LID', 999999), _number(game, b'GID', 999999))
                if key in games: raise OnlineError('Duplicate game in catalog')
                games.add(key)
                capacity = _number(game, b'MP', 512)
                players = _number(game, b'AP', capacity)
                total += players
            return OnlineStatus(players=total, servers=count)
    except OnlineError:
        raise
    except (OSError, ValueError, KeyError, struct.error) as exc:
        raise OnlineError('Master catalog unavailable') from exc
