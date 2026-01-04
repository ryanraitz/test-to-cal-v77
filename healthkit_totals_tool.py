# healthkit_totals_tool.py (ANY-DAYS / FULL-SPAN VERSION)
# PyQt5 HealthKit Totals dialog — REAL HEALTHKIT EXPORTS (row-based) + wide CSV fallback
#
# Updated: accepts as many CSV days as provided (no fixed 7/30-day window).
# Period is determined by the CSV's date span (first day -> last day).
#
# Output highlights:
# - Period: mm/dd/YYYY - mm/dd/YYYY
# - Days logged: [days present]/[expected days in span]
# - Day 1..Day N rows for every logged day (N = days present), with math:
#     Day X: Daily Caloric Goal - Active Energy = diff calories
#     CUT + diff < 0  => "(over your calorie goal)"
#     BULK + diff > 0 => "(under your calorie goal)"
# - Days without logs: expected_days - days_present
# - Protein goal achieved: x/expected_days (x counted only from days present)
# - Calorie goal achieved: x/expected_days (CUT: active <= goal, BULK: active >= goal)

import json
import csv
import re
from pathlib import Path
from datetime import datetime, date, timedelta

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QTextEdit, QMessageBox
)

# -----------------------------
# Utilities
# -----------------------------

def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0


def _parse_date(val):
    """Extract YYYY-MM-DD from a string (HealthKit exports usually contain it)."""
    if not val:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(val))
    if not m:
        return None
    y, mth, d = m.group(1).split("-")
    return date(int(y), int(mth), int(d))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_daily_calorie_goal(report_json: dict):
    """Best-effort extraction of DAILY calorie goal from your report json."""
    if not isinstance(report_json, dict):
        return None

    tokens = report_json.get("tokens", {}) or {}
    # common token names across variants
    for key in ("DAILY_CAL_GOAL", "DAILY_CALORIE_GOAL", "CALORIES", "CICO"):
        if key in tokens:
            val = _num(tokens[key])
            if val:
                return val

    # try bars-style storage
    bars = report_json.get("bars", {}) or {}
    labels = bars.get("labels")
    curr = bars.get("curr")
    try:
        if isinstance(labels, list) and isinstance(curr, list) and len(labels) == len(curr):
            norm = [str(x).strip().lower() for x in labels]
            for key in ("daily calorie goal", "daily cal goal", "calorie goal", "cico"):
                if key in norm:
                    i = norm.index(key)
                    val = _num(curr[i])
                    if val:
                        return val
    except Exception:
        pass

    return None


def _extract_daily_protein_goal(report_json: dict):
    """
    Canonical source (per Ryan): tokens["ROW_1_VALUE"] (e.g., "180 g" or "180").
    """
    try:
        toks = report_json.get("tokens") or {}
        row1 = toks.get("ROW_1_VALUE")

        # some pipelines may nest tokens
        if row1 is None:
            rd = report_json.get("REPORT_DATA") or report_json.get("report_data") or {}
            toks2 = rd.get("tokens") or {}
            row1 = toks2.get("ROW_1_VALUE")

        if row1 is not None:
            s = str(row1).strip().lower()
            m = re.search(r"(-?\d+(?:\.\d+)?)", s)
            if m:
                val = float(m.group(1))
                if val > 0:
                    return val
    except Exception:
        pass
    return None


def _extract_header_chip_1(report_json: dict):
    """HEADER_CHIP_1 typically holds CUT/BULK."""
    try:
        toks = report_json.get("tokens") or {}
        v = toks.get("HEADER_CHIP_1")
        if v is None:
            rd = report_json.get("REPORT_DATA") or report_json.get("report_data") or {}
            toks2 = rd.get("tokens") or {}
            v = toks2.get("HEADER_CHIP_1")
        if v is None:
            return None
        v = str(v).strip().upper()
        return v or None
    except Exception:
        return None


def _load_report_json(report_path_like):
    """
    Given:
      - path to last_report.json, or
      - client folder, or
      - any report json
    returns parsed JSON.
    Priority:
      - directory: latest_report.json then last_report.json
      - file: if last_report.json -> use it; else prefer sibling latest_report.json
    """
    if not report_path_like:
        return None

    try:
        rp = Path(str(report_path_like))
    except Exception:
        return None

    if rp.exists() and rp.is_dir():
        latest = rp / "latest_report.json"
        last = rp / "last_report.json"
        if latest.exists():
            return _read_json(latest)
        if last.exists():
            return _read_json(last)
        return None

    if rp.exists() and rp.is_file():
        if rp.name.lower() == "last_report.json":
            return _read_json(rp)
        latest = rp.parent / "latest_report.json"
        if latest.exists():
            return _read_json(latest)
        return _read_json(rp)

    return None


# -----------------------------
# HealthKit CSV Parsing
# -----------------------------

