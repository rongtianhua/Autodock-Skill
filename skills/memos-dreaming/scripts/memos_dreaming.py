#!/usr/bin/env python3
"""
memos_dreaming.py — MemOS + Daily Memory Dual-Source Dreaming

A Dreaming-style memory consolidation script that:
1. Reads from two sources: MemOS SQLite (skills/tasks) + daily memory logs
2. Scores candidates using Dreaming's 6 weighted signals
3. Generates a DREAMS.md draft for review
4. Promotes high-scoring entries to MEMORY.md

Signals (Dreaming-inspired):
  - Frequency (0.24): chunk references / recall count
  - Relevance (0.30): quality_score from MemOS skills
  - Query diversity (0.15): distinct session contexts
  - Recency (0.15): time-decayed freshness
  - Consolidation (0.10): multi-day recurrence
  - Conceptual richness (0.06): topic tag density
"""

import sqlite3
import json
import os
import re
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# ─── Config ──────────────────────────────────────────────────────────────────

MEMOS_DB = Path.home() / ".openclaw/memos-local/memos.db"
WORKSPACE = Path.home() / ".openclaw/workspace"
MEMORY_DIR = WORKSPACE / "memory"
DREAMS_FILE = WORKSPACE / "DREAMS.md"
MEMORY_FILE = WORKSPACE / "MEMORY.md"
PROMOTED_INDEX = WORKSPACE / ".memos-dreaming" / "promoted.jsonl"

# Scoring weights (Dreaming-inspired)
WEIGHTS = {
    "frequency": 0.24,
    "relevance": 0.30,
    "query_diversity": 0.15,
    "recency": 0.15,
    "consolidation": 0.10,
    "conceptual_richness": 0.06,
}

# Thresholds
MIN_SCORE = 0.50
MIN_RECALL_COUNT = 2
MIN_UNIQUE_QUERIES = 1
MAX_DAILY_PROMOTIONS = 5

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_now_ts() -> int:
    return int(datetime.now().timestamp() * 1000)

