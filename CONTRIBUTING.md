# Contributing to Kage Bunshin no Jutsu 🥷

Thank you for your interest in contributing to Kage Bunshin! We're excited to have you here.

**Contributions of all types are welcome** - not just code! Whether you're fixing a typo, adding a new CLI adapter, writing documentation, or helping answer questions, your contribution matters.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Coding Guidelines](#coding-guidelines)
- [Testing Guidelines](#testing-guidelines)
- [Community](#community)

---

## 📜 Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) before contributing.

**TL;DR**: Be respectful, constructive, and welcoming. We're all here to build something awesome together.

---

## 🤝 How Can I Contribute?

### 🐛 Reporting Bugs

Found a bug? Help us fix it!

**Before submitting**:
- Check if the bug has already been reported in [Issues](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/issues)
- Collect information about the bug (error messages, steps to reproduce, environment)

**When submitting**:
- Use the bug report template
- Include a clear, descriptive title
- Provide step-by-step reproduction instructions
- Include logs, error messages, and screenshots if applicable
- Mention your environment (OS, Python version, PostgreSQL version)

### ✨ Suggesting Features

Have an idea for a new feature?

**Before suggesting**:
- Check if it's already been suggested in [Issues](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/issues) or [Discussions](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/discussions)
- Consider if it fits the project's scope and vision

**When suggesting**:
- Use the feature request template
- Clearly describe the problem you're trying to solve
- Explain how your proposed solution would work
- Provide examples or mockups if applicable
- Consider implementation complexity and potential trade-offs

### 💬 Answering Questions

Help other users by:
- Responding to questions in [Discussions](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/discussions)
- Helping troubleshoot issues
- Sharing your experiences and use cases

### 📝 Improving Documentation

Documentation improvements are always welcome:
- Fix typos or grammatical errors
- Improve clarity or add examples
- Write tutorials or guides
- Add docstrings to code
- Improve README or other docs

**Small changes** (typos, minor clarifications): Can be submitted directly as PRs

**Large changes** (new sections, restructuring): Please open an issue first to discuss

### 🔧 Contributing Code

See [Making Changes](#making-changes) and [Pull Request Process](#pull-request-process) below.

---

## 🚀 Getting Started

### Prerequisites

Before you begin, ensure you have:
- **Python 3.13+** installed
- **PostgreSQL 15+** installed and running
- **Git 2.40+** installed
- At least one supported AI CLI (Claude Code, Gemini, Ollama, Auto-Claude)

### Fork and Clone

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/kage-bunshin.git
   cd kage-bunshin
   ```
3. **Add upstream remote**:
   ```bash
   git remote add upstream https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin.git
   ```

---

## 💻 Development Setup

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
# Install project dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-asyncio pytest-cov httpx black flake8 mypy
```

### 3. Set Up Database

```bash
# Create database
createdb kage_bunshin_dev

# Run migrations
psql -d kage_bunshin_dev -f migrations/001_create_tasks_tables.sql
```

### 4. Configure Environment

Create a `.env` file (or set environment variables):

```bash
export BASE_BRANCH=master  # or main
export DATABASE_URL=postgresql://user:pass@localhost/kage_bunshin_dev
export API_KEYS=dev-key-12345
```

### 5. Verify Setup

```bash
# Run tests
pytest -v

# Start development server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/docs to verify the API is running.

---

## 🔨 Making Changes

### 1. Create a Branch

Always create a new branch for your changes:

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

**Branch naming conventions**:
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test improvements

### 2. Make Your Changes

- Write clear, readable code
- Follow the [Coding Guidelines](#coding-guidelines)
- Add tests for new features
- Update documentation as needed

### 3. Test Your Changes

```bash
# Run all tests
pytest -v

# Run specific test file
pytest tests/test_api_integration.py -v

# Run with coverage
pytest --cov=. -v

# Check code formatting
black --check .

# Run linter
flake8 .

# Type checking
mypy .
```

### 4. Commit Your Changes

Write clear, descriptive commit messages:

```bash
git add .
git commit -m "feat: Add support for GitHub Copilot CLI adapter

- Implement CopilotAdapter class
- Add configuration options
- Include integration tests
- Update documentation

Closes #123"
```

**Commit message format**:
- Use present tense ("Add feature" not "Added feature")
- Start with a type prefix: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`
- First line: Brief summary (50 chars or less)
- Body: Detailed explanation if needed
- Footer: Reference related issues

### 5. Keep Your Branch Updated

```bash
# Fetch latest changes from upstream
git fetch upstream

# Rebase your branch
git rebase upstream/master
```

---

## 📤 Pull Request Process

### 1. Push Your Changes

```bash
git push origin feature/your-feature-name
```

### 2. Create Pull Request

- Go to your fork on GitHub
- Click "New Pull Request"
- Select your branch
- Fill out the PR template completely

### 3. PR Guidelines

**Your PR should**:
- Have a clear, descriptive title
- Reference related issues (e.g., "Fixes #123")
- Include a summary of changes
- List any breaking changes
- Include screenshots for UI changes
- Pass all CI checks
- Have at least one approval from a maintainer

**PR Title Format**:
```
feat: Add GitHub Copilot CLI adapter
fix: Resolve database connection pool exhaustion
docs: Update API documentation with SSE examples
```

### 4. Review Process

- Maintainers will review your PR within 24-48 hours
- Address any requested changes
- Keep the conversation respectful and constructive
- Once approved, a maintainer will merge your PR

### 5. After Merge

- Delete your branch (GitHub will prompt you)
- Pull the latest changes to your local master:
  ```bash
  git checkout master
  git pull upstream master
  ```

---

## 📐 Coding Guidelines

### Python Style

- **Follow PEP 8** with these exceptions:
  - Line length: 100 characters (not 79)
  - Use double quotes for strings (not single)

- **Use Black** for automatic formatting:
  ```bash
  black .
  ```

- **Use type hints** where appropriate:
  ```python
  def execute_task(task_id: str, timeout: int = 300) -> ExecutionResult:
      ...
  ```

### Code Organization

- **One class per file** (unless they're tightly coupled)
- **Group imports**: stdlib, third-party, local
- **Use docstrings** for public functions/classes:
  ```python
  def merge_results(results: List[CLIResult]) -> AggregatedResult:
      """
      Merge results from multiple CLI executions.

      Args:
          results: List of CLI execution results

      Returns:
          AggregatedResult with best outcome selected
      """
  ```

### Naming Conventions

- **Classes**: `PascalCase` (e.g., `OrchestratorService`)
- **Functions/methods**: `snake_case` (e.g., `execute_parallel`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
- **Private members**: prefix with `_` (e.g., `_internal_method`)

### Error Handling

- Use specific exception types
- Include context in error messages
- Log errors appropriately

```python
try:
    result = await executor.execute(task)
except CLINotFoundError as e:
    logger.error(f"CLI not found: {task.cli_name}", exc_info=True)
    raise
except Exception as e:
    logger.error(f"Unexpected error executing task {task.id}: {e}")
    raise CLIExecutionError(f"Task execution failed: {e}") from e
```

---

## 🧪 Testing Guidelines

### Test Structure

```
tests/
├── test_state_integration.py      # Week 1: State management
├── test_execution_integration.py  # Week 2: Execution engine
└── test_api_integration.py        # Week 3: API layer
```

### Writing Tests

- **One test per behavior**
- **Use descriptive test names**: `test_submit_task_with_invalid_cli_name_returns_422`
- **Follow AAA pattern**: Arrange, Act, Assert

```python
@pytest.mark.asyncio
async def test_submit_task_creates_database_record(client, database):
    # Arrange
    task_data = {
        "description": "Test task",
        "cli_assignments": [{"cli_name": "claude-code", "context": {}}]
    }

    # Act
    response = await client.post("/api/v1/tasks", json=task_data)

    # Assert
    assert response.status_code == 201
    task = await database.get_task(response.json()["id"])
    assert task is not None
```

### Test Coverage

- **Aim for 80%+ coverage** for new code
- **Test happy paths AND error cases**
- **Include edge cases**

### Running Tests

```bash
# All tests
pytest -v

# Specific test file
pytest tests/test_api_integration.py -v

# Specific test
pytest tests/test_api_integration.py::TestTaskEndpoints::test_submit_task -v

# With coverage
pytest --cov=. --cov-report=html -v
```

---

## 🎯 Areas for Contribution

Looking for where to start? Here are some areas that need help:

### High Priority

- [ ] **New CLI Adapters**: GitHub Copilot, Cursor, Aider
- [ ] **Docker/Kubernetes**: Containerization and deployment configs
- [ ] **CI/CD**: GitHub Actions workflows for testing and releases
- [ ] **Documentation**: Tutorials, examples, API docs

### Medium Priority

- [ ] **Performance**: Optimize database queries, reduce API latency
- [ ] **Monitoring**: Prometheus metrics, Grafana dashboards
- [ ] **Web UI**: Dashboard for task monitoring
- [ ] **VS Code Extension**: IDE integration

### Good First Issues

Check issues labeled [`good first issue`](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/labels/good%20first%20issue) for beginner-friendly tasks.

---

## 💬 Community

### Getting Help

- **GitHub Discussions**: Ask questions, share ideas
- **Issues**: Bug reports and feature requests
- **Documentation**: Check WEEK summaries and README

### Communication Guidelines

- **Be respectful**: Treat everyone with kindness and respect
- **Be constructive**: Provide actionable feedback
- **Be patient**: Maintainers are volunteers with limited time
- **Be helpful**: Help others when you can

---

## 🎉 Recognition

All contributors will be:
- Listed in the project README
- Mentioned in release notes for their contributions
- Credited in commit messages

**First-time contributors** get a special welcome message and guidance on their next contribution!

---

## 📚 Additional Resources

- [Week 1 Summary](WEEK1_SUMMARY.md) - State management
- [Week 2 Summary](WEEK2_SUMMARY.md) - Execution engine
- [Week 3 Summary](WEEK3_SUMMARY.md) - REST API
- [API Documentation](http://localhost:8000/docs) - Interactive Swagger UI
- [GitHub Issues](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/issues)
- [GitHub Discussions](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/discussions)

---

## ❓ Questions?

If you have questions not covered here:
1. Check [GitHub Discussions](https://github.com/AI-Prompt-Ops-Kitchen/kage-bunshin/discussions)
2. Open an issue with the `question` label
3. Ask in a relevant existing discussion thread

---

**Thank you for contributing to Kage Bunshin no Jutsu!** 🥷

Your contributions help make this project better for everyone. We appreciate your time and effort!
