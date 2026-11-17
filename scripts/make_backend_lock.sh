#!/usr/bin/env bash
# Generate backend/requirements.lock with exact versions + SHA-256 hashes
# (pip-compile from the exact-pinned pyproject.toml). pip-tools is a sandbox
# build tool only — it is NOT a product dependency.
set -euo pipefail
cd /home/z/my-project/backend

pip install -q pip-tools
pip-compile --version

# Full lock (runtime + dev): local development and CI.
pip-compile --generate-hashes --all-extras \
  --output-file=requirements.lock pyproject.toml

# Runtime-only lock (hashed): Docker image — minimal, no dev tooling.
pip-compile --generate-hashes \
  --output-file=requirements-runtime.lock pyproject.toml

echo "--- lock summary ---"
for f in requirements.lock requirements-runtime.lock; do
  echo "$f: $(grep -c '==' $f) pinned packages, $(grep -c 'sha256' $f) hash lines"
done
