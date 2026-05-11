"""Command-line entrypoint for github-analyzer.

M0.3 ships an empty Typer app — `--help` works, subcommands land in M1+.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from github_analyzer import __version__

if TYPE_CHECKING:
    from github_analyzer.schemas.github import Commit, RepoMetadata

app = typer.Typer(
    name="github-analyzer",
    help=(
        "Analyze any public GitHub repository — stack, architecture, "
        "technical debt, and documentation quality."
    ),
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"github-analyzer {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """github-analyzer CLI — see `--help` for available commands."""


@app.command("fetch")
def fetch(
    url: Annotated[str, typer.Argument(help="Public GitHub repo URL.")],
    limit: Annotated[
        int,
        typer.Option(
            "--commits",
            "-n",
            min=1,
            max=100,
            help="How many recent commits to show.",
        ),
    ] = 5,
    keep_clone: Annotated[
        bool,
        typer.Option("--keep-clone", help="Leave the temp clone on disk after the command exits."),
    ] = False,
) -> None:
    """Fetch metadata + recent commits for a public GitHub repo (M1 smoke).

    Shallow-clones the repo to a temp directory, walks the file tree, and
    prints a summary table. Intended for smoke testing the `github-tools`
    layer end-to-end.
    """
    asyncio.run(_fetch_async(url=url, limit=limit, keep_clone=keep_clone))


async def _fetch_async(*, url: str, limit: int, keep_clone: bool) -> None:
    from github_analyzer.mcp_servers.github_tools import (
        clone_shallow,
        get_commits,
        list_files,
        repo_metadata,
    )
    from github_analyzer.mcp_servers.github_tools.tools import _parse_url

    console = Console()

    with console.status(f"[bold cyan]Fetching metadata for {url} ..."):
        meta = await repo_metadata(url)
    _render_metadata(console, meta)

    with console.status("[bold cyan]Cloning (shallow, blobless) ..."):
        clone = await clone_shallow(url)
    console.print(f"  [green]✓[/green] Cloned to {clone.local_path} @ {clone.commit_sha[:8]}")

    with console.status("[bold cyan]Walking files ..."):
        files = await list_files(clone.local_path)
    console.print(f"  [green]✓[/green] {len(files)} matching files indexed (whitelist applied)")

    owner, repo = _parse_url(url)
    with console.status(f"[bold cyan]Fetching last {limit} commits ..."):
        commits = await get_commits(owner=owner, repo=repo, limit=limit)
    _render_commits(console, commits)

    if not keep_clone:
        import shutil

        shutil.rmtree(clone.local_path.parent, ignore_errors=True)
        console.print(f"  [dim]Cleaned up {clone.local_path.parent}[/dim]")
    else:
        console.print(f"  [yellow]Clone retained at[/yellow] {clone.local_path}")


def _render_metadata(console: Console, meta: RepoMetadata) -> None:
    table = Table(title="Repository metadata", show_header=False, box=None)
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    for label, value in [
        ("Owner", meta.owner),
        ("Name", meta.name),
        ("Default", meta.default_branch),
        ("Language", meta.language_hint or "—"),
        ("Size (KB)", str(meta.size_kb)),
        ("HEAD SHA", meta.latest_commit_sha[:12]),
        ("Public", "yes" if meta.is_public else "no"),
        ("URL", str(meta.html_url)),
    ]:
        table.add_row(label, value)
    console.print(table)


def _render_commits(console: Console, commits: Sequence[Commit]) -> None:
    table = Table(title=f"Recent commits ({len(commits)})", show_lines=False)
    table.add_column("SHA", style="cyan", no_wrap=True)
    table.add_column("Date", no_wrap=True)
    table.add_column("Author", no_wrap=True)
    table.add_column("Subject")
    for c in commits:
        subject = c.message.splitlines()[0][:80]
        date = c.committed_at.strftime("%Y-%m-%d")
        table.add_row(
            c.sha[:8],
            date,
            c.author_name,
            subject,
        )
    console.print(table)
