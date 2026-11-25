#!/usr/bin/env bash
# Build application and private search dependencies before runtime starts.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --disable-pip-version-check -r requirements.lock
python deploy/search.py install
