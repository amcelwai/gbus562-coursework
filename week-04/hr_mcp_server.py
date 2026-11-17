#!/usr/bin/env python3
"""hr_mcp_server.py - an MCP server that gives AI apps two HR tools for one organization.

Tools:
  search_policy(query)    the 4 HR-document chunks closest to the query, each with its source file
  get_leave_balance(...)  an employee's leave balances, from the organization's employees.csv

The organization is a folder laid out like this (default: week-04/hartwell-hr):
  hr-docs/            HR policy documents (.html)
  employees.csv       one row per employee; the columns are worked out from the header row
  sample-emails/      example employee emails (used by agent.py)
  system_prompt.txt   the system prompt (used by agent.py)

get_leave_balance has two modes:
  HR staff mode (default):          get_leave_balance(email) looks up any employee by work email.
  Employee mode (--as-employee X):  get_leave_balance() takes no inputs and can return only X's balance.

Usage (from the top of the repository):
  .venv/bin/python week-04/hr_mcp_server.py                                   # Hartwell, HR staff mode (stdio)
  .venv/bin/python week-04/hr_mcp_server.py --org week-04/ridgeline-hotels    # another organization
  .venv/bin/python week-04/hr_mcp_server.py --as-employee dana.whitfield@hartwellfoods.example
  .venv/bin/python week-04/hr_mcp_server.py --org week-04/ridgeline-hotels --rebuild   # rebuild, then exit

Each organization's search database lives in week-04/chroma/<folder name>/ (kept out of Git). It is
built on first use and rebuilt automatically when an HR document changes; --rebuild forces a fresh build.

The server talks to its client over stdin/stdout, so nothing in this program may print to stdout.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path

from pydantic import BaseModel, Field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hr_search  # noqa: E402  (local module next to this file)

NO_RECORD = (
    "No employee record matches {who}. Do not state, estimate, or guess any leave balance for this "
    "person. Say that their balance could not be found and that someone from HR will follow up."
)


# ---------------------------------------------------------------------------
# Organization folder
# ---------------------------------------------------------------------------

def resolve_org_dir(value: str | None) -> Path:
    """Return the organization folder: the given path (or a folder of that name in week-04), else Hartwell."""
    if value is None:
        return hr_search.DEFAULT_ORG_DIR
    path = Path(value).expanduser()
    if not path.is_dir() and not path.is_absolute() and (hr_search.WEEK_DIR / value).is_dir():
        path = hr_search.WEEK_DIR / value
    return path.resolve()


def check_org_dir(org_dir: Path, need: tuple[str, ...] = ("hr-docs", "employees.csv")) -> str | None:
    """Return an error message if the organization folder is missing something, else None."""
    if not org_dir.is_dir():
        return f"organization folder not found: {org_dir}"
    missing = [name for name in need if not (org_dir / name).exists()]
    if missing:
        return f"{org_dir} is missing: {', '.join(missing)}"
    return None


# ---------------------------------------------------------------------------
# Results returned to the AI app (structured output)
# ---------------------------------------------------------------------------

class LeaveBalance(BaseModel):
    name: str
    email: str
    balances: dict[str, int | float] = Field(
        description="Leave balances, keyed by the column names in the organization's employee file"
    )


class PolicyChunk(BaseModel):
    source: str = Field(description="HR document file the text came from; cite this")
    document: str = Field(description="Document title")
    section: str = Field(description="Section heading within the document")
    document_info: str = Field(description="Version and owner line of the document")
    similarity: float = Field(description="Cosine similarity to the query, 0 to 1")
    text: str


# ---------------------------------------------------------------------------
# Employee file: work out the columns from the header row
# ---------------------------------------------------------------------------

BALANCE_WORDS = re.compile(r"\b(remaining|left|balance|available|accrued|days?|hours?)\b", re.I)
LEAVE_WORDS = re.compile(r"\b(pto|vacation|holiday|annual|sick|personal|leave|time off|days?|hours?)\b", re.I)
PEOPLE_WORDS = re.compile(r"\b(manager|supervisor|boss|lead|report(s|ing)? to)\b", re.I)


def words(header: str) -> str:
    """'vacation_days_left' -> 'vacation days left' so word patterns match any naming style."""
    return re.sub(r"[_\-.]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", header)).strip()


def is_number(value: str) -> bool:
    try:
        float(value.strip())
        return True
    except ValueError:
        return False


@dataclass
class EmployeeColumns:
    email: str
    name: str | None
    balances: list[str]


def detect_columns(headers: list[str], rows: list[dict[str, str]]) -> EmployeeColumns:
    """Find the email, name, and leave-balance columns from the header row (checked against the values)."""
    def values(col: str) -> list[str]:
        return [(r.get(col) or "").strip() for r in rows if (r.get(col) or "").strip()]

    # Email: a header that mentions email, preferring one whose values look like addresses;
    # otherwise any column whose values are all addresses.
    email_like = [h for h in headers if values(h) and all("@" in v for v in values(h))]
    named_email = [h for h in headers if re.search(r"e-?mail", h, re.I) and not PEOPLE_WORDS.search(words(h))]
    email = next((h for h in named_email if h in email_like), None) or (named_email or email_like or [None])[0]
    if email is None:
        raise ValueError(f"no email column found in the header row: {headers}")

    # Name: a header that mentions name but not a manager/supervisor.
    name_cols = [h for h in headers
                 if h != email and re.search(r"\bname\b", words(h), re.I) and not PEOPLE_WORDS.search(words(h))]
    name = next((h for h in name_cols if re.fullmatch(r"(employee |full |team member |staff )?name", words(h), re.I)),
                name_cols[0] if name_cols else None)

    # Balances: numeric columns whose header names a balance (e.g. "PTO Days Remaining", "sick_days_left").
    balances = [h for h in headers
                if h not in (email, name)
                and values(h) and all(is_number(v) for v in values(h))
                and BALANCE_WORDS.search(words(h)) and LEAVE_WORDS.search(words(h))]
    if not balances:
        raise ValueError(f"no leave-balance columns found in the header row: {headers}")
    return EmployeeColumns(email=email, name=name, balances=balances)


def read_employees(path: Path) -> tuple[EmployeeColumns, list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:   # utf-8-sig drops a byte-order mark if present
        reader = csv.DictReader(f)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        rows = [{(k or "").strip(): (v or "") for k, v in row.items()} for row in reader]
    return detect_columns(headers, rows), rows


def to_number(value: str) -> int | float:
    number = float(value.strip())
    return int(number) if number.is_integer() else number


def normalize_email(value: str) -> str:
    """Accept 'dana@x.com' or 'Dana Whitfield <dana@x.com>'; compare without regard to case."""
    return parseaddr(value.strip())[1].strip().lower()


def find_employee(employees_csv: Path, email: str) -> LeaveBalance:
    target = normalize_email(email)
    if target:
        cols, rows = read_employees(employees_csv)   # read fresh so edits show up at once
        for row in rows:
            if row[cols.email].strip().lower() == target:
                return LeaveBalance(
                    name=row[cols.name].strip() if cols.name else "",
                    email=row[cols.email].strip(),
                    balances={col: to_number(row[col]) for col in cols.balances if row[col].strip()},
                )
    raise ToolError(NO_RECORD.format(who=f"'{email.strip()}'" if email.strip() else "an empty email address"))


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def create_server(org_dir: Path, as_employee: str | None) -> MCPServer:
    employees_csv = org_dir / "employees.csv"
    cols, _ = read_employees(employees_csv)
    balance_list = ", ".join(cols.balances)
    doc_list = ", ".join(p.name for p in hr_search.document_files())

    if as_employee:
        instructions = (
            f"HR tools for the organization in '{org_dir.name}', running for one employee ({as_employee}). "
            "get_leave_balance returns only that employee's own balance; no other employee's balance is "
            "available. search_policy searches the HR policy documents; cite the source file for each policy fact."
        )
    else:
        instructions = (
            f"HR tools for the organization in '{org_dir.name}', for HR staff. get_leave_balance looks up an "
            "employee's leave balance by work email. search_policy searches the HR policy documents; cite the "
            "source file for each policy fact."
        )
    server = MCPServer(name=f"{org_dir.name}", instructions=instructions)

    @server.tool(description=(
        f"Search the organization's HR policy documents ({doc_list}). Returns the 4 most relevant "
        "sections, each with the source file to cite. Use a short, specific query, e.g. "
        '"carry over unused days".'
    ))
    def search_policy(query: str) -> list[PolicyChunk]:
        if not query.strip():
            raise ToolError("The search query is empty. Give a short description of the policy topic.")
        return [PolicyChunk(**hit) for hit in hr_search.search(query.strip(), k=hr_search.TOP_K)]

    if as_employee:
        @server.tool(description=(
            f"Return the leave balances ({balance_list}) of the employee this server is running for. "
            "Takes no inputs. It cannot look up any other employee."
        ))
        def get_leave_balance() -> LeaveBalance:
            return find_employee(employees_csv, as_employee)
    else:
        @server.tool(description=(
            f"Look up an employee's leave balances ({balance_list}) by their work email address. For HR staff."
        ))
        def get_leave_balance(email: str) -> LeaveBalance:
            return find_employee(employees_csv, email)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="HR MCP server (stdio) for one organization.")
    parser.add_argument("--org", metavar="FOLDER",
                        help="organization folder with hr-docs/ and employees.csv (default: week-04/hartwell-hr)")
    parser.add_argument("--as-employee", metavar="EMAIL",
                        help="employee mode: get_leave_balance takes no inputs and returns only this employee's balance")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the search database from the HR documents, then exit")
    args = parser.parse_args()

    org_dir = resolve_org_dir(args.org)
    if (problem := check_org_dir(org_dir)):
        parser.error(problem)
    hr_search.configure(org_dir)

    if args.rebuild:
        hr_search.get_index(rebuild=True)
        return

    try:
        cols, _ = read_employees(org_dir / "employees.csv")
    except ValueError as e:
        parser.error(f"{org_dir / 'employees.csv'}: {e}")
    hr_search.log(f"{org_dir.name}: employee file columns: email='{cols.email}', name='{cols.name}', "
                  f"balances={cols.balances}")

    as_employee = normalize_email(args.as_employee) if args.as_employee is not None else None
    if args.as_employee is not None and not as_employee:
        parser.error("--as-employee needs an email address")
    if as_employee:
        try:
            find_employee(org_dir / "employees.csv", as_employee)
            hr_search.log(f"{org_dir.name}: employee mode for {as_employee}")
        except ToolError:
            hr_search.log(f"{org_dir.name}: warning: no employee record matches {as_employee}; "
                          "get_leave_balance will return an error")

    hr_search.get_index()   # open (or build) the search database before the first tool call
    create_server(org_dir, as_employee).run("stdio")


if __name__ == "__main__":
    main()
