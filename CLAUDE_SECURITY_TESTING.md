# Claude Autonomous Security Testing for TheRock

This document describes how to integrate Claude as an autonomous dynamic application security testing (DAST) agent in the TheRock CI/CD pipeline.

## Overview

Claude will execute commands on built ROCm binaries during CI/CD to discover runtime security vulnerabilities. This is **fully automated** - Claude operates autonomously without requiring human input during execution.

### What Claude Does

1. **Dynamic Testing** - Executes binaries with edge cases, malformed inputs, boundary conditions
2. **Sanitizer Analysis** - Runs tests with ASAN/UBSAN/TSAN and interprets violations
3. **GPU-Specific Security** - Tests HIP/ROCm APIs with invalid parameters, race conditions, memory bugs
4. **Adaptive Exploration** - Adjusts testing strategy based on findings
5. **Automated Reporting** - Reports vulnerabilities with severity, reproduction steps, and suggested fixes

### Key Principle: Hardware Matching

Tests run on **self-hosted runners with AMD GPUs** matching the build target:
- `gfx90a` build → tested on `gfx90a` hardware (MI210/MI250)
- `gfx942` build → tested on `gfx942` hardware (MI300)
- `gfx1100` build → tested on `gfx1100` hardware (7900 XTX)

This ensures GPU kernel execution, driver interaction, and runtime behavior can be tested realistically.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Separate Workflows (Decoupled)                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Workflow 1: Build (separate workflow, not shown here)              │
│     └─> Compile ROCm with sanitizers enabled                        │
│     └─> Upload artifacts to S3 bucket                               │
│                                                                     │
│  Workflow 2: Test Setup (optional, separate workflow)               │
│     └─> Pull ROCm artifacts from S3                                 │
│     └─> Extract to local directory on GPU runner                    │
│     └─> Run developer test suite                                    │
│     └─> Leave extracted artifacts on runner (or pass path)          │
│                                                                     │
│  Workflow 3: Claude Security Testing (this workflow)                │
│     ├─> Option A: Pull from S3 yourself                             │
│     │   └─> Download ROCm artifacts from S3                         │
│     │   └─> Extract to local directory                              │
│     │                                                                │
│     ├─> Option B: Artifacts already extracted by prior workflow     │
│     │   └─> Receive directory path as input/env var                 │
│     │                                                                │
│     └─> Run Claude Security Agent                                   │
│         └─> Pass extracted ROCm directory path                      │
│         └─> Invoke claude_security_agent.py                         │
│         └─> Claude executes bash commands autonomously              │
│         └─> Claude probes binaries for vulnerabilities              │
│         └─> Generate security report                                │
│         └─> Comment findings on PR (if vulnerabilities found)       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Design:**
- **Build happens elsewhere** - separate workflow builds ROCm with sanitizers and pushes to S3
- **Claude workflow is decoupled** - can be triggered independently of builds
- **Artifacts from S3** - either pulled by this workflow or already extracted by another workflow
- **Just pass directory path** - Claude receives the local path to extracted ROCm installation

## Prerequisites

### 1. Self-Hosted Runners with AMD GPUs

Set up GitHub Actions self-hosted runners with AMD GPUs for each ISA you build:

**Runner Requirements:**
- AMD GPU installed and working
- ROCm drivers installed
- Docker support (optional but recommended for isolation)
- Labels: `self-hosted`, `gpu`, `gfx90a` (or appropriate ISA)

**Setup Example:**
```bash
# On your MI210 machine
cd /opt/actions-runner
./config.sh --url https://github.com/ROCm/TheRock --labels self-hosted,gpu,gfx90a
./run.sh
```

**Required Runner Labels:**
- `gfx90a` - MI210/MI250 systems
- `gfx942` - MI300 systems  
- `gfx1100` - RDNA3 (7900 XTX, etc.)
- `gfx1030` - RDNA2 (6900 XT, etc.)

### 2. GitHub Secrets

Add to repository secrets (Settings → Secrets and variables → Actions):

```
ANTHROPIC_API_KEY = sk-ant-...
```

Get API key from: https://console.anthropic.com/settings/keys

### 3. S3 Access

If pulling from S3 yourself (Option A):

```
AWS_ACCESS_KEY_ID = AKIA...
AWS_SECRET_ACCESS_KEY = ...
S3_BUCKET = your-rocm-builds-bucket
```

Add these to GitHub Secrets if the workflow needs to download from S3.

### 4. Required Files

Add these files to the repository:

```
.github/
├── workflows/
│   └── claude_security_testing.yml    # Main workflow
└── scripts/
    ├── claude_security_agent.py        # Invokes Claude API
    └── security_test_config.json       # Test configuration (optional)
```

## Implementation

### File 1: GitHub Actions Workflow

**`.github/workflows/claude_security_testing.yml`**

This workflow assumes ROCm artifacts have already been built (in a separate workflow) and pushed to S3.

