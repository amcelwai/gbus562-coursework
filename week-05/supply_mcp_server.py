#!/usr/bin/env python3
"""supply_mcp_server.py - an MCP server with Brookfield Bicycle Company's supply-data tools.

Reads the CSV files in week-05/brookfield-bikes/ (fresh on every call, so edits show up at once):
  parts.csv, inbound.csv, orders.csv, bill-of-materials.csv

Tools:
  get_part(part_id)                 stock on hand, scheduled shipments, and the models that use the part
  get_orders_for_part(part_id)      open orders that need the part: units needed, ship day, late penalty
  check_coverage(part_id, arrivals) replaces the part's scheduled shipments with the given arrivals and
                                    reports, for each order, covered, or units short and first ship day

Days are counted from today (day 0).

Coverage rule: orders are filled complete, in ship-day order (ties by order number). An order takes
parts only when its whole quantity can be filled, and the orders after it wait, so a short order holds
up the ones behind it.

Usage (from the top of the repository):
  .venv/bin/python week-05/supply_mcp_server.py      # serves over stdio

The server talks to its client over stdin/stdout, so nothing in this program may print to stdout;
logs go to stderr.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DATA_DIR = Path(__file__).resolve().parent / "brookfield-bikes"
NEEDED_FILES = ("parts.csv", "inbound.csv", "orders.csv", "bill-of-materials.csv")
NO_GUESS = " Do not estimate or work out these numbers yourself."


# ---------------------------------------------------------------------------
# Reading the CSV files
# ---------------------------------------------------------------------------

def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA_DIR / name).open(newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def find_part(part_id: str) -> dict[str, str]:
    parts = read_csv("parts.csv")
    wanted = part_id.strip().upper()
    for row in parts:
        if row["part_id"].upper() == wanted:
            return row
    raise ToolError(f"No part '{part_id}'. Known parts: {', '.join(r['part_id'] for r in parts)}." + NO_GUESS)


def parts_per_bike(part_id: str) -> dict[str, int]:
    """Model -> number of this part each bike uses."""
    return {r["model"]: int(r["qty_per_bike"]) for r in read_csv("bill-of-materials.csv") if r["part_id"] == part_id}


# ---------------------------------------------------------------------------
# Results (structured output)
# ---------------------------------------------------------------------------

class Shipment(BaseModel):
    po_number: str
    supplier: str
    qty: int
    arrives_in_days: int = Field(description="Days from today until it arrives")


class ModelUse(BaseModel):
    model: str
    parts_per_bike: int


class Part(BaseModel):
    part_id: str
    description: str
    supplier: str
    on_hand: int = Field(description="Units in stock today")
    scheduled_shipments: list[Shipment]
    used_in: list[ModelUse] = Field(description="Bike models that use this part")


class OrderNeed(BaseModel):
    order_id: str
    customer: str
    model: str
    bikes: int
    parts_per_bike: int
    units_needed: int = Field(description="bikes x parts_per_bike")
    ship_day: int = Field(description="Days from today until the order is due to ship")
    late_penalty: bool


class Arrival(BaseModel):
    qty: int = Field(description="Number of units arriving")
    day: int = Field(description="Days from today until they arrive (today is day 0)")


class OrderCoverage(BaseModel):
    order_id: str
    customer: str
    model: str
    units_needed: int
    ship_day: int
    late_penalty: bool
    covered: bool = Field(description="true if the order can ship complete on its ship day")
    units_short: int = Field(description="Units of this part still missing on the ship day (0 if covered)")
    first_ship_day: int | None = Field(
        description="First day the order can ship complete; null if the stock and arrivals never cover it")


class Coverage(BaseModel):
    part_id: str
    on_hand: int
    arrivals: list[Arrival] = Field(description="The arrivals checked, which replace the scheduled shipments")
    total_supply: int = Field(description="on_hand plus all arrivals")
    total_needed: int = Field(description="Units needed by all open orders for this part")
    orders: list[OrderCoverage] = Field(description="In fill order: ship day, then order number")
    orders_not_covered: list[str]


# ---------------------------------------------------------------------------
# Tool logic
# ---------------------------------------------------------------------------

def part_info(part_id: str) -> Part:
    row = find_part(part_id)
    pid = row["part_id"]
    shipments = [
        Shipment(po_number=r["po_number"], supplier=r["supplier"], qty=int(r["qty"]),
                 arrives_in_days=int(r["arrives_in_days"]))
        for r in read_csv("inbound.csv") if r["part_id"] == pid
    ]
    return Part(
        part_id=pid,
        description=row["description"],
        supplier=row["supplier"],
        on_hand=int(row["on_hand"]),
        scheduled_shipments=sorted(shipments, key=lambda s: (s.arrives_in_days, s.po_number)),
        used_in=[ModelUse(model=m, parts_per_bike=n) for m, n in parts_per_bike(pid).items()],
    )


def orders_for_part(part_id: str) -> list[OrderNeed]:
    pid = find_part(part_id)["part_id"]
    per_bike = parts_per_bike(pid)
    orders = [
        OrderNeed(
            order_id=r["order_id"],
            customer=r["customer"],
            model=r["model"],
            bikes=int(r["qty"]),
            parts_per_bike=per_bike[r["model"]],
            units_needed=int(r["qty"]) * per_bike[r["model"]],
            ship_day=int(r["ship_in_days"]),
            late_penalty=r["late_penalty"].lower() == "yes",
        )
        for r in read_csv("orders.csv") if r["model"] in per_bike
    ]
    return sorted(orders, key=lambda o: (o.ship_day, o.order_id))


def coverage(part_id: str, arrivals: list[Arrival]) -> Coverage:
    for a in arrivals:
        if a.qty <= 0 or a.day < 0:
            raise ToolError(f"Bad arrival (qty={a.qty}, day={a.day}): qty must be more than 0 and day "
                            "0 or later (today is day 0)." + NO_GUESS)
    part = find_part(part_id)
    on_hand = int(part["on_hand"])
    arrivals = sorted(arrivals, key=lambda a: a.day)

    # Supply timeline: stock on hand today, then the given arrivals (the scheduled shipments are replaced).
    events = [(0, on_hand)] + [(a.day, a.qty) for a in arrivals]

    def supply_by(day: int) -> int:
        return sum(q for d, q in events if d <= day)

    def first_day_with(units: int) -> int | None:
        total = 0
        for d, q in events:
            total += q
            if total >= units:
                return d
        return None

    results: list[OrderCoverage] = []
    needed_so_far = 0          # units taken by this order and every order ahead of it
    for o in orders_for_part(part_id):
        needed_so_far += o.units_needed
        # Orders fill complete and in turn, so this order can ship once supply covers it and all orders
        # ahead of it, and never before the order ahead of it has shipped.
        ready = first_day_with(needed_so_far)
        if ready is not None and results and results[-1].first_ship_day is not None:
            ready = max(ready, results[-1].first_ship_day)
        covered = ready is not None and ready <= o.ship_day
        short = 0 if covered else min(o.units_needed, needed_so_far - supply_by(o.ship_day))
        results.append(OrderCoverage(
            order_id=o.order_id, customer=o.customer, model=o.model, units_needed=o.units_needed,
            ship_day=o.ship_day, late_penalty=o.late_penalty, covered=covered,
            units_short=max(short, 0) if not covered else 0,
            first_ship_day=ready,
        ))

    return Coverage(
        part_id=part["part_id"],
        on_hand=on_hand,
        arrivals=arrivals,
        total_supply=sum(q for _, q in events),
        total_needed=needed_so_far,
        orders=results,
        orders_not_covered=[r.order_id for r in results if not r.covered],
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

server = MCPServer(
    name="brookfield-supply",
    instructions=(
        "Supply-data tools for Brookfield Bicycle Company. Days are counted from today (day 0). "
        "Use check_coverage for every coverage question; never work out coverage yourself."
    ),
)


@server.tool(description=(
    "Look up one part: units on hand today, its scheduled shipments (purchase order, supplier, quantity, "
    "days from today until arrival), and the bike models that use it with parts per bike."
))
def get_part(part_id: str) -> Part:
    return part_info(part_id)


@server.tool(description=(
    "List the open customer orders that need a part, in ship-day order, with bikes ordered, parts per "
    "bike, units needed (bikes x parts per bike), ship day (days from today), and whether the order has "
    "a late penalty."
))
def get_orders_for_part(part_id: str) -> list[OrderNeed]:
    return orders_for_part(part_id)


@server.tool(description=(
    "Check which orders for a part are covered by a new arrival schedule. The arrivals (each a quantity "
    "and a day, counted from today) REPLACE all of the part's scheduled shipments, so list every arrival "
    "you expect; stock on hand is added automatically. Orders are filled complete in ship-day order, so a "
    "short order holds up the ones after it. For each order returns covered, or units short on its ship "
    "day and the first day it can ship. To compare options, call it once per option."
))
def check_coverage(part_id: str, arrivals: list[Arrival]) -> Coverage:
    return coverage(part_id, arrivals)


def main() -> None:
    missing = [n for n in NEEDED_FILES if not (DATA_DIR / n).is_file()]
    if missing:
        print(f"error: {DATA_DIR} is missing: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)
    print(f"[supply_mcp_server] data folder: {DATA_DIR}", file=sys.stderr, flush=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
