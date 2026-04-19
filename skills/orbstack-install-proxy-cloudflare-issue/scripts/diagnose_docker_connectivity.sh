#!/bin/bash
# Network diagnostic script for Docker container runtime connectivity
# Helps identify why some Docker images/services can't be pulled

set -e

TARGET_HOST="${1:-}"

echo "=== Docker Runtime Connectivity Diagnostic ==="
echo ""

if [[ -z "$TARGET_HOST" ]]; then
    echo "Usage: $0 <hostname>"
    echo "  Diagnoses connectivity issues to a given hostname"
    echo ""
    echo "Example: $0 cdn-updates.orbstack.dev"
    exit 1
fi

echo "Target: $TARGET_HOST"
echo ""

# 1. DNS resolution
echo "[1/6] DNS Resolution..."
DIG_RESULT=$(dig +short "$TARGET_HOST" 2>/dev/null || echo "FAILED")
echo "  IPs: $DIG_RESULT"

# 2. HTTPS connectivity with verbose output
echo ""
echo "[2/6] HTTPS Connection Test..."
CURL_OUTPUT=$(curl -v --connect-timeout 10 "https://$TARGET_HOST" 2>&1)
if echo "$CURL_OUTPUT" | grep -q "Connected"; then
    echo "  ✓ Connected"
else
    echo "  ✗ Connection failed"
fi

# 3. SSL/TLS handshake
echo ""
echo "[3/6] SSL Handshake..."
if echo "$CURL_OUTPUT" | grep -q "SSL connection timeout\|SSL_ERROR_SYSCALL\|handshake failed"; then
    echo "  ✗ SSL handshake failed"
    echo "$CURL_OUTPUT" | grep -E "(SSL|TLS|error)" | head -3
else
    echo "  ✓ SSL handshake OK"
fi

# 4. Check CDN/provider
echo ""
echo "[4/6] CDN Detection..."
if [[ -n "$DIG_RESULT" ]]; then
    FIRST_IP=$(echo "$DIG_RESULT" | head -1)
    echo "  Resolved to: $FIRST_IP"
    # Basic CDN detection
    if host "$FIRST_IP" 2>/dev/null | grep -qi "cloudflare"; then
        echo "  ⚠ Cloudflare CDN detected - may block datacenter IPs"
    fi
fi

# 5. Check proxy environment
echo ""
echo "[5/6] Proxy Settings..."
HTTP_PROXY="${HTTP_PROX:-${http_proxy:-}}"
HTTPS_PROXY="${HTTPS_PROXY:-${https_proxy:-}}"
SOCKS_PROXY="${SOCKS_PROXY:-${socks_proxy:-}}"

if [[ -n "$HTTP_PROXY" ]] || [[ -n "$HTTPS_PROXY" ]] || [[ -n "$SOCKS_PROXY" ]]; then
    echo "  HTTP_PROXY:  ${HTTP_PROXY:-not set}"
    echo "  HTTPS_PROXY: ${HTTPS_PROXY:-not set}"
    echo "  SOCKS_PROXY: ${SOCKS_PROXY:-not set}"
else
    echo "  No system proxy configured"
fi

# 6. Check for VPN/TUN mode
echo ""
echo "[6/6] VPN/TUN Check..."
if ip addr show 2>/dev/null | grep -q "utun"; then
    echo "  ⚠ TUN interface detected (VPN/Tunnel mode active)"
    ip addr show | grep "utun" | head -2
fi

echo ""
echo "=== Diagnostic Complete ==="
