# Git-Notes Memory

Cold storage for Elite Longterm Memory — branch-aware, permanent knowledge graph.

## Why Git-Notes?

- **Privacy-first**: No cloud, all local
- **Branch-aware**: Different memories per Git branch
- **Permanent**: Git history = knowledge history
- **Structured**: Types (decision/fact/preference/lesson)

## Usage

```bash
# Store a decision
python3 skills/git-notes-memory/memory.py -p . remember 'Use React for frontend' -t decision -i h --tags frontend

# Store a preference
python3 skills/git-notes-memory/memory.py -p . remember 'User prefers dark mode' -t preference -i m

# Retrieve all memories
python3 skills/git-notes-memory/memory.py -p . get

# Search specific topic
python3 skills/git-notes-memory/memory.py -p . get "frontend"

# Export as markdown
python3 skills/git-notes-memory/memory.py -p . export --format markdown

# Sync to remote (if configured)
python3 skills/git-notes-memory/memory.py -p . sync
```

## Memory Types

| Type | Use for |
|------|---------|
| `decision` | Architecture choices, tech stack |
| `fact` | Domain knowledge, constraints |
| `preference` | User habits, style choices |
| `lesson` | Mistakes learned, improvements |

## Importance Levels

- `h` = High (critical, always recall)
- `m` = Medium (normal priority)
- `l` = Low (archival only)
