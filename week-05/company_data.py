"""company_data.py - read one company's supply data without assuming its CSV column names.

A company folder (e.g. week-05/brookfield-bikes, week-05/copperline-coffee) holds:
  parts.csv, inbound.csv, orders.csv, bill-of-materials.csv, suppliers.csv
  prompts/      the specialists' system prompts (analyst.txt, supplier-writer.txt, ...)
  supplier-emails/

Column names differ between companies (Brookfield: model, qty, qty_per_bike, ship_in_days;
Copperline: product, units, per_unit, ship_by_day). For each file, find_columns() works out from the
header row which column holds each thing the tools need (its "role"), and Company.table() returns the
rows with standard keys, so the rest of the code never sees the company's own column names.

How a column is matched to a role: the header is lowered and split into words ("Ship By Day" ->
ship_by_day). Each role has a list of patterns, tried in order: first an exact match on the whole
header, then a match on whole words inside it ("ship" matches ship_by_day, "per" matches qty_per_bike).
Number roles (quantities, days) only take a column whose values are all whole numbers. A column is
used for one role only. The file is read fresh on every call, so edits show up at once.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

WEEK_DIR = Path(__file__).resolve().parent
DEFAULT_ORG_DIR = WEEK_DIR / "brookfield-bikes"

FILES = {
    "parts": "parts.csv",
    "inbound": "inbound.csv",
    "orders": "orders.csv",
    "bom": "bill-of-materials.csv",
    "suppliers": "suppliers.csv",
}
PROMPTS = ("analyst", "supplier-writer", "customer-writer", "reviewer", "orchestrator")

# kind -> list of (role, patterns, is_number, required). Roles are matched in this order, so a more
# specific role can claim its column before a looser pattern sees it.
ROLES: dict[str, list[tuple[str, list[str], bool, bool]]] = {
    "parts": [
        ("part_id", ["part_id", "part_number", "part_no", "part", "sku"], False, True),
        ("on_hand", ["on_hand", "qty_on_hand", "in_stock", "stock", "inventory", "available"], True, True),
        ("supplier", ["supplier", "supplier_name", "vendor"], False, True),
        ("description", ["description", "desc", "part_name", "name"], False, False),
    ],
    "inbound": [
        ("po_number", ["po_number", "po_no", "po", "purchase_order"], False, True),
        ("part_id", ["part_id", "part_number", "part_no", "part", "sku"], False, True),
        ("supplier", ["supplier", "supplier_name", "vendor"], False, False),
        ("arrives_in_days", ["arrives_in_days", "arrival_day", "arrives", "arrival", "eta", "days"], True, True),
        ("qty", ["qty", "quantity", "units", "count", "amount"], True, True),
    ],
    "orders": [
        ("order_id", ["order_id", "order_number", "order_no", "order"], False, True),
        ("contact_email", ["contact_email", "email", "e_mail"], False, False),
        ("customer", ["customer", "customer_name", "client", "account", "buyer"], False, True),
        ("ship_day", ["ship_in_days", "ship_by_day", "ship_day", "ships_in_days", "due_in_days",
                      "ship", "due"], True, True),
        ("quantity", ["qty", "quantity", "units", "unit_count", "count", "bikes", "machines"], True, True),
        ("product", ["product", "product_name", "model", "item", "sku"], False, True),
        ("late_penalty", ["late_penalty", "penalty"], False, False),
    ],
    "bom": [
        ("per_unit", ["qty_per_bike", "per_unit", "parts_per_unit", "qty_per_unit", "quantity_per",
                      "qty_per", "per"], True, True),
        ("part_id", ["part_id", "part_number", "part_no", "part"], False, True),
        ("product", ["product", "product_name", "model", "item", "sku"], False, True),
    ],
    "suppliers": [
        ("contact_email", ["contact_email", "email", "e_mail"], False, False),
        ("supplier", ["supplier", "supplier_name", "vendor", "company"], False, True),
        ("contact_name", ["contact_name", "contact", "name"], False, False),
        ("part_id", ["part_id", "part_number", "part"], False, False),
    ],
}


class DataError(ValueError):
    """A company folder is missing a file, or a needed column can't be found in a header row."""


