#!/usr/bin/env bash
# One command, no side effects: JS syntax, Python compile, the full API suite.
# Used by CI-parity checks; unlike the old laptop check.sh it never edits tests.
set -euo pipefail
cd "$(dirname "$0")/.."
node --check static/app.js && echo "JS SYNTAX OK"
python3 -m py_compile server.py && echo "PY OK"
python3 test_api.py | tee /tmp/rag-test.out
grep -q "ALL OK" /tmp/rag-test.out
! grep -q "^FAIL" /tmp/rag-test.out
echo "CHECK OK"
