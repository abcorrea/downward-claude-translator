#!/usr/bin/env python3
"""Render modern HTML reports from lab/downward ``properties`` files.

The output keeps the same report shape as lab's AbsoluteReport: algorithm
configurations are columns, attributes are sections, and each attribute has a
domain summary plus per-domain task tables.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import lzma
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Iterable

from downward.reports import PlanningReport
from downward.reports.absolute import AbsoluteReport
from lab import reports, tools


PREFERRED_ATTRIBUTES = [
    "coverage",
    "expansions",
    "max_open_list_size",
    "memory",
    "memory_limit",
    "plan_length",
    "planner_exit_code",
    "planner_wall_clock_time",
    "raw_memory",
    "search_time",
    "total_time",
    "time_limit",
    "initial_h_value",
    "exit_solved",
    "exit_incomplete",
    "exit_timeout",
    "exit_memory",
    "hc_failed",
    "descending",
]

IDENTITY_KEYS = {
    "algorithm",
    "domain",
    "problem",
    "id",
    "run_dir",
    "node",
    "error",
    "unexplained_errors",
}


@dataclass(frozen=True)
class Cell:
    value: Any
    numeric: float | None = None
    better: str = "none"
    html: bool = False
    digits: int = 2
    run_dirs: tuple[str, ...] = ()


@dataclass
class RunIndex:
    runs: list[dict[str, Any]]
    algorithms: list[str]
    domains: list[str]
    problems_by_domain: dict[str, list[str]]
    problem_runs: dict[tuple[str, str], list[dict[str, Any]]]
    by_algorithm: dict[str, list[dict[str, Any]]]
    by_domain_algorithm: dict[tuple[str, str], list[dict[str, Any]]]
    by_problem_algorithm: dict[tuple[str, str, str], list[dict[str, Any]]]


def is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def number_or_none(value: Any) -> float | None:
    if is_number(value):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if math.isfinite(parsed):
            return parsed
    return None


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    if isinstance(value, list):
        return "; ".join(fmt(item, digits) for item in value)
    return str(value)


def titleize(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").title()


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    return value.strip("-") or "section"


def load_properties(path: Path) -> dict[str, dict[str, Any]]:
    if path.is_dir():
        plain = path / "properties"
        compressed = path / "properties.xz"
        if plain.exists():
            path = plain
        elif compressed.exists():
            path = compressed
        else:
            raise FileNotFoundError(f"No properties or properties.xz in {path}")

    if path.suffix == ".xz":
        with lzma.open(path, "rt") as handle:
            data = json.load(handle)
    else:
        with path.open() as handle:
            data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Expected object at top level in {path}")
    return {key: value for key, value in data.items() if isinstance(value, dict)}


def discover_eval_dirs(root: Path) -> list[Path]:
    dirs = set()
    for path in root.rglob("properties"):
        if is_eval_dir(path.parent):
            dirs.add(path.parent)
    for path in root.rglob("properties.xz"):
        if is_eval_dir(path.parent):
            dirs.add(path.parent)
    return sorted(dirs)


def is_eval_dir(path: Path) -> bool:
    return path.name.endswith("-eval") or any(path.glob("*.html"))


def present_attributes(runs: Iterable[dict[str, Any]]) -> list[str]:
    numeric_keys = {
        key
        for run in runs
        for key, value in run.items()
        if key not in IDENTITY_KEYS and is_number(value)
    }
    preferred = [
        attribute for attribute in PREFERRED_ATTRIBUTES if attribute in numeric_keys
    ]
    return preferred + sorted(numeric_keys - set(preferred))


def build_index(
    runs: list[dict[str, Any]],
    *,
    algorithms: list[str] | None = None,
    domains: list[str] | None = None,
) -> RunIndex:
    by_algorithm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    problem_runs: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_domain_algorithm: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_problem_algorithm: dict[tuple[str, str, str], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    problems: dict[str, set[str]] = defaultdict(set)
    for run in runs:
        algorithm = str(run.get("algorithm", ""))
        domain = str(run.get("domain", ""))
        problem = str(run.get("problem", ""))
        by_algorithm[algorithm].append(run)
        problem_runs[(domain, problem)].append(run)
        by_domain_algorithm[(domain, algorithm)].append(run)
        by_problem_algorithm[(domain, problem, algorithm)].append(run)
        problems[domain].add(problem)
    algorithms = algorithms or tools.natural_sort(by_algorithm)
    domains = domains or tools.natural_sort(problems)
    return RunIndex(
        runs=runs,
        algorithms=[algorithm for algorithm in algorithms if algorithm in by_algorithm],
        domains=[domain for domain in domains if domain in problems],
        problems_by_domain={
            domain: sorted(items) for domain, items in problems.items()
        },
        problem_runs=dict(problem_runs),
        by_algorithm=dict(by_algorithm),
        by_domain_algorithm=dict(by_domain_algorithm),
        by_problem_algorithm=dict(by_problem_algorithm),
    )


def prepare_attribute(attribute: Any) -> Any:
    if hasattr(attribute, "function") and hasattr(attribute, "min_wins"):
        return attribute
    predefined = {str(item): item for item in PlanningReport.PREDEFINED_ATTRIBUTES}
    if attribute in predefined:
        return predefined[attribute]
    for pattern in PlanningReport.PREDEFINED_ATTRIBUTES:
        if fnmatch.fnmatch(attribute, pattern):
            return pattern.copy(attribute)
    return reports.Attribute(attribute)


def prepare_attributes(attributes: Iterable[Any]) -> list[Any]:
    return [prepare_attribute(attribute) for attribute in attributes]


def attribute_name(attribute: Any) -> str:
    return str(attribute)


def aggregation_label(attribute: Any) -> str:
    return reports.function_name(attribute.function).capitalize()


def better_for(attribute: Any) -> str:
    if attribute.min_wins is True:
        return "lower"
    if attribute.min_wins is False:
        return "higher"
    return "none"


def aggregate_values(attribute: Any, values: list[Any]) -> Any:
    values = [value for value in values if value is not None]
    return attribute.function(values) if values else None


def runs_matching(
    runs: list[dict[str, Any]],
    *,
    algorithm: str | None = None,
    domain: str | None = None,
    problem: str | None = None,
) -> list[dict[str, Any]]:
    return [
        run
        for run in runs
        if (algorithm is None or str(run.get("algorithm", "")) == algorithm)
        and (domain is None or str(run.get("domain", "")) == domain)
        and (problem is None or str(run.get("problem", "")) == problem)
    ]


def make_cross_table(
    rows: list[str],
    row_header: str,
    algorithms: list[str],
    cell_value,
    *,
    row_counts: dict[str, int] | None = None,
    first_col_links: dict[str, str] | None = None,
    algorithm_better: str = "none",
    include_total: bool = False,
    total_label: str = "Total",
    total_value=None,
    digits: int = 2,
    cell_run_dirs=None,
    coerce_numeric: bool = True,
) -> tuple[list[dict[str, Cell]], list[str]]:
    columns = [row_header] + algorithms
    rendered_rows: list[dict[str, Cell]] = []
    for row_name in rows:
        label = row_name
        if row_counts and row_name in row_counts:
            label = f"{row_name} ({row_counts[row_name]})"
        if first_col_links and row_name in first_col_links:
            label = f'<a href="{escape(first_col_links[row_name])}">{escape(label)}</a>'
        row = {row_header: Cell(label)}
        for algorithm in algorithms:
            value = cell_value(row_name, algorithm)
            run_dirs = (
                tuple(cell_run_dirs(row_name, algorithm)) if cell_run_dirs else ()
            )
            row[algorithm] = Cell(
                value,
                number_or_none(value) if coerce_numeric else None,
                algorithm_better,
                digits=digits,
                run_dirs=run_dirs,
            )
        rendered_rows.append(row)

    if include_total and total_value is not None:
        row = {row_header: Cell(total_label)}
        for algorithm in algorithms:
            value = total_value(algorithm)
            row[algorithm] = Cell(
                value,
                number_or_none(value) if coerce_numeric else None,
                algorithm_better,
                digits=digits,
            )
        rendered_rows.append(row)
    return rendered_rows, columns


def make_summary_rows(
    index: RunIndex, attributes: list[Any]
) -> tuple[list[dict[str, Cell]], list[str]]:
    rows: list[dict[str, Cell]] = []
    for attribute in attributes:
        name = attribute_name(attribute)
        _, _, summary_values = make_attribute_summary(index, attribute)
        label = f'<a href="#tab-{slug(name)}">{escape(name)} - {escape(aggregation_label(attribute))}</a>'
        row = {"Summary": Cell(label)}
        for algorithm in index.algorithms:
            value = summary_values.get(algorithm)
            row[algorithm] = Cell(
                value,
                number_or_none(value),
                better_for(attribute),
                digits=attribute.digits,
            )
        rows.append(row)
    return rows, ["Summary"] + index.algorithms


def unique_values(runs: list[dict[str, Any]], key: str) -> str:
    values = sorted({fmt(run.get(key)) for run in runs if fmt(run.get(key))})
    if not values:
        return "?"
    return ", ".join(values)


def make_info_rows(index: RunIndex) -> tuple[list[dict[str, Cell]], list[str]]:
    columns = [
        "algorithm",
        "local_revision",
        "global_revision",
        "build_options",
        "driver_options",
        "component_options",
        "runs",
        "domains",
        "tasks",
        "nodes",
        "time_limit",
        "memory_limit",
    ]
    rows: list[dict[str, Cell]] = []
    for algorithm in index.algorithms:
        runs = index.by_algorithm.get(algorithm, [])
        domains = {str(run.get("domain", "")) for run in runs}
        tasks = {
            (str(run.get("domain", "")), str(run.get("problem", ""))) for run in runs
        }
        rows.append(
            {
                "algorithm": Cell(algorithm),
                "local_revision": Cell(unique_values(runs, "local_revision")),
                "global_revision": Cell(unique_values(runs, "global_revision")),
                "build_options": Cell(unique_values(runs, "build_options")),
                "driver_options": Cell(unique_values(runs, "driver_options")),
                "component_options": Cell(unique_values(runs, "component_options")),
                "runs": Cell(len(runs), float(len(runs))),
                "domains": Cell(len(domains), float(len(domains))),
                "tasks": Cell(len(tasks), float(len(tasks))),
                "nodes": Cell(unique_values(runs, "node")),
                "time_limit": Cell(unique_values(runs, "time_limit")),
                "memory_limit": Cell(unique_values(runs, "memory_limit")),
            }
        )
    return rows, columns


def make_attribute_summary(
    index: RunIndex,
    attribute: Any,
) -> tuple[list[dict[str, Cell]], list[str], dict[str, Any]]:
    name = attribute_name(attribute)
    links = {domain: f"#table-{slug(name)}-{slug(domain)}" for domain in index.domains}
    domain_algo_values: dict[tuple[str, str], list[Any]] = {
        (domain, algorithm): []
        for domain in index.domains
        for algorithm in index.algorithms
    }

    for (domain, _problem), runs in index.problem_runs.items():
        if domain not in index.domains:
            continue
        if not attribute.absolute and (
            len(runs) < len(index.algorithms)
            or any(run.get(name) is None for run in runs)
        ):
            continue
        for run in runs:
            algorithm = str(run.get("algorithm", ""))
            if algorithm not in index.algorithms:
                continue
            value = run.get(name)
            if value is not None:
                domain_algo_values[(domain, algorithm)].append(value)

    domain_values = {
        (domain, algorithm): aggregate_values(attribute, values)
        for (domain, algorithm), values in domain_algo_values.items()
    }

    counts: dict[str, str] = {}
    for domain in index.domains:
        task_counts = [
            str(len(domain_algo_values[(domain, algorithm)]))
            for algorithm in index.algorithms
        ]
        counts[domain] = (
            task_counts[0] if len(set(task_counts)) == 1 else ", ".join(task_counts)
        )

    summary_values: dict[str, Any] = {}
    for algorithm in index.algorithms:
        values = [domain_values[(domain, algorithm)] for domain in index.domains]
        summary_values[algorithm] = aggregate_values(attribute, values)

    def cell(domain: str, algorithm: str) -> Any:
        return domain_values[(domain, algorithm)]

    def total(algorithm: str) -> Any:
        return summary_values.get(algorithm)

    rows, columns = make_cross_table(
        index.domains,
        name,
        index.algorithms,
        cell,
        row_counts=counts,
        first_col_links=links,
        algorithm_better=better_for(attribute),
        include_total=True,
        total_label=f"{aggregation_label(attribute)}",
        total_value=total,
        digits=attribute.digits,
    )
    return rows, columns, summary_values


def make_domain_table(
    index: RunIndex,
    attribute: Any,
    domain: str,
    *,
    is_numeric: bool = True,
) -> tuple[list[dict[str, Cell]], list[str]]:
    name = attribute_name(attribute)
    problems = index.problems_by_domain[domain]

    def cell(problem: str, algorithm: str) -> Any:
        group = index.by_problem_algorithm.get((domain, problem, algorithm), [])
        return group[-1].get(name) if group else None

    def run_dirs(problem: str, algorithm: str) -> list[str]:
        group = index.by_problem_algorithm.get((domain, problem, algorithm), [])
        return [
            str(run.get("run_dir", "")) for run in group if str(run.get("run_dir", ""))
        ]

    return make_cross_table(
        problems,
        "Problem",
        index.algorithms,
        cell,
        algorithm_better=better_for(attribute) if is_numeric else "none",
        digits=attribute.digits,
        cell_run_dirs=run_dirs,
        coerce_numeric=is_numeric,
    )


def unexplained_errors(run: dict[str, Any]) -> list[str]:
    errors = run.get("unexplained_errors") or []
    if isinstance(errors, list):
        return [str(error) for error in errors if str(error)]
    return [str(errors)] if str(errors) else []


def make_error_rows(
    runs: list[dict[str, Any]],
) -> tuple[list[dict[str, Cell]], list[str]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        errors = unexplained_errors(run)
        if errors:
            groups["\n\n".join(errors)].append(run)

    rows: list[dict[str, Cell]] = []
    for message, group in sorted(
        groups.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        group = sorted(
            group,
            key=lambda item: (
                str(item.get("domain", "")),
                str(item.get("problem", "")),
                str(item.get("algorithm", "")),
            ),
        )
        run_rows = []
        for run in group:
            cells = [
                run.get("algorithm"),
                run.get("domain"),
                run.get("problem"),
                run.get("error"),
                run.get("total_time"),
                run.get("node"),
                run.get("run_dir"),
            ]
            run_rows.append(
                '<div class="error-run">'
                + "".join(f"<span>{escape(fmt(cell))}</span>" for cell in cells)
                + "</div>"
            )
        runs_html = (
            f'<details class="error-runs"><summary>{len(group)} runs</summary>'
            '<div class="error-run error-run-head">'
            "<span>Algorithm</span><span>Domain</span><span>Problem</span><span>Error</span>"
            "<span>Total time</span><span>Node</span><span>Run dir</span>"
            "</div>" + "".join(run_rows) + "</details>"
        )
        rows.append(
            {
                "count": Cell(len(group), float(len(group))),
                "unexplained_errors": Cell(message),
                "runs": Cell(runs_html, html=True),
            }
        )
    columns = ["count", "unexplained_errors", "runs"]
    return rows, columns


def render_table(
    table_id: str,
    rows: list[dict[str, Cell]],
    columns: list[str],
    *,
    first_header: str | None = None,
    exact_data_headers: bool = False,
) -> str:
    has_run_dirs = any(
        row.get(column, Cell(None)).run_dirs for row in rows for column in columns
    )
    header_cells = []
    for index, column in enumerate(columns):
        if index == 0 and first_header:
            label = first_header
        elif exact_data_headers and index > 0:
            label = column
        else:
            label = titleize(column)
        header_cells.append(
            f'<th scope="col" data-column="{escape(column)}" data-better="{column_better(rows, column)}">'
            f'<button type="button">{escape(label)}</button></th>'
        )
    body = []
    for row in rows:
        cells = []
        for column in columns:
            cell = row.get(column, Cell(None))
            attrs = []
            if cell.numeric is not None:
                attrs.append(f'data-num="{cell.numeric}"')
                attrs.append(f'data-better="{cell.better}"')
            content = fmt(cell.value, cell.digits)
            if cell.html:
                rendered = str(cell.value)
            elif isinstance(cell.value, str) and cell.value.startswith("<a "):
                rendered = cell.value
            else:
                rendered = escape(content).replace("\n", "<br>")
            if cell.run_dirs:
                run_dir_items = "".join(
                    f"<div>{escape(run_dir)}</div>" for run_dir in cell.run_dirs
                )
                rendered += f'<div class="cell-run-dirs">{run_dir_items}</div>'
            classes = []
            if cell.numeric is not None:
                classes.append("num")
            if column in {"unexplained_errors", "runs"}:
                classes.append("wrap")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            cells.append(f"<td{class_attr} {' '.join(attrs)}>{rendered}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<div class="table-block">'
        '<div class="table-actions">'
        '<button type="button" data-action="copy-latex">Copy LaTeX</button>'
        + (
            '<button type="button" data-action="toggle-run-dirs">Show Run Dirs</button>'
            if has_run_dirs
            else ""
        )
        + '<button type="button" data-action="restore-columns">Restore Columns</button>'
        '<button type="button" data-action="reset-sort">Reset Sort</button>'
        "</div>"
        f'<div class="table-shell"><table id="{escape(table_id)}" class="data-table">'
        f"<thead><tr>{''.join(header_cells)}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        "</div>"
    )


def column_better(rows: list[dict[str, Cell]], column: str) -> str:
    for row in rows:
        cell = row.get(column)
        if cell and cell.better != "none":
            return cell.better
    return "none"


def render_attribute_section(
    index: RunIndex,
    attribute: Any,
    *,
    is_numeric: bool = True,
) -> str:
    name = attribute_name(attribute)
    domain_links = " ".join(
        f'<a href="#table-{slug(name)}-{slug(domain)}">{escape(domain)}</a>'
        for domain in index.domains
    )
    parts = [
        f'<section id="tab-{escape(slug(name))}" hidden>',
        f'<div class="section-head"><h2>{escape(name)}</h2><span class="note">{escape(aggregation_label(attribute))}</span></div>',
        f'<div class="domain-jump">{domain_links}</div>',
    ]
    if is_numeric:
        summary_rows, summary_columns, _ = make_attribute_summary(index, attribute)
        parts.append(
            render_table(
                f"table-{slug(name)}",
                summary_rows,
                summary_columns,
                first_header=name,
                exact_data_headers=True,
            )
        )
    for domain in index.domains:
        rows, columns = make_domain_table(
            index, attribute, domain, is_numeric=is_numeric
        )
        parts.extend(
            [
                f'<details id="table-{escape(slug(name))}-{escape(slug(domain))}">',
                f"<summary>{escape(domain)} <span>{len(rows)} tasks</span></summary>",
                render_table(
                    f"table-{slug(name)}-{slug(domain)}-tasks",
                    rows,
                    columns,
                    exact_data_headers=True,
                ),
                "</details>",
            ]
        )
    parts.append("</section>")
    return "\n".join(parts)


class ModernAbsoluteReport(AbsoluteReport):
    """Drop-in modern HTML replacement for downward's AbsoluteReport."""

    def __init__(self, attributes=None, format="html", filter=None, **kwargs):
        super().__init__(attributes=attributes, format=format, filter=filter, **kwargs)
        if self.output_format != "html":
            raise ValueError("ModernAbsoluteReport only supports HTML output")

    def write(self):
        properties = {str(run_id): dict(run) for run_id, run in self.props.items()}
        output = Path(self.outfile)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            render_report(
                Path(self.eval_dir),
                properties,
                attributes=list(self.attributes),
                numeric_attributes={
                    str(attribute)
                    for attribute in self.attributes
                    if self.attribute_is_numeric(attribute)
                },
                algorithms=list(self.algorithms),
                domains=tools.natural_sort(self.domains),
            )
        )
        logging.info(f"Wrote file://{self.outfile}")