TYPE_MAP = {
    # Steps
    "step count": "steps",
    "steps": "steps",

    # Active energy (what we use for the daily goal math)
    "active energy (kcal)": "active",
    "active energy": "active",

    # Dietary calories (optional)
    "dietary energy": "cal",
    "dietary energy (kcal)": "cal",
    "dietary energy (cal)": "cal",

    # Macros
    "dietary protein": "pro",
    "dietary protein (g)": "pro",

    "dietary carbohydrates": "carb",
    "dietary carbohydrates (g)": "carb",

    "dietary fat": "fat",
    "dietary fat total": "fat",
    "dietary fat total (g)": "fat",
}


def compute_totals(csv_path: Path):
    """
    Supports:
      - HealthKit row-based exports (Start Date, Type, Value)
      - Wide daily totals (Calories, Protein (g), Carbs (g), Fat (g), Steps)
    Returns totals + per-day dicts + span metadata.
    """
    with csv_path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no rows")

    is_healthkit = ("Type" in rows[0]) and ("Value" in rows[0])

    day_data = {}  # date -> dict (aggregated)

    for r in rows:
        d = None
        for k in ("Start Date", "Date", "Day", "date"):
            if k in r:
                d = _parse_date(r.get(k))
                if d:
                    break
        if not d:
            continue

        day = day_data.setdefault(d, {"cal": 0.0, "pro": 0.0, "carb": 0.0, "fat": 0.0, "steps": 0.0, "active": 0.0})

        if is_healthkit:
            typ = str(r.get("Type", "") or "").strip().lower()
            val = _num(r.get("Value"))
            key = TYPE_MAP.get(typ)
            if key:
                day[key] += val
        else:
            for col, key in [
                ("Calories", "cal"),
                ("Protein (g)", "pro"),
                ("Carbs (g)", "carb"),
                ("Fat (g)", "fat"),
                ("Steps", "steps"),
                ("Active Energy (calories)", "active"),
                ("Active Energy", "active"),
            ]:
                if col in r:
                    day[key] += _num(r.get(col))

    if not day_data:
        raise ValueError("No usable rows found (no valid dates/types)")

    dates = sorted(day_data.keys())
    start_day = dates[0]
    end_day = dates[-1]
    expected_days = (end_day - start_day).days + 1
    days_present = len(dates)
    days_missed = max(0, expected_days - days_present)

    # missing dates list across span
    present_set = set(dates)
    missing = []
    cur = start_day
    while cur <= end_day:
        if cur not in present_set:
            missing.append(cur.isoformat())
        cur = cur + timedelta(days=1)

    return {
        "calories": sum(v["cal"] for v in day_data.values()),
        "active_energy": sum(v.get("active", 0.0) for v in day_data.values()),
        "protein": sum(v["pro"] for v in day_data.values()),
        "carbs": sum(v["carb"] for v in day_data.values()),
        "fat": sum(v["fat"] for v in day_data.values()),
        "steps": sum(v["steps"] for v in day_data.values()),
        "day_protein_by_date": {d.isoformat(): day_data[d]["pro"] for d in dates},
        "day_active_by_date": {d.isoformat(): day_data[d].get("active", 0.0) for d in dates},
        "dates": [d.isoformat() for d in dates],
        "start_day": start_day.isoformat(),
        "end_day": end_day.isoformat(),
        "expected_days": expected_days,
        "days_present": days_present,
        "days_missed": days_missed,
        "missing_dates": missing,
    }


# -----------------------------
# Dialog
# -----------------------------

