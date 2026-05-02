# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)

SCRIPT_DIR = Path(__file__).resolve().parent
THEROCK_DIR = SCRIPT_DIR.parent.parent.parent

# Enable verbose ROCm logging, see
# https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/debugging.html
# Note: ROCM_KPACK_DEBUG is set for all components by test_component.yml.
os.environ["AMD_LOG_LEVEL"] = "4"

# The sanity checks run tools like 'offload-arch' which may search for DLLs on
# multiple search paths (PATH, CWD, system32, etc.).
# On Windows, the build artifacts do not include HSA runtime DLLs (hsa-runtime64.dll, etc.),
# so we must use system ROCm DLLs from system32 for the sanity test to work.
# The build/bin amdhip64_7.dll cannot initialize without the HSA runtime.
if sys.platform == "win32":
    output_artifacts_dir = Path(os.getenv("OUTPUT_ARTIFACTS_DIR", "./build")).resolve()
    os.environ["HIP_CLANG_PATH"] = str(output_artifacts_dir / "lib" / "llvm" / "bin")
    # Do NOT prepend build/bin to PATH - it lacks HSA runtime DLLs
    # Let offload-arch use system32 DLLs which have complete runtime
    logging.info(f"Using system ROCm DLLs for sanity test (build lacks HSA runtime DLLs)")

    # DIAGNOSTIC: Test GPU access at different subprocess depths
    # This helps identify where GPU access is lost in the process hierarchy:
    # GHA Runner → bash → test_sanity.py → pytest → test_rocm_sanity.py → offload-arch
    logging.info("=== GPU Access Diagnostic: Testing at subprocess depth 1 ===")
    offload_arch = output_artifacts_dir / "lib" / "llvm" / "bin" / "offload-arch.exe"

    # Test 1: Direct subprocess.run(shell=False) from test_sanity.py
    logging.info("Test 1: subprocess.run(shell=False)")
    result1 = subprocess.run([str(offload_arch)], capture_output=True, text=True, shell=False)
    logging.info(f"  Exit code: {result1.returncode}")
    logging.info(f"  Stdout: {result1.stdout[:100] if result1.stdout else '<empty>'}")
    logging.info(f"  Stderr: {result1.stderr[:100] if result1.stderr else '<empty>'}")

    # Test 2: subprocess.run(shell=True)
    logging.info("Test 2: subprocess.run(shell=True)")
    result2 = subprocess.run(str(offload_arch), capture_output=True, text=True, shell=True)
    logging.info(f"  Exit code: {result2.returncode}")
    logging.info(f"  Stdout: {result2.stdout[:100] if result2.stdout else '<empty>'}")
    logging.info(f"  Stderr: {result2.stderr[:100] if result2.stderr else '<empty>'}")

    # Test 3: os.system (redirecting to temp file to capture output)
    logging.info("Test 3: os.system")
    temp_output = output_artifacts_dir / "offload_arch_test3.txt"
    exit_code = os.system(f'"{offload_arch}" > "{temp_output}" 2>&1')
    test3_output = temp_output.read_text() if temp_output.exists() else "<no output>"
    logging.info(f"  Exit code: {exit_code}")
    logging.info(f"  Output: {test3_output[:100]}")
    if temp_output.exists():
        temp_output.unlink()

    # Test 4: Through cmd.exe
    logging.info("Test 4: subprocess via cmd.exe")
    result4 = subprocess.run(["cmd.exe", "/c", str(offload_arch)], capture_output=True, text=True, shell=False)
    logging.info(f"  Exit code: {result4.returncode}")
    logging.info(f"  Stdout: {result4.stdout[:100] if result4.stdout else '<empty>'}")
    logging.info(f"  Stderr: {result4.stderr[:100] if result4.stderr else '<empty>'}")

    # Test 5: Through bash
    logging.info("Test 5: subprocess via bash")
    bash_path = str(offload_arch).replace("\\", "/")
    result5 = subprocess.run(["bash", "-c", bash_path], capture_output=True, text=True, shell=False)
    logging.info(f"  Exit code: {result5.returncode}")
    logging.info(f"  Stdout: {result5.stdout[:100] if result5.stdout else '<empty>'}")
    logging.info(f"  Stderr: {result5.stderr[:100] if result5.stderr else '<empty>'}")

    logging.info("=== End GPU Access Diagnostic ===")
    logging.info("")

cmd = [
    sys.executable,
    "-m",
    "pytest",
    "tests/",
    "--log-cli-level=info",
    "--timeout=300",
]

logging.info(f"++ Exec [{THEROCK_DIR}]$ {' '.join(cmd)}")

# Don't pass explicit env parameter - let subprocess inherit os.environ naturally
# to preserve GPU visibility context on Windows
subprocess.run(cmd, cwd=THEROCK_DIR, check=True)