def render_report(
    source: Path,
    properties: dict[str, dict[str, Any]],
    *,
    attributes: list[Any] | None = None,
    numeric_attributes: set[str] | None = None,
    algorithms: list[str] | None = None,
    domains: list[str] | None = None,
) -> str:
    runs = list(properties.values())
    index = build_index(runs, algorithms=algorithms, domains=domains)
    attributes = prepare_attributes(attributes or present_attributes(runs))
    if numeric_attributes is None:
        numeric_attributes = {attribute_name(attribute) for attribute in attributes}
    error_count = sum(len(unexplained_errors(run)) for run in runs)

    summary_attributes = [
        attribute
        for attribute in attributes
        if attribute_name(attribute) in numeric_attributes
    ]
    summary_rows, summary_columns = make_summary_rows(index, summary_attributes)
    info_rows, info_columns = make_info_rows(index)
    error_rows, error_columns = make_error_rows(runs)
    attribute_sections = "\n".join(
        render_attribute_section(
            index,
            attribute,
            is_numeric=attribute_name(attribute) in numeric_attributes,
        )
        for attribute in attributes
    )

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = source.parent.name if source.is_file() else source.name
    tab_buttons = [
        '<button type="button" data-tab="summary" aria-selected="true">Summary</button>',
        '<button type="button" data-tab="info" aria-selected="false">Info</button>',
        f'<button type="button" data-tab="errors" aria-selected="false">Errors ({error_count})</button>',
    ] + [
        f'<button type="button" data-tab="{escape(slug(attribute_name(attribute)))}" aria-selected="false">{escape(attribute_name(attribute))}</button>'
        for attribute in attributes
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} modern report</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --text: #1c2430;
  --muted: #637083;
  --line: #d8dee8;
  --header: #263247;
  --header-text: #ffffff;
  --accent: #0f766e;
  --bad: #b42318;
  --shadow: 0 8px 22px rgba(20, 28, 40, 0.07);
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #111418;
    --panel: #181d23;
    --text: #e8edf5;
    --muted: #9aa7b8;
    --line: #303845;
    --header: #222b3a;
    --header-text: #f7fafc;
    --shadow: none;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 13px/1.42 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
