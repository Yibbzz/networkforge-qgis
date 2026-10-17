#!/usr/bin/env bash
# The checks plugins.qgis.org runs on an uploaded plugin, the ones that
# can block a version: bandit (security), detect-secrets (passwords and
# tokens in the code) and flake8's critical rules (code that can't run).
# Run on every push (tests.yml) and before every release (release.yml).
#
#     pip install bandit detect-secrets flake8
#     scripts/plugin_checks.sh
#
# Newest versions on purpose: plugins.qgis.org uses the newest too.
# The Qt6 check is scripts/qt6_check.sh.
set -euo pipefail
cd "$(dirname "$0")/.."
plugin=networkforge_qgis

echo "== bandit (reads $plugin/.bandit, which says why B404 and B603 are skipped)"
bandit -r "$plugin"

echo "== detect-secrets"
detect-secrets scan --all-files "$plugin" | python3 -c '
import json, sys
found = json.load(sys.stdin)["results"]
for path, secrets in found.items():
    for secret in secrets:
        print(path, secret["line_number"], secret["type"], sep=": ")
sys.exit(1 if found else 0)'
echo "No secrets found."

echo "== flake8 (the rules plugins.qgis.org counts as critical)"
flake8 --select=E901,E902,E999,F821,F823,F831 "$plugin"
echo "No critical flake8 problems."
