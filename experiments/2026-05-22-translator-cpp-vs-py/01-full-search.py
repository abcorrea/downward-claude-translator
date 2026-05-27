#! /usr/bin/env python3
"""Full-pipeline (translate + search) comparison: C++ port vs Python translator.

Structure mirrors Scorpion's
`experiments/2026-01-preprocessor/2026-01-08-A-preprocessor-optimizations.py`:

  - SUITE depends on whether we're running on a known compute cluster
    (REMOTE) or locally. Remote: pull the canonical SUITE_SATISFICING
    from `project.py` and resolve via $DOWNWARD_BENCHMARKS. Local:
    a 2-instance smoke suite (gripper, miconic).
  - ENV is chosen the same way: TetralithEnvironment vs LocalEnvironment.
  - One git revision (HEAD) is cached and two algorithms are built on
    top -- they differ only in `--translator cpp` vs `--translator py`,
    a driver flag added by the port to `driver/arguments.py`.

Always invoke this script through `uv run` so the Lab 8 deps in
pyproject.toml are picked up correctly:

    uv run --project ../../  experiments/2026-05-22-translator-cpp-vs-py/01-full-search.py --all
"""
import os

import custom_parser
import project

from downward import suites
from downward.experiment import (
    CachedFastDownwardRevision,
    FastDownwardAlgorithm,
    FastDownwardExperiment,
    FastDownwardRun,
)
from lab.experiment import Experiment

from modern_lab_report import ModernAbsoluteReport


# --- Repository + benchmarks --------------------------------------------------

REPO = str(project.REPO)

# Local: tiny smoke-test suite (matches Scorpion's
# `experiments/.../*-preprocessor-optimizations.py` shape).
SUITE = [
    "gripper:prob01.pddl",
    "miconic:s1-0.pddl",
]
REVISION_CACHE = (
    os.environ.get("DOWNWARD_REVISION_CACHE")
    or project.DIR / "data" / "revision-cache"
)

if project.REMOTE:
    BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
    SUITE = project.SUITE_SATISFICING
    ENV = project.BaselSlurmEnvironment(
        partition="infai_2",
        memory_per_cpu="6G",
        cpus_per_task=2,
        setup=BaselSlurmEnvironment.DEFAULT_SETUP,
    )
else:
    project.assert_local_paths_exist()
    BENCHMARKS_DIR = str(project.LOCAL_BENCHMARKS_DIR)
    ENV = project.LocalEnvironment(processes=2)


# --- Algorithms & configurations ---------------------------------------------

# Satisficing config: LAMA-first via the bundled `--alias` mechanism
# in fast-downward.py. The alias expands to a full LAMA-first
# search/heuristic stack (lazy_greedy + FF + landmark counting +
# preferred ops), so the search itself goes through driver options
# rather than component options. Each tuple is
# (nick, extra driver options, component options).
CONFIGS = [
    ("lama-first", ["--alias", "lama-first"], []),
]

# We compare the same revision against itself with the translator
# backend swapped. The translator choice is a driver-level flag we
# added in driver/arguments.py: `--translator {cpp,py}`.
#
# `--with-translate-cpp` makes ./build.py also build the C++ translator
# port (src/translate-cpp/) and drop its binary at
# builds/<config>/bin/translate-cpp. That's the path the driver looks
# for first; Lab's CachedFastDownwardRevision cleanup keeps
# `builds/*/bin/` so the binary survives the cache prep.
#
# Pin REV explicitly to the commit we want measured so re-running the
# script from a fresher checkout still rebuilds the cache against the
# exact same code. Update this SHA when bringing new translator-port
# work into the next cluster run. Current pin is
# `5136d035e -- choose_groups picks last-of-tied to match py's pop
#                direction (closes blocks-domain divergence), on top
#                of the pre_post sort / operator sort, SCC forward-
#                order fix, MaxDAG port, parser O(N*P), and
#                SIGXCPU/bad_alloc signal handlers.`
REV = "5136d035e93411b826b0f2aabc7666ab1d134cfc"
BUILD_OPTIONS = ["--with-translate-cpp"]
DRIVER_OPTIONS_COMMON = [
    "--validate",
    "--overall-time-limit", "300s",
    "--overall-memory-limit", "8G",
]
TRANSLATOR_VARIANTS = [
    ("cpp", ["--translator", "cpp"]),
    ("py",  ["--translator", "py"]),
]