header {{
  padding: 14px clamp(14px, 3vw, 28px) 10px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  z-index: 20;
}}
h1 {{
  margin: 0 0 6px;
  font-size: clamp(18px, 2.4vw, 28px);
  line-height: 1.15;
  letter-spacing: 0;
}}
.meta, .note, details summary span {{ color: var(--muted); }}
.table-actions {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin: 0 0 6px;
}}
button {{
  min-height: 30px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--text);
  padding: 5px 9px;
  cursor: pointer;
}}
button:hover {{ border-color: var(--accent); }}
main {{ padding: 14px clamp(14px, 3vw, 28px) 36px; }}
.tabs {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  max-height: 116px;
  overflow: auto;
}}
.tabs button[aria-selected="true"] {{
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}}
section[hidden] {{ display: none; }}
section h2 {{ margin: 0; font-size: 21px; }}
.section-head {{
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin: 14px 0 8px;
}}
.domain-jump {{
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  margin: 0 0 8px;
}}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.table-shell {{
  width: 100%;
  max-height: calc(100vh - 235px);
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 7px;
  box-shadow: var(--shadow);
}}
.table-block {{ margin-bottom: 12px; }}
table {{
  border-collapse: separate;
  border-spacing: 0;
  width: 100%;
  min-width: 820px;
}}
th, td {{
  border-bottom: 1px solid var(--line);
  border-right: 1px solid var(--line);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}}
