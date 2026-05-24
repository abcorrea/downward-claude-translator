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
    ENV = project.TetralithEnvironment(
        memory_per_cpu="3584M",
        # Override these in a remote checkout:
        # email="user@example.com",
        # extra_options="#SBATCH --account=naissXXXX-Y-ZZZ",
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
REV = "HEAD"
BUILD_OPTIONS = ["--with-translate-cpp"]
DRIVER_OPTIONS_COMMON = [
    "--validate",
    "--overall-time-limit", "120s",
    "--overall-memory-limit", "2G",
]
TRANSLATOR_VARIANTS = [
    ("cpp", ["--translator", "cpp"]),
    ("py",  ["--translator", "py"]),
]


# --- Experiment ---------------------------------------------------------------

exp = Experiment(environment=ENV)

cached_rev = CachedFastDownwardRevision(REVISION_CACHE, REPO, REV, BUILD_OPTIONS)
cached_rev.cache()
exp.add_resource("", cached_rev.path, cached_rev.get_relative_exp_path())

for tnick, tflags in TRANSLATOR_VARIANTS:
    for cnick, cdriver, ccomponent in CONFIGS:
        algo_name = f"{tnick}-{cnick}"
        for task in suites.build_suite(BENCHMARKS_DIR, SUITE):
            algo = FastDownwardAlgorithm(
                algo_name,
                cached_rev,
                DRIVER_OPTIONS_COMMON + tflags + cdriver,
                ccomponent,
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
    cls = kwargs.pop("cls", project.AbsoluteReport)
    report = cls(attributes=ATTRIBUTES, **kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute")
add_report(
    "compare-cpp-vs-py",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-lama-first", "cpp-lama-first")],
)

exp.run_steps()