def normalize(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", header.strip().lower()).strip("_")


def _all_whole_numbers(rows: list[dict[str, str]], column: str) -> bool:
    values = [r.get(column, "").strip() for r in rows]
    values = [v for v in values if v]
    return bool(values) and all(re.fullmatch(r"-?\d+", v) for v in values)


def find_columns(kind: str, header: list[str], rows: list[dict[str, str]]) -> dict[str, str]:
    """Return role -> the company's column name, worked out from the header row."""
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for role, patterns, is_number, required in ROLES[kind]:
        found = None
        for exact in (True, False):
            for pattern in patterns:
                for column in header:
                    if column in used:
                        continue
                    name = normalize(column)
                    hit = name == pattern if exact else f"_{pattern}_" in f"_{name}_"
                    if hit and (not is_number or _all_whole_numbers(rows, column)):
                        found = column
                        break
                if found:
                    break
            if found:
                break
        if found is not None:
            mapping[role] = found
            used.add(found)
        elif required:
            raise DataError(f"{FILES[kind]}: can't tell which column holds '{role}' "
                            f"(columns: {', '.join(header)})")
    return mapping


def is_yes(value: str) -> bool:
    return value.strip().lower() in ("yes", "y", "true", "t", "1")


class Company:
    """One company folder. Every read goes back to the CSV files."""

    def __init__(self, folder: Path):
        self.dir = Path(folder).resolve()
        self.name = self.dir.name
        self.prompts_dir = self.dir / "prompts"

    def _read(self, kind: str) -> tuple[list[str], list[dict[str, str]]]:
        path = self.dir / FILES[kind]
        if not path.is_file():
            raise DataError(f"{self.dir} is missing {FILES[kind]}")
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = [(h or "").strip() for h in (reader.fieldnames or [])]
            rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
        return header, rows

    def columns(self, kind: str) -> dict[str, str]:
        header, rows = self._read(kind)
        return find_columns(kind, header, rows)

    def table(self, kind: str) -> list[dict]:
        """The file's rows with standard keys; number roles as int, late_penalty as bool."""
        header, rows = self._read(kind)
        mapping = find_columns(kind, header, rows)
        numbers = {role for role, _, is_number, _ in ROLES[kind] if is_number}
        out = []
        for row in rows:
            rec: dict = {}
            for role, column in mapping.items():
                value = row.get(column, "")
                rec[role] = int(value) if role in numbers else value
            if kind == "orders":
                rec["late_penalty"] = is_yes(rec.get("late_penalty", ""))
            out.append(rec)
        return out

    def check(self, need_prompts: bool = True) -> list[str]:
        """Problems that would stop the tools working (empty list if none)."""
        problems = []
        if not self.dir.is_dir():
            return [f"company folder not found: {self.dir}"]
        for kind in FILES:
            try:
                self.columns(kind)
            except DataError as e:
                problems.append(str(e))
        if need_prompts:
            missing = [p for p in PROMPTS if not (self.prompts_dir / f"{p}.txt").is_file()]
            if missing:
                problems.append(f"{self.prompts_dir} is missing: {', '.join(p + '.txt' for p in missing)}")
        return problems

    def describe_columns(self) -> list[str]:
        """One line per file: role=column for every role found."""
        lines = []
        for kind, filename in FILES.items():
            try:
                cols = self.columns(kind)
                lines.append(f"{filename}: " + ", ".join(f"{r}={c}" for r, c in cols.items()))
            except DataError as e:
                lines.append(f"{filename}: ERROR {e}")
        return lines


def resolve_org_dir(value: str | Path | None) -> Path:
    """The --org value as a folder: a path, or the name of a folder in week-05. None -> Brookfield."""
    if value is None:
        return DEFAULT_ORG_DIR
    path = Path(value).expanduser()
    if not path.is_dir() and not path.is_absolute() and (WEEK_DIR / path).is_dir():
        path = WEEK_DIR / path
    return path.resolve()
