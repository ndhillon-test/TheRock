# Testing Job Object Configuration

## The Key Question

You're absolutely right - when you ran the Python script directly on the server, it created subprocesses THE SAME WAY as the test does, and they all worked. This proves:

**The issue is NOT Python subprocess** - it's **GitHub Actions runner's Job Object isolation**

## Test This Theory

### 1. Run via SSH (Direct on Server)
```powershell
cd C:\actions-runner\_work\TheRock\TheRock
python check_job_object.py
```

**Expected**: "Not in Job Object" (no restrictions)

### 2. Add Workflow Step to Check Inside GHA

Add this step to `.github/workflows/test_component.yml` after "Setup Visual Studio Environment":

```yaml
- name: Check Job Object Settings (Diagnostic)
  if: ${{ runner.os == 'Windows' }}
  shell: bash
  run: |
    echo "=== Depth 0 (bash in workflow) ==="
    python check_job_object.py

    echo ""
    echo "=== Depth 1 (from venv Python) ==="
    python -c "
import subprocess
subprocess.run(['python', 'check_job_object.py'])
"
```

**Expected**:
- Depth 0: In Job Object, but GPU still accessible
- Depth 1: In Job Object, GPU access blocked

## What to Look For

The output will show if `BREAKAWAY_OK` or `SILENT_BREAKAWAY_OK` is set:

**If BREAKAWAY_OK is NOT set**:
- Subprocesses CANNOT escape the Job Object
- They inherit all Job Object restrictions
- **This could be blocking GPU access propagation**

**If KILL_ON_JOB_CLOSE is set**:
- All processes die when workflow ends (this is normal)
- But combined with no breakaway, keeps everything locked in

## Possible Fix (If We Find the Right Setting)

If the Job Object settings are too restrictive, we might be able to:

1. **Modify GHA runner service** to use different Job Object flags
2. **Update runner configuration** if there's a setting for this
3. **Run runner differently** (less likely to work)

But we need to see the actual settings first to know if this is fixable.

---

## Summary

Your observation is **100% correct**: Direct SSH execution proves Python subprocess CAN work with GPU on this Windows machine. The problem is specifically the GitHub Actions runner's process isolation, not Windows or Python itself.

The `check_job_object.py` script will tell us exactly what restrictions the runner is imposing.
