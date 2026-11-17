#!/usr/bin/env bash
# Rebuild the MarginPilot Phase 2 / Step 1 archive with a verifiable manifest.
# Same guarantees as the Phase 1 script, extended for Phase 2 content:
#   * real .env NEVER enters the archive (excluded AND hard-fail guard below)
#   * node_modules / build artifacts / tool caches NEVER enter (guards below)
#   * .env.example ALWAYS enters (re-added explicitly after the excludes)
#   * download/evidence/* (gate outputs cited by the report) re-added explicitly
#   * manifest hashes verified byte-for-byte against archive CONTENTS
#   * unzip -t must pass; composition counts verified
set -euo pipefail
cd /home/z/my-project

OUT=download/marginpilot-phase2-step1-20261116.zip
rm -f "$OUT"

# 1) repository content; exclude .git, real .env, sandbox dirs, deps & artifacts
zip -qr "$OUT" . \
  -x ".git/*" ".env" ".env.*" "skills/*" "upload/*" "download/*" \
     "*node_modules*" "*.pyc" "*__pycache__*" \
     ".venv/*" "*/.venv/*" "venv/*" \
     "frontend/dist/*" "scripts/matrix_smoke/dist/*" \
     "*.pytest_cache/*" "*.mypy_cache/*" "*.ruff_cache/*" "*.tsbuildinfo" \
     "scripts/matrix_smoke/package-lock.json"

# 2) template + reports + evidence: added explicitly, after the excludes
zip -q "$OUT" .env.example \
  download/Phase0_Environment_Audit_Report.md \
  download/Phase1_Architecture_Report.md \
  download/Phase1_Corrective_Review_Report.md \
  download/Phase1_Final_Corrections_Report.md \
  download/Phase1_Final_Corrections_Report_v2.md \
  download/Phase1_Final_Corrections_Report_v3.md \
  download/Phase2_Step1_Report.md \
  download/PHASE1_MANIFEST.txt \
  download/evidence/backend_integration_tests.txt \
  download/evidence/backend_lint_type_test.txt \
  download/evidence/backend_lock_generation.txt \
  download/evidence/backend_smoke.txt \
  download/evidence/frontend_lint_type_test_build.txt \
  download/evidence/frontend_matrix_smoke.txt \
  download/evidence/image_digests.json \
  download/evidence/npm_audit.txt \
  download/evidence/pip_audit.txt \
  download/evidence/pydantic_settings_repro.txt \
  download/evidence/uvicorn_phase_a.log \
  download/evidence/uvicorn_phase_b.log

# 3) hard guards: no real .env, no node_modules, no caches inside
if unzip -Z1 "$OUT" | grep -qE '(^|/)\.env$'; then
  echo "FATAL: real .env found inside archive" >&2; exit 1
fi
if unzip -Z1 "$OUT" | grep -q 'node_modules'; then
  echo "FATAL: node_modules found inside archive" >&2; exit 1
fi
if unzip -Z1 "$OUT" | grep -qE '\.pyc$|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache'; then
  echo "FATAL: build/cache artifacts found inside archive" >&2; exit 1
fi
for f in .env.example README.md CHANGELOG.md SECURITY.md docker-compose.yml Caddyfile \
         .github/workflows/ci.yml \
         backend/pyproject.toml backend/requirements.lock backend/requirements-runtime.lock \
         backend/Dockerfile backend/app/main.py backend/app/core/config.py backend/app/core/db.py \
         backend/app/core/logging.py backend/app/core/errors.py backend/app/core/middleware.py \
         backend/app/api/v1/health.py backend/tests/unit/test_config.py \
         backend/tests/unit/test_health.py backend/tests/unit/test_errors.py \
         backend/tests/integration/test_db_readiness.py \
         frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
         frontend/tsconfig.json frontend/eslint.config.js frontend/index.html \
         frontend/src/main.tsx frontend/src/App.tsx frontend/src/lib/api.ts \
         frontend/src/features/welcome/WelcomePage.tsx \
         frontend/src/features/welcome/WelcomePage.test.tsx frontend/Dockerfile \
         scripts/make_backend_lock.sh scripts/smoke_backend.sh \
         docs/architecture.md docs/dependencies.md docs/environment-limitations.md \
         docs/security.md docs/testing-strategy.md docs/data-model.md docs/api-contract.md \
         docs/calculation-principles.md docs/decisions.md \
         download/Phase2_Step1_Report.md download/evidence/pip_audit.txt; do
  unzip -l "$OUT" "$f" >/dev/null 2>&1 || { echo "FATAL: $f missing from archive" >&2; exit 1; }
