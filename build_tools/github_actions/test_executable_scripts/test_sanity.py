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
