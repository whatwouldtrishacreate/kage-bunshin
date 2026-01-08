# Ollama Adapter Integration Tests

Comprehensive test suite for the Ollama CLI adapter.

## Test Overview

**Total Tests:** 23
**Test File:** `test_ollama_adapter.py`
**Status:** ✅ ALL PASSING

### Test Categories

1. **ANSI Code Stripping** (5 tests)
   - Basic ANSI color codes
   - Cursor movement codes
   - Complex sequences (spinners)
   - Edge cases (empty, plain text)

2. **Output Parsing** (6 tests)
   - Markdown code blocks
   - Multiple code blocks
   - Language specifiers
   - Plain text responses
   - Empty output
   - stderr handling

3. **Command Construction** (2 tests)
   - Simple command construction
   - Command with file context

4. **Task Execution** (6 integration tests)
   - Simple task execution
   - Complex task execution
   - Output file creation
   - Git commit creation
   - ANSI code stripping in output
   - Timeout handling

5. **Error Handling** (2 tests)
   - Invalid model names
   - Empty task descriptions

6. **Performance** (2 tests)
   - Simple task performance (<5 min)
   - Cost verification ($0.00)

## Running Tests

### All Tests
```bash
cd /home/ndninja/projects/kage-bunshin
source venv/bin/activate
pytest tests/test_ollama_adapter.py -v
```

### Unit Tests Only (Fast)
```bash
pytest tests/test_ollama_adapter.py -v -m "not integration"
```

### Integration Tests Only (Requires Ollama)
```bash
pytest tests/test_ollama_adapter.py -v -m "integration"
```

### Performance Tests
```bash
pytest tests/test_ollama_adapter.py -v -m "performance"
```

### Specific Test Class
```bash
pytest tests/test_ollama_adapter.py::TestAnsiCodeStripping -v
pytest tests/test_ollama_adapter.py::TestOutputParsing -v
pytest tests/test_ollama_adapter.py::TestTaskExecution -v
```

## Requirements

### For Unit Tests
- Python 3.13+
- pytest
- pytest-asyncio
- No external dependencies

### For Integration Tests
- Ollama installed and running
- qwen2.5-coder:32b model downloaded
- Git configured
- ~8-10 minutes execution time

## Test Results (2026-01-08)

```
23 passed in 502.57s (0:08:22)
```

### Unit Tests
- **ANSI Stripping:** 5/5 ✅
- **Output Parsing:** 6/6 ✅
- **Command Construction:** 2/2 ✅

### Integration Tests
- **Task Execution:** 6/6 ✅
- **Error Handling:** 2/2 ✅
- **Performance:** 2/2 ✅

## Coverage

The test suite validates:

1. **Core Functionality**
   - ✅ ANSI escape code removal
   - ✅ Flexible output parsing
   - ✅ Command construction
   - ✅ Task execution pipeline

2. **Integration Points**
   - ✅ Ollama CLI communication
   - ✅ Git worktree operations
   - ✅ File creation and commits
   - ✅ Output capture and cleaning

3. **Edge Cases**
   - ✅ Empty inputs
   - ✅ Invalid models
   - ✅ Timeout scenarios
   - ✅ Plain text responses
   - ✅ Multiple code blocks

4. **Quality Metrics**
   - ✅ Performance (<5 min for simple tasks)
   - ✅ Cost ($0.00 local execution)
   - ✅ Output quality (production-ready code)

## Test Environment

**Machine:** Gaming rig (ndnlinuxserv)
**OS:** Linux 6.17.0-8-generic
**Python:** 3.13.7
**Ollama:** 0.13.5
**Model:** qwen2.5-coder:32b (19GB)
**Hardware:** RTX 4090 24GB VRAM

## CI/CD Integration

These tests are designed to run in CI/CD pipelines with the following markers:

- `@pytest.mark.integration` - Requires Ollama (skip in environments without it)
- `@pytest.mark.performance` - May take longer (can be run separately)

Example CI configuration:
```yaml
# Fast tests (no Ollama required)
- name: Run unit tests
  run: pytest tests/test_ollama_adapter.py -m "not integration" -v

# Full tests (requires Ollama)
- name: Run integration tests
  run: pytest tests/test_ollama_adapter.py -v
```

## Maintenance

### Adding New Tests

1. Follow existing test patterns
2. Use appropriate fixtures (`ollama_adapter`, `temp_git_repo`, etc.)
3. Add integration marker if test requires Ollama
4. Keep tests focused and independent
5. Use descriptive test names

### Debugging Failed Tests

```bash
# Run with full output
pytest tests/test_ollama_adapter.py -v -s

# Run single test with debugging
pytest tests/test_ollama_adapter.py::TestName::test_name -v -s --pdb

# Show full traceback
pytest tests/test_ollama_adapter.py -v --tb=long
```

## Related Files

- `/home/ndninja/projects/kage-bunshin/orchestrator/execution/adapters/ollama.py` - Adapter implementation
- `/home/ndninja/projects/kage-bunshin/pyproject.toml` - Pytest configuration
- `/tmp/OLLAMA_ADAPTER_FIX_RESULTS.md` - Fix documentation
- `/tmp/OLLAMA_COMPLEX_TASK_TEST.md` - Complex task validation

## Known Issues

None - all tests passing ✅

## Future Enhancements

Potential additional tests:
- [ ] Multi-file refactoring tasks
- [ ] API client implementation tasks
- [ ] Database query optimization tasks
- [ ] Async/await pattern tasks
- [ ] Streaming output tests
- [ ] Retry logic tests
- [ ] Parallel execution tests

## Support

For issues with tests:
1. Verify Ollama is running: `ollama list`
2. Check model is available: `ollama list | grep qwen2.5-coder:32b`
3. Verify git is configured: `git config --list`
4. Check Python version: `python --version` (requires 3.13+)

---

**Last Updated:** 2026-01-08
**Status:** ✅ Production Ready
**Test Coverage:** Comprehensive
