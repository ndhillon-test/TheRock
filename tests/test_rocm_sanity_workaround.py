# Copyright Advanced Micro Devices, Inc.
# SPDX-License-Identifier: MIT

"""
GPU Access Workaround Test

This test demonstrates the solution to the Windows GHA subprocess GPU access issue.
It uses pre-detected GPU architecture from the workflow level instead of running
offload-arch from within Python subprocess.

For comparison, run this alongside test_rocm_sanity.py to see:
- Original test: May fail on Windows GHA due to subprocess GPU access blocking
- This test: Should pass by using workflow-level GPU detection

Investigation: https://github.com/ROCm/TheRock/issues/4617
"""

from pathlib import Path
from pytest_check import check
import logging
import os
import platform
import pytest
import shlex
import subprocess
import sys

THIS_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

THEROCK_BIN_DIR = Path(os.getenv("THEROCK_BIN_DIR")).resolve()

# Importing is_asan from github_actions_api.py
sys.path.append(str(THIS_DIR.parent / "build_tools" / "github_actions"))
from github_actions_api import is_asan


def is_windows():
    return "windows" == platform.system().lower()


def run_command(command: list[str], cwd=None, env=None):
    logger.info(f"++ Run [{cwd}]$ {shlex.join(command)}")

    process = subprocess.run(
        command, capture_output=True, cwd=cwd, shell=False, text=True, env=env
    )
    if process.returncode != 0:
        logger.error(f"Command failed!")
        logger.error("command stdout:")
        for line in process.stdout.splitlines():
            logger.error(line)
        logger.error("command stderr:")
        for line in process.stderr.splitlines():
            logger.error(line)
        raise Exception(f"Command failed: `{shlex.join(command)}`, see output above")
    return process


class TestROCmSanityWorkaround:
    """
    Test ROCm GPU detection and HIP compilation using the workaround approach.

    This test uses pre-detected GPU architecture from environment variable
    on Windows to avoid subprocess GPU access issues in GitHub Actions.
    """

    # TODO(#3313): Re-enable once hipcc test is fixed for ASAN builds
    @pytest.mark.skipif(
        is_asan(), reason="hipcc test fails with ASAN build, see TheRock#3313"
    )
    def test_hip_printf_with_workaround(self):
        """Test HIP compilation using workflow-detected GPU architecture."""
        platform_executable_suffix = ".exe" if is_windows() else ""

        # WORKAROUND: Use pre-detected GPU arch from workflow environment variable
        # This avoids the subprocess GPU access issue at depth 2+ in Windows GHA.
        #
        # Root cause investigation found:
        # - SSH session: subprocess CAN access GPU (breakaway allowed)
        # - GHA workflow depth 0 (bash): CAN access GPU
        # - GHA workflow depth 1+ (Python subprocess): CANNOT access GPU
        # - Job Object has SILENT_BREAKAWAY_OK in both SSH and GHA
        # - Issue is NOT Job Object blocking, but Windows service session + GPU driver interaction
        #
        # Solution: Detect GPU at workflow bash level (depth 0) and pass via env var
        detected_gpu_arch = os.getenv("DETECTED_GPU_ARCH")

        if is_windows() and detected_gpu_arch:
            logger.info(f"[WORKAROUND] Using pre-detected GPU arch from workflow: {detected_gpu_arch}")
            logger.info("This avoids subprocess GPU access issue in Windows GHA environment")
            offload_arch = detected_gpu_arch
        else:
            # Linux or no pre-detection - run offload-arch normally
            offload_arch_executable_file = f"offload-arch{platform_executable_suffix}"
            offload_arch_path = (
                THEROCK_BIN_DIR
                / ".."
                / "lib"
                / "llvm"
                / "bin"
                / offload_arch_executable_file
            ).resolve()

            logger.info(f"Running offload-arch from: {offload_arch_path}")
            logger.info(f"offload-arch exists: {offload_arch_path.exists()}")

            process = run_command([str(offload_arch_path)])

            # Extract the arch from output
            offload_arch = None
            for line in process.stdout.splitlines():
                if "gfx" in line:
                    offload_arch = line
                    break
            assert (
                offload_arch is not None
            ), f"Expected offload-arch to return gfx####, got:\n{process.stdout}"

        logger.info(f"Using GPU architecture: {offload_arch}")

        # Compile test program using hipcc
        hipcc_check_executable_file = f"hipcc_check_workaround{platform_executable_suffix}"
        run_command(
            [
                f"{THEROCK_BIN_DIR}/hipcc",
                str(THIS_DIR / "hipcc_check.cpp"),
                "-Xlinker",
                f"-rpath={THEROCK_BIN_DIR}/../lib/",
                f"--offload-arch={offload_arch}",
                "-o",
                hipcc_check_executable_file,
            ],
            cwd=str(THEROCK_BIN_DIR),
        )

        # Run the compiled executable
        platform_executable_prefix = "./" if not is_windows() else ""
        hipcc_check_executable = f"{platform_executable_prefix}hipcc_check_workaround"
        process = run_command([hipcc_check_executable], cwd=str(THEROCK_BIN_DIR))
        check.equal(process.returncode, 0)
        check.greater(
            os.path.getsize(str(THEROCK_BIN_DIR / hipcc_check_executable_file)), 0
        )

        logger.info("✓ HIP compilation and execution successful with workaround approach")

    def test_gpu_detection_diagnostic(self):
        """
        Diagnostic test to document GPU detection behavior.

        This test documents the findings from the investigation:
        - Shows what environment variables are available
        - Confirms the workaround is in place
        - Logs the execution context
        """
        logger.info("=== GPU Detection Diagnostic ===")
        logger.info(f"Platform: {platform.system()}")
        logger.info(f"Python: {sys.executable}")
        logger.info(f"Process depth: pytest → test (depth 2)")

        detected_gpu_arch = os.getenv("DETECTED_GPU_ARCH")
        logger.info(f"DETECTED_GPU_ARCH env var: {detected_gpu_arch or '<not set>'}")

        if is_windows():
            if detected_gpu_arch:
                logger.info("✓ Workaround active: Using workflow-detected GPU architecture")
                logger.info("  This avoids subprocess GPU access limitation in Windows GHA")
            else:
                logger.warning("! Workaround not active: DETECTED_GPU_ARCH not set")
                logger.warning("  Test may fail if running in Windows GHA environment")
        else:
            logger.info("Linux: No workaround needed, GPU access works normally")

        logger.info("=== End Diagnostic ===")

        # Test always passes - it's just for logging
        assert True
