#!/bin/bash
# Benchmark the C++ translator: rebuild, warm up, then time >=3 reps.
# Prints one `METRIC total_cpu=<seconds>` line per rep (sum of the
# translator's own user+sys CPU over all tasks in the autoresearch suite).
# The build is OFF the metric clock -- total_cpu is measured per-process via
# os.wait4 rusage, so build/python/shell overhead never enters the metric.
set -euo pipefail
cd "$(dirname "$0")"

BIN=builds/release/bin/translate-cpp

# --- rebuild the translator (incremental; ~1-2s when unchanged) -------------
# A build failure aborts with non-zero -> the loop treats it as a crash/revert.
./build.py release --with-translate-cpp >/tmp/autoresearch-build.log 2>&1 || {
    echo "BUILD FAILED -- see /tmp/autoresearch-build.log" >&2
    tail -20 /tmp/autoresearch-build.log >&2
    exit 1
}

# --- fast sanity pre-check (<1s) --------------------------------------------
[ -x "$BIN" ] || { echo "translator binary missing after build" >&2; exit 1; }

# --- warm up (1 discarded pass) + 3 timed reps, pinned to one core ----------
# taskset reduces cross-core migration noise; fall back if unavailable.
RUNNER=(python3 misc/tests/run_translator_benchmark.py --warmup 1 --reps 3)
if command -v taskset >/dev/null 2>&1; then
    exec taskset -c 1 "${RUNNER[@]}"
else
    exec "${RUNNER[@]}"
fi