```yaml
name: Claude Security Testing

on:
  # Trigger manually or via workflow_call from other workflows
  workflow_dispatch:
    inputs:
      gpu_target:
        description: 'GPU target to test (e.g., gfx90a)'
        required: true
        default: 'gfx90a'
      s3_artifact_path:
        description: 'S3 path to build artifact (e.g., s3://bucket/builds/gfx90a-sanitized.tar.gz)'
        required: false
      rocm_local_path:
        description: 'Local path to already-extracted ROCm (if already pulled by another workflow)'
        required: false
  
  workflow_call:
    inputs:
      gpu_target:
        description: 'GPU target to test'
        required: true
        type: string
      s3_artifact_path:
        description: 'S3 path to build artifact'
        required: false
        type: string
      rocm_local_path:
        description: 'Local path to extracted ROCm'
        required: false
        type: string
    secrets:
      ANTHROPIC_API_KEY:
        required: true
      AWS_ACCESS_KEY_ID:
        required: false
      AWS_SECRET_ACCESS_KEY:
        required: false

env:
  PYTHON_VERSION: '3.12'

jobs:
  claude-security-test:
    runs-on: [self-hosted, gpu, '${{ inputs.gpu_target }}']
    timeout-minutes: 120
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      
      - name: Install dependencies
        run: |
          pip install anthropic boto3 requests
      
      # OPTION A: Pull from S3 (if s3_artifact_path provided)
      - name: Download from S3
        if: inputs.s3_artifact_path != ''
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.AWS_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          AWS_DEFAULT_REGION: us-east-1
        run: |
          # Download artifact from S3
          aws s3 cp ${{ inputs.s3_artifact_path }} ./rocm-build.tar.gz
          
          # Extract
          mkdir -p rocm-extracted
          tar -xzf rocm-build.tar.gz -C rocm-extracted
          
          # Set ROCM_DIR for subsequent steps
          echo "ROCM_DIR=$PWD/rocm-extracted" >> $GITHUB_ENV
      
      # OPTION B: Use already-extracted path (if rocm_local_path provided)
      - name: Use pre-extracted ROCm
        if: inputs.rocm_local_path != ''
        run: |
          # Verify path exists
          if [ ! -d "${{ inputs.rocm_local_path }}" ]; then
            echo "Error: ROCm path not found: ${{ inputs.rocm_local_path }}"
            exit 1
          fi
          
          # Use the provided path
          echo "ROCM_DIR=${{ inputs.rocm_local_path }}" >> $GITHUB_ENV
      
      # Setup environment for ROCm
      - name: Setup ROCm environment
        run: |
          # Determine ROCm installation path
          if [ -d "$ROCM_DIR/build/dist/rocm" ]; then
            ROCM_PATH="$ROCM_DIR/build/dist/rocm"
          elif [ -d "$ROCM_DIR/dist/rocm" ]; then
            ROCM_PATH="$ROCM_DIR/dist/rocm"
          elif [ -d "$ROCM_DIR/rocm" ]; then
            ROCM_PATH="$ROCM_DIR/rocm"
          else
            ROCM_PATH="$ROCM_DIR"
          fi
          
          echo "ROCM_PATH=$ROCM_PATH" >> $GITHUB_ENV
          echo "LD_LIBRARY_PATH=$ROCM_PATH/lib:$LD_LIBRARY_PATH" >> $GITHUB_ENV
          echo "PATH=$ROCM_PATH/bin:$PATH" >> $GITHUB_ENV
          
          echo "Using ROCm at: $ROCM_PATH"
          ls -la "$ROCM_PATH"
      
      - name: Verify GPU availability
        run: |
          rocm-smi
          hipinfo | head -20
          echo "GPU_COUNT=$(rocm-smi --showbus | grep -c GPU)" >> $GITHUB_ENV
      
      - name: Run Claude Security Agent
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GPU_TARGET: ${{ inputs.gpu_target }}
        run: |
          python .github/scripts/claude_security_agent.py \
            --rocm-dir "$ROCM_DIR" \
            --gpu-target "$GPU_TARGET" \
            --gpu-count "$GPU_COUNT" \
            --report-output claude-security-report-${{ inputs.gpu_target }}.md \
            --max-runtime-minutes 90
        timeout-minutes: 100
        continue-on-error: true
      
      - name: Upload security report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: claude-security-report-${{ matrix.gpu_target }}
          path: |
            claude-security-report-${{ matrix.gpu_target }}.md
            claude-execution-log-${{ matrix.gpu_target }}.txt
            asan-*.log
            ubsan-*.log
            core.*
      
      - name: Check for critical findings
        if: always()
        id: check-findings
        run: |
          if grep -q "CRITICAL\|HIGH" claude-security-report-${{ matrix.gpu_target }}.md; then
            echo "has_critical=true" >> $GITHUB_OUTPUT
            echo "### :rotating_light: Critical Security Findings Detected" >> $GITHUB_STEP_SUMMARY
            grep -A 5 "CRITICAL\|HIGH" claude-security-report-${{ matrix.gpu_target }}.md >> $GITHUB_STEP_SUMMARY
          else
            echo "has_critical=false" >> $GITHUB_OUTPUT
          fi
      
      - name: Comment on PR
        if: github.event_name == 'pull_request' && steps.check-findings.outputs.has_critical == 'true'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('claude-security-report-${{ matrix.gpu_target }}.md', 'utf8');
            
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: `## :lock: Claude Security Analysis (${{ matrix.gpu_target }})\n\n${report}\n\n---\n*Automated security testing by Claude AI*`
            });
      
      - name: Fail if critical vulnerabilities found
        if: steps.check-findings.outputs.has_critical == 'true'
        run: |
          echo "Critical security vulnerabilities detected. See report for details."
          exit 1
```

### File 2: Claude Security Agent Script

**`.github/scripts/claude_security_agent.py`**

```python
#!/usr/bin/env python3
"""
Claude Autonomous Security Testing Agent

Invokes Claude to perform dynamic security testing on ROCm build artifacts.
Claude executes commands autonomously to discover runtime vulnerabilities.

Usage:
    python claude_security_agent.py \
        --rocm-dir ./rocm-extracted \
        --gpu-target gfx90a \
        --gpu-count 2 \
        --report-output security-report.md
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

import anthropic


class ClaudeSecurityAgent:
    """Autonomous security testing agent powered by Claude."""
    
    def __init__(
        self,
        rocm_dir: Path,
        gpu_target: str,
        gpu_count: int,
        report_output: Path,
        max_runtime_minutes: int = 90
    ):
        self.rocm_dir = rocm_dir
        self.gpu_target = gpu_target
        self.gpu_count = gpu_count
        self.report_output = report_output
        self.max_runtime_minutes = max_runtime_minutes
        
        # Initialize Anthropic client
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        
        # Execution log
        self.execution_log = []
        self.start_time = datetime.now()
    
    def find_rocm_paths(self) -> Dict[str, Path]:
        """Find ROCm installation and build directories."""
        # Try different possible structures
        candidates = [
            self.rocm_dir / "build" / "dist" / "rocm",  # Full TheRock build structure
            self.rocm_dir / "dist" / "rocm",             # Partial structure
            self.rocm_dir / "rocm",                      # Direct rocm dir
            self.rocm_dir,                                # rocm_dir itself is the installation
        ]
        
        rocm_install_path = None
        for candidate in candidates:
            if candidate.exists() and (candidate / "bin").exists():
                rocm_install_path = candidate
                break
        
        if not rocm_install_path:
            raise ValueError(f"Could not find ROCm installation in {self.rocm_dir}")
        
        # Find build directory (may contain test binaries)
        build_dir = None
        if (self.rocm_dir / "build").exists():
            build_dir = self.rocm_dir / "build"
        else:
            build_dir = self.rocm_dir
        
        return {
            'rocm_install': rocm_install_path,
            'build_dir': build_dir,
        }
    
    def gather_build_context(self) -> Dict[str, Any]:
        """Gather information about the build artifacts."""
        paths = self.find_rocm_paths()
        rocm_path = paths['rocm_install']
        build_dir = paths['build_dir']
        
        # Find binaries
        binaries = []
        if (rocm_path / "bin").exists():
            binaries = [f.name for f in (rocm_path / "bin").iterdir() if f.is_file()]
        
        # Find libraries
        libraries = []
        if (rocm_path / "lib").exists():
            libraries = [f.name for f in (rocm_path / "lib").iterdir() if f.is_file()][:20]
        
        # Find test executables
        test_binaries = []
        for pattern in ["*test*", "*_gtest", "*benchmark*"]:
            test_binaries.extend(
                str(p.relative_to(build_dir))
                for p in build_dir.rglob(pattern)
                if p.is_file() and os.access(p, os.X_OK)
            )
        
        return {
            'rocm_path': str(rocm_path),
            'build_dir': str(build_dir),
            'gpu_target': self.gpu_target,
            'gpu_count': self.gpu_count,
            'binaries': binaries[:30],
            'libraries': libraries,
            'test_binaries': test_binaries[:50],
            'total_test_binaries': len(test_binaries),
        }
    
    def create_initial_prompt(self, context: Dict[str, Any]) -> str:
        """Create the initial prompt for Claude."""
        return f"""You are performing autonomous dynamic security testing on a ROCm build in CI/CD.

