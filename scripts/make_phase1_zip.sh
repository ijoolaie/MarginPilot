#!/usr/bin/env bash
# Rebuild the MarginPilot Phase 1 archive with a verifiable manifest.
# Guarantees (third-review fixes):
#   * real .env NEVER enters the archive (excluded by pattern AND verified below)
#   * .env.example ALWAYS enters the archive (re-added explicitly — Info-ZIP has
#     no negation in -x, so the ".env.*" exclude would otherwise drop it)
#   * manifest hashes are verified byte-for-byte against archive CONTENTS
#     (unzip -p comparison) — the script fails hard on any mismatch/absence
#   * real archive composition is reported (files / directories / total entries
#     separately — P2 fix of audit 4); unzip -t must pass
set -euo pipefail
cd /home/z/my-project

OUT=download/marginpilot-phase1-20261116.zip
rm -f "$OUT"

# 1) repository content; exclude .git, the real .env and any .env.* variant
zip -qr "$OUT" . \
  -x ".git/*" ".env" ".env.*" "skills/*" "node_modules/*" \
     "db/*" "upload/*" "download/*" "*.pyc" "*__pycache__*"

# 2) template + verification reports: added explicitly, after the excludes
zip -q "$OUT" .env.example \
  download/Phase0_Environment_Audit_Report.md \
  download/Phase1_Architecture_Report.md \
  download/Phase1_Corrective_Review_Report.md \
  download/Phase1_Final_Corrections_Report.md \
  download/Phase1_Final_Corrections_Report_v2.md \
  download/Phase1_Final_Corrections_Report_v3.md

# 3) guard: real .env must not be inside, template must be inside
if unzip -l "$OUT" | grep -qE '(^|/)\.env$'; then
  echo "FATAL: real .env found inside archive" >&2; exit 1
fi
for f in .env.example README.md docs/*.md \
         download/Phase0_Environment_Audit_Report.md \
         download/Phase1_Architecture_Report.md \
         download/Phase1_Corrective_Review_Report.md \
         download/Phase1_Final_Corrections_Report.md \
         download/Phase1_Final_Corrections_Report_v2.md \
         download/Phase1_Final_Corrections_Report_v3.md; do
  unzip -l "$OUT" "$f" >/dev/null 2>&1 || { echo "FATAL: $f missing from archive" >&2; exit 1; }
done

# 3b) archive composition (P2 fix, audit 4): real files vs directories vs total
FILES_PRE=$(unzip -Z1 "$OUT" | grep -vc '/$' || true)
DIRS_PRE=$(unzip -Z1 "$OUT" | grep -c '/$' || true)
FILES=$((FILES_PRE + 1))    # +1 = PHASE1_MANIFEST.txt, added after this manifest is written
TOTAL=$((FILES + DIRS_PRE))

# 4) manifest: git state + hash↔content verification for every hashed file
{
  echo "MarginPilot — Phase 1 Archive Verification Manifest"
  echo "Generated (UTC): $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "Git HEAD: $(git rev-parse HEAD) (branch: $(git rev-parse --abbrev-ref HEAD))"
  echo "NOTE: the agent performs NO commit/push/merge; checkpoint commits with"
  echo "      UUID messages are created automatically by the session harness."
  echo "NOTE: .git is intentionally NOT archived; this manifest is the git-state"
  echo "      evidence (HEAD, working-tree status, .env ignore proof)."
  echo ""
  echo "Working tree (git status --porcelain):"
  git status --porcelain
  echo ""
  echo ".env ignored by git: $(git check-ignore .env >/dev/null 2>&1 && echo 'YES' || echo 'NO')"
  echo ".env present in worktree: $([ -f .env ] && echo 'YES (excluded from archive)' || echo 'no')"
  echo ".env.example inside archive: YES (re-added explicitly after excludes)"
  echo ""
  echo "Archive composition: $FILES real files · $DIRS_PRE directories · $TOTAL entries"
  echo "  (includes PHASE1_MANIFEST.txt; verified after zipping — script fails on mismatch)"
  echo ""
  echo "SHA-256 of design files — each verified byte-for-byte against archive contents:"
  for f in .env.example README.md docs/*.md; do
    h_src=$(sha256sum "$f" | awk '{print $1}')
    h_zip=$(unzip -p "$OUT" "$f" | sha256sum | awk '{print $1}')
    if [ "$h_src" = "$h_zip" ]; then
      echo "MATCH  $h_src  $f"
    else
      echo "MISMATCH  $h_src  $f" >&2; exit 1
    fi
  done
} > PHASE1_MANIFEST.txt

zip -q "$OUT" PHASE1_MANIFEST.txt
mv PHASE1_MANIFEST.txt download/PHASE1_MANIFEST.txt

# 4b) composition self-verification (P2 fix, audit 4)
F2=$(unzip -Z1 "$OUT" | grep -vc '/$' || true)
D2=$(unzip -Z1 "$OUT" | grep -c '/$' || true)
if [ "$F2" -ne "$FILES" ] || [ "$D2" -ne "$DIRS_PRE" ]; then
  echo "FATAL: composition mismatch — archive has $F2 files/$D2 dirs, manifest claims $FILES/$DIRS_PRE" >&2
  exit 1
fi

# 5) integrity + separate counts (files, directories, total entries)
unzip -t "$OUT" | tail -1
echo "ARCHIVE OK: $OUT — composition: $FILES real files + $DIRS_PRE directories = $TOTAL entries"
unzip -l "$OUT" | tail -2
