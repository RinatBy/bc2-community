import ctypes
import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from ..manifest import UpdateError, _json
from .paths import inside, version_dir
from .package import verify_installed


def _kernel():
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    return kernel


def _image_path(kernel, handle):
    from ctypes import wintypes
    buffer = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(buffer))
    if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        raise UpdateError('Cannot verify launcher process identity.')
    return os.path.normcase(os.path.abspath(buffer.value))


def wait_for_old_process(pid, expected_executable, timeout=60, on_open=lambda: None):
    if os.name != 'nt': raise UpdateError('Process handoff requires Windows.')
    if type(pid) is not int or pid <= 0: raise UpdateError('Invalid previous launcher process.')
    kernel = _kernel(); handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle: raise UpdateError('Previous launcher process no longer matches the request.')
    try:
        expected = os.path.normcase(os.path.abspath(expected_executable))
        if _image_path(kernel, handle) != expected: raise UpdateError('Unexpected previous launcher process.')
        on_open()
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise UpdateError('Previous launcher has not closed. Update was not activated.')
    finally: kernel.CloseHandle(handle)


def _available(fd):
    if os.name == 'nt':
        import msvcrt
        from ctypes import wintypes
        available = wintypes.DWORD()
        if not _kernel().PeekNamedPipe(msvcrt.get_osfhandle(fd), None, 0, None, ctypes.byref(available), None):
            return 0
        return available.value
    import select
    return 4096 if select.select([fd], [], [], 0)[0] else 0


class Child:
    def __init__(self, process, read_fd, nonce, version):
        self.process = process; self.read_fd = read_fd; self.nonce = nonce; self.version = version

    def wait_ready(self, timeout=30):
        deadline = time.monotonic() + timeout; data = bytearray()
        while time.monotonic() < deadline:
            if self.process.poll() is not None: raise UpdateError('New launcher exited before becoming ready.')
            count = _available(self.read_fd)
            if count:
                data.extend(os.read(self.read_fd, min(count, 4097 - len(data))))
                if len(data) > 4096: raise UpdateError('Invalid startup acknowledgement.')
                if b'\n' in data:
                    try:
                        p = _json(bytes(data))
                        if (not isinstance(p, dict) or set(p) != {'nonce', 'pid', 'version'}
                                or p['nonce'] != self.nonce or p['version'] != self.version
                                or type(p['pid']) is not int or p['pid'] != self.process.pid): raise ValueError()
                    except (ValueError, TypeError, UnicodeError) as exc:
                        raise UpdateError('Startup acknowledgement does not match the child process.') from exc
                    return
            time.sleep(.025)
        raise UpdateError('New launcher did not confirm startup in time.')

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)

    def close(self):
        if self.read_fd is not None: os.close(self.read_fd); self.read_fd = None


def spawn_ready(command, cwd, version, *, append_arguments=True, env=None):
    read_fd, write_fd = os.pipe(); os.set_inheritable(write_fd, True)
    nonce = secrets.token_hex(32)
    kwargs = dict(cwd=cwd, shell=False, close_fds=True, env=env,
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == 'nt':
        import msvcrt
        handle = msvcrt.get_osfhandle(write_fd)
        startup = subprocess.STARTUPINFO(); startup.lpAttributeList = {'handle_list': [handle]}
        kwargs['startupinfo'] = startup
    else:
        handle = write_fd; kwargs['pass_fds'] = (write_fd,)
    arguments = ['--ready-handle', str(handle), '--ready-token', nonce] if append_arguments else [str(handle), nonce]
    try: process = subprocess.Popen([*map(str, command), *arguments], **kwargs)
    except Exception:
        os.close(read_fd); raise
    finally: os.close(write_fd)
    return Child(process, read_fd, nonce, version)


def acknowledge_ready(handle, nonce, version):
    if not isinstance(nonce, str) or len(nonce) != 64: raise UpdateError('Invalid startup token.')
    if os.name == 'nt':
        import msvcrt
        handle = msvcrt.open_osfhandle(handle, os.O_WRONLY)
    try:
        os.write(handle, json.dumps(dict(nonce=nonce, pid=os.getpid(), version=version)).encode() + b'\n')
    finally: os.close(handle)


def probe_version(root, version, public_key):
    verify_installed(root, version, public_key)
    cache = inside(root, 'cache'); cache.mkdir(exist_ok=True)
    report = inside(cache, 'probe-' + secrets.token_hex(12) + '.json')
    command = [str(version_dir(root, version) / 'BC2Client.exe'), '--self-test', '--report', str(report)]
    kwargs = dict(cwd=version_dir(root, version), shell=False)
    if os.name == 'nt': kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        process = subprocess.Popen(command, **kwargs)
        try: code = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5); raise UpdateError('Launcher self-test timed out.')
        if code or not report.is_file() or report.stat().st_size > 16384: raise UpdateError('Launcher self-test failed.')
        p = _json(report.read_bytes())
        if not (p.get('ok') is True and p.get('qt_imports_ok') is True
                and p.get('resources_ok') is True and p.get('version') == version):
            raise UpdateError('Launcher self-test did not confirm resources and Qt.')
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise UpdateError('Unable to run launcher self-test.') from exc
    finally: report.unlink(missing_ok=True)


def launch_verified(root, version, public_key, *, smoke=False):
    verify_installed(root, version, public_key)
    command = [version_dir(root, version) / 'BC2Client.exe']
    if smoke: command += ['--smoke-startup']
    return spawn_ready(command, version_dir(root, version), version)
