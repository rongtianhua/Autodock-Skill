#!/usr/bin/env python3
"""
Cron entry point for memos-dreaming — always runs with apply=True.
Use memos_dreaming.py for manual dry-run exploration.
"""
import sys
from pathlib import Path

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

# Import the main module under an alias to avoid __name__ conflict
import memos_dreaming as dreaming_module

if __name__ == "__main__":
    # Always apply for cron runs — promote entries to MEMORY.md
    dreaming_module.main(apply=True, limit=5, min_score=0.50, dry_run=False)
