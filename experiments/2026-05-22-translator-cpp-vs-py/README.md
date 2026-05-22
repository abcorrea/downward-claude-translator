# 2026-05-22 — Translator C++ vs Python (Lab experiment)

Lab-based comparison of the C++ port (`src/translate-cpp/`) and the
upstream Python translator (`src/translate/`) on the bundled benchmark
suite (`misc/tests/benchmarks/`).

Layout mirrors Scorpion's `experiments/.../` convention
(https://github.com/jendrikseipp/scorpion/tree/scorpion/experiments):

| File | Purpose |
|---|---|
| `project.py` | Repo-local helpers: paths, suite list, env wiring, compat shim for lab+Py3.10. |
| `custom_parser.py` | Picks up the C++ port's `  [phase] X.Ys` timer format, `Translator kind`, and the driver's `translate exit code:` line. |
| `01-translate-only.py` | `--translate`-only comparison (no search). Two algorithms: `cpp` and `py`. |
| `data/` | Lab output (runs + parsed properties + HTML reports). Gitignored. |

## Setup

Lab 4.2 is required (`pip install lab`). The script also expects the
C++ translator to be built:

```
cmake -S src/translate-cpp -B src/translate-cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build src/translate-cpp/build -j
```

The Python translator is found at `src/translate/` (no build needed).

## Running

```
# All steps (build runs → execute → parse → fetch → report).
python3 01-translate-only.py --all

# Or one step at a time.
python3 01-translate-only.py build
python3 01-translate-only.py start
python3 01-translate-only.py fetch
python3 01-translate-only.py absolute
python3 01-translate-only.py compare-cpp-vs-py
```

Reports land in `data/01-translate-only-eval/*.html`.

## What gets compared

Per-run, both translators are invoked through `fast-downward.py
--translate <domain> <problem>`. Which binary the driver picks is
controlled by env vars set per run:

| Algorithm | Env vars set by the runner |
|---|---|
| `cpp` | `FD_TRANSLATE_CPP=<repo>/src/translate-cpp/build/translate` |
| `py`  | `FD_TRANSLATE_PY=1` |

(See `driver/run_components.py` for how the toggle works.)

Each run is capped at **120 s wall** and **2 GiB virtual memory**,
matching the project-wide test constraint.

## Attributes recorded

The bundled Lab translator parser (`downward.scripts.translator-parser`)
already picks up:

- `translator_variables`, `translator_facts`, `translator_mutex_groups`,
  `translator_operators`, `translator_axioms`, `translator_task_size`,
  `translator_peak_memory`
- `translator_relevant_atoms`, `translator_uncovered_facts`, etc.
- Python-style phase timings: `translator_time_*` (each `[X.Xs CPU, …]`
  line).

`custom_parser.py` adds:

- `translator_kind` — `cpp` or `py`.
- `translate_exit_code` / `translate_wall_clock_time` from
  `driver.log`.
- `translator_total_time_cpp` / `_py` — the footer total.
- `cpp_phase_<name>_time` — every `  [phase] X.Ys` line emitted by the
  C++ port (parse, normalize, build_program, split_rules,
  compute_model, instantiate, fact_groups, handle_axioms,
  translate_strips_operators, simplify, variable_order, write, plus
  `fg.*` sub-phase timers).

## First-run snapshot (sanity check, not for citation)

The first end-to-end run on this machine produced
(`data/01-translate-only-eval/properties` → `translate_wall_clock_time`):

| Instance | C++ | Python | Speedup |
|---|--:|--:|--:|
| airport/p40-airport5MUC-p4 | 0.71 s | 3.75 s | 5.3× |
| ged/d-5-10 | 1.59 s | 12.14 s | 7.6× |
| ged-positional/d-1-3 | 0.47 s | 1.89 s | 4.0× |
| gripper/prob01 | 0.05 s | 0.10 s | 2.0× |
| logistics/p01 | 2.21 s | 13.38 s | 6.1× |
| miconic/s1-0 | 0.05 s | 0.11 s | 2.2× |
| miconic-simpleadl/s1-0 | 0.05 s | 0.10 s | 2.0× |
| organic-synthesis-MIT/p3 | 2.57 s | 9.43 s | 3.7× |
| philosophers/p01-phil2 | 0.06 s | 0.14 s | 2.3× |
| satellite/p25-HC-pfile5 | 0.49 s | 3.28 s | 6.7× |

For the cumulative correctness picture (which instances are
byte-identical to Python's output vs canonically equivalent), see
`eval/EVALUATION.md`.

## Adding follow-up experiments

Follow Scorpion's convention: a new script `02-something.py` next to
`01-translate-only.py`, sharing `project.py` and (if needed)
extending `custom_parser.py`. Keep the experiment's own data under
`data/<script-stem>/` (Lab does this automatically).

The natural follow-ups already on the radar:

- `02-full-search.py`: re-use `FastDownwardExperiment` to drive the
  full pipeline (translate + search) and verify both encodings
  produce equivalent plans on the satisficing track.
- `03-translator-revisions.py`: compare two C++ port revisions to
  measure an optimization's wall-clock impact across the suite
  (`CachedFastDownwardRevision` style).