done

# 3b) composition: real files vs directories vs total
FILES_PRE=$(unzip -Z1 "$OUT" | grep -vc '/$' || true)
DIRS_PRE=$(unzip -Z1 "$OUT" | grep -c '/$' || true)
FILES=$((FILES_PRE + 1))    # +1 = PHASE2_MANIFEST.txt, added after counting
TOTAL=$((FILES + DIRS_PRE))

# 4) manifest: git state + hash<->content verification for key files
{
  echo "MarginPilot — Phase 2 / Step 1 Archive Verification Manifest"
  echo "Generated (UTC): $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "Git HEAD: $(git rev-parse HEAD) (branch: $(git rev-parse --abbrev-ref HEAD))"
  echo "NOTE: the agent performs NO commit/push/merge; checkpoint commits with"
  echo "      UUID messages are created automatically by the session harness."
  echo "NOTE: .git is intentionally NOT archived; this manifest is the git-state"
  echo "      evidence (HEAD, working-tree status, .env ignore proof)."
  echo ""
  echo "Working tree (git status --porcelain):"
  git status --porcelain || true
  echo ""
  echo ".env ignored by git: $(git check-ignore .env >/dev/null 2>&1 && echo 'YES' || echo 'NO')"
  echo ".env present in worktree: $([ -f .env ] && echo 'YES (excluded from archive)' || echo 'no')"
  echo ".env.example inside archive: YES (re-added explicitly after excludes)"
  echo "node_modules / caches / dist inside archive: NO (hard-fail guards passed)"
  echo ""
  echo "Archive composition: $FILES real files · $DIRS_PRE directories · $TOTAL entries"
  echo "  (includes PHASE2_MANIFEST.txt; verified after zipping — script fails on mismatch)"
  echo ""
  echo "SHA-256 of key files — each verified byte-for-byte against archive contents:"
  for f in .env.example README.md CHANGELOG.md SECURITY.md docker-compose.yml Caddyfile \
           .github/workflows/ci.yml \
           backend/pyproject.toml backend/requirements.lock backend/requirements-runtime.lock \
           backend/app/main.py frontend/package.json frontend/package-lock.json \
           frontend/src/features/welcome/WelcomePage.tsx \
           download/Phase2_Step1_Report.md download/evidence/pip_audit.txt \
           download/evidence/backend_integration_tests.txt; do
    h_src=$(sha256sum "$f" | awk '{print $1}')
    h_zip=$(unzip -p "$OUT" "$f" | sha256sum | awk '{print $1}')
    if [ "$h_src" = "$h_zip" ]; then
      echo "MATCH  $h_src  $f"
    else
      echo "MISMATCH  $h_src  $f" >&2; exit 1
    fi
  done
} > PHASE2_MANIFEST.txt

zip -q "$OUT" PHASE2_MANIFEST.txt
mv PHASE2_MANIFEST.txt download/PHASE2_MANIFEST.txt

# 4b) composition self-verification
F2=$(unzip -Z1 "$OUT" | grep -vc '/$' || true)
D2=$(unzip -Z1 "$OUT" | grep -c '/$' || true)
if [ "$F2" -ne "$FILES" ] || [ "$D2" -ne "$DIRS_PRE" ]; then
  echo "FATAL: composition mismatch — archive has $F2 files/$D2 dirs, manifest claims $FILES/$DIRS_PRE" >&2
  exit 1
fi

# 5) integrity + summary
unzip -t "$OUT" | tail -1
echo "ARCHIVE OK: $OUT — composition: $FILES real files + $DIRS_PRE directories = $TOTAL entries"
unzip -l "$OUT" | tail -2
