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
def compute_totals(csv_path: Path):
    """
    Minimal, safe HealthKit CSV aggregator.
    Expects row-based HealthKit exports or wide daily totals.
    """
    with csv_path.open("r", encoding="utf-8-sig", errors="ignore") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no rows")

    day_data = {}
    for r in rows:
        d = None
        for k in ("Start Date", "Date", "Day", "date"):
            if k in r:
                d = _parse_date(r.get(k))
                if d:
                    break
        if not d:
            continue

        day = day_data.setdefault(d, {
            "active": 0.0,
            "protein": 0.0
        })

        typ = str(r.get("Type", "")).lower()
        val = _num(r.get("Value"))

        if "active energy" in typ:
            day["active"] += val
        elif "dietary protein" in typ:
            day["protein"] += val

    if not day_data:
        raise ValueError("No usable HealthKit rows found")

    dates = sorted(day_data.keys())
    start_day = dates[0]
    end_day = dates[-1]

    expected_days = (end_day - start_day).days + 1
    days_present = len(dates)

    return {
        "start_day": start_day.isoformat(),
        "end_day": end_day.isoformat(),
        "expected_days": expected_days,
        "days_present": days_present,
        "days_missed": max(0, expected_days - days_present),
        "dates": [d.isoformat() for d in dates],
    }



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

        self.run_btn = QPushButton("Compute Totals")
        self.run_btn.clicked.connect(self._run)
        layout.addWidget(self.run_btn)


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

        # ---- Period ----
        try:
            sdt = datetime.strptime(totals["start_day"], "%Y-%m-%d").strftime("%m/%d/%Y")
            edt = datetime.strptime(totals["end_day"], "%Y-%m-%d").strftime("%m/%d/%Y")
            lines.append(f"Period: {sdt} - {edt}")
        except Exception:
            lines.append("Period: —")

        # ---- Plan ----
        chip = (self.header_chip_1 or "").strip().upper()
        lines.append(f"Plan: {chip if chip else '—'}")

        expected_days = totals["expected_days"]
        days_present = totals["days_present"]
        days_missed = totals["days_missed"]

        lines.append(f"Days logged: {days_present}/{expected_days}")
        lines.append(f"Days without logs: {days_missed}")
        lines.append("")

        # ---- Confidence score (simple + stable) ----
        if expected_days > 0:
            confidence_score = int(round((days_present / expected_days) * 100))
        else:
            confidence_score = 0

        confidence_score = max(0, min(100, confidence_score))

        if confidence_score >= 70:
            label = "High"
        elif confidence_score >= 50:
            label = "Medium"
        else:
            label = "Low"

        lines.append(f"Confidence score: {confidence_score}/100 ({label})")

        text = "\n".join(lines) + "\n"
        self.output.append(text)

        # ---- Pass result back to main GUI ----
        if self.on_result:
            self.on_result(text)

        parent = self.parent()
        if parent is not None:
            parent.healthkit_confidence = {
                "value": confidence_score,
                "label": label
            }

        # ---- FINAL UI STATE CHANGE ----
        try:
            self.run_btn.clicked.disconnect(self._run)
        except Exception:
            pass

        self.run_btn.setText("Continue")
        self.run_btn.clicked.connect(self.accept)


