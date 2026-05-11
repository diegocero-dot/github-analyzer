"""Command-line entrypoint for github-analyzer.

M0.3 ships an empty Typer app — `--help` works, subcommands land in M1+.
"""

import typer

from github_analyzer import __version__

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
