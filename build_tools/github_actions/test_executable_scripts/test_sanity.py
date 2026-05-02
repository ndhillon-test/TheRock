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
# For typical "installs" of ROCm, the rocm/bin/ dir can be expected to be
# added to PATH, so we do that here. If we don't do this, DLLs on test runners
# in system32 may be picked up instead and the tests may not be representative,
# see https://github.com/ROCm/TheRock/issues/2019 and
# https://github.com/ROCm/TheRock/pull/3230#issuecomment-3844854922.
if sys.platform == "win32":
    output_artifacts_dir = Path(os.getenv("OUTPUT_ARTIFACTS_DIR", "./build")).resolve()
    os.environ["HIP_CLANG_PATH"] = str(output_artifacts_dir / "lib" / "llvm" / "bin")
    os.environ["PATH"] = str(output_artifacts_dir / "bin") + os.pathsep + os.environ.get("PATH", "")
    logging.info(f"Prepended build/bin to PATH for ROCm DLL loading")

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
