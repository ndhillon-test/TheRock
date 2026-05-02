#!/usr/bin/env python3
"""
Test script to run directly on Shark server to diagnose offload-arch behavior.
This helps isolate whether the issue is Python subprocess in general, or
specifically when run under GitHub Actions runner context.

Usage: python test_offload_arch_direct.py <path_to_offload_arch.exe>
"""

import subprocess
import os
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print("Usage: python test_offload_arch_direct.py <path_to_offload_arch.exe>")
    print("Example: python test_offload_arch_direct.py C:/actions-runner/_work/TheRock/TheRock/build/lib/llvm/bin/offload-arch.exe")
    sys.exit(1)

offload_arch = Path(sys.argv[1])
if not offload_arch.exists():
    print(f"ERROR: File not found: {offload_arch}")
    sys.exit(1)

print(f"Testing offload-arch: {offload_arch}")
print(f"File size: {offload_arch.stat().st_size} bytes")
print("=" * 80)

# Test 1: Direct execution (what we do at command line)
print("\n### Test 1: Direct execution (os.system)")
print("Command: offload-arch.exe")
exit_code = os.system(f'"{offload_arch}"')
print(f"Exit code: {exit_code}")
print("=" * 80)

# Test 2: Python subprocess with shell=False (what fails in CI)
print("\n### Test 2: Python subprocess.run(shell=False)")
print("This is what the test_rocm_sanity.py test does")
result2 = subprocess.run(
    [str(offload_arch)],
    capture_output=True,
    text=True,
    shell=False
)
print(f"Exit code: {result2.returncode}")
print(f"Stdout: {result2.stdout}")
print(f"Stderr: {result2.stderr}")
print("=" * 80)

# Test 3: Python subprocess with shell=True
print("\n### Test 3: Python subprocess.run(shell=True)")
result3 = subprocess.run(
    str(offload_arch),
    capture_output=True,
    text=True,
    shell=True
)
print(f"Exit code: {result3.returncode}")
print(f"Stdout: {result3.stdout}")
print(f"Stderr: {result3.stderr}")
print("=" * 80)

# Test 4: Through bash (what works in CI workflow debug step)
print("\n### Test 4: Python subprocess through bash")
result4 = subprocess.run(
    ["bash", "-c", str(offload_arch)],
    capture_output=True,
    text=True,
    shell=False
)
print(f"Exit code: {result4.returncode}")
print(f"Stdout: {result4.stdout}")
print(f"Stderr: {result4.stderr}")
print("=" * 80)

# Test 5: Through cmd.exe
print("\n### Test 5: Python subprocess through cmd.exe")
result5 = subprocess.run(
    ["cmd.exe", "/c", str(offload_arch)],
    capture_output=True,
    text=True,
    shell=False
)
print(f"Exit code: {result5.returncode}")
print(f"Stdout: {result5.stdout}")
print(f"Stderr: {result5.stderr}")
print("=" * 80)

# Test 6: With verbose HIP logging
print("\n### Test 6: Python subprocess with verbose HIP logging")
env = os.environ.copy()
env["AMD_LOG_LEVEL"] = "7"
env["HIP_ENABLE_GPU_LOG"] = "1"
env["HIP_VISIBLE_DEVICES"] = "0"
result6 = subprocess.run(
    [str(offload_arch)],
    capture_output=True,
    text=True,
    shell=False,
    env=env
)
print(f"Exit code: {result6.returncode}")
print(f"Stdout: {result6.stdout}")
print(f"Stderr: {result6.stderr}")
print("=" * 80)

# Summary
print("\n### SUMMARY")
print(f"Test 1 (os.system):           {'PASS' if exit_code == 0 else 'FAIL'}")
print(f"Test 2 (subprocess shell=False): {'PASS' if result2.returncode == 0 else 'FAIL'}")
print(f"Test 3 (subprocess shell=True):  {'PASS' if result3.returncode == 0 else 'FAIL'}")
print(f"Test 4 (via bash):               {'PASS' if result4.returncode == 0 else 'FAIL'}")
print(f"Test 5 (via cmd.exe):            {'PASS' if result5.returncode == 0 else 'FAIL'}")
print(f"Test 6 (verbose logging):        {'PASS' if result6.returncode == 0 else 'FAIL'}")
print("\nIf Test 2 fails but Test 1/4 pass, then the issue is Python subprocess context")
print("If all tests pass, then the issue is specific to GitHub Actions runner environment")
