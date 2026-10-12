"""mail-intake run    -> process new mail once (for a scheduled task)

Settings come from environment variables: GRAPH_TENANT_ID, GRAPH_CLIENT_ID,
GRAPH_CLIENT_SECRET, INTAKE_MAILBOX, INTAKE_FOLDER, INTAKE_FILED_FOLDER_ID,
INTAKE_DRIVE_ID, and optionally INTAKE_STATE (default intake_state.json).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .graph import Graph, GraphConfig
from .intake import IntakeConfig, State, run


def main() -> int:
    env = os.environ
    graph = Graph(GraphConfig(env["GRAPH_TENANT_ID"], env["GRAPH_CLIENT_ID"], env["GRAPH_CLIENT_SECRET"]))
    cfg = IntakeConfig(
        mailbox=env["INTAKE_MAILBOX"],
        folder=env.get("INTAKE_FOLDER", "inbox"),
        filed_folder_id=env["INTAKE_FILED_FOLDER_ID"],
        drive_id=env["INTAKE_DRIVE_ID"],
    )
    state_path = Path(env.get("INTAKE_STATE", "intake_state.json"))
    state = State.load(state_path)
    report = run(graph, cfg, state)
    state.save(state_path)

    print(f"Messages with attachments: {report.messages}")
    for p in report.filed:
        print(f"  filed      {p}")
    for n in report.duplicates:
        print(f"  duplicate  {n}")
    for n in report.skipped:
        print(f"  skipped    {n} (not a PDF)")
    for e in report.errors:
        print(f"  ERROR      {e}", file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
