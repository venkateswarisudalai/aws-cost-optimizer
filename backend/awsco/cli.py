"""awsco CLI — `serve` launches the dashboard, `scan` does a one-shot scan."""

from __future__ import annotations

import json
import logging
import sys

import click
import uvicorn
from rich.console import Console
from rich.table import Table

from awsco import __version__
from awsco.demo.fixtures import build_demo_scan
from awsco.models import Severity
from awsco.scanner import run_scan
from awsco.server import AppState, create_app
from awsco.storage import save_scan

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="awsco")
def main() -> None:
    """aws-cost-optimizer — find wasted AWS spend, locally."""


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=3000, show_default=True, type=int)
@click.option("--profile", default=None, help="AWS profile name (default: env / default)")
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Specific region(s) to scan. Repeatable. Default: all enabled regions.",
)
@click.option(
    "--demo-data",
    is_flag=True,
    help="Serve realistic demo findings without making AWS API calls.",
)
def serve(host: str, port: int, profile: str | None, regions: tuple[str, ...], demo_data: bool):
    """Launch the dashboard server."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    AppState.demo_mode = demo_data
    AppState.profile = profile
    AppState.regions = list(regions) if regions else None
    if demo_data:
        console.print("[yellow]Demo mode:[/yellow] using fake findings, no AWS calls.")
    else:
        console.print(f"[green]Live mode:[/green] profile={profile or 'default'}")
    console.print(f"Dashboard → http://localhost:{port}")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@main.command()
@click.option("--profile", default=None)
@click.option("--region", "regions", multiple=True)
@click.option("--demo-data", is_flag=True)
@click.option("--json", "json_out", is_flag=True, help="Emit JSON instead of a table.")
def scan(profile: str | None, regions: tuple[str, ...], demo_data: bool, json_out: bool):
    """One-shot scan, print findings as a table (or JSON)."""
    logging.basicConfig(level=logging.WARNING)
    if demo_data:
        result = build_demo_scan()
    else:
        try:
            result = run_scan(profile=profile, regions=list(regions) if regions else None)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Scan failed:[/red] {exc}")
            sys.exit(1)
    save_scan(result)

    if json_out:
        click.echo(result.model_dump_json(indent=2))
        return

    _print_table(result)


def _print_table(result) -> None:
    color = {Severity.HIGH: "red", Severity.MEDIUM: "yellow", Severity.LOW: "white"}
    console.print(
        f"\n[bold]Account:[/bold] {result.account_id}    "
        f"[bold]Regions:[/bold] {len(result.regions_scanned)}    "
        f"[bold]Findings:[/bold] {result.finding_count}    "
        f"[bold]Monthly savings:[/bold] [green]${result.total_monthly_savings_usd:,.2f}[/green]\n"
    )
    table = Table(show_lines=False, header_style="bold")
    table.add_column("Sev", width=6)
    table.add_column("$ / mo", justify="right", width=10)
    table.add_column("Check", width=22)
    table.add_column("Region", width=12)
    table.add_column("Resource", overflow="fold")
    for f in result.findings:
        table.add_row(
            f"[{color[f.severity]}]{f.severity.value.upper()}[/{color[f.severity]}]",
            f"${f.monthly_savings_usd:,.2f}",
            f.check_id,
            f.region,
            f.title,
        )
    console.print(table)
    console.print(
        "\n[dim]Use `awsco serve` for the dashboard with copy-paste fix commands.[/dim]"
    )
    if result.errors:
        console.print(f"\n[yellow]{len(result.errors)} collector(s) failed:[/yellow]")
        for e in result.errors[:5]:
            console.print(f"  {e['collector']} @ {e['region']}: {e['error']}")


if __name__ == "__main__":
    main()
