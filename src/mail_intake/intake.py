"""Supplier invoices from a shared mailbox to a SharePoint library.

For each new message in the watched folder:
  1. take its PDF attachments (skip inline images, signatures, other types);
  2. skip any file already filed before (same SHA-256), so re-sent invoices don't duplicate;
  3. save as  Invoices/<yyyy>/<mm>/<sender domain>/<yyyy-mm-dd>_<file name>;
  4. move the message to a "Filed" folder so people can see what was handled.

State (the delta link and the hashes already filed) is a small JSON file, so a
re-run after a failure carries on where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .graph import Graph, GraphError

ALLOWED_TYPES = {"application/pdf"}
SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass
class IntakeConfig:
    mailbox: str  # e.g. invoices@company.co.za
    folder: str  # folder id or well-known name, e.g. "inbox"
    filed_folder_id: str
    drive_id: str  # SharePoint document library
    root: str = "Invoices"


@dataclass
class State:
    delta_link: str | None = None
    filed_hashes: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> State:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("delta_link"), set(data.get("filed_hashes", [])))

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"delta_link": self.delta_link, "filed_hashes": sorted(self.filed_hashes)}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)  # atomic: a crash never leaves half a state file


@dataclass
class RunReport:
    messages: int = 0
    filed: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def safe_name(name: str) -> str:
    cleaned = SAFE.sub("_", name).strip(" .")
    return cleaned[:120] or "attachment.pdf"


def sender_domain(message: dict) -> str:
    address = message.get("from", {}).get("emailAddress", {}).get("address", "")
    return safe_name(address.split("@")[-1].lower()) if "@" in address else "unknown-sender"


def target_path(cfg: IntakeConfig, message: dict, filename: str) -> str:
    received = message["receivedDateTime"][:10]  # YYYY-MM-DD
    year, month = received[:4], received[5:7]
    return f"{cfg.root}/{year}/{month}/{sender_domain(message)}/{received}_{safe_name(filename)}"


def run(graph: Graph, cfg: IntakeConfig, state: State) -> RunReport:
    report = RunReport()
    messages, next_delta = graph.message_delta(cfg.mailbox, cfg.folder, state.delta_link)
    for message in messages:
        if not message.get("hasAttachments"):
            continue
        report.messages += 1
        try:
            for name, content_type, content in graph.file_attachments(cfg.mailbox, message["id"]):
                is_pdf = content_type in ALLOWED_TYPES or name.lower().endswith(".pdf")
                if not is_pdf:
                    report.skipped.append(name)
                    continue
                digest = hashlib.sha256(content).hexdigest()
                if digest in state.filed_hashes:
                    report.duplicates.append(name)
                    continue
                path = target_path(cfg, message, name)
                graph.upload_small_file(cfg.drive_id, path, content)
                state.filed_hashes.add(digest)
                report.filed.append(path)
            graph.move_message(cfg.mailbox, message["id"], cfg.filed_folder_id)
        except GraphError as e:
            # Leave the message where it is; the next run will try it again.
            report.errors.append(f"{message.get('subject', message['id'])}: {e}")
    if not report.errors:
        state.delta_link = next_delta  # only advance when everything in this window was handled
    return report