# H2 invariant synthesis is the dominant source of cpp-vs-py SAS+
# nondeterminism: both translators run a randomized greedy refinement
# and pick different (but equally valid) mutex groupings depending on
# the action-shuffle RNG. `--invariant-generation-max-candidates 0`
# disables it; that gives us a control arm with no H2 RNG noise so we
# can tell whether the residual cpp/py coverage gap is really
# H2-driven or whether something else is at play.
#
# `--translate-options ...` is a separator inside the
# fast-downward.py command line that switches subsequent options to
# the translate component, so the flag goes in component_options.
H2_VARIANTS = [
    ("h2",    []),
    ("no-h2", ["--translate-options",
               "--invariant-generation-max-candidates", "0"]),
]


# --- Experiment ---------------------------------------------------------------

exp = Experiment(environment=ENV)

cached_rev = CachedFastDownwardRevision(REVISION_CACHE, REPO, REV, BUILD_OPTIONS)
cached_rev.cache()
exp.add_resource("", cached_rev.path, cached_rev.get_relative_exp_path())

for tnick, tflags in TRANSLATOR_VARIANTS:
    for hnick, hflags in H2_VARIANTS:
        for cnick, cdriver, ccomponent in CONFIGS:
            # Algorithm names: cpp-h2-lama-first, cpp-no-h2-lama-first,
            # py-h2-lama-first, py-no-h2-lama-first.
            algo_name = f"{tnick}-{hnick}-{cnick}"
            for task in suites.build_suite(BENCHMARKS_DIR, SUITE):
                algo = FastDownwardAlgorithm(
                    algo_name,
                    cached_rev,
                    DRIVER_OPTIONS_COMMON + tflags + cdriver,
                    ccomponent + hflags,
                )
                exp.add_run(FastDownwardRun(exp, algo, task))

# Lab's bundled parsers cover everything we care about; the custom
# parser adds the C++-specific [phase] timer lines. Lab 8's add_parser
# wants Parser *instances*, not paths to scripts (the lab-4-style
# path-based registration was removed).
exp.add_parser(FastDownwardExperiment.EXITCODE_PARSER)
exp.add_parser(FastDownwardExperiment.TRANSLATOR_PARSER)
exp.add_parser(FastDownwardExperiment.SINGLE_SEARCH_PARSER)
exp.add_parser(custom_parser.get_parser())
exp.add_parser(FastDownwardExperiment.PLANNER_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")


# --- Reports -----------------------------------------------------------------

ATTRIBUTES = [
    # Identity / outcome.
    "error", "coverage", "planner_exit_code",
    "search_start_time", "search_start_memory", "total_time",
    "translator_total_time_cpp", "translator_total_time_py",
    # Translator output stats (emitted by both implementations).
    "translator_kind",
    "translator_variables", "translator_facts", "translator_mutex_groups",
    "translator_operators", "translator_axioms", "translator_task_size",
    "translator_peak_memory",
    # Search-side numbers.
    "expansions", "generated", "evaluations", "memory", "cost", "plan_length",
    # C++ phase timers (only populated for cpp-* algorithms).
    "cpp_phase_compute_model_time",
    "cpp_phase_instantiate_time",
    "cpp_phase_translate_strips_operators_time",
    "cpp_phase_simplify_time",
    "cpp_phase_write_time",
    "cpp_phase_pddl_to_sas_total_time",
]


def add_report(name, **kwargs):
    cls = kwargs.pop("cls", ModernAbsoluteReport)
    report = cls(attributes=ATTRIBUTES, **kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute")
# Core comparison with H2 on (the default LAMA pipeline).
add_report(
    "compare-cpp-vs-py-h2",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-h2-lama-first", "cpp-h2-lama-first")],
)
# Control: with H2 disabled the only translator-side nondeterminism
# left is choose_groups / MaxDAG tie-breaking. If cpp and py line up
# closely here, we've confirmed the residual coverage gap is dominated
# by H2 RNG.
add_report(
    "compare-cpp-vs-py-no-h2",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-no-h2-lama-first", "cpp-no-h2-lama-first")],
)
# How much does H2 actually help LAMA on each translator?
add_report(
    "compare-h2-vs-no-h2-cpp",
    cls=project.ComparativeReport,
    algorithm_pairs=[("cpp-no-h2-lama-first", "cpp-h2-lama-first")],
)
add_report(
    "compare-h2-vs-no-h2-py",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-no-h2-lama-first", "py-h2-lama-first")],
)

exp.run_steps()
