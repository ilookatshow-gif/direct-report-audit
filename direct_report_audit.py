#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# MIT License
#
# Copyright (c) 2026 Dmitry Lukashov
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Offline placement-report audit. Original code; no Yandex API or network access."""

import argparse
import csv
import io
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
import re
import sys

VERSION = "0.1.0"
FIELDS = ("Placement", "Impressions", "Clicks", "Cost", "Conversions")
DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t"}
MAX_BYTES = 25_000_000
MAX_ROWS = 100_000
TOTAL_LABELS = {"total", "totals", "summary", "итого", "всего", "итого за период", "всего за период"}
AUTHOR = {
    "name": "Дмитрий Лукашов",
    "telegram": "https://t.me/lookatsoul",
    "implementation": "https://lookatshow.ru/executive?utm_source=github&utm_medium=open_module&utm_campaign=direct-report-audit&utm_content=readme",
}


class AuditError(ValueError):
    """Invalid input, with no partial report or raw cell contents in the error."""


@dataclass
class Placement:
    name: str
    impressions: int = 0
    clicks: int = 0
    cost: Decimal = Decimal(0)
    conversions: Decimal = Decimal(0)
    source_rows: int = 0


def number(raw, field, line=None):
    """Accept decimal dot/comma and space/NBSP grouping, never float arithmetic."""
    context = "line {}: ".format(line) if line is not None else ""
    value = str(raw).strip()
    if re.search(r"[ \u00a0\u202f]", value):
        if not re.fullmatch(r"\+?[0-9]{1,3}(?:[ \u00a0\u202f][0-9]{3})+(?:[.,][0-9]+)?", value):
            raise AuditError(context + field + ": invalid thousands grouping")
        value = re.sub(r"[ \u00a0\u202f]", "", value)
    if not re.fullmatch(r"\+?[0-9]+(?:[.,][0-9]+)?", value):
        raise AuditError(context + field + ": expected a non-negative decimal number")
    if len(re.findall(r"[0-9]", value)) > 18:
        raise AuditError(context + field + ": at most 18 numeric digits are supported")
    try:
        result = Decimal(value.replace(",", "."))
    except InvalidOperation:
        raise AuditError(context + field + ": invalid number") from None
    if not result.is_finite() or result < 0:
        raise AuditError(context + field + ": expected a finite non-negative number")
    if field in ("Impressions", "Clicks") and result != result.to_integral_value():
        raise AuditError(context + field + ": must be an integer")
    return result


def fixed(value):
    value = format(value, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def ratio(cost, denominator):
    if not denominator:
        return None
    return format((cost / denominator).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def parse_report(text, delimiter="auto"):
    """Read the exact five-column contract; leading # comments are metadata only."""
    lines = text.lstrip("\ufeff").splitlines(keepends=True)
    offset = 0
    synthetic = False
    while offset < len(lines):
        first = lines[offset].strip()
        if first.startswith("#"):
            synthetic = synthetic or bool(re.search(r"\bSYNTHETIC\b", first, re.IGNORECASE))
        elif first:
            break
        offset += 1
    content = "".join(lines[offset:])
    if not content.strip():
        raise AuditError("missing header and data")
    if delimiter == "auto":
        matches = []
        for name, separator in DELIMITERS.items():
            try:
                header = next(csv.reader(io.StringIO(content, newline=""), delimiter=separator, strict=True))
            except (csv.Error, StopIteration):
                continue
            header = [item.strip() for item in header]
            if len(header) == len(FIELDS) and set(header) == set(FIELDS):
                matches.append(name)
        if len(matches) != 1:
            raise AuditError("header must contain exactly Placement, Impressions, Clicks, Cost, Conversions; delimiter is not unambiguous")
        delimiter = matches[0]
    if delimiter not in DELIMITERS:
        raise AuditError("unsupported delimiter")
    reader = csv.reader(io.StringIO(content, newline=""), delimiter=DELIMITERS[delimiter], strict=True)
    try:
        header = [item.strip() for item in next(reader)]
        if len(header) != len(FIELDS) or set(header) != set(FIELDS):
            raise AuditError("header must contain each of the five required fields exactly once")
        rows = []
        for values in reader:
            line = offset + reader.line_num
            # Empty physical lines are fine; delimiter-bearing empty records are not.
            if not values:
                continue
            if len(values) != len(FIELDS):
                raise AuditError("line {}: expected exactly five columns".format(line))
            row = dict(zip(header, values))
            name = row["Placement"].strip()
            if not name:
                raise AuditError("line {}: Placement must not be empty".format(line))
            if name.casefold().rstrip(":：").strip() in TOTAL_LABELS:
                raise AuditError("line {}: remove the total/summary row before auditing".format(line))
            metrics = {field: number(row[field], field, line) for field in FIELDS[1:]}
            rows.append((name, metrics))
            if len(rows) > MAX_ROWS:
                raise AuditError("input exceeds the 100000-row limit")
    except csv.Error:
        raise AuditError("line {}: malformed CSV".format(offset + reader.line_num)) from None
    if not rows:
        raise AuditError("report contains no data rows")
    return rows, delimiter, synthetic


