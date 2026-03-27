#!/usr/bin/env bash
# ══════════════════════════════════════════════════════
#   STENOGRAPHER — version bump
#   Usage:
#     ./bump.sh          # bump patch  1.0.0 → 1.0.1
#     ./bump.sh minor    # bump minor  1.0.1 → 1.1.0
#     ./bump.sh major    # bump major  1.1.0 → 2.0.0
# ══════════════════════════════════════════════════════
set -euo pipefail

PART="${1:-patch}"

# ── Get current version from latest tag ───────────────────────────────────────
CURRENT=$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || echo "0.0.0")
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$PART" in
    major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
    minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
    patch) PATCH=$((PATCH + 1)) ;;
    *)     echo "Usage: $0 [patch|minor|major]"; exit 1 ;;
esac

NEXT="${MAJOR}.${MINOR}.${PATCH}"
TAG="v${NEXT}"

echo "  Current version : v${CURRENT}"
echo "  New version     : ${TAG}"
echo ""
read -rp "Tag and push ${TAG}? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

git tag "$TAG"
git push origin "$TAG"

echo ""
echo "  ✓ Tagged ${TAG} — CI is building the release."
echo "    https://github.com/feanor08/Stenographer/actions"
