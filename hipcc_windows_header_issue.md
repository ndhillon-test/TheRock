# hipcc Header Path Issue on Windows GitHub Actions Runners

## Problem Statement

HIP code compilation fails on Windows GitHub Actions runners with the error:
```
error: use of undeclared identifier '__AMDGCN_WAVEFRONT_SIZE'
```

This occurs in `amd_warp_functions.h` when compiling with hipcc, even though the build artifacts contain all necessary headers.

## Root Cause

**hipcc uses system ROCm 6.4 headers instead of build headers**, causing a version mismatch between:
- Build's clang compiler (expects `__AMDGCN_WAVEFRONT_SIZE` to be defined)
- System ROCm 6.4 headers (define this symbol differently or not at all)

### Why This Happens

1. **hipcc looks for `.hipVersion` file** to determine HIP installation directory
   - On Windows builds, `build/bin/.hipVersion` does not exist
   - Without this file, hipcc cannot determine the correct installation path

2. **Setting `HIP_PATH` environment variable is insufficient**
   - hipcc on Windows does not use `HIP_PATH` to add include directories
   - Even with `HIP_PATH` set, hipcc still defaults to system headers

3. **hipcc falls back to system ROCm installation**
   - Finds `C:\Program Files\AMD\ROCm\6.4\` via system PATH
   - Uses incompatible headers from this installation

### Evidence

Compilation command shows **no `-I` flag** pointing to build headers:
```
clang.exe --offload-arch=gfx1100 -O3 --driver-mode=g++ ... <source.cpp>
```

Error path confirms system headers are being used:
```
C:\Program Files\AMD\ROCm\6.4\include\hip/amd_detail\amd_warp_functions.h:87:33: error
```

Build actually contains the correct headers:
```
build/include/hip/hip_runtime.h ✓ exists
build/include/hip/amd_detail/amd_warp_functions.h ✓ exists
```

## Solution

Use `HIPCC_COMPILE_FLAGS_APPEND` environment variable to explicitly add build include path:

```python
os.environ["HIPCC_COMPILE_FLAGS_APPEND"] = f"-I{build_directory}/include"
```

This forces hipcc to prepend the build include directory, ensuring build headers are found before system headers.

### Why This Works

- `HIPCC_COMPILE_FLAGS_APPEND` is processed by hipcc wrapper before invoking clang
- The `-I` flag is added to the compilation command
- Compiler search order: explicit `-I` paths → system includes
- Build headers are found first and used successfully

## Test Results

| Configuration | Without Fix | With Fix |
|--------------|-------------|----------|
| Self-hosted runner | ❌ Failed | ✅ Passed |
| Runner-controller managed | ❌ Failed | ✅ Passed |

Both runner configurations show identical behavior, confirming the issue is header path resolution, not runner orchestration.

## Implementation

See `tests/test_rocm_sanity_workaround.py` for working implementation:

```python
if sys.platform == "win32":
    output_artifacts_dir = Path(os.getenv("OUTPUT_ARTIFACTS_DIR", "./build")).resolve()
    build_include_path = str(output_artifacts_dir / "include")
    test_env = os.environ.copy()
    test_env["HIPCC_COMPILE_FLAGS_APPEND"] = f"-I{build_include_path}"

    # Use test_env when calling hipcc
    subprocess.run([hipcc_path, ...], env=test_env)
```

## Related Issues

- Initial misdiagnosis: GPU detection was thought to be failing in subprocess
- Reality: offload-arch worked correctly at all subprocess depths
- The compilation failure was masked by GPU detection debugging

## Platform Specifics

**Linux**: hipcc correctly uses `HIP_PATH` environment variable and rocm_agent_enumerator

**Windows**: hipcc requires explicit `-I` flags via `HIPCC_COMPILE_FLAGS_APPEND` because:
- `.hipVersion` file is missing from build artifacts
- `HIP_PATH` environment variable is not respected for include paths
- System ROCm installation takes precedence
