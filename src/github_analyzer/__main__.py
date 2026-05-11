"""Allow `python -m github_analyzer` to launch the Typer CLI."""

from github_analyzer.cli import app

if __name__ == "__main__":
    app()
