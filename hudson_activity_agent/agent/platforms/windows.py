"""Windows probes using only ctypes (no pywin32 dependency)."""
import ctypes
import os
import subprocess
import winreg
from ctypes import wintypes
from functools import lru_cache

from .. import APP_NAME
from . import Foreground

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
version = ctypes.WinDLL("version", use_last_error=True)


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.restype = wintypes.BOOL

kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
version.GetFileVersionInfoW.restype = wintypes.BOOL
version.VerQueryValueW.argtypes = [
    ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
version.VerQueryValueW.restype = wintypes.BOOL

user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBoxW.restype = ctypes.c_int

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_READOBJECTS = 0x0001
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# ----------------------------------------------------------------- idle / lock
def idle_seconds() -> float:
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    # dwTime is a 32-bit tick count: compare modulo 2**32 so wrap-around (49.7 days) is safe.
    tick = kernel32.GetTickCount64() & 0xFFFFFFFF
    return ((tick - lii.dwTime) % 2**32) / 1000.0


def _session_locked() -> bool:
    # While the workstation is locked the input desktop is "Winlogon", which a
    # normal user process cannot open.
    handle = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
    if not handle:
        return True
    user32.CloseDesktop(handle)
    return False


# ------------------------------------------------------------------ processes
def _pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _process_path(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def _uwp_child_pid(hwnd, host_pid):
    """Store apps (Calculator, Settings...) run inside ApplicationFrameHost.exe;
    the real app owns one of the frame's child windows."""
    found = []

    @WNDENUMPROC
    def callback(child, _lparam):
        pid = _pid(child)
        if pid and pid != host_pid:
            found.append(pid)
            return False
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return found[0] if found else None


@lru_cache(maxsize=512)
def _friendly_name(path: str) -> str:
    """FileDescription from the exe's version resource, e.g. 'Google Chrome'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return stem
        buf = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buf):
            return stem
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        langs = []
        if (version.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(length))
                and length.value >= 4):
            lang, codepage = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
            langs.append(f"{lang:04x}{codepage:04x}")
        langs += ["040904b0", "040904e4", "000004b0"]
        for key in ("FileDescription", "ProductName"):
            for lang in langs:
                if (version.VerQueryValueW(buf, f"\\StringFileInfo\\{lang}\\{key}",
                                           ctypes.byref(ptr), ctypes.byref(length))
                        and length.value > 1):
                    value = ctypes.wstring_at(ptr, length.value).rstrip("\x00").strip()
                    if value:
                        return value
    except OSError:
        pass
    return stem


def _window_title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return None
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value or None


def foreground(capture_title: bool = True) -> Foreground:
    if _session_locked():
        return Foreground(locked=True)
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return Foreground()
    pid = _pid(hwnd)
    path = _process_path(pid) if pid else None
    if path and os.path.basename(path).lower() == "applicationframehost.exe":
        child = _uwp_child_pid(hwnd, pid)
        if child:
            path = _process_path(child) or path
    process = os.path.basename(path) if path else None
    if process and process.lower() == "lockapp.exe":
        return Foreground(locked=True)
    return Foreground(
        app=_friendly_name(path) if path else None,
        process=process,
        title=_window_title(hwnd) if capture_title else None,
    )


# ----------------------------------------------------------------- autostart
def install_autostart(command):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, subprocess.list2cmdline(command))


def remove_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass


def message(title, text, yes_no=False) -> bool:
    """Native message box. Returns True for OK / Yes."""
    MB_YESNO, MB_ICONINFORMATION, MB_SETFOREGROUND, MB_TOPMOST = 0x4, 0x40, 0x10000, 0x40000
    flags = MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST | (MB_YESNO if yes_no else 0)
    result = user32.MessageBoxW(None, text, title, flags)
    return result == (6 if yes_no else 1)  # IDYES / IDOK


def run_main_loop(stop_event):
    while not stop_event.wait(0.5):
        pass