td {{ white-space: nowrap; }}
th {{
  position: sticky;
  top: 0;
  z-index: 5;
  background: var(--header);
  color: var(--header-text);
  white-space: normal;
  min-width: 8rem;
}}
th button {{
  border: 0;
  background: transparent;
  color: inherit;
  padding: 0;
  min-height: 0;
  font: inherit;
  text-align: left;
  overflow-wrap: anywhere;
  word-break: normal;
}}
th .hide-column {{
  float: right;
  margin-left: 7px;
  opacity: .76;
  font-weight: 700;
}}
th .hide-column:hover {{ opacity: 1; }}
th:first-child {{ min-width: 10rem; }}
th:first-child, td:first-child {{
  position: sticky;
  left: 0;
}}
td:first-child {{
  background: var(--panel);
  z-index: 2;
  font-weight: 520;
}}
th:first-child {{ z-index: 6; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.best-cell {{ font-weight: 750; }}
.cell-run-dirs {{
  display: none;
  margin-top: 5px;
  padding: 4px 6px;
  border-radius: 4px;
  background: #f4ead6;
  color: #68707d;
  font-size: 11px;
  font-style: italic;
  line-height: 1.3;
  text-align: left;
  white-space: normal;
  overflow-wrap: anywhere;
}}
table.show-run-dirs .cell-run-dirs {{ display: block; }}
td.wrap {{
  white-space: normal;
  min-width: 22rem;
  max-width: 56rem;
  overflow-wrap: anywhere;
  line-height: 1.35;
}}
#table-errors th[data-column="count"],
#table-errors td:first-child {{
  min-width: 4.25rem;
  width: 4.25rem;
  text-align: right;
}}
.error-runs summary {{
  margin: 0;
  font-size: 13px;
  font-weight: 650;
}}
.error-run {{
  display: grid;
  grid-template-columns: minmax(12rem, 1.5fr) minmax(7rem, .8fr) minmax(8rem, 1fr) minmax(7rem, .8fr) minmax(5rem, .6fr) minmax(5rem, .6fr) minmax(10rem, 1fr);
  gap: 6px;
  padding: 3px 0;
  border-top: 1px solid var(--line);
}}
.error-run span {{
  min-width: 0;
  overflow-wrap: anywhere;
}}
.error-run-head {{
  color: var(--muted);
  font-weight: 650;
  margin-top: 6px;
}}
tbody tr:hover td {{ outline: 1px solid color-mix(in srgb, var(--accent) 34%, transparent); }}
details {{ margin-top: 13px; }}
details summary {{
  cursor: pointer;
  margin-bottom: 7px;
  font-weight: 650;
  font-size: 17px;
}}
@media (max-width: 720px) {{
  .table-actions {{ justify-content: flex-start; }}
  header {{ position: static; }}
  .table-shell {{ max-height: 70vh; }}
}}
</style>
</head>
<body>
<header>
  <h1>{escape(title)}</h1>
  <div class="meta">Generated from {escape(str(source))} at {escape(generated)}</div>
