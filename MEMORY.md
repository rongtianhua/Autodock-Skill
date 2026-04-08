# MEMORY.md — Long-Term Memory

## About the User
- Name: Allen Rong (戎天华)
- Timezone: Asia/Shanghai
- Occupation: Spine surgeon, Beijing

## Projects
- Tushare stock skill (Python 3.14 installed)
- Elite longterm memory setup (in progress)

## Decisions Log
- Switched to local Ollama bge-m3 embeddings for memory (2026-04-08)
- Session-state stored at workspace root

## Lessons Learned
- Config loss after update; now using config-guardian backups
- Always verify memorySearch config matches provider capabilities

## Preferences
- Use local models where possible
- Context: workspace /Users/allenrong/.openclaw/workspace

---
*Curated memory — distill insights from daily logs here*