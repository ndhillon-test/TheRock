#!/usr/bin/env python3
"""
Check if this process is running in a Windows Job Object and what restrictions it has.
Run this both via SSH and inside GHA workflow to compare.

Usage: python check_job_object.py
"""

import sys
import ctypes
from ctypes import wintypes

if sys.platform != "win32":
    print("This script only works on Windows")
    sys.exit(1)

# Windows API definitions
kernel32 = ctypes.windll.kernel32

# Constants
PROCESS_QUERY_INFORMATION = 0x0400
JobObjectBasicLimitInformation = 2
JobObjectExtendedLimitInformation = 9

class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(wintypes.ULONG)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", wintypes.ULARGE_INTEGER),
        ("WriteOperationCount", wintypes.ULARGE_INTEGER),
        ("OtherOperationCount", wintypes.ULARGE_INTEGER),
        ("ReadTransferCount", wintypes.ULARGE_INTEGER),
        ("WriteTransferCount", wintypes.ULARGE_INTEGER),
        ("OtherTransferCount", wintypes.ULARGE_INTEGER),
    ]

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

# Limit flags
JOB_OBJECT_LIMIT_WORKINGSET = 0x00000001
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_AFFINITY = 0x00000010
JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x00000020
JOB_OBJECT_LIMIT_PRESERVE_JOB_TIME = 0x00000040
JOB_OBJECT_LIMIT_SCHEDULING_CLASS = 0x00000080
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_SUBSET_AFFINITY = 0x00004000

def check_job_object():
    """Check if current process is in a Job Object and print its settings."""

    # Get current process handle - need a real handle, not pseudo-handle
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    current_pid = kernel32.GetCurrentProcessId()
    current_process = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        current_pid
    )

    if not current_process:
        print(f"ERROR: OpenProcess failed with error {kernel32.GetLastError()}")
        return

    # Check if in job (NULL handle = check if in ANY job)
    is_in_job = wintypes.BOOL()
    result = kernel32.IsProcessInJob(current_process, None, ctypes.byref(is_in_job))

    if not result:
        error_code = kernel32.GetLastError()
        print(f"ERROR: IsProcessInJob failed with error {error_code}")
        kernel32.CloseHandle(current_process)
        return

    print(f"Process ID: {kernel32.GetCurrentProcessId()}")
    print(f"Is in Job Object: {bool(is_in_job)}")
    print()

    if not is_in_job:
        print("Not running in a Job Object - this is normal for SSH sessions")
        kernel32.CloseHandle(current_process)
        return

    # Get job object limits
    print("Job Object is active - getting limit information...")

    job_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    return_length = wintypes.DWORD()

    # Query the job object information
    result = kernel32.QueryInformationJobObject(
        None,  # NULL = query job of current process
        JobObjectExtendedLimitInformation,
        ctypes.byref(job_info),
        ctypes.sizeof(job_info),
        ctypes.byref(return_length)
    )

    if not result:
        error = kernel32.GetLastError()
        print(f"ERROR: QueryInformationJobObject failed with error {error}")
        return

    # Parse limit flags
    flags = job_info.BasicLimitInformation.LimitFlags
    print(f"\nLimit Flags: 0x{flags:08X}")
    print("\nActive Limits:")

    flag_names = {
        JOB_OBJECT_LIMIT_WORKINGSET: "WORKINGSET",
        JOB_OBJECT_LIMIT_PROCESS_TIME: "PROCESS_TIME",
        JOB_OBJECT_LIMIT_JOB_TIME: "JOB_TIME",
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS: "ACTIVE_PROCESS",
        JOB_OBJECT_LIMIT_AFFINITY: "AFFINITY",
        JOB_OBJECT_LIMIT_PRIORITY_CLASS: "PRIORITY_CLASS",
        JOB_OBJECT_LIMIT_PRESERVE_JOB_TIME: "PRESERVE_JOB_TIME",
        JOB_OBJECT_LIMIT_SCHEDULING_CLASS: "SCHEDULING_CLASS",
        JOB_OBJECT_LIMIT_PROCESS_MEMORY: "PROCESS_MEMORY",
        JOB_OBJECT_LIMIT_JOB_MEMORY: "JOB_MEMORY",
        JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION: "DIE_ON_UNHANDLED_EXCEPTION",
        JOB_OBJECT_LIMIT_BREAKAWAY_OK: "BREAKAWAY_OK",
        JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK: "SILENT_BREAKAWAY_OK",
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: "KILL_ON_JOB_CLOSE",
        JOB_OBJECT_LIMIT_SUBSET_AFFINITY: "SUBSET_AFFINITY",
    }

    for flag_value, flag_name in flag_names.items():
        if flags & flag_value:
            print(f"  ✓ {flag_name}")

    print("\nKey Settings:")
    print(f"  Active Process Limit: {job_info.BasicLimitInformation.ActiveProcessLimit}")
    print(f"  Process Memory Limit: {job_info.ProcessMemoryLimit:,} bytes")
    print(f"  Job Memory Limit: {job_info.JobMemoryLimit:,} bytes")

    # Check for breakaway (important for subprocess creation)
    if flags & JOB_OBJECT_LIMIT_BREAKAWAY_OK:
        print("\n⚠️  BREAKAWAY_OK is SET - processes CAN break away from job")
    elif flags & JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK:
        print("\n⚠️  SILENT_BREAKAWAY_OK is SET - processes can silently break away")
    else:
        print("\n❌ Breakaway NOT allowed - subprocesses stay in job object")
        print("   This may restrict GPU access inheritance!")

    if flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE:
        print("❌ KILL_ON_JOB_CLOSE is SET - all processes die when job closes")

    # Cleanup
    kernel32.CloseHandle(current_process)

if __name__ == "__main__":
    print("=" * 80)
    print("Windows Job Object Analysis")
    print("=" * 80)
    print()

    try:
        check_job_object()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 80)
    print("\nCompare results:")
    print("  1. Run via SSH - should show 'Not in Job Object'")
    print("  2. Run in GHA workflow - should show Job Object limits")
    print("=" * 80)
