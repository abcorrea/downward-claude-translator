# 2026-05-22 — Translator C++ vs Python (Lab experiment)

Lab-based comparison of the C++ port (`src/translate-cpp/`) and the
upstream Python translator (`src/translate/`).

Layout mirrors Scorpion's `experiments/.../` convention
(https://github.com/jendrikseipp/scorpion/tree/scorpion/experiments).

| File | Purpose |
|---|---|
| `project.py` | Repo-local helpers: paths, suite list, env wiring, `SUITE_SATISFICING`, REMOTE detection, compat shim for lab+Py3.10. |
| `custom_parser.py` | Picks up the C++ port's `  [phase] X.Ys` timer format, `translator_kind`, and the driver's `translate exit code:` line. |
| `01-full-search.py` | Full pipeline (translate + search). Two algorithms: `cpp-lazy-ff` and `py-lazy-ff`. |
| `data/` | Lab output (runs + parsed properties + HTML reports). Gitignored. |

## Setup

Lab 4.2 is required (`pip install lab`). The script also expects both
binaries to be built:

```
# C++ translator port
cmake -S src/translate-cpp -B src/translate-cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build src/translate-cpp/build -j

# Fast Downward search component
./build.py release
```

## How the translator backend is selected

The `driver/arguments.py` port adds a `--translator {cpp,py}` flag
that's mapped onto the existing `FD_TRANSLATE_CPP` / `FD_TRANSLATE_PY`
mechanism inside `driver/run_components.py`. The experiment passes the
flag through Lab's `driver_options`, so each algorithm picks its
translator backend without any env-var fiddling.

| Algorithm | Driver flag |
|---|---|
| `cpp-lazy-ff` | `--translator cpp` |
| `py-lazy-ff`  | `--translator py` |

## Local vs remote behaviour

Same pattern as Scorpion's `experiments/2026-01-preprocessor/`:

```python
SUITE = [
    "gripper:prob01.pddl",      # smoke-test suite when running locally
    "miconic:s1-0.pddl",
]

if project.REMOTE:
    BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
    SUITE = project.SUITE_SATISFICING
    ENV  = project.TetralithEnvironment(memory_per_cpu="3584M", …)
else:
    BENCHMARKS_DIR = str(project.LOCAL_BENCHMARKS_DIR)
    ENV = project.LocalEnvironment(processes=2)
```

`project.REMOTE` is true on a Slurm job node (looks for `SLURM_JOB_ID`
or `SLURM_CLUSTER_NAME` in env — lab 4.2's PyPI release doesn't ship
the `<Env>.is_present()` helper Scorpion's lab fork uses, so we sniff
the env vars directly).

`SUITE_SATISFICING` and `SUITE_OPTIMAL_STRIPS` are copied verbatim
from Scorpion's `project.py`.

## Running

```
# All steps (build runs → execute → parse → fetch → report).
python3 01-full-search.py --all

# Individual steps.
python3 01-full-search.py build
python3 01-full-search.py start
python3 01-full-search.py parse-again
python3 01-full-search.py fetch
python3 01-full-search.py absolute
python3 01-full-search.py compare-cpp-vs-py
```

Reports land in `data/01-full-search-eval/*.html`.

## Attributes recorded

Lab's bundled parsers already capture everything we care about:

- `translator-parser`: `translator_variables`, `translator_facts`,
  `translator_mutex_groups`, `translator_operators`, `translator_axioms`,
  `translator_task_size`, `translator_peak_memory`,
  `translator_relevant_atoms`, `translator_uncovered_facts`,
  Python-side phase timings (`translator_time_*`).
- `single-search-parser`: `expansions`, `generated`, `evaluations`,
  `search_start_time`, `search_start_memory`, `memory`, `cost`,
  `plan_length`.
- `exitcode-parser`: `error`, `planner_exit_code`, `unsolvable`.
- `planner-parser`: `coverage`, `total_time`.

`custom_parser.py` adds the C++-specific bits the stock parsers miss:

- `translator_kind` — `cpp` or `py`.
- `translate_exit_code` / `translate_wall_clock_time` from `driver.log`.
- `translator_total_time_cpp` / `_py` — translator footer total.
- `cpp_phase_<name>_time` — every `  [phase] X.Ys` line emitted by the
  C++ port (parse, normalize, build_program, split_rules,
  compute_model, instantiate, fact_groups, handle_axioms,
  translate_strips_operators, simplify, variable_order, write, plus
  `fg.*` sub-phase timers).

## Implementation note

Lab 4.2's `FastDownwardExperiment.add_algorithm` uses
`CachedRevision`, which is Mercurial-only. Since this repo is git, we
skip `add_algorithm` and use a custom `TranslateAndSearchRun(Run)` that
invokes the in-tree `fast-downward.py` directly. We still reference
`FastDownwardExperiment`'s class-level parser constants
(`TRANSLATOR_PARSER`, `SINGLE_SEARCH_PARSER`, …) — those are what the
Scorpion experiments use too, just plumbed differently. For a git-aware
`add_algorithm`, install Scorpion's lab fork:

```
pip install git+https://github.com/jendrikseipp/lab@scorpion
```

…and replace the custom Run loop with the canonical `add_algorithm`
pattern.

## Local smoke-test snapshot

First end-to-end run (`data/01-full-search-eval/properties`):

| Algorithm | Instance | translator | vars | cov | cost | plan length | total_time |
|---|---|---|--:|--:|--:|--:|--:|
| cpp-lazy-ff | gripper:prob01 | cpp | 7 | 1 | 13 | 13 | 0.01 s |
| cpp-lazy-ff | miconic:s1-0   | cpp | 3 | 1 |  4 |  4 | 0.01 s |
| py-lazy-ff  | gripper:prob01 | py  | 7 | 1 | 13 | 13 | 0.01 s |
| py-lazy-ff  | miconic:s1-0   | py  | 3 | 1 |  4 |  4 | 0.01 s |

Same plan length & cost from both translators ⇒ the encodings are
search-equivalent on the smoke-test instances. For larger correctness
evidence across 10 instances see `eval/EVALUATION.md`.

## Follow-up experiments

Drop a new `02-*.py` next to `01-full-search.py`, sharing `project.py`
and (if needed) extending `custom_parser.py`. Lab automatically puts
its data under `data/<script-stem>/`. Likely next steps:

- `02-translator-revisions.py`: A/B two translator-port commits across
  the same SUITE to measure an optimization's wall-clock and search
  impact (once we have the git-aware add_algorithm).
- `03-h2-vs-no-mutex.py`: turn off invariant synthesis in the C++ port
  and quantify the search cost on the satisficing suite — that's the
  flip side of the ged-positional "stronger mutex" observation in
  `eval/EVALUATION.md`.
