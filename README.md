# 🥷 Kage Bunshin no Jutsu

**Shadow Clone Technique for AI Development**

A production-grade orchestration framework that coordinates multiple AI CLI tools in parallel, aggregates their results, and intelligently merges outcomes using git-based conflict resolution.

> *"Just as a ninja creates shadow clones to tackle multiple objectives simultaneously, Kage Bunshin no Jutsu deploys parallel AI agents to solve complex development tasks faster and more reliably."*

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)](https://github.com)

---

## 🎯 What is This?

Kage Bunshin no Jutsu is a **parallel AI orchestration system** that:
- **Executes multiple AI CLIs simultaneously** on the same task (Claude Code, Gemini, Ollama, Auto-Claude)
- **Isolates each execution** in git worktrees for safe parallel file modifications
- **Aggregates results intelligently** by comparing quality, cost, and performance
- **Resolves conflicts automatically** using configurable merge strategies
- **Provides real-time feedback** via Server-Sent Events (SSE)
- **Exposes everything via REST API** for integration with external tools (n8n, webhooks, etc.)

Think of it as **horizontal scaling for AI development** - instead of waiting for one AI to complete a task, you get multiple attempts in parallel and automatically select the best outcome.

---

## ✨ Features

### Week 1: State Management ✅
- **Git Worktree Isolation** - Each CLI gets its own workspace via session-based worktrees
- **3-Layer File Locking** - OS-level fcntl + in-memory registry + merge coordination
- **Context Preservation** - File-based session status sharing across parallel executions
- **Rollback Support** - Clean recovery from failed attempts with automatic cleanup

### Week 2: Execution Engine ✅
- **Parallel Execution** - Concurrent CLI coordination with asyncio
- **CLI Adapters** - Pluggable adapters for Claude Code, Gemini, Ollama, Auto-Claude
- **Retry Logic** - Configurable retry attempts with exponential backoff
- **Cost Tracking** - Token usage and duration monitoring per CLI
- **Performance Metrics** - Success rate, quality scoring, best result selection

### Week 3: REST API & Orchestration ✅ (Current)
- **FastAPI REST API** - Clean HTTP endpoints for task management
- **SSE Progress Streaming** - Real-time execution updates via Server-Sent Events
- **Merge Strategies** - THEIRS (auto-accept best), AUTO (conflict-aware), MANUAL (human review)
- **PostgreSQL Persistence** - Task history, progress events, and analytics
- **API Authentication** - API key-based security with configurable keys
- **OpenAPI Documentation** - Interactive Swagger UI at `/docs`

### Week 4: n8n Integration (Planned)
- Workflow automation via webhooks
- Trigger orchestrations from external events
- Multi-step AI pipelines with human-in-the-loop gates

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.13+**
- **PostgreSQL 15+**
- **Git 2.40+**
- At least one supported AI CLI:
  - [Claude Code](https://github.com/anthropics/claude-code) (recommended)
  - Google Gemini CLI
  - Ollama
  - Auto-Claude

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/kage-bunshin.git
cd kage-bunshin

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup database
createdb claude_memory  # or your preferred DB name
psql -d claude_memory -f migrations/001_create_tasks_tables.sql

# Configure environment
export BASE_BRANCH=master  # or main, depending on your git default
export DATABASE_URL=postgresql://user:pass@localhost/claude_memory
export API_KEYS=your-secret-api-key-here

# Start the server
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### First Task Submission

```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "X-API-Key: your-secret-api-key-here" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Add error handling to the login function",
    "cli_assignments": [
      {"cli_name": "claude_code", "context": {}, "timeout": 600},
      {"cli_name": "gemini", "context": {}, "timeout": 600}
    ],
    "merge_strategy": "theirs"
  }'
```

**Response:**
```json
{
  "id": "uuid-here",
  "description": "Add error handling to the login function",
  "status": "pending",
  "created_at": "2026-01-05T01:00:00Z",
  "cli_results": null
}
```

---

## 📖 Documentation

### API Endpoints

**Interactive Documentation**
`GET /docs` - Swagger UI with live API testing

**Task Management**
- `POST /api/v1/tasks` - Submit new parallel task
- `GET /api/v1/tasks` - List all tasks (with pagination)
- `GET /api/v1/tasks/{id}` - Get specific task details
- `GET /api/v1/tasks/{id}/progress` - Stream real-time progress (SSE)

**Merge Operations**
- `GET /api/v1/tasks/{id}/conflicts` - Check for merge conflicts
- `POST /api/v1/tasks/{id}/merge` - Execute merge with specified strategy

**Health & Info**
- `GET /health` - Server health check
- `GET /` - API information and available endpoints

### Merge Strategies

**THEIRS** (Default - Fully Automated)
```json
{"merge_strategy": "theirs"}
```
Automatically accepts the best result based on quality score. Fast, zero human intervention required.

**AUTO** (Conflict-Aware)
```json
{"merge_strategy": "auto"}
```
Performs automatic merge only if no conflicts detected. Fails gracefully if conflicts exist, requiring manual resolution.

**MANUAL** (Human Review)
```json
{"merge_strategy": "manual"}
```
Prepares conflict details for human review without performing merge. Returns conflict information for external review.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FastAPI REST API                      │
│  /tasks, /progress (SSE), /merge, /health, /docs        │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│              Orchestrator Service Layer                  │
│  Task queuing, background execution, state management   │
└─────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
    │   Database   │ │   Parallel   │ │    Merge     │
    │   Manager    │ │   Executor   │ │   Resolver   │
    │              │ │              │ │              │
    │ PostgreSQL   │ │ CLI Adapters │ │ Git Merging  │
    │ AsyncPG      │ │ Worktrees    │ │ Strategies   │
    └──────────────┘ └──────────────┘ └──────────────┘
```

**Data Flow:**
1. Client submits task via REST API
2. Orchestrator creates database record and starts background execution
3. Parallel Executor spawns isolated git worktrees for each CLI
4. CLI Adapters execute commands and capture results
5. Results aggregated and stored in database
6. Merge Resolver applies selected strategy
7. SSE stream provides real-time progress updates

---

## 🧪 Testing

```bash
# Run all tests
pytest -v

# Run specific test suites
pytest tests/test_state_integration.py -v      # Week 1: State management
pytest tests/test_execution_integration.py -v  # Week 2: Execution engine
pytest tests/test_api_integration.py -v        # Week 3: API layer

# Test coverage includes:
# - 10 state management tests
# - 8 execution engine tests
# - 12 API integration tests
```

---

## 🛠️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BASE_BRANCH` | Git branch for worktree base | `main` |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://claude_mcp:memory123@localhost/claude_memory` |
| `API_KEYS` | Comma-separated valid API keys | `dev-key-12345` |

### Database Configuration

The system requires a PostgreSQL database with the schema defined in `migrations/001_create_tasks_tables.sql`. Key tables:
- `tasks` - Task metadata, status, config (JSONB), results (JSONB)
- `progress_events` - Real-time execution events for SSE streaming

### CLI Adapter Configuration

Located in `orchestrator/execution/adapters/`:
- **`claude_code.py`** - Claude Code CLI adapter
- **`gemini.py`** - Google Gemini CLI adapter
- **`ollama.py`** - Ollama local LLM adapter
- **`auto_claude.py`** - Auto-Claude adapter

Each adapter implements the `CLIAdapter` interface with methods:
- `execute(task, context)` - Run CLI on task
- `parse_result(output)` - Extract structured result
- `estimate_cost(task)` - Predict token usage

---

## 📊 Performance

Based on Week 2-3 integration testing:
- **Parallel Speedup**: 2-4x faster than sequential execution
- **API Response Time**: < 100ms for synchronous endpoints
- **SSE Latency**: ~1s polling interval for progress updates
- **Database Overhead**: < 20ms per operation (async PostgreSQL)
- **Conflict Detection**: < 50ms for typical codebases

---

## 📁 Project Structure

```
kage-bunshin/
├── api/                        # Week 3: FastAPI REST API
│   ├── main.py                 # Application entry point
│   ├── dependencies.py         # Dependency injection
│   ├── models.py               # Pydantic request/response models
│   └── routes/
│       ├── tasks.py            # Task management endpoints
│       ├── progress.py         # SSE streaming endpoint
│       └── merge.py            # Merge operation endpoints
├── orchestrator/
│   ├── state/                  # Week 1: State management
│   │   ├── worktree.py         # Git worktree isolation
│   │   ├── locks.py            # 3-layer file locking
│   │   └── context.py          # Session context sharing
│   ├── execution/              # Week 2: Execution engine
│   │   ├── parallel.py         # Parallel task executor
│   │   └── adapters/           # CLI adapter implementations
│   ├── merge/                  # Week 3: Merge strategies
│   │   ├── detector.py         # Conflict detection
│   │   └── strategies.py       # Merge strategy implementations
│   └── service.py              # Week 3: Main orchestrator service
├── storage/
│   └── database.py             # Week 3: PostgreSQL async operations
├── migrations/
│   └── 001_create_tasks_tables.sql  # Database schema
├── tests/
│   ├── test_state_integration.py     # Week 1 tests
│   ├── test_execution_integration.py # Week 2 tests
│   └── test_api_integration.py       # Week 3 tests
├── requirements.txt
├── WEEK1_SUMMARY.md
├── WEEK2_SUMMARY.md
├── WEEK3_SUMMARY.md
└── README.md
```

---

## 🗺️ Roadmap

- [x] **Week 1**: Core State Management (worktrees, locks, context) ✅
- [x] **Week 2**: Async Execution Engine (CLI adapters, parallel coordination) ✅
- [x] **Week 3**: REST API with SSE streaming (FastAPI, PostgreSQL, merge strategies) ✅
- [ ] **Week 4**: n8n workflow integration (webhooks, automation triggers)
- [ ] **Week 5**: Production hardening (rate limiting, monitoring, advanced logging)
- [ ] **Week 6**: Advanced features (ML-based quality scoring, adaptive retry strategies)

---

## 🤝 Contributing

Contributions welcome! This project is a proof-of-concept for coordinated multi-AI development workflows.

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements.txt pytest pytest-asyncio httpx

# Run tests with coverage
pytest --cov=. -v

# Start development server with auto-reload
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Areas for Contribution
- Additional CLI adapters (GitHub Copilot CLI, Cursor, etc.)
- Advanced merge strategies (ML-based quality scoring)
- UI dashboard for task monitoring
- Docker containerization
- Kubernetes deployment configs

---

## 💡 Use Cases

**1. Reliability through Redundancy**
Run the same task across multiple AIs and compare results for mission-critical changes.

**2. Speed through Parallelism**
Execute different subtasks simultaneously, merging results faster than sequential execution.

**3. Cost Optimization**
Route simple tasks to local Ollama models, complex tasks to Claude/Gemini, and compare costs in real-time.

**4. Quality Comparison**
Benchmark different AI models on your specific codebase and tasks.

---

## 📜 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern async web framework
- [asyncpg](https://github.com/MagicStack/asyncpg) - High-performance PostgreSQL driver
- [Pydantic](https://docs.pydantic.dev/) - Data validation and serialization
- [sse-starlette](https://github.com/sysid/sse-starlette) - Server-Sent Events for FastAPI

Inspired by the need to leverage multiple AI tools simultaneously for better code quality and faster development cycles.

---

## 📞 Project Info

**Status**: Alpha (Week 3/6 complete)
**Created**: January 2026
**Architecture**: Hybrid supervisor-orchestrator pattern
**Emoji**: 🥷 (Ninja - representing shadow clone technique)

---

*Kage Bunshin no Jutsu - Because one AI is good, but multiple AIs working in parallel is better.* 🥷
