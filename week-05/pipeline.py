#!/usr/bin/env python3
"""pipeline.py - run Brookfield's specialists on one supplier email, in a fixed order.

  1. The supply analyst (run_analyst) works out which orders are at risk.
  2. A customer notice for each order at risk (skipped if there are none).
  3. A reply to the supplier.

Every draft goes through the review step in specialists.py (write -> review -> revise at most twice ->
name check -> save to week-05/drafts/). Nothing is ever sent. At the end the pipeline prints a summary:
drafts saved, drafts marked for a person, decisions for a person, and total tokens.

Usage (from the top of the repository):
  .venv/bin/python week-05/pipeline.py --email week-05/brookfield-bikes/supplier-emails/01-northgate-controller-delay.eml
  .venv/bin/python week-05/pipeline.py --email week-05/brookfield-bikes/supplier-emails/01-northgate-controller-delay.eml \\
      --save week-05/runs/01-northgate.txt

--save also writes everything printed to the named text file (UTF-8).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

import specialists as sp


class Tee:
    """A stdout/stderr stand-in that writes to the terminal and to a file."""

    def __init__(self, terminal: TextIO, file: TextIO):
        self.terminal, self.file = terminal, file

    def write(self, text: str) -> int:
        self.terminal.write(text)
        self.file.write(text)
        return len(text)

    def flush(self) -> None:
        self.terminal.flush()
        self.file.flush()


def step(number: int, title: str) -> None:
    print("\n" + "=" * 72)
    print(f"STEP {number}: {title}")
    print("=" * 72, flush=True)


def summary(drafts: list[dict], brief: dict | None) -> None:
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    print(f"Drafts saved: {len(drafts)}")
    for d in drafts:
        print(f"  {d['path']}")

    flagged = [d for d in drafts if d["needs_person"]]
    print(f"\nDrafts marked for a person: {len(flagged)}")
    for d in flagged:
        print(f"  {d['path'].name}: {'; '.join(d['reasons'])}")

    decisions = (brief or {}).get("decisions_for_a_person") or []
    print(f"\nDecisions for a person: {len(decisions)}")
    for item in decisions:
        print(f"  - {item}")

    total_in = sum(t["input"] for t in sp.TOKENS.values())
    total_out = sum(t["output"] for t in sp.TOKENS.values())
    print(f"\nTotal tokens: {total_in + total_out:,} ({total_in:,} input, {total_out:,} output)")
    sp.print_token_report()


def run(email_path: Path) -> int:
    print(f"Email: {email_path}")
    print(f"Model: {sp.MODEL}")
    drafts: list[dict] = []
    brief: dict | None = None
    try:
        email = sp.read_email(email_path)

        step(1, "supply analyst")
        brief = sp.run_analyst(email)

        orders = brief.get("orders_at_risk") or []
        step(2, f"customer notices ({len(orders)} order(s) at risk)")
        if not orders:
            print("No orders at risk; skipping customer notices.")
        for order in orders:
            drafts.append(sp.reviewed_customer_notice(order, email["file"], brief))

        step(3, "reply to the supplier")
        drafts.append(sp.reviewed_supplier_reply(email, brief))
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename}", file=sys.stderr)
        return 1
    except sp.SpecialistError as e:
        print(f"error: {e}", file=sys.stderr)
        summary(drafts, brief)
        return 1

    summary(drafts, brief)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Brookfield's specialists on one supplier email.")
    parser.add_argument("--email", required=True, type=Path, help="path to one supplier email (.eml)")
    parser.add_argument("--save", metavar="FILE", type=Path,
                        help="also write everything printed to this text file (UTF-8)")
    args = parser.parse_args()
    email_path = args.email.resolve()

    if args.save is None:
        sys.exit(run(email_path))

    save_path = args.save.resolve()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    out, err = sys.stdout, sys.stderr
    with save_path.open("w", encoding="utf-8") as f:
        sys.stdout, sys.stderr = Tee(out, f), Tee(err, f)
        try:
            code = run(email_path)
        finally:
            sys.stdout, sys.stderr = out, err
    print(f"Output saved to {save_path}")
    sys.exit(code)


if __name__ == "__main__":
    main()