# Build Context

**GPU Target:** {context['gpu_target']}
**Available GPUs:** {context['gpu_count']}
**ROCm Path:** {context['rocm_path']}
**ROCm Directory:** {context['build_dir']}

**Environment Variables Set:**
- ROCM_PATH={context['rocm_path']}
- LD_LIBRARY_PATH includes ROCm libraries
- PATH includes ROCm binaries

**Binaries Available ({len(context['binaries'])} total):**
{chr(10).join(f"  - {b}" for b in context['binaries'][:20])}
{'  ... and more' if len(context['binaries']) > 20 else ''}

**Test Executables ({context['total_test_binaries']} total):**
{chr(10).join(f"  - {b}" for b in context['test_binaries'][:15])}
{'  ... and more' if context['total_test_binaries'] > 15 else ''}

# Build Configuration

This build was compiled with:
- `-fsanitize=address,undefined` - ASAN and UBSAN enabled
- `-fno-omit-frame-pointer -g` - Debug symbols for stack traces
- Target ISA: {context['gpu_target']}

# Your Mission

Perform comprehensive autonomous security testing to discover runtime vulnerabilities. You have {self.max_runtime_minutes} minutes.

## Testing Strategy

1. **GPU Verification**
   - Verify GPU is accessible via rocm-smi and hipinfo
   - Check GPU memory, temperature, utilization baseline

2. **Static Reconnaissance**  
   - Examine available binaries and tests
   - Identify security-critical components (memory management, kernel launches, parsers, IPC)
   - Check file permissions, SUID bits, capabilities

3. **Dynamic Testing - Edge Cases**
   - Invalid GPU IDs (-1, 999999, INT_MAX)
   - Null/invalid pointers
   - Zero/negative/overflow sizes
   - Extreme dimensions for kernels (INT_MAX, SIZE_MAX)
   - Resource exhaustion (ulimit)

4. **Dynamic Testing - Sanitizer Guided**
   - Run tests with ASAN_OPTIONS configured for maximum detection
   - Parse sanitizer output for heap-buffer-overflow, use-after-free, leaks
   - Analyze stack traces to identify root causes

5. **Dynamic Testing - GPU Specific**
   - Concurrent kernel launches (race conditions)
   - Invalid memory copies (host-device boundary violations)
   - Kernel parameter validation
   - Stream/event synchronization bugs
   - Multi-GPU edge cases

6. **Fuzzing (if time permits)**
   - Quick fuzz testing on parsers/input handlers
   - Random data injection
   - Malformed inputs

## Testing Guidelines

- **Be thorough but efficient** - prioritize high-impact tests
- **Log all findings** - even minor issues may indicate larger problems
- **Provide reproduction steps** - exact commands that trigger vulnerabilities
- **Assess severity** - CRITICAL (RCE, privilege escalation), HIGH (memory corruption), MEDIUM (DoS), LOW (info leak)
- **Suggest fixes** - provide actionable remediation guidance
- **Work autonomously** - no human intervention is available

## Output Format

For each vulnerability found, document:

```
### [SEVERITY] Vulnerability Title

**Component:** Affected binary/library
**Type:** Buffer overflow / use-after-free / race condition / etc.

**Reproduction:**
```bash
<exact commands to reproduce>
```

**Sanitizer Output:**
```
<ASAN/UBSAN output>
```

**Root Cause:** Technical explanation
**Security Impact:** What an attacker could achieve
**Suggested Fix:** Code-level remediation
```

## Environment Notes

- You're running on a self-hosted GitHub Actions runner with real {context['gpu_target']} hardware
- AMD GPU drivers and ROCm are installed
- You have full bash access
- Binaries are already built and available in {context['rocm_path']}
- Time limit: {self.max_runtime_minutes} minutes
- This is fully automated - operate autonomously

## Start Testing

