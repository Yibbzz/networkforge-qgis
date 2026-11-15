#!/usr/bin/env bash
# Writes the lists of exactly what the plugin installs for its engine,
# every file with its checksum (networkforge_qgis/locks/). The plugin
# installs from these lists only, and refuses a file whose checksum
# differs, so users get the versions that were tested and nothing else.
#
#     scripts/lock_engine.sh <engine version> <uv version>
#     scripts/lock_engine.sh 1.4.1 0.11.32
#
# Run it to upgrade the engine or uv, then change ENGINE_VERSION /
# UV_VERSION in engine.py to match (a test checks they agree). The
# engine's dependencies are the versions its own tests ran with (its
# uv.lock at that tag).
# Needs uv and the internet. Review the diff before committing it.
set -euo pipefail
cd "$(dirname "$0")/.."
engine="${1:?engine version, e.g. 1.4.1}"
uv_version="${2:?uv version, e.g. 0.11.32}"
locks=networkforge_qgis/locks
mkdir -p "$locks"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

compile() {  # compile <requirement> <output> [extra uv options]
  local requirement="$1" output="$2"; shift 2
  echo "$requirement" > "$work/in.txt"
  # --universal: one list for Windows, macOS and Linux.
  uv pip compile --quiet --universal --python-version 3.12 --generate-hashes \
     --no-header --no-annotate "$@" "$work/in.txt" -o "$output"
}

# The versions the engine's own tests ran with: its uv.lock at that tag.
mkdir "$work/engine"
for file in pyproject.toml uv.lock; do
  curl -fsSL "https://raw.githubusercontent.com/Yibbzz/networkforge/v$engine/$file" \
       -o "$work/engine/$file"
done
tested() {  # tested <output> [extra uv options]: name==version lines
  local output="$1"; shift
  uv export --quiet --frozen --no-dev --no-emit-project --no-hashes --no-header \
     --no-annotate --project "$work/engine" "$@" -o "$output"
}
tested "$work/tested.txt"
tested "$work/tested-traffic.txt" --extra traffic
compile "networkforge==$engine" "$locks/engine.txt" -c "$work/tested.txt"
# Traffic adds Valhalla (pyvalhalla); everything else is as above.
compile "networkforge[traffic]==$engine" "$locks/traffic.txt" -c "$work/tested-traffic.txt"
# uv itself, as a Python package (how the plugin fetches it where QGIS has pip).
compile "uv==$uv_version" "$locks/uv.txt"

# uv's own builds (where QGIS's Python has no pip): name and SHA-256.
{
  echo "# uv $uv_version: its builds on GitHub and their SHA-256 checksums."
  echo "# Written by scripts/lock_engine.sh; don't edit by hand."
  for name in uv-x86_64-pc-windows-msvc.zip uv-aarch64-pc-windows-msvc.zip \
              uv-x86_64-apple-darwin.tar.gz uv-aarch64-apple-darwin.tar.gz \
              uv-x86_64-unknown-linux-musl.tar.gz uv-aarch64-unknown-linux-musl.tar.gz; do
    sum=$(curl -fsSL "https://github.com/astral-sh/uv/releases/download/$uv_version/$name.sha256" | cut -d' ' -f1)
    [ ${#sum} -eq 64 ] || { echo "no checksum for $name" >&2; exit 1; }
    echo "$name $sum"
  done
} > "$locks/uv-downloads.txt"
echo "Wrote $locks: $(grep -c '==' "$locks/engine.txt") packages for the engine."