</header>
<main>
  <nav class="tabs" aria-label="Report tables">
    {"".join(tab_buttons)}
  </nav>
  <section id="tab-summary">
    <div class="section-head"><h2>Summary</h2><span class="note">{len(attributes)} attributes</span></div>
    {render_table("table-summary", summary_rows, summary_columns, first_header="Summary", exact_data_headers=True)}
  </section>
  <section id="tab-info" hidden>
    <div class="section-head"><h2>Info</h2><span class="note">{len(info_rows)} algorithm configurations</span></div>
    {render_table("table-info", info_rows, info_columns)}
  </section>
  <section id="tab-errors" hidden>
    <div class="section-head"><h2>Errors</h2><span class="note">{len(error_rows)} grouped error messages</span></div>
    {render_table("table-errors", error_rows, error_columns)}
  </section>
  {attribute_sections}
</main>
<script>
const tabs = [...document.querySelectorAll(".tabs button")];
const sections = [...document.querySelectorAll("main section")];

function rowsOf(table) {{
  return [...table.tBodies[0].rows];
}}

function visibleCells(row) {{
  return [...row.cells].filter(cell => !cell.hidden);
}}

function cellText(cell) {{
  const clone = cell.cloneNode(true);
  clone.querySelectorAll(".hide-column").forEach(button => button.remove());
  clone.querySelectorAll(".cell-run-dirs").forEach(block => block.remove());
  return clone.textContent.trim();
}}

