from pathlib import Path
import sys

from rich.console import Console
import typer

from .check import check_slos
from .gen import generate_prometheus_rules

app = typer.Typer(
    help="SLO-P: Calibrate SLO objectives and generate Prometheus rules."
)
console = Console()


def _normalize_days(days: int) -> int:
    if days not in (7, 30):
        console.print("[bold red]Warning:[/bold red] Days must be 7 or 30. Using default 7 days.")
        return 7
    return days


@app.command()
def check(
    file: Path = typer.Argument(..., help="Path to the input YAML file"),
    days: int = typer.Option(7, "--days", "-d", help="Days of history to analyze"),
    write: bool = typer.Option(False, "--write", "-w", help="Write the objectives to the YAML file"),
):
    days = _normalize_days(days)
    had_errors = check_slos(file, days, write)
    if had_errors:
        sys.exit(1)


@app.command()
def gen(
    file: Path = typer.Argument(..., help="Path to the input YAML file"),
    days: int = typer.Option(7, "--days", "-d", help="Days of history to analyze"),
    check: bool = typer.Option(False, "--check", "-c", help="Check objectives before generating rules"),
    output: Path = typer.Option("rules.yaml", "--output", "-o", help="Output Prometheus rules file"),
):
    days = _normalize_days(days)

    had_errors = False
    if check:
        had_errors = check_slos(file, days, write=True)

    gen_errors = generate_prometheus_rules(file, output, days=days)
    if had_errors or gen_errors:
        sys.exit(1)


if __name__ == "__main__":
    app()