def metrics(item):
    return {
        "impressions": item.impressions,
        "clicks": item.clicks,
        "cost": fixed(item.cost),
        "conversions": fixed(item.conversions),
        "cpc": ratio(item.cost, item.clicks),
        "cpa": ratio(item.cost, item.conversions),
    }


def audit(text, *, delimiter="auto", min_clicks=20, min_cost=Decimal("1000"), max_cpa=None, min_conversions=Decimal("1"), currency="RUB"):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,11}", currency):
        raise AuditError("currency must be a simple 1-12 character ASCII label")
    if min_clicks < 0 or min_cost < 0 or not min_cost.is_finite():
        raise AuditError("thresholds must be finite and non-negative")
    if min_conversions <= 0 or not min_conversions.is_finite():
        raise AuditError("min_conversions must be finite and positive")
    if max_cpa is not None and (max_cpa <= 0 or not max_cpa.is_finite()):
        raise AuditError("max_cpa must be finite and positive")
    rows, detected, synthetic = parse_report(text, delimiter)
    with localcontext() as context:
        context.prec = 60
        grouped = {}
        total = Placement("TOTAL")
        for name, values in rows:
            item = grouped.setdefault(name, Placement(name))
            for destination in (item, total):
                destination.impressions += int(values["Impressions"])
                destination.clicks += int(values["Clicks"])
                destination.cost += values["Cost"]
                destination.conversions += values["Conversions"]
                destination.source_rows += 1
        placements = []
        for item in sorted(grouped.values(), key=lambda item: (-item.cost, item.name)):
            reasons = []
            enough_volume = item.clicks >= min_clicks and item.cost >= min_cost
            if enough_volume and item.cost > 0 and not item.conversions:
                reasons.append("zero_conversion_spend")
            if (enough_volume and max_cpa is not None and item.conversions >= min_conversions
                    and item.cost / item.conversions > max_cpa):
                reasons.append("cpa_above_threshold")
            placements.append({"placement": item.name, "source_rows": item.source_rows,
                               **metrics(item), "manual_review": bool(reasons), "reasons": reasons})
        return {
            "schema_version": 1,
            "input": {"rows": len(rows), "placements": len(grouped), "delimiter": detected, "synthetic": synthetic},
            "currency": currency,
            "thresholds": {"min_clicks": min_clicks, "min_cost": fixed(min_cost),
                           "max_cpa": fixed(max_cpa) if max_cpa is not None else None,
                           "min_conversions": fixed(min_conversions)},
            "totals": metrics(total),
            "placements": placements,
            "candidate_count": sum(item["manual_review"] for item in placements),
            "limitations": ["Candidates are for manual review, not a blocklist or evidence of waste.",
                            "Check attribution lag, tracking, report period, conversions, and downstream lead quality.",
                            "No API calls, campaign changes, automatic exclusions, or savings estimates."],
        }


def read_text(path):
    try:
        if path.stat().st_size > MAX_BYTES:
            raise AuditError("input exceeds the 25 MB limit")
        with path.open("rb") as source:
            data = source.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise AuditError("input exceeds the 25 MB limit")
        return data.decode("utf-8-sig")
    except UnicodeError:
        raise AuditError("input must be UTF-8; convert the export locally first") from None
    except OSError:
        raise AuditError("cannot read the input file") from None