class HealthkitTotalsDialog(QDialog):
    def __init__(self, parent=None, on_result=None, selected_prev_report_path=None, prev_report_path=None, **kwargs):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle("HealthKit Totals")
        self.resize(560, 540)

        report_hint = selected_prev_report_path or prev_report_path or getattr(parent, "selected_prev_report_path", None)
        report_json = _load_report_json(report_hint)

        self.header_chip_1 = _extract_header_chip_1(report_json) if report_json else None
        self.daily_calorie_goal = _extract_daily_calorie_goal(report_json) if report_json else None
        self.daily_protein_goal = _extract_daily_protein_goal(report_json) if report_json else None

        self.csv_path = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        if self.daily_calorie_goal is not None:
            header = QLabel(f"<b>Daily Calorie Goal:</b> {int(self.daily_calorie_goal):,} calories")
        else:
            header = QLabel("<i>Daily Calorie Goal: —</i>")
        layout.addWidget(header)

        if self.daily_protein_goal is not None:
            pheader = QLabel(f"<b>Daily Protein Goal:</b> {int(self.daily_protein_goal):,} g")
        else:
            pheader = QLabel("<i>Daily Protein Goal: —</i>")
        layout.addWidget(pheader)

        browse_btn = QPushButton("Select HealthKit CSV")
        browse_btn.clicked.connect(self._browse)
        layout.addWidget(browse_btn)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        run_btn = QPushButton("Compute Totals")
        run_btn.clicked.connect(self._run)
        layout.addWidget(run_btn)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select HealthKit CSV", "", "CSV Files (*.csv)")
        if path:
            self.csv_path = Path(path)
            self.output.append(f"Loaded CSV: {self.csv_path.name}")

    def _run(self):
        if not self.csv_path or not self.csv_path.exists():
            QMessageBox.warning(self, "Error", "Please select a valid CSV file")
            return

        try:
            totals = compute_totals(self.csv_path)
        except Exception as e:
            QMessageBox.critical(self, "HealthKit Parse Error", str(e))
            return

        lines = []
        lines.append("=== HealthKit Totals ===")

        # Period (CSV span)
        try:
            sdt = datetime.strptime(totals["start_day"], "%Y-%m-%d").strftime("%m/%d/%Y")
            edt = datetime.strptime(totals["end_day"], "%Y-%m-%d").strftime("%m/%d/%Y")
            lines.append(f"Period: {sdt} - {edt}")
        except Exception:
            lines.append("Period: —")

        chip = (getattr(self, "header_chip_1", None) or "").strip().upper()
        if chip:
            lines.append(f"Plan: {chip.title() if chip in ('CUT','BULK') else chip}")
        else:
            lines.append("Plan: —")

        expected_days = int(totals.get("expected_days", 0) or 0)
        days_present = int(totals.get("days_present", 0) or 0)
        days_missed = int(totals.get("days_missed", 0) or 0)

        lines.append(f"Days logged: {days_present}/{expected_days if expected_days else days_present}")
        lines.append("")

        # Day-by-day rows (for every logged day)
        if self.daily_calorie_goal is not None:
            try:
                goal = float(self.daily_calorie_goal)
                day_active = totals.get("day_active_by_date", {}) or {}
                dates_present = totals.get("dates", []) or []

                for idx, dk in enumerate(dates_present, start=1):
                    active = _num(day_active.get(dk, 0))
                    diff = active - goal  # ACTUAL - GOAL (surplus positive, deficit negative)
                    msg = f"Day {idx}: {active:,.0f} - {goal:,.0f} = {diff:+,.0f} calories"
                    if chip == "CUT" and diff > 0:
                        msg += " (over your calorie goal)"
                    elif chip == "BULK" and diff < 0:
                        msg += " (under your calorie goal)"
                    lines.append(msg)
            except Exception:
                pass


        # Overall caloric balance across the entire CSV span
        if self.daily_calorie_goal is not None and expected_days:
            try:
                goal = float(self.daily_calorie_goal)
                day_active = totals.get("day_active_by_date", {}) or {}
                total_active = 0.0
                for dk in (totals.get("dates", []) or []):
                    total_active += _num(day_active.get(dk, 0))

                total_goal = goal * expected_days
                balance = total_active - total_goal  # ACTUAL - GOAL (surplus positive, deficit negative)

                suffix = ""
                if chip == "CUT" and balance > 0:
                    suffix = " (over your calorie goal)"
                elif chip == "BULK" and balance < 0:
                    suffix = " (under your calorie goal)"

                label = ""
                if balance < 0:
                    label = " (deficit)"
                elif balance > 0:
                    label = " (surplus)"
                lines.append(
                    f"Overall caloric balance: {total_active:,.0f} (total actual calories) - {total_goal:,.0f} (total goal calories) = {balance:+,.0f} calories{label}{suffix}"
                )
            except Exception:
                pass

        lines.append(f"Days without logs: {days_missed}")

        missing = totals.get("missing_dates") or []
        if missing:
            lines.append("Missing dates: " + ", ".join(missing))

        # Protein goal achieved (denominator = expected days in span)
        if self.daily_protein_goal is not None and expected_days:
            try:
                day_pro = totals.get("day_protein_by_date", {}) or {}
                achieved = 0
                for dk in (totals.get("dates", []) or []):
                    grams = _num(day_pro.get(dk, 0))
                    if grams >= float(self.daily_protein_goal):
                        achieved += 1
                lines.append(f"Protein goal achieved: {achieved}/{expected_days} days")
            except Exception:
                pass

        # Calorie goal achieved (denominator = expected days in span)
        if self.daily_calorie_goal is not None and expected_days:
            try:
                day_active = totals.get("day_active_by_date", {}) or {}
                met = 0
                goal = float(self.daily_calorie_goal)

                for dk in (totals.get("dates", []) or []):
                    active = _num(day_active.get(dk, 0))
                    if chip == "BULK":
                        if active >= goal:
                            met += 1
                    elif chip == "CUT":
                        if active <= goal:
                            met += 1

                lines.append(f"Calorie goal achieved: {met}/{expected_days} days")
            except Exception:
                pass

        text = "\n".join(lines) + "\n"
        self.output.append(text)
        if self.on_result:
            self.on_result(text + "\n")
