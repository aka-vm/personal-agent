#!/usr/bin/env python3
"""Stop the Playwright browser if it's been running > 15 min. It's an on-demand
tool — the agent starts it when needed; this reaps it so it never lingers."""
import subprocess, datetime
C = "playwright-mcp-playwright-mcp-1"
r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}|{{.State.StartedAt}}", C],
                   capture_output=True, text=True).stdout.strip()
if r.startswith("true|"):
    started = datetime.datetime.fromisoformat(r.split("|")[1].replace("Z", "+00:00"))
    age = (datetime.datetime.now(datetime.timezone.utc) - started).total_seconds()
    if age > 900:
        subprocess.run(["docker", "stop", C], capture_output=True)
        print(f"reaped browser (was up {int(age)}s)")
