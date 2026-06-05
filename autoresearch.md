# Autoresearch: speed up the C++ translator

## Objective
Make the C++ translator (`src/translate-cpp/`) **as fast as possible** while
producing **byte-for-byte identical** `output.sas` on every benchmark task.
Speed only; correctness is a hard gate, not a trade-off.

## Metric
- **`total_cpu`** (seconds, **lower is better**): sum of the translator's own
  user+system CPU over all tasks in the suite, measured per-process via
  `os.wait4` rusage (build/python/shell overhead excluded).
- Secondary (watch, don't optimize): peak RSS is not currently tracked; add it
  to the runner if an idea trades memory for speed.

## How to run
- Benchmark: `./autoresearch.sh` → prints `METRIC total_cpu=<sec>` x3 (1 warmup
  discarded). Rebuilds the translator first (incremental, ~1-2s, off-metric).
- Correctness: `./autoresearch.checks.sh` → byte-compares every task's
  `output.sas` to its committed reference; non-zero exit on any deviation.
- Decide: `python3 .claude/skills/autoresearch/scripts/decide.py --best "<samples>" --candidate "<samples>" --direction lower`

## The loop
`think -> edit src/translate-cpp -> ./autoresearch.sh -> decide -> if KEEP run
./autoresearch.checks.sh -> commit if checks pass, else revert -> log -> repeat`
Run checks only on benchmark-KEEP candidates (they're off the hot path). A
checks failure reverts exactly like a crash.

## Files in scope (edit these)
- `src/translate-cpp/**` — all translator C++ sources. Hot path for these
  hard-to-ground tasks is grounding: `grounding/{model,build,program,split}.cc`,
  then `instantiate/`, `normalize/`, `parser/`, `simplify/`.

## Off-limits (never edit)
- `misc/tests/run_translator_benchmark.py` (the benchmark harness)
- `misc/tests/benchmarks/autoresearch/**` (the task inputs)
- `misc/tests/benchmarks/autoresearch-refs/**` (the references — the ground
  truth for correctness; only regenerate deliberately if output *intentionally*
  changes, which for a pure speedup it must not)
- `autoresearch.sh`, `autoresearch.checks.sh`

## Constraints
- Output must stay byte-identical to the references (the whole point is a
  faster translator with the *same* result). No algorithmic change that alters
  variable order, mutex groups, operator order, etc.
- C++20; must build with `./build.py release --with-translate-cpp`.
- Keep it simple: removing code while holding the metric is a win; ugly
  complexity for a tiny gain is a discard.
- **Elegant code only, no hacks** (user directive). Every kept change must be a
  clean improvement a maintainer would accept: no benchmark special-casing, no
  fragile micro-hacks, no correctness shortcuts. Prefer better algorithms/data
  structures over tricks. If the only way to win is ugly, discard it.

## Suite (18 tasks, one per domain family, each ~translator_time_done near 20s)
HTG (8): blocksworld-large-simple, childsnack-contents-parsize2-cham7,
genome-edit-distance-positional, logistics-large-simple,
organic-synthesis-original, pipesworld-tankage-nosplit, rovers-large-simple,
visitall-multidimensional-3-dim-visitall-CLOSE-g2.
IPC (10): agricola-sat18-strips, caldera-sat18-adl, flashfill-sat18-adl,
nurikabe-sat18-adl, openstacks-strips, organic-synthesis-split-sat18-strips,
psr-large, satellite, scanalyzer-08-strips, settlers-sat18-adl.
(Families whose slowest task was <=10s were skipped per the selection rule.)

## State
- Ledger: `autoresearch.jsonl` (append-only; config header + one line per run).
- Baseline is the first result line (segment 0).

## What's Been Tried
(empty — baseline pending)
- 
