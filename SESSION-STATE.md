# SESSION-STATE.md — Active Working Memory

This file is the agent's "RAM" — survives compaction, restarts, distractions.
Chat history is a BUFFER. This file is STORAGE.

## Current Task
[None]

## Key Context
[None yet]

## Pending Actions
- [ ] None

## Recent Decisions
- Git-Notes memory system initialized (2026-04-08)

## Memory Architecture
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ SESSION-    │     │  LanceDB    │     │  Git-Notes  │
│ STATE.md    │ ←→  │  Vectors    │ ←→  │  (Cold)     │
│ (Hot RAM)   │     │ (Warm)      │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
      ↑                    ↑                   ↑
   实时状态              语义搜索          永久知识库
```

### Git-Notes Commands
```bash
# Store a decision
python3 skills/git-notes-memory/memory.py -p . remember 'Content here' -t decision -i h --tags project

# Retrieve memories
python3 skills/git-notes-memory/memory.py -p . get "query"

# Sync to remote
python3 skills/git-notes-memory/memory.py -p . sync
```

---
*Last updated: 2026-04-08*