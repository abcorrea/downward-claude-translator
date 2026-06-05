#!/bin/bash
# Correctness gate: the optimized translator must produce byte-for-byte the
# same output.sas as the committed reference for every task. Run AFTER a
# passing benchmark (off the metric clock). Any deviation exits non-zero, and
# the loop reverts -- this stops the loop from "winning" by changing output.
set -euo pipefail
cd "$(dirname "$0")"

REFS=misc/tests/benchmarks/autoresearch-refs
[ -d "$REFS" ] || { echo "reference dir $REFS missing; regenerate with --save-sas" >&2; exit 1; }

exec python3 misc/tests/run_translator_benchmark.py --check "$REFS"