function cellValue(cell) {{
  if (cell.dataset.num !== undefined) return Number(cell.dataset.num);
  return cell.textContent.trim().toLowerCase();
}}

function sortTable(table, index, direction) {{
  const rows = rowsOf(table);
  rows.sort((a, b) => {{
    const av = cellValue(a.cells[index]);
    const bv = cellValue(b.cells[index]);
    if (typeof av === "number" && typeof bv === "number") return direction * (av - bv);
    return direction * String(av).localeCompare(String(bv), undefined, {{numeric: true}});
  }});
  table.tBodies[0].append(...rows);
  table.querySelectorAll("th").forEach(th => th.dataset.sort = "");
  table.tHead.rows[0].cells[index].dataset.sort = direction === 1 ? "asc" : "desc";
}}

function resetTable(table) {{
  const rows = rowsOf(table);
  rows.sort((a, b) => Number(a.dataset.originalIndex) - Number(b.dataset.originalIndex));
  table.tBodies[0].append(...rows);
  resetColumnOrder(table);
  table.querySelectorAll("th").forEach(th => th.dataset.sort = "");
}}

function applyHeat(table) {{
  rowsOf(table).forEach(row => {{
    ["higher", "lower"].forEach(better => {{
      const cells = [...row.cells].filter(cell => cell.dataset.num !== undefined && cell.dataset.better === better);
      if (cells.length < 2) return;
      const values = cells.map(cell => Number(cell.dataset.num));
      const min = Math.min(...values);
      const max = Math.max(...values);
      if (min === max) return;
      cells.forEach(cell => {{
        let heat = (Number(cell.dataset.num) - min) / (max - min);
        if (better === "lower") heat = 1 - heat;
        const alpha = 0.10 + heat * 0.35;
        const color = heat >= 0.5 ? `rgba(15, 118, 110, ${{alpha}})` : `rgba(180, 35, 24, ${{0.16 - heat * 0.10}})`;
        cell.style.background = color;
      }});
    }});
  }});
}}

