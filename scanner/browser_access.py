"""Windows browser lock diagnostics and user-approved browser shutdown.

No database contents are read here. Restart Manager identifies file owners.
Only verified Chrome/Edge processes can be selected for shutdown.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import time

BROWSERS = {"chrome.exe": "Chrome", "msedge.exe": "Edge"}


class UniqueProcess(ctypes.Structure):
    _fields_ = [("pid", w.DWORD), ("started", w.FILETIME)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [("process", UniqueProcess), ("app_name", w.WCHAR * 256),
                ("service_name", w.WCHAR * 64), ("app_type", ctypes.c_int),
                ("status", w.ULONG), ("session_id", w.DWORD), ("restartable", w.BOOL)]


def _apis():
    if os.name != "nt":
        raise OSError("Browser lock management is available on Windows only")
    rm = ctypes.WinDLL("Rstrtmgr", use_last_error=True)
    rm.RmStartSession.argtypes = [ctypes.POINTER(w.DWORD), w.DWORD, w.LPWSTR]
    rm.RmStartSession.restype = w.DWORD
    rm.RmRegisterResources.argtypes = [w.DWORD, w.UINT, ctypes.POINTER(w.LPCWSTR), w.UINT,
                                      ctypes.POINTER(UniqueProcess), w.UINT, ctypes.POINTER(w.LPCWSTR)]
    rm.RmRegisterResources.restype = w.DWORD
    rm.RmGetList.argtypes = [w.DWORD, ctypes.POINTER(w.UINT), ctypes.POINTER(w.UINT),
                            ctypes.POINTER(ProcessInfo), ctypes.POINTER(w.DWORD)]
    rm.RmGetList.restype = w.DWORD
    rm.RmShutdown.argtypes = [w.DWORD, w.ULONG, ctypes.c_void_p]
    rm.RmShutdown.restype = w.DWORD
    rm.RmEndSession.argtypes = [w.DWORD]
    rm.RmEndSession.restype = w.DWORD
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.GetProcessTimes.argtypes = [w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME),
                                      ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)]
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    kernel.TerminateProcess.restype = w.BOOL
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    return rm, kernel


@contextmanager
def _session(rm):
    handle = w.DWORD()
    key = ctypes.create_unicode_buffer(33)
    status = rm.RmStartSession(ctypes.byref(handle), 0, key)
    if status:
        raise OSError(status, "Windows could not start browser lock diagnostics")
    try:
        yield handle
    finally:
        rm.RmEndSession(handle)


def _process_identity(pid):
    _, kernel = _apis()
    handle = kernel.OpenProcess(0x1000, False, pid)  # Query metadata only; never termination rights.
    if not handle:
        code = ctypes.get_last_error()
        if code == 87:  # Process has exited.
            return None
        raise OSError(code, "Cannot verify browser process identity")
    try:
        return _identity_from_handle(kernel, handle, pid)
    finally:
        kernel.CloseHandle(handle)


def _identity_from_handle(kernel, handle, pid):
    exit_code = w.DWORD()
    if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
        raise OSError(ctypes.get_last_error(), "Cannot inspect browser process")
    if exit_code.value != 259:
        return None
    size = w.DWORD(32768)
    image = ctypes.create_unicode_buffer(size.value)
    if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
        raise OSError(ctypes.get_last_error(), "Cannot inspect browser executable")
    created, exited, user, system = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
    if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
        raise OSError(ctypes.get_last_error(), "Cannot verify browser process start time")
    return {"pid": pid, "executable": Path(image.value).name.lower(),
            "started": (created.dwHighDateTime << 32) | created.dwLowDateTime}


def has_visible_windows(pid):
    if os.name != "nt":
        raise OSError("Browser window checks are available on Windows only")
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    found = []
    @callback_type
    def visit(hwnd, param):
        owner = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd):
            found.append(True)
        return True
    if not user.EnumWindows(visit, 0):
        raise OSError(ctypes.get_last_error(), "Could not verify browser windows are closed")
    return bool(found)


def _stop_background(targets):
    """Explicit-consent fallback, limited to verified windowless browser owners."""
    if any(has_visible_windows(p["pid"]) for p in targets):
        raise RuntimeError("A browser window is open. Close it before stopping background processes.")
    _, kernel = _apis()
    for target in targets:
        # Recheck identity on the actual handle used to stop the process.
        handle = kernel.OpenProcess(0x1001 | 0x100000, False, target["pid"])
        if not handle:
            if ctypes.get_last_error() == 87:
                continue
            raise OSError(ctypes.get_last_error(), "Cannot stop the selected background browser")
        try:
            identity = _identity_from_handle(kernel, handle, target["pid"])
            if identity is None:
                continue
            if identity != target or identity["executable"] not in BROWSERS:
                raise RuntimeError("Browser process identity changed; scan again before stopping anything.")
            if has_visible_windows(target["pid"]):
                raise RuntimeError("A browser window opened. Background shutdown was cancelled.")
            if not kernel.TerminateProcess(handle, 0):
                raise OSError(ctypes.get_last_error(), "Could not stop the selected background browser")
            if kernel.WaitForSingleObject(handle, 5000) != 0:
                raise RuntimeError("The selected browser has not exited yet. Scan again after it exits.")
        finally:
            kernel.CloseHandle(handle)


def file_users(path):
    """Return verified browser identities for processes holding a specific file."""
    rm, _ = _apis()
    with _session(rm) as session:
        files = (w.LPCWSTR * 1)(str(Path(path).resolve()))
        status = rm.RmRegisterResources(session, 1, files, 0, None, 0, None)
        if status:
            raise OSError(status, "Windows could not inspect the browser file")
        for _ in range(3):
            needed, count, reason = w.UINT(), w.UINT(), w.DWORD()
            status = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
            if status == 0:
                return []
            if status != 234:
                raise OSError(status, "Windows could not identify file owners")
            info = (ProcessInfo * needed.value)()
            count.value = needed.value
            status = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), info, ctypes.byref(reason))
            if status == 234:
                continue
            if status:
                raise OSError(status, "Windows could not identify file owners")
            browsers = []
            for row in info[:count.value]:
                identity = _process_identity(row.process.pid)
                created = (row.process.started.dwHighDateTime << 32) | row.process.started.dwLowDateTime
                if identity and identity["executable"] in BROWSERS and identity["started"] == created:
                    browsers.append(identity)
            return browsers
        raise OSError("Browser processes changed during lock inspection; scan again")


def describe_failure(path, error):
    """Keep errors explicit; an unavailable source is never treated as empty."""
    owners = []
    code = getattr(error, "sqlite_errorcode", 0) or 0
    locked = code & 0xFF in {5, 6} or "locked" in str(error).lower()
    candidate = locked or code & 0xFF == 14 or "unable to open" in str(error).lower() or isinstance(error, PermissionError)
    if candidate:
        try:
            owners = file_users(path)
        except OSError:
            pass
    if owners:
        names = ", ".join(f"{BROWSERS[p['executable']]} (PID {p['pid']})" for p in owners)
        return {"reason": "browser_running", "blocked_by": owners,
                "message": f"{names} still holds this file, even when its windows are closed. Use 'Close browsers and rescan'."}
    return {"reason": "file_locked" if locked else "source_unavailable", "blocked_by": [],
            "message": ("This file is locked, but Windows did not identify a Chrome/Edge owner. " if locked else
                        "This browser file could not be read; no Chrome/Edge owner was confirmed. ") + str(error)}


def close_browsers(processes, *, allow_background_stop=False):
    """Request normal exit of the user-selected, still-verified browser processes.

    The default requests normal exit only. The explicit-consent fallback can
    stop verified windowless browsers if Windows refuses normal shutdown.
    There are no broad process-name kills, lock bypasses or browser restarts.
    """
    targets = []
    for expected in {p["pid"]: p for p in processes}.values():
        actual = _process_identity(expected["pid"])
        if actual is None:
            continue
        if actual != expected or actual["executable"] not in BROWSERS:
            raise RuntimeError("A lock-owning process changed. Rescan before closing browsers.")
        targets.append(actual)
    if not targets:
        return
    if allow_background_stop and any(has_visible_windows(p["pid"]) for p in targets):
        raise RuntimeError("Close Chrome/Edge windows first; background shutdown does not close visible browser windows.")
    rm, _ = _apis()
    identities = (UniqueProcess * len(targets))()
    for row, target in zip(identities, targets):
        row.pid = target["pid"]
        row.started.dwLowDateTime = target["started"] & 0xFFFFFFFF
        row.started.dwHighDateTime = target["started"] >> 32
    with _session(rm) as session:
        status = rm.RmRegisterResources(session, 0, None, len(targets), identities, 0, None)
        if status:
            raise OSError(status, "Windows could not register the selected browsers")
        status = rm.RmShutdown(session, 0, None)  # RmForceShutdown is deliberately never used.
        if status:
            if allow_background_stop and status == 351:
                _stop_background(targets)
            else:
                raise OSError(status, "A browser did not exit normally. Save browser work and use Chrome/Edge menu > Exit, then rescan.")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not any(_process_identity(p["pid"]) == p for p in targets):
            return
        time.sleep(0.2)
    raise RuntimeError("A browser is still running. It was not force-closed; exit it fully and rescan.")


def close_browser_windows(timeout=20.0):
    """Ask every visible Chrome/Edge window to close, exactly like clicking its X (WM_CLOSE).

    Needed because the Cookies lock belongs to a background network process that the browser
    restarts at once while any window is open. Returns the executable paths that were running,
    so the caller can reopen them with their last session. Never terminates anything itself.
    """
    if os.name != "nt":
        raise OSError("Browser window closing is available on Windows only")
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    _, kernel = _apis()

    def browser_windows():
        found = []

        @callback_type
        def visit(hwnd, param):
            owner = w.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if user.IsWindowVisible(hwnd):
                found.append((hwnd, owner.value))
            return True
        user.EnumWindows(visit, 0)
        out, cache = [], {}
        for hwnd, pid in found:
            if pid not in cache:
                cache[pid] = _image_path(kernel, pid)
            path = cache[pid]
            if path and Path(path).name.lower() in BROWSERS:
                out.append((hwnd, path))
        return out

    windows = browser_windows()
    paths = sorted({p for _, p in windows})
    for hwnd, _ in windows:
        user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE: normal close, the browser saves its session
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and browser_windows():
        time.sleep(0.3)
    if browser_windows():
        raise RuntimeError("A browser window did not close (it may be asking a question). Close it and scan again.")
    return paths


def _image_path(kernel, pid):
    handle = kernel.OpenProcess(0x1000, False, pid)  # query only
    if not handle:
        return None
    try:
        size = w.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        return buf.value if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else None
    finally:
        kernel.CloseHandle(handle)


def reopen_browsers(paths):
    """Start each browser again with its previous tabs."""
    import subprocess
    for path in paths:
        if Path(path).name.lower() in BROWSERS and Path(path).is_file():
            subprocess.Popen([path, "--restore-last-session"], close_fds=True,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
