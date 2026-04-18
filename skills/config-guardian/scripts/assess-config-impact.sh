#!/bin/bash
# Assess impact of configuration changes
# Usage: assess-config-impact.sh <changed_paths...>

set -e

if [ $# -eq 0 ]; then
    echo "Usage: $0 <config_path1> [config_path2] ..."
    echo "Example: $0 gateway.port plugins.allow"
    exit 1
fi

echo "=== Configuration Change Impact Assessment ==="
echo "Time: $(date)"
echo ""

RESTART_NEEDED=false
IMPACT_LEVEL="low"
AFFECTED_COMPONENTS=()

for path in "$@"; do
    echo "Analyzing: $path"
    
    # Check if restart is required
    if [[ "$path" == gateway.* ]] || \
       [[ "$path" == "discovery" ]] || \
       [[ "$path" == "canvasHost" ]] || \
       [[ "$path" == "plugins" ]]; then
        RESTART_NEEDED=true
        IMPACT_LEVEL="high"
        AFFECTED_COMPONENTS+=("gateway")
        echo "  ⚠️  REQUIRES RESTART: $path"
    elif [[ "$path" == channels.*.enabled ]] || \
         [[ "$path" == channels.*.connectionMode ]]; then
        IMPACT_LEVEL="high"
        AFFECTED_COMPONENTS+=("channels")
        echo "  ⚠️  AFFECTS CHANNELS: $path"
    elif [[ "$path" == agents.* ]]; then
        IMPACT_LEVEL="medium"
        AFFECTED_COMPONENTS+=("agents")
        echo "  ℹ️  AFFECTS AGENTS: $path (hot-reloadable)"
    else
        echo "  ✓ Hot-reloadable: $path"
    fi
done

echo ""
echo "=== Assessment Result ==="
echo "Impact Level: $IMPACT_LEVEL"
echo "Restart Required: $RESTART_NEEDED"

if [ ${#AFFECTED_COMPONENTS[@]} -gt 0 ]; then
    echo "Affected Components: ${AFFECTED_COMPONENTS[*]}"
fi

# Check active tasks if high impact
if [ "$IMPACT_LEVEL" = "high" ]; then
    echo ""
    echo "=== Active Task Check ==="
    CHECK_SCRIPT="$(dirname "$0")/check-active-tasks.sh"
    if [ -f "$CHECK_SCRIPT" ]; then
        if ! "$CHECK_SCRIPT" 2>/dev/null; then
            echo ""
            echo "⚠️  WARNING: Active tasks detected + High impact change"
            echo "    Recommendation: Wait or ask user for confirmation"
            exit 2
        fi
    fi
fi

echo ""
if [ "$RESTART_NEEDED" = true ]; then
    echo "OUTPUT: RESTART_NEEDED"
    exit 0
else
    echo "OUTPUT: HOT_RELOAD_SUFFICIENT"
    exit 0
fi