function latexEscape(text) {{
  return text
    .replace(/\\\\/g, "\\\\textbackslash{{}}")
    .replace(/([#$%&_{{}}])/g, "\\\\$1")
    .replace(/\\^/g, "\\\\textasciicircum{{}}")
    .replace(/~/g, "\\\\textasciitilde{{}}");
}}

function bestVisibleCellIndexes(row) {{
  const cells = visibleCells(row);
  const numericCells = cells
    .map((cell, index) => ({{cell, index}}))
    .filter(item => item.cell.dataset.num !== undefined && ["higher", "lower"].includes(item.cell.dataset.better));
  if (numericCells.length < 2) return new Set();
  const better = numericCells[0].cell.dataset.better;
  const comparable = numericCells.filter(item => item.cell.dataset.better === better);
  const values = comparable.map(item => Number(item.cell.dataset.num));
  const best = better === "higher" ? Math.max(...values) : Math.min(...values);
  return new Set(comparable.filter(item => Number(item.cell.dataset.num) === best).map(item => item.index));
}}

function markBestCells(table) {{
  rowsOf(table).forEach(row => {{
    [...row.cells].forEach(cell => cell.classList.remove("best-cell"));
    const cells = visibleCells(row);
    const bestIndexes = bestVisibleCellIndexes(row);
    cells.forEach((cell, index) => cell.classList.toggle("best-cell", bestIndexes.has(index)));
  }});
}}

function latexCell(cell, bold) {{
  const text = latexEscape(cellText(cell).replace(/\\s+/g, " "));
  return bold ? "\\\\textbf{{" + text + "}}" : text;
}}

function tableToLatex(table) {{
  const headers = visibleCells(table.tHead.rows[0]).map(cell => latexEscape(cellText(cell)));
  const rows = rowsOf(table)
    .map(row => {{
      const bestIndexes = bestVisibleCellIndexes(row);
      return visibleCells(row).map((cell, index) => latexCell(cell, bestIndexes.has(index)));
    }});
  const spec = "l" + "r".repeat(Math.max(0, headers.length - 1));
  return [
    `\\\\begin{{tabular}}{{${{spec}}}}`,
    "\\\\toprule",
    `${{headers.join(" & ")}} \\\\\\\\`,
    "\\\\midrule",
    ...rows.map(cells => `${{cells.join(" & ")}} \\\\\\\\`),
    "\\\\bottomrule",
    "\\\\end{{tabular}}",
  ].join("\\n");
}}

function copyTableLatex(table) {{
  navigator.clipboard.writeText(tableToLatex(table));
}}

function reorderColumns(table, order) {{
  [...table.rows].forEach(row => {{
    const cells = [...row.cells];
    row.append(...order.map(index => cells[index]).filter(Boolean));
  }});
}}

function resetColumnOrder(table) {{
  const headerCells = [...table.tHead.rows[0].cells];
  const order = headerCells
    .map((cell, index) => ({{index, original: Number(cell.dataset.originalColumnIndex)}}))
    .sort((a, b) => a.original - b.original)
    .map(item => item.index);
  reorderColumns(table, order);
  delete table.dataset.orderedByRow;
  delete table.dataset.columnOrderDirection;
}}

function orderColumnsByRow(row) {{
  const table = row.closest("table");
  const cells = [...row.cells];
  const first = cells[0];
  const sortable = cells.slice(1)
    .map((cell, offset) => ({{
      index: offset + 1,
      value: cell.dataset.num === undefined ? null : Number(cell.dataset.num),
      better: cell.dataset.better,
      original: Number(table.tHead.rows[0].cells[offset + 1].dataset.originalColumnIndex),
    }}))
    .filter(item => ["higher", "lower"].includes(item.better));
  if (!first || sortable.filter(item => item.value !== null).length < 2) return;
  const better = sortable.find(item => item.value !== null).better;
  const sameRow = table.dataset.orderedByRow === row.dataset.originalIndex;
  const direction = sameRow && table.dataset.columnOrderDirection === "best" ? "worst" : "best";
  sortable.sort((a, b) => {{
    if (a.better !== better) return a.original - b.original;
    if (a.value === null && b.value === null) return a.original - b.original;
    if (a.value === null) return 1;
    if (b.value === null) return -1;
    if (a.value === b.value) return a.original - b.original;
    const bestFirst = better === "higher" ? b.value - a.value : a.value - b.value;
    return direction === "best" ? bestFirst : -bestFirst;
  }});
  const unsorted = cells.slice(1)
    .map((cell, offset) => ({{index: offset + 1, original: Number(table.tHead.rows[0].cells[offset + 1].dataset.originalColumnIndex)}}))
    .filter(item => !sortable.some(sorted => sorted.index === item.index))
    .sort((a, b) => a.original - b.original);
  reorderColumns(table, [0, ...sortable.map(item => item.index), ...unsorted.map(item => item.index)]);
  table.dataset.orderedByRow = row.dataset.originalIndex;
  table.dataset.columnOrderDirection = direction;
  table.querySelectorAll("th").forEach(th => th.dataset.sort = "");
}}

function setColumnHidden(table, index, hidden) {{
  [...table.rows].forEach(row => {{
    if (row.cells[index]) row.cells[index].hidden = hidden;
  }});
  markBestCells(table);
}}

function restoreColumns(table) {{
  [...table.rows].forEach(row => [...row.cells].forEach(cell => cell.hidden = false));
  markBestCells(table);
}}

function addColumnHideControls(table) {{
  table.querySelectorAll("th").forEach(th => {{
    if ([...th.parentElement.cells].indexOf(th) === 0) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hide-column";
    button.title = "Hide column";
    button.textContent = "x";
    button.addEventListener("click", event => {{
      event.stopPropagation();
      const index = [...th.parentElement.cells].indexOf(th);
      setColumnHidden(table, index, true);
    }});
    th.appendChild(button);
  }});
}}

function tableForAction(button) {{
  return button.closest(".table-block").querySelector("table");
}}

function toggleRunDirs(button) {{
  const table = tableForAction(button);
  const shown = table.classList.toggle("show-run-dirs");
  button.textContent = shown ? "Hide Run Dirs" : "Show Run Dirs";
}}

document.querySelectorAll("table").forEach(table => {{
  rowsOf(table).forEach((row, index) => row.dataset.originalIndex = String(index));
  [...table.rows].forEach(row => {{
    [...row.cells].forEach((cell, index) => cell.dataset.originalColumnIndex = String(index));
  }});
  applyHeat(table);
  addColumnHideControls(table);
  markBestCells(table);
  rowsOf(table).forEach(row => {{
    row.addEventListener("click", event => {{
      if (event.target.closest("a")) return;
      if (event.target.closest("td") !== row.cells[0]) return;
      orderColumnsByRow(row);
    }});
  }});
  table.querySelectorAll("th").forEach(th => {{
    th.addEventListener("click", () => {{
      const index = [...th.parentElement.cells].indexOf(th);
      const next = th.dataset.sort === "asc" ? -1 : 1;
      sortTable(table, index, next);
    }});
  }});
}});

document.querySelectorAll("[data-action='copy-latex']").forEach(button => {{
  button.addEventListener("click", () => copyTableLatex(tableForAction(button)));
}});

document.querySelectorAll("[data-action='restore-columns']").forEach(button => {{
  button.addEventListener("click", () => restoreColumns(tableForAction(button)));
}});

document.querySelectorAll("[data-action='toggle-run-dirs']").forEach(button => {{
  button.addEventListener("click", () => toggleRunDirs(button));
}});

document.querySelectorAll("[data-action='reset-sort']").forEach(button => {{
  button.addEventListener("click", () => resetTable(tableForAction(button)));
}});

tabs.forEach(tab => {{
  tab.addEventListener("click", () => {{
    tabs.forEach(item => item.setAttribute("aria-selected", String(item === tab)));
    sections.forEach(section => section.hidden = section.id !== `tab-${{tab.dataset.tab}}`);
  }});
}});

document.querySelectorAll('a[href^="#tab-"]').forEach(link => {{
  link.addEventListener("click", event => {{
    const target = link.getAttribute("href").slice("#tab-".length);
    const tab = tabs.find(item => item.dataset.tab === target);
    if (!tab) return;
    event.preventDefault();
    tab.click();
    history.replaceState(null, "", link.getAttribute("href"));
  }});
}});

document.querySelectorAll('a[href^="#table-"]').forEach(link => {{
  link.addEventListener("click", event => {{
    const target = document.querySelector(link.getAttribute("href"));
    if (!target) return;
    if (target.tagName.toLowerCase() === "details") target.open = true;
  }});
}});

if (location.hash.startsWith("#tab-")) {{
  const target = location.hash.slice("#tab-".length);
  const tab = tabs.find(item => item.dataset.tab === target);
  if (tab) tab.click();
}}
</script>
</body>
</html>
"""


def write_report(eval_dir: Path, output_name: str) -> Path:
    properties = load_properties(eval_dir)
    output = (
        eval_dir / output_name if eval_dir.is_dir() else eval_dir.parent / output_name
    )
    output.write_text(render_report(eval_dir, properties))
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        type=Path,
        help="Eval directory, properties file, or root directory with --all",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="modern-report.html",
        help="Output filename, written beside properties",
    )
    parser.add_argument(
        "--all", action="store_true", help="Render every eval directory below PATH"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.all:
        for eval_dir in discover_eval_dirs(args.path):
            output = write_report(eval_dir, args.output)
            print(output)
    else:
        output = write_report(args.path, args.output)
        print(output)


if __name__ == "__main__":
    main()
