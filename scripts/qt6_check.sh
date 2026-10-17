#!/usr/bin/env bash
# plugins.qgis.org's "Qt6 compatibility" check: QGIS's own pyqt5_to_pyqt6
# script, which lists names that changed for QGIS 4 / Qt6 (such as enum
# values that need their enum's name in front). Its warnings don't block
# a version, but they show on the plugin's page.
#
# Needs QGIS 4's Python with PyQt6, as in the qgis/qgis:latest image
# (tests.yml runs it there):
#
#     docker run --rm -v "$PWD:/w" -w /w qgis/qgis:latest scripts/qt6_check.sh
#
# The script is taken from QGIS's master branch, like plugins.qgis.org.
# It always exits 0, so its output decides.
set -euo pipefail
cd "$(dirname "$0")/.."

# Two PyQt6 modules the script imports that the image doesn't have.
if ! python3 -c "from PyQt6 import QtQuickWidgets, Qsci" 2>/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        python3-pyqt6.qtquick python3-pyqt6.qsci >/dev/null
fi
python3 -m pip install -q --break-system-packages --root-user-action=ignore tokenize-rt

work=$(mktemp -d)
python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(*sys.argv[1:])' \
    https://raw.githubusercontent.com/qgis/QGIS/master/scripts/pyqt5_to_pyqt6/pyqt5_to_pyqt6.py \
    "$work/pyqt5_to_pyqt6.py"
python3 "$work/pyqt5_to_pyqt6.py" --dry_run networkforge_qgis 2>&1 | tee "$work/log"

# Its findings are lines like "compat.py:23:25 - Enum error, ...".
if grep -qE '\.py:[0-9]+:[0-9]+ - ' "$work/log"; then
    echo "Qt6 problems found (above)."
    exit 1
fi
echo "No Qt6 problems found."
