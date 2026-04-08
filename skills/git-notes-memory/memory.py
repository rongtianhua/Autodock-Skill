#!/usr/bin/env python3
"""
Git-Notes Memory - Cold Store for Elite Longterm Memory
Branch-aware knowledge graph using Git Notes.
"""

import argparse
import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

class GitNotesMemory:
    def __init__(self, project_path):
        self.project_path = Path(project_path).resolve()
        self.notes_ref = "refs/notes/memory"
        self._ensure_git_repo()
    
    def _ensure_git_repo(self):
        """Ensure we're in a git repository."""
        git_dir = self.project_path / ".git"
        if not git_dir.exists():
            raise RuntimeError(f"Not a git repository: {self.project_path}")
    
    def _run_git(self, args, capture_output=True):
        """Run a git command."""
        cmd = ["git", "-C", str(self.project_path)] + args
        result = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=True
        )
        return result
    
    def get_current_branch(self):
        """Get current git branch."""
        result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        return result.stdout.strip() if result.returncode == 0 else "main"
    
    def remember(self, content, category="fact", importance="m", tags=None):
        """
        Store a memory in git notes.
        
        Args:
            content: The memory content (string or dict)
            category: Type of memory (decision/fact/preference/lesson)
            importance: h=high, m=medium, l=low
            tags: List of tags
        """
        branch = self.get_current_branch()
        timestamp = datetime.now().isoformat()
        
        memory = {
            "type": category,
            "content": content if isinstance(content, str) else json.dumps(content),
            "branch": branch,
            "timestamp": timestamp,
            "importance": importance,
            "tags": tags or []
        }
        
        # Create a synthetic commit for the note
        note_content = json.dumps(memory, indent=2, ensure_ascii=False)
        
        # Store in git notes
        result = self._run_git([
            "notes", "--ref", self.notes_ref,
            "add", "-m", note_content,
            "HEAD"
        ], capture_output=False)
        
        if result.returncode != 0:
            # If note already exists, append
            result = self._run_git([
                "notes", "--ref", self.notes_ref,
                "append", "-m", "\n---\n" + note_content,
                "HEAD"
            ], capture_output=False)
        
        print(f"✓ Stored [{category}] on branch '{branch}'")
        return memory
    
    def get(self, query=None, limit=10):
        """
        Retrieve memories matching query.
        
        Args:
            query: Search term (optional)
            limit: Maximum results
        """
        result = self._run_git([
            "notes", "--ref", self.notes_ref,
            "list"
        ])
        
        if result.returncode != 0 or not result.stdout:
            print("No memories found.")
            return []
        
        memories = []
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                commit_hash = parts[0]
                note_hash = parts[1]
                
                # Get note content
                note_result = self._run_git([
                    "notes", "--ref", self.notes_ref,
                    "show", note_hash
                ])
                
                if note_result.returncode == 0:
                    try:
                        memory = json.loads(note_result.stdout)
                        if query is None or query.lower() in str(memory).lower():
                            memories.append(memory)
                    except json.JSONDecodeError:
                        # Handle plain text notes
                        memories.append({
                            "type": "raw",
                            "content": note_result.stdout,
                            "commit": commit_hash
                        })
        
        return memories[:limit]
    
    def sync(self, start=False):
        """
        Sync notes with remote.
        
        Args:
            start: Initialize if not exists
        """
        if start:
            # Create initial commit if needed
            result = self._run_git(["rev-parse", "HEAD"])
            if result.returncode != 0:
                print("Creating initial commit...")
                self._run_git(["add", "-A"], capture_output=False)
                self._run_git([
                    "commit", "-m", "Initial commit for git-notes memory",
                    "--allow-empty"
                ], capture_output=False)
        
        # Push notes
        result = self._run_git([
            "push", "origin", self.notes_ref
        ])
        
        if result.returncode == 0:
            print("✓ Notes synced to remote")
        else:
            print("Note: Remote sync skipped (no remote configured or already up to date)")
    
    def export(self, format="json"):
        """Export all memories."""
        memories = self.get(limit=1000)
        
        if format == "json":
            return json.dumps(memories, indent=2, ensure_ascii=False)
        elif format == "markdown":
            lines = ["# Git-Notes Memory Export\n"]
            for m in memories:
                lines.append(f"## [{m.get('type', 'unknown').upper()}] {m.get('timestamp', 'unknown')}")
                lines.append(f"- **Branch**: {m.get('branch', 'unknown')}")
                lines.append(f"- **Importance**: {m.get('importance', 'm')}")
                lines.append(f"- **Tags**: {', '.join(m.get('tags', []))}")
                lines.append(f"\n{m.get('content', '')}\n")
                lines.append("---\n")
            return "\n".join(lines)
        
        return memories

def main():
    parser = argparse.ArgumentParser(description="Git-Notes Memory CLI")
    parser.add_argument("-p", "--project", default=".", help="Project path")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # remember command
    remember_parser = subparsers.add_parser("remember", help="Store a memory")
    remember_parser.add_argument("content", help="Memory content (JSON string or text)")
    remember_parser.add_argument("-t", "--type", default="fact", 
                                  choices=["decision", "fact", "preference", "lesson"],
                                  help="Memory category")
    remember_parser.add_argument("-i", "--importance", default="m",
                                  choices=["h", "m", "l"],
                                  help="Importance level")
    remember_parser.add_argument("--tags", nargs="+", default=[],
                                  help="Tags for the memory")
    
    # get command
    get_parser = subparsers.add_parser("get", help="Retrieve memories")
    get_parser.add_argument("query", nargs="?", help="Search query")
    get_parser.add_argument("-n", "--limit", type=int, default=10,
                            help="Maximum results")
    
    # sync command
    sync_parser = subparsers.add_parser("sync", help="Sync with remote")
    sync_parser.add_argument("--start", action="store_true",
                             help="Initialize if needed")
    
    # export command
    export_parser = subparsers.add_parser("export", help="Export memories")
    export_parser.add_argument("--format", default="json",
                               choices=["json", "markdown"],
                               help="Export format")
    
    args = parser.parse_args()
    
    try:
        memory = GitNotesMemory(args.project)
        
        if args.command == "remember":
            # Try to parse as JSON, fallback to string
            try:
                content = json.loads(args.content)
            except json.JSONDecodeError:
                content = args.content
            
            memory.remember(
                content=content,
                category=args.type,
                importance=args.importance,
                tags=args.tags
            )
        
        elif args.command == "get":
            memories = memory.get(query=args.query, limit=args.limit)
            for m in memories:
                print(f"\n[{m.get('type', 'unknown').upper()}] {m.get('timestamp', '')}")
                print(f"Branch: {m.get('branch', 'unknown')}")
                print(f"Content: {m.get('content', '')}")
                print("-" * 40)
        
        elif args.command == "sync":
            memory.sync(start=args.start)
        
        elif args.command == "export":
            print(memory.export(format=args.format))
        
        else:
            parser.print_help()
    
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
