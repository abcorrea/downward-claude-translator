#! /usr/bin/env python3
"""Full-pipeline (translate + search) comparison of the C++ port vs the
Python translator on the HTG (hard-to-ground) flattened benchmark
suite (40 domains under $HTG_BENCHMARKS_FLATTENED).

Structure mirrors 01-full-search.py:

  - SUITE depends on whether we're running on a known compute cluster
    (REMOTE) or locally. Remote: the full HTG suite (40 domains).
    Local: a single smoke-test instance from organic-synthesis-alkene.
  - $HTG_BENCHMARKS_FLATTENED is read in *both* arms -- it points to
    the same flattened layout on the user's laptop and on the cluster.
  - Same four algorithms as 01: cpp/py x h2/no-h2, all on LAMA-first.

Invoke through `uv run` so the Lab 8 deps in pyproject.toml resolve:

    uv run --project ../../ ./02-htg-search.py --all
"""
import os

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
BENCHMARKS_DIR = os.environ["HTG_BENCHMARKS_FLATTENED"]

REVISION_CACHE = (
    os.environ.get("DOWNWARD_REVISION_CACHE")
    or project.DIR / "data" / "revision-cache"
)

# Full HTG suite: 40 flattened-domain dirs under $HTG_BENCHMARKS_FLATTENED.
SUITE_HTG = [
    "blocksworld-large-simple",
    "childsnack-contents-parsize1-cham3",
    "childsnack-contents-parsize1-cham5",
    "childsnack-contents-parsize1-cham7",
    "childsnack-contents-parsize2-cham3",
    "childsnack-contents-parsize2-cham5",
    "childsnack-contents-parsize2-cham7",
    "childsnack-contents-parsize3-cham3",
    "childsnack-contents-parsize3-cham5",
    "childsnack-contents-parsize3-cham7",
    "childsnack-contents-parsize4-cham3",
    "childsnack-contents-parsize4-cham5",
    "childsnack-contents-parsize4-cham7",
    "genome-edit-distance",
    "genome-edit-distance-positional",
    "genome-edit-distance-split",
    "logistics-large-simple",
    "organic-synthesis-MIT",
    "organic-synthesis-alkene",
    "organic-synthesis-original",
    "pipesworld-tankage-nosplit",
    "rovers-large-simple",
    "visitall-multidimensional-3-dim-visitall-CLOSE-g1",
    "visitall-multidimensional-3-dim-visitall-CLOSE-g2",
    "visitall-multidimensional-3-dim-visitall-CLOSE-g3",
    "visitall-multidimensional-3-dim-visitall-FAR-g1",
    "visitall-multidimensional-3-dim-visitall-FAR-g2",
    "visitall-multidimensional-3-dim-visitall-FAR-g3",
    "visitall-multidimensional-4-dim-visitall-CLOSE-g1",
    "visitall-multidimensional-4-dim-visitall-CLOSE-g2",
    "visitall-multidimensional-4-dim-visitall-CLOSE-g3",
    "visitall-multidimensional-4-dim-visitall-FAR-g1",
    "visitall-multidimensional-4-dim-visitall-FAR-g2",
    "visitall-multidimensional-4-dim-visitall-FAR-g3",
    "visitall-multidimensional-5-dim-visitall-CLOSE-g1",
    "visitall-multidimensional-5-dim-visitall-CLOSE-g2",
    "visitall-multidimensional-5-dim-visitall-CLOSE-g3",
    "visitall-multidimensional-5-dim-visitall-FAR-g1",
    "visitall-multidimensional-5-dim-visitall-FAR-g2",
    "visitall-multidimensional-5-dim-visitall-FAR-g3",
]

if project.REMOTE:
    SUITE = SUITE_HTG
    ENV = project.BaselSlurmEnvironment(
        partition="infai_2",
        memory_per_cpu="6G",
        cpus_per_task=2,
        setup=BaselSlurmEnvironment.DEFAULT_SETUP,
    )
else:
    # Local smoke: one organic-synthesis-alkene task only.
    SUITE = ["organic-synthesis-alkene:p1.pddl"]
    ENV = project.LocalEnvironment(processes=2)


# --- Algorithms & configurations ---------------------------------------------

# Same satisficing config as 01: LAMA-first via the bundled --alias.
CONFIGS = [
    ("lama-first", ["--alias", "lama-first"], []),
]

# Pin REV to the latest translator-port commit on this branch so the
# cluster rebuilds the cache against the exact code being measured.
# Current pin: 8cddd784e -- C++ translator prints the Python phase-log
# format so the stock TRANSLATOR_PARSER captures translator_time_* /
# translator_peak_memory for both backends, on top of argument interning
# (peak RSS ~-56% on rovers), index-based compute_model dedup +
# join/product indexes, choose_groups last-of-tied, pre_post/operator
# sort, SCC forward-order, MaxDAG, parser O(N*P), and SIGXCPU/bad_alloc
# signal handlers.
REV = "8cddd784e9171880f41b0f5a1e4d5f2535e36e59"
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
            algo_name = f"{tnick}-{hnick}-{cnick}"
            for task in suites.build_suite(BENCHMARKS_DIR, SUITE):
                algo = FastDownwardAlgorithm(
                    algo_name,
                    cached_rev,
                    DRIVER_OPTIONS_COMMON + tflags + cdriver,
                    ccomponent + hflags,
                )
                exp.add_run(FastDownwardRun(exp, algo, task))

# Stock parsers only: the C++ port prints the Python translator's
# phase-log format, so TRANSLATOR_PARSER captures translator_time_<phase>
# and translator_peak_memory for both backends -- no custom parser.
exp.add_parser(FastDownwardExperiment.EXITCODE_PARSER)
exp.add_parser(FastDownwardExperiment.TRANSLATOR_PARSER)
exp.add_parser(FastDownwardExperiment.SINGLE_SEARCH_PARSER)
exp.add_parser(FastDownwardExperiment.PLANNER_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")


# --- Reports -----------------------------------------------------------------

ATTRIBUTES = [
    "error", "coverage", "planner_exit_code",
    "search_start_time", "search_start_memory", "total_time",
    # Translator timings + peak memory from the stock TRANSLATOR_PARSER,
    # populated for both backends (the C++ port prints the Python
    # translator's phase-log format). translator_time_done is the total.
    "translator_time_done",
    "translator_time_parsing",
    "translator_time_normalizing_task",
    "translator_time_generating_datalog_program",
    "translator_time_normalizing_datalog_program",
    "translator_time_computing_model",
    "translator_time_completing_instantiation",
    "translator_time_computing_fact_groups",
    "translator_time_processing_axioms",
    "translator_time_translating_task",
    "translator_time_detecting_unreachable_propositions",
    "translator_time_reordering_and_filtering_variables",
    "translator_time_writing_output",
    "translator_peak_memory",
    "translator_variables", "translator_facts", "translator_mutex_groups",
    "translator_operators", "translator_axioms", "translator_task_size",
    "expansions", "generated", "evaluations", "memory", "cost", "plan_length",
]


def add_report(name, **kwargs):
    cls = kwargs.pop("cls", ModernAbsoluteReport)
    report = cls(attributes=ATTRIBUTES, **kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute")
add_report(
    "compare-cpp-vs-py-h2",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-h2-lama-first", "cpp-h2-lama-first")],
)
add_report(
    "compare-cpp-vs-py-no-h2",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-no-h2-lama-first", "cpp-no-h2-lama-first")],
)
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
