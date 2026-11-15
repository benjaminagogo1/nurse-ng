#!/usr/bin/env bash
# Install the private search service without changing the app's Python environment.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
search_revision=3a3dd15bfafcb645a1b45c2c6c0798a8f786aaaf
search_root="$PWD/.local-tools/searxng"
search_source="$search_root/searxng-$search_revision"
mkdir -p "$search_root"
chmod 700 "$search_root"
if [ ! -d "$search_source" ]; then
  curl --location --fail --max-time 120 \
    --output "$search_root/source.tar.gz" \
    "https://github.com/searxng/searxng/archive/$search_revision.tar.gz"
  venv/bin/python - "$search_root" <<'PY'
import hashlib
import sys
import tarfile
from pathlib import Path

root = Path(sys.argv[1])
archive = root / "source.tar.gz"
expected = "1a10d9278f9b75aafab368f9f03ebc9bec653390b28091d60f961f325acb52ed"
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit("Search source archive did not match the pinned checksum.")
with tarfile.open(archive) as source:
    source.extractall(root, filter="data")
PY
fi
if [ ! -x "$search_root/venv/bin/python" ]; then
  venv/bin/python -m venv "$search_root/venv"
fi
"$search_root/venv/bin/python" -m pip install --no-cache-dir \
  -r "$search_source/requirements.txt" -r "$search_source/requirements-server.txt"
venv/bin/python - "$search_root" <<'PY'
import secrets
import sys
from pathlib import Path

settings = Path(sys.argv[1]) / "settings.yml"
if not settings.exists():
    template = Path("deploy/searxng/settings.yml").read_text()
    settings.write_text(template.replace(
        "server:\n", "server:\n  secret_key: " + secrets.token_hex(32) + "\n"
    ))
    settings.chmod(0o600)
PY
printf '%s\n' 'Search installed. Install and start deploy/systemd/nurse-ng-search.service.'
