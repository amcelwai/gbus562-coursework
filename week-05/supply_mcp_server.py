#!/usr/bin/env python3
"""supply_mcp_server.py - an MCP server with one company's supply-data tools.

--org names a company folder (default: week-05/brookfield-bikes). The server reads its CSV files
(fresh on every call, so edits show up at once):
  parts.csv, inbound.csv, orders.csv, bill-of-materials.csv
Column names are not assumed: company_data.py works out from each header row which column holds the
product, the quantity, the parts per unit, the ship day, and so on.

Tools:
  get_part(part_id)                 stock on hand, scheduled shipments, and the products that use the part
  get_orders_for_part(part_id)      open orders that need the part: units needed, ship day, late penalty
  check_coverage(part_id, arrivals) replaces the part's scheduled shipments with the given arrivals and
                                    reports, for each order, covered, or units short and first ship day

Days are counted from today (day 0).

Coverage rule: orders are filled complete, in ship-day order (ties by order number). An order takes
parts only when its whole quantity can be filled, and the orders after it wait, so a short order holds
up the ones behind it.

Usage (from the top of the repository):
  .venv/bin/python week-05/supply_mcp_server.py                          # Brookfield, over stdio
  .venv/bin/python week-05/supply_mcp_server.py --org copperline-coffee  # or a path to the folder

The server talks to its client over stdin/stdout, so nothing in this program may print to stdout;
logs go to stderr.
"""

from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from company_data import Company, DataError, resolve_org_dir

NO_GUESS = " Do not estimate or work out these numbers yourself."

company = Company(resolve_org_dir(None))       # replaced in main() when --org is given


# ---------------------------------------------------------------------------
# Reading the data (standard keys from company_data, whatever the CSV headers say)
# ---------------------------------------------------------------------------

def table(kind: str) -> list[dict]:
    try:
        return company.table(kind)
    except DataError as e:
        raise ToolError(f"Data problem: {e}") from None


def find_part(part_id: str) -> dict:
    parts = table("parts")
    wanted = part_id.strip().upper()
    for row in parts:
        if row["part_id"].upper() == wanted:
            return row
    raise ToolError(f"No part '{part_id}'. Known parts: {', '.join(r['part_id'] for r in parts)}." + NO_GUESS)


def parts_per_unit(part_id: str) -> dict[str, int]:
    """Product -> number of this part each unit of the product uses."""
    return {r["product"]: r["per_unit"] for r in table("bom") if r["part_id"] == part_id}


# ---------------------------------------------------------------------------
# Results (structured output)
# ---------------------------------------------------------------------------

class Shipment(BaseModel):
    po_number: str
    supplier: str
    qty: int
    arrives_in_days: int = Field(description="Days from today until it arrives")


class ProductUse(BaseModel):
    product: str
    parts_per_unit: int


class Part(BaseModel):
    part_id: str
    description: str
    supplier: str
    on_hand: int = Field(description="Units in stock today")
    scheduled_shipments: list[Shipment]
    used_in: list[ProductUse] = Field(description="Products that use this part")


class OrderNeed(BaseModel):
    order_id: str
    customer: str
    product: str
    units: int = Field(description="Units of the product ordered")
    parts_per_unit: int
    units_needed: int = Field(description="units x parts_per_unit: parts this order needs")
    ship_day: int = Field(description="Days from today until the order is due to ship")
    late_penalty: bool


class Arrival(BaseModel):
    qty: int = Field(description="Number of units arriving")
    day: int = Field(description="Days from today until they arrive (today is day 0)")


class OrderCoverage(BaseModel):
    order_id: str
    customer: str
    product: str
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
        Shipment(po_number=r["po_number"], supplier=r.get("supplier") or row["supplier"], qty=r["qty"],
                 arrives_in_days=r["arrives_in_days"])
        for r in table("inbound") if r["part_id"] == pid
    ]
    return Part(
        part_id=pid,
        description=row.get("description", ""),
        supplier=row["supplier"],
        on_hand=row["on_hand"],
        scheduled_shipments=sorted(shipments, key=lambda s: (s.arrives_in_days, s.po_number)),
        used_in=[ProductUse(product=p, parts_per_unit=n) for p, n in parts_per_unit(pid).items()],
    )


def orders_for_part(part_id: str) -> list[OrderNeed]:
    pid = find_part(part_id)["part_id"]
    per_unit = parts_per_unit(pid)
    orders = [
        OrderNeed(
            order_id=r["order_id"],
            customer=r["customer"],
            product=r["product"],
            units=r["quantity"],
            parts_per_unit=per_unit[r["product"]],
            units_needed=r["quantity"] * per_unit[r["product"]],
            ship_day=r["ship_day"],
            late_penalty=r["late_penalty"],
        )
        for r in table("orders") if r["product"] in per_unit
    ]
    return sorted(orders, key=lambda o: (o.ship_day, o.order_id))


def coverage(part_id: str, arrivals: list[Arrival]) -> Coverage:
    for a in arrivals:
        if a.qty <= 0 or a.day < 0:
            raise ToolError(f"Bad arrival (qty={a.qty}, day={a.day}): qty must be more than 0 and day "
                            "0 or later (today is day 0)." + NO_GUESS)
    part = find_part(part_id)
    on_hand = part["on_hand"]
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
            order_id=o.order_id, customer=o.customer, product=o.product, units_needed=o.units_needed,
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
    name="supply-data",
    instructions=(
        "Supply-data tools for one company (the folder given with --org). Days are counted from today "
        "(day 0). Use check_coverage for every coverage question; never work out coverage yourself."
    ),
)


@server.tool(description=(
    "Look up one part: units on hand today, its scheduled shipments (purchase order, supplier, quantity, "
    "days from today until arrival), and the products that use it with parts per unit."
))
def get_part(part_id: str) -> Part:
    return part_info(part_id)


@server.tool(description=(
    "List the open customer orders that need a part, in ship-day order, with units ordered, parts per "
    "unit, units needed (units x parts per unit), ship day (days from today), and whether the order has "
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
    global company
    parser = argparse.ArgumentParser(description="Serve one company's supply-data tools over stdio.")
    parser.add_argument("--org", metavar="FOLDER",
                        help="company folder, or the name of one in week-05 (default: brookfield-bikes)")
    args = parser.parse_args()

    company = Company(resolve_org_dir(args.org))
    problems = company.check(need_prompts=False)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        raise SystemExit(1)
    print(f"[supply_mcp_server] company folder: {company.dir}", file=sys.stderr)
    for line in company.describe_columns():
        print(f"[supply_mcp_server]   {line}", file=sys.stderr)
    sys.stderr.flush()
    server.run("stdio")


if __name__ == "__main__":
    main()
