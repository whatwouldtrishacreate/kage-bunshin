# Kage Bunshin Setup Session - January 7, 2026

## Session Summary
Successfully set up and verified Kage Bunshin project on gaming rig (ndnlinuxserv) and confirmed ROG Flow Z13 setup. Downloaded Qwen 2.5 Coder 32B model on both machines. Started Kage Bunshin API server successfully.

## Machines Configured

### Gaming Rig (ndnlinuxserv) - CURRENT MACHINE
- **Hostname**: ndnlinuxserv
- **Ollama**: v0.13.5 ✓
- **Models**:
  - qwen2.5-coder:32b (19 GB) - PRIMARY MODEL FOR KAGE BUNSHIN
  - mistral:latest (4.4 GB)
- **Kage Bunshin API**: Running on http://0.0.0.0:8000 ✓
- **Database**: PostgreSQL `claude_memory` with tables: `tasks`, `progress_events` ✓
- **Project Path**: /home/ndninja/projects/kage-bunshin
- **Python venv**: Activated with all dependencies installed ✓

### ROG Flow Z13 (Portable)
- **IP**: 100.93.122.109
- **OS**: Ubuntu Linux (Kernel 6.17.0-8-generic)
- **Ollama**: v0.13.1 ✓
- **Models**: qwen2.5-coder:32b (19 GB) ✓
- **SSH**: Accessible via `ssh ndninja@100.93.122.109` ✓

## Project Status

### Kage Bunshin no Jutsu
- **Status**: Week 3/6 Complete (Active Development)
- **Description**: Parallel AI orchestration framework coordinating multiple AI CLIs (Claude Code, Ollama, Gemini, Auto-Claude) in parallel execution with intelligent result merging
- **Current Phase**: REST API with SSE streaming operational
- **Completed**:
  - ✓ Week 1: State Management (git worktrees, file locking, context sharing)
  - ✓ Week 2: Execution Engine (CLI adapters, parallel coordination)
  - ✓ Week 3: REST API & Orchestration (FastAPI, SSE, merge strategies, PostgreSQL)
- **Next**: Week 4 - n8n Integration

### API Endpoints Available
- `GET /health` - Health check (Status: healthy ✓)
- `GET /docs` - Swagger UI documentation
- `POST /api/v1/tasks` - Submit parallel AI task
- `GET /api/v1/tasks` - List all tasks
- `GET /api/v1/tasks/{id}` - Get task details
- `GET /api/v1/tasks/{id}/progress` - Stream real-time progress (SSE)
- `GET /api/v1/tasks/{id}/conflicts` - Check merge conflicts
- `POST /api/v1/tasks/{id}/merge` - Execute merge with strategy

### Environment Configuration
```bash
BASE_BRANCH=master
DATABASE_URL=postgresql://claude_mcp:memory123@localhost/claude_memory
API_KEYS=dev-key-12345
```

## Key Commands

### Start Kage Bunshin API
```bash
cd ~/projects/kage-bunshin
source venv/bin/activate
export BASE_BRANCH=master
export DATABASE_URL=postgresql://claude_mcp:memory123@localhost/claude_memory
export API_KEYS=dev-key-12345
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### SSH to ROG Flow Z13
```bash
ssh ndninja@100.93.122.109
```

### Test Ollama (Local)
```bash
ollama run qwen2.5-coder:32b "Write a hello world function in Python"
```

### Submit Test Task to Kage Bunshin
```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "X-API-Key: dev-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Write a hello world function in Python",
    "cli_assignments": [
      {"cli_name": "ollama", "context": {}, "timeout": 600}
    ],
    "merge_strategy": "theirs"
  }'
```

## Problems Solved
1. ✓ ROG Flow Z13 SSH connectivity verified (100.93.122.109)
2. ✓ Ollama model installation on both gaming rig and ROG Flow Z13
3. ✓ Qwen 2.5 Coder 32B download (19 GB) on both machines
4. ✓ Kage Bunshin API startup and health check passed
5. ✓ Database schema verified (tasks and progress_events tables exist)
6. ✓ Python venv dependencies confirmed installed

## Action Items (Pending)
- [ ] Test Kage Bunshin with parallel AI execution (HIGH PRIORITY)
- [ ] Test Ollama adapter with real coding tasks (HIGH PRIORITY)
- [ ] Configure n8n integration for Week 4 (MEDIUM PRIORITY)
- [ ] Fix claude-memory database server at 100.77.248.9:5432 (authentication issue)

## Technical Notes
- Kage Bunshin uses git worktrees to isolate each AI CLI execution
- Ollama adapter expects Qwen 2.5 Coder 32B by default (configured in orchestrator/execution/adapters/ollama.py)
- API uses Server-Sent Events (SSE) for real-time progress streaming
- Three merge strategies: THEIRS (auto), AUTO (conflict-aware), MANUAL (human review)
- Cost tracking shows $0.00 for Ollama (local execution)

## Repository
- GitHub: ai-prompt-ops-kitchen/kage-bunshin
- Local paths:
  - Gaming rig: /home/ndninja/projects/kage-bunshin
  - Also referenced in: /home/ndninja/projects/llm-council/cli-council (git worktrees)

---
*Session Date: 2026-01-07*
*Machine: ndnlinuxserv (gaming rig)*
*User: ndninja*
