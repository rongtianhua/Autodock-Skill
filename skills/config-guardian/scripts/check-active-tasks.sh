#!/bin/bash
# Check for active long-running tasks before destructive operations
# Usage: check-active-tasks.sh [--warn]

set -e

WORKSPACE="${1:-/Users/allenrong/.openclaw/workspace}"
LOGS_DIR="${2:-/Users/allenrong/.openclaw/logs}"
WARN_MODE=false

if [ "$1" = "--warn" ]; then
    WARN_MODE=true
fi

echo "=== Active Task Check ==="
echo "Time: $(date)"
echo ""

# Check 1: Session lock files
LOCK_COUNT=$(find "$WORKSPACE" -name "*.lock" -type f 2>/dev/null | wc -l)
echo "1. Session lock files: $LOCK_COUNT"
if [ "$LOCK_COUNT" -gt 0 ]; then
    echo "   ⚠️  Found lock files (indicates active sessions):"
    find "$WORKSPACE" -name "*.lock" -type f 2>/dev/null | head -5 | sed 's/^/      /'
fi
echo ""

# Check 2: Recent incomplete dispatches in gateway log (only last 5 minutes)
if [ -f "$LOGS_DIR/gateway.log" ]; then
    echo "2. Recent dispatch activity (last 5 min):"
    
    # Get current time in epoch seconds
    NOW=$(date +%s)
    FIVE_MIN_AGO=$((NOW - 300))
    
    # Extract recent log entries (simplified: check last 50 lines within time window)
    RECENT_DISPATCH=$(grep -E "dispatching|dispatch complete" "$LOGS_DIR/gateway.log" 2>/dev/null | tail -50 | while read line; do
        # Extract timestamp from log line (format: 2026-04-08T17:45:00+08:00)
        TIMESTAMP=$(echo "$line" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' | head -1)
        if [ -n "$TIMESTAMP" ]; then
            # Convert to epoch (macOS compatible)
            LOG_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$TIMESTAMP" +%s 2>/dev/null || echo "0")
            if [ "$LOG_EPOCH" -gt "$FIVE_MIN_AGO" ] 2>/dev/null; then
                echo "$line"
            fi
        fi
    done)
    
    if [ -n "$RECENT_DISPATCH" ]; then
        # Count incomplete dispatches (dispatching without complete in recent window)
        DISPATCHING_COUNT=$(echo "$RECENT_DISPATCH" | grep -c "dispatching" || echo "0")
        COMPLETE_COUNT=$(echo "$RECENT_DISPATCH" | grep -c "dispatch complete" || echo "0")
        INCOMPLETE=$((DISPATCHING_COUNT - COMPLETE_COUNT))
        
        echo "   Recent dispatching: $DISPATCHING_COUNT"
        echo "   Recent complete: $COMPLETE_COUNT"
        if [ "$INCOMPLETE" -gt 0 ]; then
            echo "   ⚠️  WARNING: $INCOMPLETE task(s) may be in progress (last 5 min)"
        else
            echo "   ✅ All recent dispatches completed"
        fi
    else
        echo "   ✅ No dispatch activity in last 5 minutes"
    fi
else
    echo "2. Gateway log not found at $LOGS_DIR/gateway.log"
fi
echo ""

# Check 3: Active sessions from status
echo "3. OpenClaw sessions:"
openclaw status 2>/dev/null | grep -E "Sessions|active" | head -3 | sed 's/^/   /' || echo "   Could not retrieve session info"
echo ""

# Summary
echo "=== Summary ==="
if [ "$LOCK_COUNT" -gt 0 ] || [ "${INCOMPLETE:-0}" -gt 0 ]; then
    echo "⚠️  CAUTION: Active tasks detected"
    echo "   Recommendation: Wait for tasks to complete, or ask user for confirmation"
    exit 1
else
    echo "✅ No active long-running tasks detected"
    echo "   Safe to proceed with restart/reload"
    exit 0
fi