def ts_to_date(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")

def ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def load_promoted() -> set:
    """Load set of already-promoted entry hashes."""
    if not PROMOTED_INDEX.exists():
        return set()
    with open(PROMOTED_INDEX) as f:
        return {line.strip().split("|")[0] for line in f if line.strip()}

def append_promoted(entry_hash: str, title: str, source: str):
    ensure_dir(PROMOTED_INDEX)
    # Skip if already promoted (dedup on write)
    if PROMOTED_INDEX.exists():
        existing = PROMOTED_INDEX.read_text()
        if entry_hash in existing:
            return
    with open(PROMOTED_INDEX, "a") as f:
        f.write(f"{entry_hash}|{source}|{ts_to_date(get_now_ts())}\n")

# ─── MemOS Source ────────────────────────────────────────────────────────────

def get_memOS_candidates(conn: sqlite3.Connection) -> list[dict]:
    """Fetch high-value tasks and skills from MemOS SQLite."""
    now = get_now_ts()
    day_ago = now - 86400 * 1000
    week_ago = now - 86400 * 7 * 1000

    candidates = []

    # Skills with quality scores
    rows = conn.execute("""
        SELECT id, name, description, quality_score, source_type,
               tags, created_at, updated_at, visibility
        FROM skills
        WHERE status = 'active'
          AND quality_score IS NOT NULL
          AND quality_score >= 5.0
          ORDER BY quality_score DESC
        LIMIT 50
    """).fetchall()

    for r in rows:
        cid, name, desc, qs, src, tags, ca, ua, vis = r
        entry_hash = hashlib.sha256(f"skill:{cid}".encode()).hexdigest()[:12]
        candidates.append({
            "entry_hash": entry_hash,
            "type": "skill",
            "id": cid,
            "title": name,
            "summary": desc,
            "quality_score": qs or 0,
            "tags": json.loads(tags) if tags else [],
            "merge_count": 1,
            "created_at": ca,
            "updated_at": ua,
            "visibility": vis,
        })

    # Tasks with skill_status='promoted' (these were elevated to skills)
    rows = conn.execute("""
        SELECT id, title, summary, topic, skill_status, skill_reason,
               started_at, updated_at
        FROM tasks
        WHERE status = 'active'
          AND skill_status = 'promoted'
        ORDER BY updated_at DESC
        LIMIT 50
    """).fetchall()

    for r in rows:
        cid, title, summary, topic, ss, sr, ca, ua = r
        entry_hash = hashlib.sha256(f"task:{cid}".encode()).hexdigest()[:12]
        candidates.append({
            "entry_hash": entry_hash,
            "type": "task",
            "id": cid,
            "title": title or "(untitled task)",
            "summary": summary or "",
            "topic": topic or "",
            "tags": [],
            "quality_score": 0,
            "skill_status": ss,
            "skill_reason": sr,
            "merge_count": 1,
            "created_at": ca,
            "updated_at": ua,
        })

    return candidates

# ─── Daily Memory Log Source ─────────────────────────────────────────────────

def get_daily_memory_candidates() -> list[dict]:
    """Scan recent daily memory logs for high-value entries."""
    candidates = []
    today = datetime.now()
    cutoff = today - timedelta(days=3)

    for log_file in sorted(MEMORY_DIR.glob("2026-*.md")):
        try:
            log_date = datetime.strptime(log_file.stem[:10], "%Y-%m-%d")
            if log_date < cutoff:
                continue
        except ValueError:
            continue

        content = log_file.read_text()
        # Extract sections: ## Decisions, ## Lessons Learned, ## Projects
        # Extract ALL ## sections (not just named ones)
        section_pattern = r"## (.+?)(?:\n|$)(.*?)(?=\n## |\Z)"
        for m in re.finditer(section_pattern, content, re.DOTALL):
            section_title = m.group(1).strip()
            section_body = m.group(2).strip()
            # Skip pure timestamps or very short headers
            if len(section_title) < 3:
                continue
            # Extract bullet points
            bullets = re.findall(r"^- (.+)$", section_body, re.MULTILINE)
            for b in bullets:
                b = b.strip()
                if len(b) < 15:
                    continue
                entry_hash = hashlib.sha256(b.encode()).hexdigest()[:12]
                candidates.append({
                    "entry_hash": entry_hash,
                    "type": "daily_log",
                    "title": b[:80],
                    "summary": b,
                    "source_file": log_file.name,
                    "section": section_title,
                    "updated_at": int(log_file.stat().st_mtime * 1000),
                })
            # Also extract bold/key lines (lines starting with - or ** but not bullets)
            # Already captured above via bullets
            for b in bullets:
                b = b.strip()
                if len(b) < 20:
                    continue
                entry_hash = hashlib.sha256(b.encode()).hexdigest()[:12]
                candidates.append({
                    "entry_hash": entry_hash,
                    "type": "daily_log",
                    "title": b[:80],
                    "summary": b,
                    "source_file": log_file.name,
                    "updated_at": int(log_file.stat().st_mtime * 1000),
                })

    return candidates

# ─── Scoring ─────────────────────────────────────────────────────────────────

def compute_score(c: dict, all_entries: list[dict], now_ts: int) -> float:
    """Compute 6-signal weighted score."""

    # Frequency (0.20): merge_count / recall evidence
    # For daily_log, use text length as a quality proxy (detailed = important)
    merge_count = c.get("merge_count", 0)
    if merge_count > 0:
        freq = min(merge_count / 10, 1.0)
    elif c.get("type") == "daily_log":
        # Reward longer, more detailed bullets
        summary = c.get("summary", c.get("title", ""))
        freq = min(len(summary) / 200, 1.0)  # 200 chars = max freq
    else:
        freq = 0.0

    # Relevance (0.30): quality_score from MemOS (0-10 scale → 0-1)
    # For daily_log entries without quality_score, reward content quality
    qs = c.get("quality_score", 0) or 0
    if qs > 0:
        relevance = min(qs / 10.0, 1.0)
    else:
        # daily_log: derive relevance from content quality signals
        summary = c.get("summary", c.get("title", ""))
        text_len = len(summary)
        # Technical indicators: file paths, function names, error types, version numbers
        tech_indicators = sum([
            0.2 if any(p in summary for p in ["//", "~/", "/.", "`", "="]) else 0,  # paths/code
            0.2 if any(kw in summary for kw in ["ERROR", "Fix", "Bug", "Crash", "Failed", "修复", "根因", "bug"]) else 0,
            0.2 if any(s in summary for s in ["def ", "class ", "import ", "conda ", "docker ", "git "]) else 0,
            0.2 if any(v in summary for v in ["v1.", "v2.", "v3.", "0.1", "1.0", "2024", "2025", "2026"]) else 0,  # versions
            0.2 if text_len > 80 else (0.1 if text_len > 40 else 0),
        ])
        relevance = min(tech_indicators, 1.0)

    # Query diversity (0.15): distinct source files/sessions
    sources = set()
    if c.get("type") == "daily_log":
        sources.add(c.get("source_file", ""))
    diversity = min(len(sources) / 3, 1.0) if sources else 0.5

    # Recency (0.15): time-decayed, half-life 30 days
    updated = c.get("updated_at", now_ts)
    days_old = (now_ts - updated) / (86400 * 1000)
    recency = max(0, 1 - (days_old / 30))

    # Consolidation (0.10): entries appearing across multiple days
    consolidation = 0.0
    if c["type"] == "daily_log":
        # count days this entry appears
        consolidation = 0.5  # simplified
    elif c.get("merge_count", 0) > 5:
        consolidation = 1.0

    # Conceptual richness (0.06): topic/tag density
    # For daily_log, use section type and content detail as richness signal
    topic_len = len((c.get("topic") or "").split())
    tags_count = len(c.get("tags", []))
    if tags_count > 0 or topic_len > 0:
        richness = min((topic_len + tags_count) / 10, 1.0)
    elif c.get("type") == "daily_log":
        # Reward certain section types as higher-value content
        section = c.get("section", "").lower()
        section_score = 0.0
        if any(kw in section for kw in ["lesson", "learned", "决策", "decision"]):
            section_score = 1.0
        elif any(kw in section for kw in ["fix", "bug", "修复", "debug", "错误"]):
            section_score = 0.9
        elif any(kw in section for kw in ["project", "项目", "done", "完成"]):
            section_score = 0.7
        elif any(kw in section for kw in ["工具", "tool", "skill", "配置"]):
            section_score = 0.7
        # Bonus for technical content (file paths, commands)
        summary = c.get("summary", "")
        tech_bonus = 0.2 if any(p in summary for p in ["//", "~/", "/.", "conda ", "pip ", "python ", "git "]) else 0
        richness = min(section_score + tech_bonus, 1.0)
    else:
        richness = 0.0

    score = (
        WEIGHTS["frequency"] * freq +
        WEIGHTS["relevance"] * relevance +
        WEIGHTS["query_diversity"] * diversity +
        WEIGHTS["recency"] * recency +
        WEIGHTS["consolidation"] * consolidation +
        WEIGHTS["conceptual_richness"] * richness
    )

    return round(min(score, 1.0), 4)

# ─── Output Formatters ────────────────────────────────────────────────────────

def format_skill_entry(c: dict) -> str:
    tags = ", ".join(c.get("tags", [])[:5])
    quality = c.get("quality_score", 0) or 0
    return (
        f"- **{c['title']}** (skill)\n"
        f"  - {c.get('summary', '')[:200]}\n"
        f"  - 质量评分: {quality:.2f} | 话题: {c.get('topic', 'N/A')} | 标签: {tags or '无'}\n"
        f"  - 来源: MemOS skill / 更新时间: {ts_to_date(c.get('updated_at', 0))}"
    )

def format_task_entry(c: dict) -> str:
    return (
        f"- **{c['title']}** (task)\n"
        f"  - {c.get('summary', '')[:200]}\n"
        f"  - 合并引用: {c.get('merge_count', 0)}次 | 话题: {c.get('topic', 'N/A')}\n"
        f"  - 来源: MemOS task / 更新时间: {ts_to_date(c.get('updated_at', 0))}"
    )

def format_daily_entry(c: dict) -> str:
    return (
        f"- {c['summary']}\n"
        f"  - 来源: {c.get('source_file', 'memory log')} | 评分: {c.get('_score', 0):.3f}"
    )

def format_dreams_draft(candidates: list[dict], scores: dict[str, float],
                        promoted: set) -> str:
    """Generate DREAMS.md review draft."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M %Z%z")
    lines = [
        f"# DREAMS.md — {now_str}",
        "",
        "## Dreaming Summary",
        "",
        f"Scanned: {len(candidates)} candidates",
        f"Above threshold: {sum(1 for h in scores if scores[h] >= MIN_SCORE)}",
        f"New promotions: {sum(1 for h in scores if scores[h] >= MIN_SCORE and h not in promoted)}",
        "",
        "## Phase: Deep Sleep",
        "",
    ]

    scored = [(c["entry_hash"], c, scores[c["entry_hash"]]) for c in candidates
                if c["entry_hash"] in scores and scores[c["entry_hash"]] >= MIN_SCORE]
    scored.sort(key=lambda x: x[2], reverse=True)

    for entry_hash, c, score in scored[:10]:
        marker = "✅" if entry_hash in promoted else "🆕"
        c["_score"] = score  # attach for format functions
        if c["type"] == "skill":
            entry_text = format_skill_entry(c)
        elif c["type"] == "task":
            entry_text = format_task_entry(c)
        else:
            entry_text = format_daily_entry(c)
        lines.append(f"{marker} {entry_text}")
        lines.append(f"   Score: {score:.3f}\n")

    return "\n".join(lines)

def format_memory_promotion(c: dict) -> str:
    """Format entry for MEMORY.md."""
    ts = ts_to_date(c.get("updated_at", get_now_ts()))
    if c["type"] == "skill":
        return (
            f"\n- **{c['title']}** (skill, {ts})\n"
            f"  {c.get('summary', '')[:200]}\n"
        )
    elif c["type"] == "task":
        return (
            f"\n- **{c['title']}** (task, {ts})\n"
            f"  {c.get('summary', '')[:200]}\n"
        )
    else:
        return f"\n- {c.get('summary', c.get('title', ''))} (daily log, {ts})\n"

# ─── Main ─────────────────────────────────────────────────────────────────────

def main(apply: bool = False, limit: int = MAX_DAILY_PROMOTIONS,
         min_score: float = MIN_SCORE, dry_run: bool = False):
    now_ts = get_now_ts()
    print(f"[memos-dreaming] Starting at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Apply mode: {apply} | Dry run: {dry_run} | Min score: {min_score}")

    # Load already-promoted
    promoted = load_promoted()
    print(f"  Already promoted: {len(promoted)} entries")

    # Gather candidates
    candidates = []

    # Source 1: MemOS
    if MEMOS_DB.exists():
        conn = sqlite3.connect(str(MEMOS_DB))
        memos_cands = get_memOS_candidates(conn)
        conn.close()
        print(f"  MemOS candidates: {len(memos_cands)}")
        candidates.extend(memos_cands)
    else:
        print(f"  [WARN] MemOS DB not found at {MEMOS_DB}")

    # Source 2: Daily memory logs
    daily_cands = get_daily_memory_candidates()
    print(f"  Daily memory candidates: {len(daily_cands)}")
    candidates.extend(daily_cands)

    # Deduplicate candidates by entry_hash (same content from same/diff files)
    seen_hashes = set()
    unique_candidates = []
    for c in candidates:
        if c["entry_hash"] not in seen_hashes:
            seen_hashes.add(c["entry_hash"])
            unique_candidates.append(c)
    candidates = unique_candidates
    print(f"  Deduplicated: {len(candidates)} unique candidates")

    # Score all
    scores = {c["entry_hash"]: compute_score(c, candidates, now_ts) for c in candidates}

    # Filter above threshold
    above = [(c["entry_hash"], c) for c in candidates
             if scores.get(c["entry_hash"], 0) >= min_score
             and c["entry_hash"] not in promoted]
    above.sort(key=lambda x: scores[x[0]], reverse=True)
    new_count = sum(1 for h, _ in above if h not in promoted)
    print(f"  Above threshold: {len(above)} (new: {new_count})")

    # Generate DREAMS draft
    dreams_content = format_dreams_draft(candidates, scores, promoted)
    ensure_dir(DREAMS_FILE)
    DREAMS_FILE.write_text(dreams_content)
    print(f"  DREAMS draft written: {DREAMS_FILE}")

    # Apply to MEMORY.md
    to_promote = [c for h, c in above if h not in promoted][:limit]
    if not to_promote:
        print("  Nothing new to promote.")
        return

    if dry_run:
        print(f"  [DRY RUN] Would promote {len(to_promote)} entries:")
        for c in to_promote:
            print(f"    - {c['title'][:60]} (score={scores[c['entry_hash']]:.3f})")
        return

    if apply:
        # Append to MEMORY.md
        ensure_dir(MEMORY_FILE)
        existing = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
        # Find last section
        if "## Promoted" in existing:
            insert_pos = existing.rfind("## Promoted")
        elif "## Lessons Learned" in existing:
            insert_pos = existing.rfind("## Lessons Learned")
        else:
            insert_pos = len(existing)

        new_entries = []
        for c in to_promote:
            new_entries.append(format_memory_promotion(c))
            append_promoted(c["entry_hash"], c.get("title", ""), c["type"])


    # Clean duplicate lines from promoted.jsonl
    if PROMOTED_INDEX.exists():
        lines = PROMOTED_INDEX.read_text().strip().split("\n")
        seen = set()
        cleaned = []
        for line in lines:
            h = line.split("|")[0] if line else ""
            if h and h not in seen:
                seen.add(h)
                cleaned.append(line)
        PROMOTED_INDEX.write_text("\n".join(cleaned) + "\n")
        promoted_block = (
            f"\n\n## Promoted Entries ({datetime.now().strftime('%Y-%m-%d')})\n"
            + "".join(new_entries)
        )

        updated = existing[:insert_pos] + promoted_block + existing[insert_pos:]
        MEMORY_FILE.write_text(updated)
        print(f"  ✅ Promoted {len(to_promote)} entries to MEMORY.md")
    else:
        print(f"  Run with --apply to write to MEMORY.md")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MemOS Dreaming — Memory Consolidation")
    parser.add_argument("--apply", action="store_true", help="Write to MEMORY.md (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Force dry run")
    parser.add_argument("--limit", type=int, default=MAX_DAILY_PROMOTIONS)
    parser.add_argument("--min-score", type=float, default=MIN_SCORE)
    args = parser.parse_args()

    dry_run = args.dry_run or not args.apply
    main(apply=args.apply, limit=args.limit, min_score=args.min_score, dry_run=dry_run)
