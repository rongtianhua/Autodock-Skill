#!/bin/bash
# Setup script for ClawBio skill development
# Ensures proper Python package structure and permissions

set -e

CLAWBIO_ROOT="${CLAWBIO_ROOT:-$HOME/.openclaw/clawbio}"
SKILL_NAME="${1:-}"

if [[ -z "$SKILL_NAME" ]]; then
    echo "Usage: $0 <skill-name>"
    echo "  Sets up a new skill with proper Python package structure"
    exit 1
fi

SKILL_DIR="$CLAWBIO_ROOT/skills/$SKILL_NAME"

echo "Setting up skill: $SKILL_NAME"

# Create skill directory if not exists
mkdir -p "$SKILL_DIR"

# Add __init__.py to make it a proper Python package
echo '"""ClawBio skill: '$SKILL_NAME'"""' > "$SKILL_DIR/__init__.py"

# Make any .py files executable
find "$SKILL_DIR" -name "*.py" -exec chmod +x {} \;

echo "✓ Skill structure initialized: $SKILL_DIR"
echo "✓ Added __init__.py"
echo "✓ Set execute permissions on .py files"
