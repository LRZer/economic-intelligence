"""Bind a Windows worker to its verified launcher and retained process handle."""
from __future__ import annotations
import ctypes
import os


def parent_pid(pid: int) -> int:
    class Entry(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('usage', ctypes.c_uint32), ('pid', ctypes.c_uint32),
                    ('heap', ctypes.c_size_t), ('module', ctypes.c_uint32), ('threads', ctypes.c_uint32),
                    ('parent', ctypes.c_uint32), ('priority', ctypes.c_long), ('flags', ctypes.c_uint32),
                    ('exe', ctypes.c_wchar * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise RuntimeError('Unable to verify owned worker parent')
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        valid = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while valid:
            if entry.pid == pid:
                return int(entry.parent)
            valid = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    raise RuntimeError('Owned worker no longer exists')


class OwnedProcess:
    def __init__(self, pid: int, expected_parent: int):
        if os.name != 'nt' or type(pid) is not int or pid <= 0 or parent_pid(pid) != expected_parent:
            raise RuntimeError('Model process is not a verified child of our launcher')
        self.pid = pid
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.kernel.OpenProcess.restype = ctypes.c_void_p
        self.kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self.kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000 | 0x0001, False, pid)
        if not self.handle:
            raise RuntimeError('Owned model process handle unavailable')

    def alive(self) -> bool:
        code = ctypes.c_uint32()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise RuntimeError('Owned process status unavailable')
        return code.value == 259

    def terminate(self) -> None:
        if self.alive() and not self.kernel.TerminateProcess(self.handle, 1):
            raise RuntimeError('Unable to stop owned model process')

    def close(self) -> None:
        self.kernel.CloseHandle(self.handle)
