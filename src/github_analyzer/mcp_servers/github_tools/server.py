"""MCP server entrypoint — placeholder for M3.

Right now the tools (`tools.py`) are consumed as regular async Python
functions by the CLI and (later) the LangGraph nodes. The MCP transport
wrapper (`stdio` or `http`) lands in M3 once at least one agent needs
to consume them via MCP rather than direct import.

When M3 lands, this module will:
- Construct a `mcp.Server` (or equivalent) instance.
- Register each function from `tools.py` as an MCP tool with its schema.
- Expose a CLI entrypoint `python -m github_analyzer.mcp_servers.github_tools.server`
  that serves stdio.

For now, importing this module is a no-op.
"""

from __future__ import annotations


def main() -> None:
    """Placeholder entrypoint. Raises NotImplementedError when invoked."""
    raise NotImplementedError(
        "MCP transport wrapper lands in M3. For M1, use tools.py functions directly."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
