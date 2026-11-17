from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import httpx
from rich.console import Console

from ..yaml_utils import extract_data, write_yaml
from .calibrate import calibrate_slo

MAX_WORKERS = 4
console = Console()


def check_slos(file: Path, days: int, write: bool):
    """Calibrate all SLOs in a YAML config file and optionally write objectives back."""
    console.print(f"[bold green]Reading file:[/bold green] {file}")

    try:
        full_dict = extract_data(file)
        slos = full_dict.get("slos", [])
        prom = full_dict.get("prometheus", {}) or {}
        prom_url = prom.get("url")
        prom_token = prom.get("token")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Failed to extract data from {file}: {e}")
        sys.exit(1)

    if not isinstance(slos, list) or not slos or not prom_url:
        console.print("[bold red]Error:[/bold red] No SLOs or prometheus url found in file.")
        sys.exit(1)

    def _calibrate_one(slo):
        if not isinstance(slo, dict):
            return slo, None, None, "Invalid SLO data."

        slo_name = slo.get("name", "Unknown")
        try:
            objective = calibrate_slo(prom_url, prom_token, slo, days, client=client)
            return slo, slo_name, objective, None
        except Exception as e:
            return slo, slo_name, None, f"Failed to calibrate SLO {slo_name}: {e}"

    had_error = False
    updated = False
    with httpx.Client() as client, ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(slos))) as executor:
        for slo, slo_name, objective, error in executor.map(_calibrate_one, slos):
            if slo_name is not None:
                console.print(f"[bold blue]Checking SLO:[/bold blue] {slo_name}")

            if error:
                console.print(f"[bold red]Error:[/bold red] {error}")
                had_error = True
                continue

            slo["objective"] = objective
            updated = True
            console.print(f"[bold green]SLO:[/bold green] {slo_name} - [bold yellow]Objective:[/bold yellow] {objective}")

    if write and updated:
        console.print(f"[bold blue]Writing objectives to file:[/bold blue] {file}")
        try:
            write_yaml(file, full_dict)
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] Failed to write objectives to {file}: {e}")
            sys.exit(1)

    return had_error
