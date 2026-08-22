"""Rebuild the review queue from run records already on disk.

    python -m src.review

The batch emits this file itself, so this command is not how the queue is normally
produced. It exists because the queue is *derived* — every item in it comes from a record
`out/runs/` already holds — and a derived artifact that can only be produced by re-running
the thing that derived it is not really derived, it is a side effect. This costs no model
requests and does not need the accounting system running.

Exit status: 0 when the queue was written and nothing needs a person, 1 when it was
written and something does, 2 when there was nothing to build from. The middle case is not
an error — a queue with items in it is the system working — but a caller that wants to
know whether a human is needed should not have to parse the file to find out.
"""

from __future__ import annotations

import sys

from . import load_records, write_queue

EXIT_NOTHING_QUEUED = 0
EXIT_NEEDS_A_PERSON = 1
EXIT_NOTHING_TO_BUILD_FROM = 2


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    records = load_records()
    if not records:
        print(
            "No run records found in out/runs/. Run the pipeline first:\n"
            "    python -m src.main invoices/"
        )
        return EXIT_NOTHING_TO_BUILD_FROM

    path, queue = write_queue(records)

    print(f"records       {len(records)} read from out/runs/")
    print(f"queue         {queue.needs_a_person} document(s) need a person")
    print(f"written       {path}")

    return EXIT_NEEDS_A_PERSON if queue.items else EXIT_NOTHING_QUEUED


if __name__ == "__main__":
    raise SystemExit(main())
