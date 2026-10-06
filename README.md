# MCP File Server

A sandboxed MCP file server (Python + FastMCP, Streamable HTTP) that gives agents
a shared, persistent workspace through 10 small tools, two permission roles
(reader / writer), and handoff files for multi-session work.

**Status:** M1-M2 in progress. `sandbox.py` and its tests are done; tools are next.

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then set real tokens and WORKSPACE_ROOT
```

Create the live workspace **outside** this repo and seed it:

```bash
mkdir ~/mcp-workspace
cp -r examples/workspace/. ~/mcp-workspace/
cd ~/mcp-workspace && git init && git add -A && git commit -m "chore: seed workspace"
```

## Tests

```bash
python -m pytest
```

## Layout

```text
server/        config.py, sandbox.py, tools/ (more modules added per milestone)
examples/      seed copy of the handoff files
tests/         pytest suites
docs/          report, transcript, demo script (added at M5)
logs/          tool_calls.jsonl (git-ignored)
```

Run the server with `python -m server.main` (not `python server/main.py`).
