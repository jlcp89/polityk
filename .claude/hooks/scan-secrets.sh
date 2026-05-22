#!/bin/bash
# Scan staged files for common secret patterns
# Used as a pre-commit hook to prevent accidental secret commits

set -euo pipefail

PATTERNS='(AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{48}|ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|xox[bpors]-[a-zA-Z0-9-]+|password\s*[:=]\s*["\x27][^"\x27]{8,}["\x27]|"type":\s*"service_account"|-----BEGIN.*PRIVATE KEY-----|DefaultEndpointsProtocol=|Bearer [a-zA-Z0-9_-]{20,}|sk_live_[a-zA-Z0-9]{24,}|SG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43})'

STAGED=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)

if [ -z "$STAGED" ]; then
  exit 0
fi

found=0
for file in $STAGED; do
  # Skip binary files and lock files
  case "$file" in
    *.lock|*.png|*.jpg|*.gif|*.ico|*.woff*|*.ttf|*.eot) continue ;;
  esac

  if [ -f "$file" ] && grep -qEi "$PATTERNS" "$file" 2>/dev/null; then
    echo "BLOCKED: Potential secret found in $file" >&2
    found=1
  fi
done

if [ "$found" -eq 1 ]; then
  echo "Remove secrets before committing. Use environment variables instead." >&2
  exit 1
fi
