import math
import re
import sys

from rich.console import Console
from ruamel.yaml.scalarstring import LiteralScalarString

from ..check.calibrate import OPERATORS
from ..yaml_utils import extract_data, write_yaml

ERROR_WINDOWS = ("5m", "30m", "1h", "6h")
BURN_TIERS = (
    ("Fast", "1h", "5m", 14.4, "2m", "page"),
    ("Slow", "6h", "30m", 6.0, "15m", "ticket"),
)
MAX_BURN_ERROR_THRESHOLD = 0.99

console = Console()


def _build_slo_group(slo, days):
    """Validate one SLO definition and build its Prometheus rule group."""
    if not isinstance(slo, dict):
        raise ValueError(f"Invalid SLO entry: {slo}")

    name = slo.get("name")
    query = slo.get("query")
    op = slo.get("operator")
    threshold = slo.get("threshold")
    objective = slo.get("objective")

    if (
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(query, str)
        or not query.strip()
        or op not in OPERATORS
        or isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or isinstance(objective, bool)
        or not isinstance(objective, (int, float))
        or not math.isfinite(objective)
        or not (0.0 < float(objective) < 1.0)
    ):
        raise ValueError(f"Invalid or uncalibrated SLO '{name or slo}'.")

    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    if not slug:
        raise ValueError(f"SLO name {name!r} produces an empty metric identifier.")
    if slug[0].isdigit():
        slug = f"slo_{slug}"

    alert_prefix = "".join(part.capitalize() for part in slug.split("_") if part)
    prefix = f"slop:{slug}"
    objective = float(objective)
    error_budget = 1.0 - objective

    rules = [
        {"record": f"{prefix}:sli_good", "expr": f"({query.strip()}) {op} bool {threshold}"},
        *[
            {"record": f"{prefix}:error_ratio{w}", "expr": f"1 - avg_over_time({prefix}:sli_good[{w}])"}
            for w in ERROR_WINDOWS
        ],
        {"record": f"{prefix}:compliance_{days}d", "expr": f"avg_over_time({prefix}:sli_good[{days}d])"},
        {"record": f"{prefix}:objective", "expr": f"vector({objective})"},
    ]

    for tier, long_win, short_win, multiplier, duration, severity in BURN_TIERS:
        burn_limit = round(min(MAX_BURN_ERROR_THRESHOLD, multiplier * error_budget), 6)
        expr = LiteralScalarString(
            f"{prefix}:error_ratio{long_win} > {burn_limit}\n"
            f"and\n"
            f"{prefix}:error_ratio{short_win} > {burn_limit}\n"
        )
        rules.append({
            "alert": f"{alert_prefix}ErrorBudgetBurn{tier}",
            "expr": expr,
            "for": duration,
            "labels": {"severity": severity, "slo": name},
            "annotations": {
                "summary": f"{tier} error budget burn on {name}",
                "description": (
                    f"{name} is burning error budget at >{multiplier:g}x over "
                    f"{long_win} and {short_win} (objective: {objective})."
                ),
            },
        })

    return slug, {"name": f"slop_{slug}", "interval": "1m", "rules": rules}


def generate_prometheus_rules(file_path, output_path, days=7):
    """Read SLO config from file_path and write Prometheus rules YAML to output_path."""
    try:
        slos = extract_data(file_path).get("slos", [])
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Failed to extract data from {file_path}: {e}")
        sys.exit(1)

    if not isinstance(slos, list) or not slos:
        console.print("[bold red]Error:[/bold red] No SLOs found in file.")
        sys.exit(1)

    groups = []
    seen_slugs = set()
    had_error = False

    for slo in slos:
        slo_name = slo.get("name", "Unknown") if isinstance(slo, dict) else "Unknown"
        try:
            slug, group = _build_slo_group(slo, days)
            if slug in seen_slugs:
                raise ValueError(f"Duplicate SLO metric identifier '{slug}'.")
            seen_slugs.add(slug)
            groups.append(group)
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] Failed to generate rules for SLO {slo_name}: {e}")
            had_error = True
            continue

    if groups:
        try:
            write_yaml(output_path, {"groups": groups}, width=4096)
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] Failed to write rules to {output_path}: {e}")
            sys.exit(1)

        console.print(f"[bold green]Generated rules from {file_path} to:[/bold green] {output_path}")

    return had_error
