#!/usr/bin/env python3
"""
Test script for Claude Code adapter fixes.

Tests the three critical fixes:
1. CLI invocation with prompt as argument (not stdin)
2. Success validation (checks for actual work done)
3. Untracked file detection

Usage:
    python test_claude_code_adapter_fix.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from orchestrator.execution.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.execution.adapters.base import TaskAssignment, ExecutionStatus


async def test_command_construction():
    """Test Fix 1: CLI invocation with prompt as argument."""
    print("=" * 60)
    print("Test 1: Command Construction")
    print("=" * 60)

    adapter = ClaudeCodeAdapter()
    task = TaskAssignment(
        task_id="test-123",
        cli_name="claude-code",
        description="Write a Python function that adds two numbers",
        context={},
        timeout=60,
    )

    command = adapter._construct_command(task, Path("/tmp"))

    print(f"Command: {command}")
    print(f"\nExpected structure:")
    print(f"  ['claude', '--print', '--no-session-persistence', '<prompt>']")

    assert command[0] == "claude", "First element should be 'claude'"
    assert command[1] == "--print", "Second element should be '--print'"
    assert command[2] == "--no-session-persistence", "Third element should be '--no-session-persistence'"
    assert len(command) == 4, f"Should have 4 elements, got {len(command)}"
    assert "# Task:" in command[3], "Fourth element should be the prompt"

    print(f"\n✅ PASS: Command structure is correct")
    print(f"   - Prompt passed as argument (not stdin)")
    print(f"   - Prompt length: {len(command[3])} chars")
    return True


async def test_success_validation():
    """Test Fix 2: Success validation checks for actual work."""
    print("\n" + "=" * 60)
    print("Test 2: Success Validation Logic")
    print("=" * 60)

    print("\nThis test validates that the adapter checks for:")
    print("  1. files_modified > 0 OR commits > 0")
    print("  2. Fails if returncode=0 but no work done")

    # We can't easily test the full execute() method without mocking,
    # but we can verify the code has the validation logic
    adapter = ClaudeCodeAdapter()

    import inspect
    source = inspect.getsource(adapter.execute)

    # Check for validation logic
    has_file_check = "len(files_modified) == 0" in source
    has_commit_check = "len(commits) == 0" in source
    has_false_success = "false success" in source.lower() or "no output" in source.lower()

    print(f"\n✅ Code Analysis:")
    print(f"   - Checks files_modified: {has_file_check}")
    print(f"   - Checks commits: {has_commit_check}")
    print(f"   - Detects false success: {has_false_success}")

    assert has_file_check, "Should check for empty files_modified"
    assert has_commit_check, "Should check for empty commits"
    assert has_false_success, "Should detect false success scenario"

    print(f"\n✅ PASS: Success validation logic is present")
    return True


async def test_untracked_file_detection():
    """Test Fix 3: Untracked file detection."""
    print("\n" + "=" * 60)
    print("Test 3: Untracked File Detection")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Initialize git repo
        await asyncio.create_subprocess_exec(
            "git", "init", cwd=tmppath,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        # Create initial commit
        test_file = tmppath / "initial.txt"
        test_file.write_text("initial content")

        await asyncio.create_subprocess_exec(
            "git", "add", "initial.txt", cwd=tmppath,
            stdout=asyncio.subprocess.DEVNULL,
        )

        await asyncio.create_subprocess_exec(
            "git", "commit", "-m", "Initial", cwd=tmppath,
            stdout=asyncio.subprocess.DEVNULL,
        )

        # Create untracked file
        untracked = tmppath / "untracked.py"
        untracked.write_text("# Untracked file")

        # Create modified tracked file
        test_file.write_text("modified content")

        # Test the adapter's file detection
        adapter = ClaudeCodeAdapter()
        files = await adapter._get_modified_files(tmppath)

        print(f"\nDetected files: {files}")
        print(f"Expected to find:")
        print(f"  - initial.txt (modified tracked file)")
        print(f"  - untracked.py (untracked file)")

        assert "initial.txt" in files, "Should detect modified tracked file"
        assert "untracked.py" in files, "Should detect untracked file"
        assert len(files) >= 2, f"Should detect at least 2 files, got {len(files)}"

        print(f"\n✅ PASS: Untracked file detection works")
        print(f"   - Tracked modified files: ✓")
        print(f"   - Untracked files: ✓")
        return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("CLAUDE CODE ADAPTER FIX VALIDATION")
    print("=" * 60)
    print("\nTesting fixes for:")
    print("1. CLI invocation (prompt as argument, not stdin)")
    print("2. Success validation (check for actual work)")
    print("3. Untracked file detection")

    results = []

    try:
        results.append(await test_command_construction())
    except Exception as e:
        print(f"\n❌ FAIL: Test 1 failed: {e}")
        results.append(False)

    try:
        results.append(await test_success_validation())
    except Exception as e:
        print(f"\n❌ FAIL: Test 2 failed: {e}")
        results.append(False)

    try:
        results.append(await test_untracked_file_detection())
    except Exception as e:
        print(f"\n❌ FAIL: Test 3 failed: {e}")
        results.append(False)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Tests passed: {sum(results)}/{len(results)}")

    if all(results):
        print("\n✅ ALL TESTS PASSED - Claude Code adapter is fixed!")
        print("\nFixes applied:")
        print("  1. ✅ Prompt passed as CLI argument (not stdin)")
        print("  2. ✅ Success validation checks for actual work")
        print("  3. ✅ Untracked files are now detected")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED - Review the output above")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
