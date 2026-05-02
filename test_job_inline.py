import ctypes
from ctypes import wintypes
import subprocess
import sys

def check_job():
    k32 = ctypes.windll.kernel32
    pid = k32.GetCurrentProcessId()
    h = k32.OpenProcess(0x1400, False, pid)
    ij = wintypes.BOOL()
    k32.IsProcessInJob(h, None, ctypes.byref(ij))

    print(f'PID: {pid}')
    print(f'In Job: {bool(ij)}')

    if not ij:
        print('Not in Job Object')
        k32.CloseHandle(h)
        return

    class JBLI(ctypes.Structure):
        _fields_ = [
            ('a', wintypes.LARGE_INTEGER),
            ('b', wintypes.LARGE_INTEGER),
            ('LimitFlags', wintypes.DWORD),
            ('c', ctypes.c_size_t),
            ('d', ctypes.c_size_t),
            ('e', wintypes.DWORD),
            ('f', ctypes.POINTER(wintypes.ULONG)),
            ('g', wintypes.DWORD),
            ('h', wintypes.DWORD)
        ]

    class IOC(ctypes.Structure):
        _fields_ = [('a', wintypes.ULARGE_INTEGER)] * 6

    class JELI(ctypes.Structure):
        _fields_ = [
            ('BasicLimitInformation', JBLI),
            ('IoInfo', IOC),
            ('a', ctypes.c_size_t),
            ('b', ctypes.c_size_t),
            ('c', ctypes.c_size_t),
            ('d', ctypes.c_size_t)
        ]

    ji = JELI()
    rl = wintypes.DWORD()
    k32.QueryInformationJobObject(None, 9, ctypes.byref(ji), ctypes.sizeof(ji), ctypes.byref(rl))

    flags = ji.BasicLimitInformation.LimitFlags
    print(f'Flags: 0x{flags:04X}')
    print(f'BREAKAWAY_OK: {bool(flags & 0x800)}')
    print(f'KILL_ON_JOB_CLOSE: {bool(flags & 0x2000)}')

    k32.CloseHandle(h)

if len(sys.argv) > 1 and sys.argv[1] == 'test-depth':
    print("=== DEPTH 0: Direct ===")
    check_job()
    print()
    print("=== DEPTH 1: Subprocess ===")
    subprocess.run([sys.executable, __file__])
else:
    check_job()
