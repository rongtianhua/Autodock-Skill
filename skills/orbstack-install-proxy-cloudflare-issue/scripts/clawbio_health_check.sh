#!/bin/bash
# ClawBio Health Check Script
# Verifies full deployment and runs demo suite

set -e

CLAWBIO_ROOT="${CLAWBIO_ROOT:-$HOME/.openclaw/clawbio}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/.openclaw/workspace}"

echo "=== ClawBio Health Check ==="
echo ""

# 1. Check Python package
echo "[1/5] Checking Python package..."
cd "$CLAWBIO_ROOT"
python -c "import clawbio; print(f'  ✓ clawbio v{clawbio.__version__}')" 2>/dev/null || echo "  ✗ Import failed"

# 2. Check Docker/Colima status
echo ""
echo "[2/5] Checking Docker runtime..."
if docker ps >/dev/null 2>&1; then
    echo "  ✓ Docker is running"
else
    echo "  ✗ Docker is not running"
fi

# 3. Run full demo suite
echo ""
echo "[3/5] Running demo suite..."
SKILLS=("gwas-lookup" "clinpgx" "equity-scorer" "pharmgx-reporter" "genome-compare" "bigquery-bridge" "rna-seq-de" "galaxy-bridge")

cd "$CLAWBIO_ROOT"
for skill in "${SKILLS[@]}"; do
    echo -n "  Testing $skill... "
    if python clawbio.py demo "$skill" >/dev/null 2>&1; then
        echo "✓"
    else
        echo "✗"
    fi
done

# 4. Check methylation-clock
echo ""
echo "[4/5] Checking methylation-clock..."
METHYL_DIR="$CLAWBIO_ROOT/skills/methylation-clock"
if [[ -d "$METHYL_DIR" ]]; then
    if [[ -x "$METHYL_DIR/methylation_clock.py" ]]; then
        echo "  ✓ methylation_clock.py is executable"
    else
        echo "  ✗ methylation_clock.py missing execute permission"
    fi
    # Check shebang points to correct Python
    SHEBANG=$(head -1 "$METHYL_DIR/methylation_clock.py" 2>/dev/null || echo "")
    if [[ "$SHEBANG" == *"pyaging"* ]] || [[ "$SHEBANG" == *"miniconda3"* ]]; then
        echo "  ✓ Correct Python interpreter in shebang"
    else
        echo "  ⚠ Shebang may be incorrect: $SHEBANG"
    fi
fi

# 5. Clean temp files
echo ""
echo "[5/5] Checking for temp files..."
TEMP_FILES=$(find "$WORKSPACE_DIR" -name "*.txt" -type f 2>/dev/null | head -5)
if [[ -n "$TEMP_FILES" ]]; then
    echo "  Found temp files:"
    echo "$TEMP_FILES" | while read -r f; do
        echo "    - $f"
    done
    read -p "  Remove these files? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "$TEMP_FILES" | xargs rm -f && echo "  ✓ Cleaned up"
    fi
else
    echo "  ✓ No temp files found"
fi

echo ""
echo "=== Health Check Complete ==="