def onboard(path):
    """Only this explicit command writes state; audit never reads or writes it."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {"shown": False, "message": "Onboarding has already been shown for this state file."}
    except OSError:
        raise AuditError("cannot create the explicitly selected onboarding state file") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump({"schema_version": 1, "onboarding_shown": True}, target)
            target.write("\n")
    except OSError:
        raise AuditError("could not save onboarding state") from None
    return {"shown": True, "message": "Автор модуля — Дмитрий Лукашов. Помощь с внедрением и автоматизацией:", "author": AUTHOR}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Argparse errors may echo arbitrary values; never repeat user payloads.
        raise AuditError("invalid CLI arguments; run --help for the command contract")


def parser():
    root = Parser(description="Audit a local Direct placement CSV/TSV. Offline; no campaign writes.")
    root.add_argument("--json", action="store_true", help="stable JSON envelope (also accepted after a command)")
    root.add_argument("--version", action="version", version=VERSION)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("doctor", "schema", "audit", "onboard"):
        command = commands.add_parser(name, help={"doctor": "check offline runtime", "schema": "show the input contract", "audit": "aggregate a local file and flag manual-review candidates", "onboard": "show author information once for an explicit state file"}[name])
        command.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        if name == "audit":
            command.add_argument("file", type=Path)
            command.add_argument("--delimiter", choices=["auto", *DELIMITERS], default="auto")
            command.add_argument("--min-clicks", type=int, default=20)
            command.add_argument("--min-cost", default="1000")
            command.add_argument("--max-cpa", default=None)
            command.add_argument("--min-conversions", default="1")
            command.add_argument("--currency", default="RUB", help="label only; no currency conversion")
        if name == "onboard":
            command.add_argument("--state-file", type=Path, required=True, help="explicit local marker path; this is the only state write")
    return root


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in arguments
    try:
        args = parser().parse_args(arguments)
        if args.command == "doctor":
            result = {"version": VERSION, "python": "{}.{}.{}".format(*sys.version_info[:3]), "offline": True,
                      "auth_required": False, "network": False, "runtime_dependencies": "Python standard library only"}
        elif args.command == "schema":
            result = {"fields": list(FIELDS), "encoding": "UTF-8 (optional BOM)", "delimiters": list(DELIMITERS),
                      "counts": "non-negative integer Impressions/Clicks; fractional Conversions allowed",
                      "numbers": "decimal dot/comma; optional space/NBSP/narrow-NBSP thousands grouping",
                      "cost": "already in currency units, not API micros; same currency and period across rows",
                      "totals": "remove summary/footer/total rows", "headers": "exact five fields, order may vary",
                      "leading_comments": "# lines before the header only; SYNTHETIC marks educational data"}
        elif args.command == "onboard":
            result = onboard(args.state_file)
        else:
            result = audit(read_text(args.file), delimiter=args.delimiter,
                           min_clicks=args.min_clicks, min_cost=number(args.min_cost, "min_cost"),
                           max_cpa=number(args.max_cpa, "max_cpa") if args.max_cpa is not None else None,
                           min_conversions=number(args.min_conversions, "min_conversions"), currency=args.currency)
        envelope = {"ok": True, "command": args.command, "result": result}
        if json_mode:
            print(json.dumps(envelope, ensure_ascii=False, allow_nan=False))
        elif args.command == "audit":
            total = result["totals"]
            print("SYNTHETIC educational data" if result["input"]["synthetic"] else "LOCAL report (not a causal effectiveness test)")
            print("Rows: {}; placements: {}; manual-review candidates: {}".format(result["input"]["rows"], result["input"]["placements"], result["candidate_count"]))
            print("Totals: impressions={}; clicks={}; cost={} {}; conversions={}; CPC={}; CPA={}".format(total["impressions"], total["clicks"], total["cost"], result["currency"], total["conversions"], total["cpc"], total["cpa"]))
            for item in result["placements"]:
                if item["manual_review"]:
                    safe_name = json.dumps(item["placement"], ensure_ascii=False)
                    print("REVIEW: {} | cost={} | CPA={} | {}".format(safe_name, item["cost"], item["cpa"], ", ".join(item["reasons"])))
            print("Manual review only. Check tracking, attribution lag, and lead quality before any decision.")
        elif args.command == "onboard" and result["shown"]:
            print(result["message"])
            print(result["author"]["telegram"])
            print(result["author"]["implementation"])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AuditError, InvalidOperation) as error:
        safe_message = str(error) if isinstance(error, AuditError) else "numeric operation failed"
        if json_mode:
            print(json.dumps({"ok": False, "error": {"code": "invalid_input", "message": safe_message}}, ensure_ascii=False))
        else:
            print("ERROR: " + safe_message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