Begin by verifying GPU access, then proceed with systematic security testing. Work methodically and document everything you find.
"""
    
    def execute_command(self, command: str, timeout: int = 300) -> Dict[str, Any]:
        """Execute a bash command and return results."""
        self.execution_log.append({
            'timestamp': datetime.now().isoformat(),
            'command': command
        })
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.rocm_dir)
            )
            
            output = {
                'stdout': result.stdout,
                'stderr': result.stderr,
                'exit_code': result.returncode,
                'timed_out': False
            }
            
        except subprocess.TimeoutExpired as e:
            output = {
                'stdout': e.stdout.decode() if e.stdout else '',
                'stderr': e.stderr.decode() if e.stderr else '',
                'exit_code': -1,
                'timed_out': True,
                'error': f'Command timed out after {timeout}s'
            }
        
        self.execution_log[-1]['output'] = output
        return output
    
    def run(self) -> str:
        """Run the autonomous security testing session."""
        print(f"[*] Starting Claude Security Agent")
        print(f"[*] GPU Target: {self.gpu_target}")
        print(f"[*] ROCm Directory: {self.rocm_dir}")
        print(f"[*] Max Runtime: {self.max_runtime_minutes} minutes")
        print()
        
        # Gather build context
        print("[*] Gathering build context...")
        context = self.gather_build_context()
        
        # Create initial prompt
        initial_prompt = self.create_initial_prompt(context)
        
        # Start conversation with Claude
        messages = [{"role": "user", "content": initial_prompt}]
        
        print("[*] Invoking Claude...")
        print()
        
        tool_definition = {
            "name": "bash",
            "description": "Execute bash commands in the CI/CD environment to test for security vulnerabilities",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The bash command to execute"
                    },
                    "description": {
                        "type": "string", 
                        "description": "Brief description of what this command does"
                    }
                },
                "required": ["command"]
            }
        }
        
        iteration = 0
        max_iterations = 100
        
        while iteration < max_iterations:
            iteration += 1
            
            # Check time limit
            elapsed = (datetime.now() - self.start_time).total_seconds() / 60
            if elapsed >= self.max_runtime_minutes:
                print(f"\n[!] Time limit reached ({self.max_runtime_minutes} minutes)")
                messages.append({
                    "role": "user",
                    "content": f"Time limit reached. Please provide your final security report now with all findings discovered so far."
                })
            
            # Call Claude
            try:
                response = self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=8192,
                    temperature=0.7,
                    messages=messages,
                    tools=[tool_definition]
                )
            except Exception as e:
                print(f"[!] Error calling Claude API: {e}")
                break
            
            # Process response
            assistant_message = []
            
            for block in response.content:
                if block.type == "text":
                    print(block.text)
                    assistant_message.append(block)
                
                elif block.type == "tool_use" and block.name == "bash":
                    command = block.input["command"]
                    description = block.input.get("description", "")
                    
                    print(f"\n[CMD] {description if description else command}")
                    print(f"$ {command}")
                    
                    # Execute the command
                    result = self.execute_command(command)
                    
                    # Show output
                    if result['stdout']:
                        print(f"[OUT] {result['stdout'][:500]}")
                        if len(result['stdout']) > 500:
                            print("... (truncated)")
                    if result['stderr']:
                        print(f"[ERR] {result['stderr'][:500]}")
                        if len(result['stderr']) > 500:
                            print("... (truncated)")
                    print(f"[EXIT] {result['exit_code']}")
                    print()
                    
                    assistant_message.append(block)
            
            # Add assistant message to conversation
            messages.append({"role": "assistant", "content": assistant_message})
            
            # If Claude used tools, send results back
            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        # Find the execution result
                        for log_entry in reversed(self.execution_log):
                            if log_entry['command'] == block.input['command']:
                                output = log_entry['output']
                                break
                        
                        # Create tool result message
                        result_content = f"Exit code: {output['exit_code']}\n\n"
                        if output['stdout']:
                            result_content += f"STDOUT:\n{output['stdout']}\n\n"
                        if output['stderr']:
                            result_content += f"STDERR:\n{output['stderr']}\n"
                        if output.get('timed_out'):
                            result_content += f"\n[Command timed out]"
                        
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_content
                        })
                
                messages.append({"role": "user", "content": tool_results})
            
            # Check if Claude is done
            elif response.stop_reason == "end_turn":
                print("\n[*] Claude has completed testing")
                break
        
        # Extract final report from conversation
        report = self.extract_report(messages)
        
        # Write report to file
        with open(self.report_output, 'w') as f:
            f.write(report)
        
        # Write execution log
        log_path = self.report_output.parent / f"claude-execution-log-{self.gpu_target}.txt"
        with open(log_path, 'w') as f:
            json.dump(self.execution_log, f, indent=2)
        
        print(f"\n[*] Security report written to: {self.report_output}")
        print(f"[*] Execution log written to: {log_path}")
        
        return report
    
    def extract_report(self, messages: List[Dict]) -> str:
        """Extract the security report from conversation."""
        report_parts = []
        
        # Add header
        report_parts.append(f"# Claude Security Analysis Report")
        report_parts.append(f"\n**GPU Target:** {self.gpu_target}")
        report_parts.append(f"**Test Date:** {datetime.now().isoformat()}")
        report_parts.append(f"**Duration:** {(datetime.now() - self.start_time).total_seconds() / 60:.1f} minutes")
        report_parts.append(f"**Commands Executed:** {len(self.execution_log)}\n")
        report_parts.append("---\n")
        
        # Extract all text from assistant messages
        for message in messages:
            if message['role'] == 'assistant':
                content = message.get('content', [])
                if isinstance(content, str):
                    content = [{'type': 'text', 'text': content}]
                
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        report_parts.append(block['text'])
                    elif hasattr(block, 'type') and block.type == 'text':
                        report_parts.append(block.text)
        
        return '\n\n'.join(report_parts)


def main():
    parser = argparse.ArgumentParser(
        description="Claude autonomous security testing agent"
    )
    parser.add_argument(
        '--rocm-dir',
        type=Path,
        required=True,
        help='Directory containing extracted ROCm installation'
    )
    parser.add_argument(
        '--gpu-target',
        type=str,
        required=True,
        help='GPU target (e.g., gfx90a, gfx942)'
    )
    parser.add_argument(
        '--gpu-count',
        type=int,
        default=1,
        help='Number of GPUs available'
    )
    parser.add_argument(
        '--report-output',
        type=Path,
        required=True,
        help='Path to write security report'
    )
    parser.add_argument(
        '--max-runtime-minutes',
        type=int,
        default=90,
        help='Maximum runtime in minutes'
    )
    
    args = parser.parse_args()
    
    # Validate ROCm directory
    if not args.rocm_dir.exists():
        print(f"Error: ROCm directory not found: {args.rocm_dir}")
        sys.exit(1)
    
    # Create agent
    agent = ClaudeSecurityAgent(
        rocm_dir=args.rocm_dir,
        gpu_target=args.gpu_target,
        gpu_count=args.gpu_count,
        report_output=args.report_output,
        max_runtime_minutes=args.max_runtime_minutes
    )
    
    # Run security testing
    try:
        report = agent.run()
        
        # Check for critical findings
        if 'CRITICAL' in report or 'HIGH' in report:
            print("\n[!] Critical or high severity vulnerabilities found!")
            sys.exit(1)
        else:
            print("\n[*] No critical vulnerabilities detected")
            sys.exit(0)
    
    except Exception as e:
        print(f"\n[!] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
```

### File 3: Test Configuration (Optional)

**`.github/scripts/security_test_config.json`**

```json
{
  "high_priority_components": [
    "hipify",
    "clr",
    "rocblas",
    "rocfft",
    "miopen"
  ],
  "sanitizer_options": {
    "ASAN_OPTIONS": "detect_leaks=1:fast_unwind_on_malloc=0:malloc_context_size=50:symbolize=1:abort_on_error=0",
    "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=0:symbolize=1",
    "TSAN_OPTIONS": "second_deadlock_stack=1:history_size=7:halt_on_error=0"
  },
  "test_categories": {
    "memory_safety": {
      "tests": ["buffer_overflow", "use_after_free", "double_free", "memory_leak"],
      "priority": "critical"
    },
    "gpu_boundary": {
      "tests": ["invalid_device_id", "null_pointer", "size_overflow", "concurrent_access"],
      "priority": "high"
    },
    "input_validation": {
      "tests": ["negative_values", "extreme_values", "malformed_data"],
      "priority": "medium"
    }
  },
  "timeout_per_test_seconds": 60,
  "max_fuzz_iterations": 1000
}
```

## Detailed Flow: Automated Vulnerability Discovery

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: Build with Sanitizers (Separate Workflow)                             │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Actions:                                                                      │
│  • Compile ROCm with -fsanitize=address,undefined,thread                       │
│  • Enable debug symbols (-g -fno-omit-frame-pointer)                           │
│  • Build all components and tests                                              │
│  • Package: build/dist/rocm + test binaries                                    │
│  • Upload to S3: s3://bucket/builds/gfx90a-sanitized-{commit}.tar.gz          │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Instruments code with runtime checks for memory bugs                        │
│  ✓ Adds tracking for undefined behavior, races, leaks                          │
│                                                                                │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: Trigger Security Testing (Manual or Automated)                        │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Triggers:                                                                     │
│  • Manual: workflow_dispatch with S3 path                                      │
│  • Auto: workflow_call from build workflow after S3 upload                     │
│  • Schedule: Nightly scan of latest builds                                     │
│                                                                                │
│  Inputs:                                                                       │
│  • gpu_target: gfx90a                                                          │
│  • s3_artifact_path OR rocm_local_path                                         │
│                                                                                │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 3: Setup on GPU Runner (self-hosted, gpu, gfx90a)                        │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Actions:                                                                      │
│  • Download from S3 (if s3_artifact_path provided):                            │
│    └─> aws s3 cp s3://bucket/builds/gfx90a.tar.gz ./                          │
│    └─> tar -xzf gfx90a.tar.gz                                                 │
│                                                                                │
│  • OR use pre-extracted path (if rocm_local_path provided):                    │
│    └─> Verify directory exists                                                │
│    └─> Set ROCM_DIR=$rocm_local_path                                          │
│                                                                                │
│  • Setup environment:                                                          │
│    └─> export ROCM_PATH=$ROCM_DIR/build/dist/rocm                             │
│    └─> export LD_LIBRARY_PATH=$ROCM_PATH/lib                                  │
│    └─> export PATH=$ROCM_PATH/bin:$PATH                                       │
│                                                                                │
│  • Verify GPU:                                                                 │
│    └─> rocm-smi (check GPUs available)                                        │
│    └─> hipinfo (verify HIP runtime works)                                     │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Ensures testing happens on real hardware matching build ISA                 │
│  ✓ GPU drivers loaded, ready to catch runtime GPU errors                       │
│                                                                                │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: Invoke Claude Security Agent                                          │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Command:                                                                      │
│  python claude_security_agent.py \                                             │
│    --rocm-dir $ROCM_DIR \                                                      │
│    --gpu-target gfx90a \                                                       │
│    --gpu-count 2 \                                                             │
│    --report-output report.md \                                                 │
│    --max-runtime-minutes 90                                                    │
│                                                                                │
│  Agent Initializes:                                                            │
│  • Connects to Anthropic API (Claude Sonnet 4.6)                               │
│  • Scans ROCM_DIR for binaries, libraries, tests                               │
│  • Creates execution context for Claude                                        │
│  • Starts autonomous testing loop                                              │
│                                                                                │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: Claude Autonomous Testing (Up to 90 Minutes)                          │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Phase 1: Reconnaissance (5-10 min)                                            │
│  ──────────────────────────────────────────────────────────                   │
│  Claude executes:                                                              │
│  • ls -la $ROCM_PATH/bin | head -50                                            │
│  • find $ROCM_DIR -name "*test*" -executable | wc -l                          │
│  • file $ROCM_PATH/bin/rocm-smi                                                │
│  • ldd $ROCM_PATH/lib/libamdhip64.so                                           │
│  • rocm-smi --showproductname                                                  │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Identifies attack surface (binaries, shared libs)                           │
│  ✓ Finds test executables that can be probed                                   │
│  ✓ Checks for SUID bits, unusual permissions                                   │
│                                                                                │
│ ─────────────────────────────────────────────────────────────────────────────  │
│  Phase 2: Static Analysis (10-15 min)                                          │
│  ──────────────────────────────────────────────────────────                   │
│  Claude executes:                                                              │
│  • strings $ROCM_PATH/bin/hipcc | grep -i "buffer\|alloc\|free"               │
│  • nm -D $ROCM_PATH/lib/libamdhip64.so | grep malloc                          │
│  • readelf -s $ROCM_PATH/lib/*.so | grep FUNC | head -100                     │
│  • grep -r "memcpy\|strcpy" $ROCM_DIR/*/src 2>/dev/null | head -20            │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Identifies unsafe functions (strcpy, sprintf)                               │
│  ✓ Finds memory management patterns                                            │
│  ✓ Maps exported APIs for dynamic testing                                      │
│                                                                                │
│ ─────────────────────────────────────────────────────────────────────────────  │
│  Phase 3: Edge Case Testing (20-30 min)                                        │
│  ──────────────────────────────────────────────────────────                   │
│  Claude executes tests with invalid inputs:                                    │
│                                                                                │
│  Invalid GPU IDs:                                                              │
│  • HIP_VISIBLE_DEVICES=-1 $ROCM_PATH/bin/hipinfo                              │
│  • HIP_VISIBLE_DEVICES=999 $test_binary                                        │
│                                                                                │
│  Size overflows:                                                               │
│  • $test_hipMemcpy --size 4294967295  # 0xFFFFFFFF                            │
│  • $test_hipMemcpy --size -1                                                   │
│  • $test_hipMemcpy --size 0                                                    │
│                                                                                │
│  Null pointers:                                                                │
│  • $test_hipMemcpy --src-ptr 0x0                                               │
│  • $test_hipMemcpy --dst-ptr NULL                                              │
│                                                                                │
│  Kernel dimension overflows:                                                   │
│  • $test_kernel_launch --grid 2147483647,2147483647                           │
│  • $test_kernel_launch --block 1024,1024,1024                                 │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Crashes reveal missing input validation                                     │
│  ✓ Segfaults indicate null pointer dereferences                                │
│  ✓ Integer overflows in size calculations                                      │
│                                                                                │
│ ─────────────────────────────────────────────────────────────────────────────  │
│  Phase 4: Sanitizer-Guided Testing (30-40 min)                                 │
│  ──────────────────────────────────────────────────────────                   │
│  Claude runs tests with sanitizers enabled:                                    │
│                                                                                │
│  AddressSanitizer (heap bugs):                                                 │
│  • ASAN_OPTIONS=detect_leaks=1:symbolize=1 $test_binary                       │
│    ──> DETECTS: heap-buffer-overflow at address 0x7f8a2c004008                │
│    ──> STACK TRACE: hipMemcpy+0x3f4 → main+0x1c8                              │
│                                                                                │
│  UndefinedBehaviorSanitizer (UB):                                              │
│  • UBSAN_OPTIONS=print_stacktrace=1 $test_integer_math                        │
│    ──> DETECTS: signed integer overflow: 2147483647 + 1                       │
│    ──> STACK TRACE: calculateSize+0x42                                        │
│                                                                                │
│  ThreadSanitizer (races):                                                      │
│  • TSAN_OPTIONS=second_deadlock_stack=1 $test_concurrent                      │
│    ──> DETECTS: data race on shared_counter                                   │
│    ──> Thread 1: write at kernelLaunch+0x89                                   │
│    ──> Thread 2: read at kernelLaunch+0x103                                   │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ ASAN catches buffer overflows, use-after-free, leaks                        │
│  ✓ UBSAN catches integer overflows, null deref, bad casts                      │
│  ✓ TSAN catches race conditions, deadlocks                                     │
│  ✓ Stack traces pinpoint exact vulnerable code locations                       │
│                                                                                │
│ ─────────────────────────────────────────────────────────────────────────────  │
│  Phase 5: GPU-Specific Testing (15-20 min)                                     │
│  ──────────────────────────────────────────────────────────────                   │
│  Claude tests GPU boundary conditions:                                         │
│                                                                                │
│  Concurrent kernel launches (race conditions):                                 │
│  • for i in {1..20}; do $test_kernel & done; wait                             │
│    ──> DETECTS: race in device memory allocation                              │
│                                                                                │
│  Memory copy boundary violations:                                              │
│  • $test_hipMemcpy --src host --dst device --size-exceeds-device-mem          │
│    ──> DETECTS: heap corruption in device allocator                           │
│                                                                                │
│  Stream synchronization bugs:                                                  │
│  • $test_streams --unsynchronized-access                                       │
│    ──> DETECTS: use of destroyed stream object                                │
│                                                                                │
│  Multi-GPU edge cases:                                                         │
│  • HIP_VISIBLE_DEVICES=0,1 $test_p2p_transfer --size-exceeds-bar              │
│    ──> DETECTS: PCIe BAR overflow in P2P transfer                             │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ GPU-specific memory corruption                                              │
│  ✓ Driver/runtime boundary violations                                          │
│  ✓ Concurrency bugs in GPU queue management                                    │
│                                                                                │
│ ─────────────────────────────────────────────────────────────────────────────  │
│  Phase 6: Fuzzing (10-15 min, if time permits)                                 │
│  ──────────────────────────────────────────────────────────                   │
│  Claude runs quick fuzz tests:                                                 │
│                                                                                │
│  Random input fuzzing:                                                         │
│  • for i in {1..1000}; do                                                      │
│      dd if=/dev/urandom bs=1K count=1 2>/dev/null | $parser || echo "crash"   │
│    done                                                                        │
│                                                                                │
│  Malformed HIP API calls:                                                      │
│  • python -c "import ctypes; hip=ctypes.CDLL('libamdhip64.so');                │
│               hip.hipMemcpy(0xdeadbeef, 0xcafebabe, 0xffffffff, 0)"           │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Parser crashes on malformed inputs                                          │
│  ✓ API crashes with unexpected argument combinations                           │
│                                                                                │
│ ─────────────────────────────────────────────────────────────────────────────  │
│  Phase 7: Analysis & Root Cause (remaining time)                               │
│  ──────────────────────────────────────────────────────────                   │
│  For each crash/sanitizer violation, Claude:                                   │
│  • Analyzes stack trace to identify vulnerable function                        │
│  • Reads source code context (if available in build dir)                       │
│  • Assesses exploitability (RCE? DoS? Info leak?)                              │
│  • Assigns severity (CRITICAL/HIGH/MEDIUM/LOW)                                 │
│  • Suggests fix (input validation, bounds check, etc.)                         │
│  • Generates minimal reproduction steps                                        │
│                                                                                │
│  Vuln Discovery:                                                               │
│  ✓ Root cause analysis of crashes                                              │
│  ✓ Exploitability assessment                                                   │
│  ✓ Actionable remediation guidance                                             │
│                                                                                │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: Generate Security Report                                              │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Report Contains:                                                              │
│  • Executive summary (X critical, Y high, Z medium)                            │
│  • For each vulnerability:                                                     │
│    - Severity (CRITICAL/HIGH/MEDIUM/LOW)                                       │
│    - Component affected                                                        │
│    - Type (buffer overflow, race condition, etc.)                              │
│    - Exact reproduction commands                                               │
│    - Sanitizer output / stack trace                                            │
│    - Root cause explanation                                                    │
│    - Security impact (RCE, privilege escalation, DoS)                          │
│    - Suggested fix (code patch or mitigation)                                  │
│    - CWE/CVSS if applicable                                                    │
│                                                                                │
│  Saved to: claude-security-report-gfx90a.md                                    │
│  Execution log: claude-execution-log-gfx90a.txt (all commands run)             │
│                                                                                │
└──────────────────────┬─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: Upload & Alert                                                        │
├────────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Actions:                                                                      │
│  • Upload report as GitHub Actions artifact                                    │
│  • Check for CRITICAL/HIGH findings                                            │
│  • If found:                                                                   │
│    └─> Comment on PR with vulnerability summary                               │
│    └─> Fail CI workflow (block merge)                                         │
│    └─> Add to GitHub Step Summary                                             │
│  • If none found:                                                              │
│    └─> Pass workflow                                                           │
│                                                                                │
│  Result:                                                                       │
│  ✓ Developers see vulnerabilities before merge                                 │
│  ✓ CI blocks unsafe code from entering main                                    │
│  ✓ Security issues caught early in development cycle                           │
│                                                                                │
└────────────────────────────────────────────────────────────────────────────────┘
```

## Industry Standard Comparison

### How Claude DAST Compares to Industry Tools

| Capability | Claude DAST | Synopsys Seeker | Veracode DAST | Checkmarx IAST | Traditional Pentesting |
|------------|-------------|-----------------|---------------|----------------|------------------------|
| **Dynamic Analysis** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **GPU/Hardware Testing** | ✅ Real GPU hardware | ❌ Software only | ❌ Software only | ❌ Software only | ⚠️ Manual only |
| **Sanitizer Integration** | ✅ ASAN/UBSAN/TSAN | ⚠️ Limited | ❌ No | ⚠️ Basic | ❌ No |
| **Autonomous Exploration** | ✅ AI-guided | ⚠️ Rule-based | ⚠️ Crawler-based | ⚠️ Instrumentation | ✅ Human-guided |
| **Custom Test Generation** | ✅ Adaptive | ❌ No | ❌ No | ❌ No | ✅ Manual |
| **Root Cause Analysis** | ✅ AI-powered | ⚠️ Basic | ⚠️ Basic | ✅ Good | ✅ Expert-level |
| **GPU Kernel Testing** | ✅ Yes | ❌ No | ❌ No | ❌ No | ⚠️ Rare |
| **Cost** | ~$100-150/mo | $50K-100K/yr | $30K-80K/yr | $40K-90K/yr | $150-300/hr |
| **Setup Time** | 1-2 hours | Days-weeks | Days-weeks | Days-weeks | Per-engagement |
| **CI/CD Integration** | ✅ Native | ✅ Yes | ✅ Yes | ✅ Yes | ❌ Manual |
| **False Positive Rate** | Low (execution-based) | Medium | Medium-High | Low | Very Low |
| **Custom HW Support** | ✅ Any GPU | ❌ No | ❌ No | ❌ No | ✅ Yes |

### Industry Standard DAST Approaches

**1. IAST (Interactive Application Security Testing)**
- **How it works:** Instruments application code with sensors
- **Examples:** Checkmarx IAST, Contrast Security, Synopsys Seeker
- **Pros:** Low false positives, precise vulnerability location
- **Cons:** Requires code modification, no GPU support
- **Claude equivalent:** Sanitizers (ASAN/UBSAN) provide similar instrumentation

**2. Traditional DAST**
- **How it works:** Black-box testing via HTTP/API fuzzing
- **Examples:** OWASP ZAP, Burp Suite, Veracode DAST
- **Pros:** No source code needed, finds runtime issues
- **Cons:** Web-focused, can't test GPU code
- **Claude equivalent:** Edge case testing phase, but GPU-aware

**3. Fuzzing**
- **How it works:** Generate random inputs to find crashes
- **Examples:** AFL, libFuzzer, OSS-Fuzz, Google ClusterFuzz
- **Pros:** Great at finding edge cases, automated
- **Cons:** Requires harnesses, no context awareness
- **Claude equivalent:** Phase 6, but Claude writes fuzz harnesses on-the-fly

**4. Manual Penetration Testing**
- **How it works:** Security experts manually probe application
- **Examples:** Consultant firms, bug bounty programs
- **Pros:** Human creativity, complex attack chains
- **Cons:** Expensive, slow, not continuous
- **Claude equivalent:** Similar exploration, but automated and continuous

### What Makes Claude DAST Unique

**GPU-First Testing:**
- Industry tools don't understand GPU kernels, HIP APIs, or PCIe transfers
- Claude tests GPU memory boundaries, kernel launch races, P2P violations
- Runs on real hardware (gfx90a/MI300) to catch driver/hardware interactions

**Adaptive Intelligence:**
- Traditional DAST uses static rules (if X then check Y)
- Claude adapts: if ASAN finds overflow → investigates similar code paths
- Generates custom test cases based on discovered attack surface

**Sanitizer-Native:**
- Most DAST tools don't leverage ASAN/UBSAN/TSAN
- Claude orchestrates sanitizers as "sensors" like IAST
- Gets both dynamic testing AND instrumented precision

**Context-Aware:**
- Understands ROCm architecture, HIP semantics, GPU concepts
- Industry tools would treat `hipMemcpy` like any other function
- Claude knows to test device/host boundaries, size overflows, stream ordering

**Cost-Effective Continuous Testing:**
- Enterprise DAST: $30K-100K/year + setup effort
- Claude DAST: ~$100-150/month + 2 hours setup
- Runs on every PR, not quarterly scans

### When to Use What

| Use Case | Best Tool |
|----------|-----------|
| Web app security (XSS, SQLi, CSRF) | Traditional DAST (OWASP ZAP, Burp) |
| Java/.NET app testing | IAST (Checkmarx, Contrast) |
| Finding crashes in parsers/libraries | Fuzzing (AFL, libFuzzer) |
| GPU/HPC software security | **Claude DAST** (unique capability) |
| ROCm/HIP runtime testing | **Claude DAST** (unique capability) |
| Complex attack chain discovery | Manual pentesting |
| Continuous security in CI/CD | IAST or **Claude DAST** |
| Low budget, high automation | **Claude DAST** or open-source fuzzing |

### Industry Standards Claude Follows

✅ **OWASP ASVS** - Application Security Verification Standard  
✅ **CWE/SANS Top 25** - Common Weakness Enumeration  
✅ **CVSS Scoring** - Vulnerability severity assessment  
✅ **Sanitizer Coverage** - Industry-standard memory safety tools  
✅ **CI/CD Integration** - Shift-left security testing  
✅ **SAST + DAST** - Combined static + dynamic analysis  

### Best Practice: Layered Security

Claude DAST should be **one layer** in a defense-in-depth strategy:

```
┌─────────────────────────────────────────┐
│ 1. SAST - Static Analysis               │  ← Find bugs in source code
│    (clang-tidy, cppcheck, CodeQL)       │
├─────────────────────────────────────────┤
│ 2. Unit Tests - Developer Tests         │  ← Test expected behavior
│    (gtest, pytest)                      │
├─────────────────────────────────────────┤
│ 3. DAST - Claude Security Testing       │  ← Find runtime vulnerabilities ⭐
│    (This workflow)                      │
├─────────────────────────────────────────┤
│ 4. Fuzzing - Continuous Fuzzing         │  ← Long-running crash discovery
│    (OSS-Fuzz integration)               │
├─────────────────────────────────────────┤
│ 5. Pentesting - Annual Security Audit   │  ← Expert human review
│    (External security firm)             │
└─────────────────────────────────────────┘
```

Claude DAST fills the gap between unit tests (too narrow) and manual pentesting (too slow/expensive), with unique GPU testing capabilities no other tool provides.

## How It Works

### Build Phase (Separate Workflow, Not Shown Here)

A separate workflow handles building ROCm with sanitizers:

```bash
cmake -B build -GNinja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer -g" \
  -DTHEROCK_AMDGPU_FAMILIES=gfx90a

ninja -C build

# Upload to S3
aws s3 cp build-gfx90a.tar.gz s3://bucket/builds/
```

### Claude Security Testing Workflow

**Step 1: Artifact Retrieval**
- Either pull from S3, OR
- Receive path to already-extracted ROCm from prior workflow

**Step 2: Environment Setup**
- Setup environment variables (ROCM_PATH, LD_LIBRARY_PATH)
- Verify GPU availability

**Step 3: Invoke Claude Agent**
- Pass ROCm directory path to `claude_security_agent.py`
- Claude operates autonomously for up to 90 minutes

**Step 4: Autonomous Testing**
Claude executes commands to:
1. Explore available binaries and tests
2. Identify security-critical components
3. Execute commands to probe for vulnerabilities
4. Run tests with edge cases, malformed inputs
5. Analyze sanitizer output
6. Test GPU-specific attack surface
7. Document all findings with reproduction steps

**Step 5: Reporting**
1. Generate security report markdown
2. Upload report as CI artifact
3. Comment on PR if critical issues found
4. Fail CI if critical/high severity vulnerabilities detected

### What Claude Tests Autonomously

**Memory Safety:**
- Buffer overflows (heap and stack)
- Use-after-free
- Double-free
- Memory leaks
- Out-of-bounds access

**GPU-Specific:**
- Invalid device IDs
- Null pointer handling in HIP APIs
- Memory copy boundary violations
- Concurrent kernel launch races
- Stream/event synchronization bugs
- Multi-GPU edge cases

**Input Validation:**
- Negative values where unsigned expected
- Integer overflows in size calculations
- Extreme values (INT_MAX, SIZE_MAX)
- Malformed data to parsers

**Privilege Boundaries:**
- SUID/capability checks
- File permission issues
- Resource limit bypasses

**Concurrency:**
- Race conditions
- Deadlocks
- Shared memory violations

## Example Claude Workflow

When executed, Claude will autonomously:

```bash
# Verify GPU access
$ rocm-smi
$ hipinfo

# Explore available tests
$ find build -name "*test*" -executable | head -20

# Run tests with edge cases
$ build/clr/build/clients/tests/hipMemcpy --device-id -1
$ build/clr/build/clients/tests/hipMemcpy --device-id 999999
$ build/clr/build/clients/tests/hipMemcpy --size 0

# Test with sanitizers
$ ASAN_OPTIONS=detect_leaks=1 build/rocblas/build/bin/rocblas-test --size 2147483647

# Check for crashes
$ timeout 5s build/hipify/build/bin/hipify-perl < /dev/urandom

# Test concurrent access
$ for i in {1..10}; do build/clr/build/clients/tests/hipStreamSemantics & done; wait

# Analyze any crashes
$ dmesg | grep -i "segfault\|general protection"
```

Claude adapts its strategy based on what it finds - if ASAN detects an overflow, it investigates similar code paths.

## Report Format

Claude generates detailed reports like:

```markdown
# Claude Security Analysis Report

**GPU Target:** gfx90a
**Test Date:** 2026-05-10T14:32:18
**Duration:** 87.3 minutes
**Commands Executed:** 247

---

## Executive Summary

Tested 342 binaries and 89 test executables. Found 3 critical, 5 high, and 12 medium severity vulnerabilities.

## Critical Findings

### [CRITICAL] Heap Buffer Overflow in hipMemcpy

**Component:** `build/clr/build/clients/tests/hipMemcpyNegative`
**Type:** Heap buffer overflow
**CWE:** CWE-122

**Reproduction:**
```bash
ASAN_OPTIONS=detect_leaks=1 build/clr/build/clients/tests/hipMemcpyNegative --size 4294967295
```

**Sanitizer Output:**
```
==23145==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x7f8a2c004008
WRITE of size 8 at 0x7f8a2c004008 thread T0
    #0 0x55c3e8b2c3f4 in hipMemcpy /path/to/hip_memory.cpp:142
    #1 0x55c3e8b2a1c8 in main /path/to/test.cpp:67
```

**Root Cause:** 
Integer overflow in size parameter (0xFFFFFFFF) causes allocation of small buffer (4 bytes due to wrap-around), but memcpy attempts to write 4GB.

**Security Impact:**
Remote code execution potential. Attacker-controlled size parameter could corrupt heap metadata and gain control of instruction pointer.

**Suggested Fix:**
```cpp
// In hip_memory.cpp:142
if (size > HIP_MAX_TRANSFER_SIZE || size == 0) {
    return hipErrorInvalidValue;
}
```

**CVSS Score:** 9.8 (Critical)

---

### [HIGH] Race Condition in hipStreamSynchronize
...
```

## Security Considerations

### Sensitive Information

The security reports may contain:
- Stack traces with code paths
- Memory addresses (not sensitive with ASLR)
- Binary names and versions

**Do not include** in reports:
- Actual cryptographic keys
- Production credentials
- Customer data

The agent is configured to redact any accidental exposure.

### API Key Security

- Store ANTHROPIC_API_KEY in GitHub Secrets (not in code)
- Use repository secrets, not environment secrets (more restrictive)
- Rotate keys periodically
- Monitor API usage at console.anthropic.com

### Runner Security

Self-hosted GPU runners should:
- Run in isolated environments (VMs or containers)
- Have limited network access (egress to GitHub and Anthropic only)
- Be ephemeral (destroyed after each run) if possible
- Not have production credentials

## Cost Estimation

**Claude API Costs:**
- Model: Claude Sonnet 4.6 (~$3/$15 per million input/output tokens)
- Typical session: 50K input tokens, 20K output tokens
- Cost per run: ~$0.45
- With 3 GPU targets: ~$1.35 per PR
- Monthly (assuming 50 PRs + nightly): ~$100-150/month

This is typically far cheaper than manual security reviews or dedicated DAST tools.

## Limitations

**What Claude Can Test:**
✅ Runtime behavior on real hardware
✅ Memory safety with sanitizers  
✅ GPU-specific vulnerabilities
✅ Edge case handling
✅ Input validation

**What Claude Cannot Test:**
❌ GPU kernel internals (requires disassembly)
❌ Timing attacks (requires precise timing measurement)
❌ Hardware-specific exploits (Rowhammer, etc.)
❌ Cryptographic vulnerabilities (needs specialized tools)
❌ Code paths not covered by available tests

Claude's effectiveness depends on:
- Quality of existing test suite (code coverage)
- Availability of test inputs
- Time allocated for testing

## Roadmap / Future Improvements

1. **Fuzzing Integration** - Generate fuzz harnesses automatically
2. **Kernel Analysis** - Disassemble and analyze GPU kernels
3. **Regression Testing** - Track fixed vulnerabilities, ensure they stay fixed
4. **Performance Impact** - Measure performance overhead of sanitizers
5. **Custom Exploits** - Develop proof-of-concept exploits for critical findings
6. **Integration with Security Tools** - Combine with valgrind, perf, gdb

## Getting Started

### Quick Start

1. **Set up self-hosted runner** with AMD GPU:
   ```bash
   cd /opt/actions-runner
   ./config.sh --url https://github.com/ROCm/TheRock \
     --labels self-hosted,gpu,gfx90a
   ./run.sh
   ```

2. **Add API key** to GitHub Secrets:
   - Go to repo Settings → Secrets → Actions
   - New repository secret: `ANTHROPIC_API_KEY`
   - Get key from https://console.anthropic.com/

3. **Add workflow files** from this document to `.github/workflows/` and `.github/scripts/`

4. **Test manually first**:
   ```bash
   # On a GPU machine with ROCm already extracted
   export ANTHROPIC_API_KEY=sk-ant-...
   python .github/scripts/claude_security_agent.py \
     --rocm-dir ./rocm-extracted \
     --gpu-target gfx90a \
     --gpu-count 1 \
     --report-output test-report.md \
     --max-runtime-minutes 30
   ```

5. **Enable workflow** by pushing the files to main

6. **Monitor first run** - check Actions tab for results

### Gradual Rollout

**Phase 1: Manual Testing**
- Run Claude agent locally on a test build
- Review reports for quality
- Adjust prompts if needed

**Phase 2: Nightly Only**
- Enable only scheduled runs (not PRs)
- Review reports daily
- Build confidence in the system

**Phase 3: PR Integration**
- Enable on PRs
- Start with warnings (don't fail CI)
- Gradually increase severity threshold

**Phase 4: Full Enforcement**
- Fail CI on critical findings
- Require fixes before merge

## Troubleshooting

**Problem:** Agent times out
- Increase `max_runtime_minutes`
- Reduce number of test binaries to check

**Problem:** Too many false positives
- Adjust sanitizer options
- Tune Claude prompt to reduce noise
- Add filtering in report generation

**Problem:** Runner runs out of memory
- ASAN uses 2-3x memory - ensure runner has enough RAM
- Add memory limits to sanitizer options: `ASAN_OPTIONS="quarantine_size_mb=64"`

**Problem:** API rate limits
- Anthropic has generous rate limits, but add delays if needed
- Consider caching results for unchanged code

## Support

- **Claude Code Issues**: https://github.com/anthropics/claude-code/issues
- **Anthropic API Docs**: https://docs.anthropic.com/
- **TheRock Issues**: https://github.com/ROCm/TheRock/issues

## License

This security testing infrastructure follows TheRock's MIT license.

---

*Last updated: 2026-05-10*
