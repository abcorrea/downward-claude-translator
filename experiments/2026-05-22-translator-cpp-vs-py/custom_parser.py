#! /usr/bin/env python3
"""Extra patterns the C++ port emits that Lab's stock translator-parser
doesn't pick up.

The Python translator prints phases like

    Computing fact groups: [0.012s CPU, 0.012s wall-clock]

The C++ port prints

      [compute_model] 0.605801s
        [fg.choose_groups] 0.017502s (130 groups)

This parser collects the C++-style phase timers under
`cpp_phase_<phase>_time` so they appear alongside the Python timings.
"""
import re

from lab.parser import Parser


def parse_cpp_phase_timers(content, props):
    """Capture `  [phase] X.Ys` and `    [sub.phase] X.Ys` lines.

    Labels may contain spaces (e.g. `[pddl_to_sas total]`), which we
    map to underscores in the attribute name.
    """
    pattern = re.compile(r"^\s*\[([^\]]+)\]\s+([0-9.eE+-]+)s")
    for line in content.splitlines():
        m = pattern.match(line)
        if m:
            phase = re.sub(r"[ .]+", "_", m.group(1).strip())
            try:
                props[f"cpp_phase_{phase}_time"] = float(m.group(2))
            except ValueError:
                pass


def parse_translator_kind(content, props):
    """Mark which translator emitted the log (C++ banner vs Python's
    'Parsing... [0.030s CPU, ...]').
    """
    if "Fast Downward translator (C++ port)" in content:
        props["translator_kind"] = "cpp"
    elif "Done!" in content and "[" in content and "CPU," in content:
        props["translator_kind"] = "py"


def parse_driver_log_exit_code(content, props):
    """fast-downward.py --translate prints `translate exit code: N` and
    `translate wall-clock time: Xs` in driver.log. Capture them under
    `translate_exit_code` / `translate_wall_clock_time`."""
    for line in content.splitlines():
        if "translate exit code:" in line:
            try:
                props["translate_exit_code"] = int(line.split(":")[-1].strip())
            except ValueError:
                pass
        elif "translate wall-clock time:" in line:
            try:
                tok = line.split(":")[-1].strip().rstrip("s")
                props["translate_wall_clock_time"] = float(tok)
            except ValueError:
                pass


def get_parser():
    p = Parser()
    p.add_function(parse_cpp_phase_timers)
    p.add_function(parse_translator_kind)
    p.add_function(parse_driver_log_exit_code, file="driver.log")
    # Emit a final "translator_total_time" pulled from either the C++
    # "Total time: X.Ys" footer or the Python "Done! [X.Ys CPU,...]" footer.
    p.add_pattern("translator_total_time_cpp",
                  r"Total time:\s+([0-9.eE+-]+)s", type=float)
    p.add_pattern("translator_total_time_py",
                  r"Done! \[([0-9.eE+-]+)s CPU,", type=float)
    return p


if __name__ == "__main__":
    get_parser().parse()
