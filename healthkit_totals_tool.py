
# healthkit_totals_tool.py
# PyQt5 HealthKit Totals dialog — FIXED FOR REAL HEALTHKIT EXPORTS
#
# Handles BOTH formats:
# 1) Wide CSVs (Calories, Protein (g), etc. as columns)
# 2) TRUE HealthKit CSVs (Start Date | Type | Value)

import json
import csv
import re
from pathlib import Path
from datetime import date

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt


# -----------------------------
# Utilities
# -----------------------------

def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0


def _extract_daily_calorie_goal(report_path: Path):
    if not report_path or not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    tokens = data.get("tokens", {})
    for key in ("DAILY_CAL_GOAL", "CALORIES", "CICO"):
        if key in tokens:
            return _num(tokens[key])

    bars = data.get("bars", {})
    curr = bars.get("curr")
    if isinstance(curr, list):
        nums = [_num(v) for v in curr]
        return max(nums) if nums else None

    return None


# -----------------------------
# HealthKit CSV Parsing
# -----------------------------

TYPE_MAP = {
    "Step Count": "steps",
    "Active Energy (kcal)": "cal",
    "Dietary Protein": "pro",
    "Dietary Carbohydrates": "carb",
    "Dietary Fat": "fat",
}


def _parse_date(val):
    if not val:
        return None
    m = re.search(r"(\d{4}-\d{2}-\d{2})", str(val))
    if not m:
        return None
    y, mth, d = m.group(1).split("-")
    return date(int(y), int(mth), int(d))


def compute_totals(csv_path: Path):
    with csv_path.open("r", encoding="utf-8-sig", errors="ignore") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no rows")

    # Detect HealthKit-style (Type/Value) vs wide format
    is_healthkit = "Type" in rows[0] and "Value" in rows[0]

    day_data = {}

    for r in rows:
        # ---- Date ----
        d = None
        for k in ("Start Date", "Date", "Day", "date"):
            if k in r:
                d = _parse_date(r.get(k))
                if d:
                    break
        if not d:
            continue

        day = day_data.setdefault(d, {
            "cal": 0, "pro": 0, "carb": 0, "fat": 0, "steps": 0
        })

        # ---- HealthKit format ----
        if is_healthkit:
            typ = r.get("Type", "")
            val = _num(r.get("Value"))
            key = TYPE_MAP.get(typ)
            if key:
                day[key] += val

        # ---- Wide format fallback ----
        else:
            for col, key in [
                ("Calories", "cal"),
                ("Protein (g)", "pro"),
                ("Carbs (g)", "carb"),
                ("Fat (g)", "fat"),
                ("Steps", "steps"),
            ]:
                if col in r:
                    day[key] += _num(r[col])

    if not day_data:
        raise ValueError("No usable HealthKit rows found")

    dates = sorted(day_data)
    days_present = len(dates)
    expected_days = (dates[-1] - dates[0]).days + 1
    days_missed = max(expected_days - days_present, 0)

    return {
        "period": (
            "WEEKLY" if days_present == 7 else
            "MONTHLY" if days_present in (30, 31) else
            f"CUSTOM ({days_present} days)"
        ),
        "days_missed": days_missed,
        "calories": sum(v["cal"] for v in day_data.values()),
        "protein": sum(v["pro"] for v in day_data.values()),
        "carbs": sum(v["carb"] for v in day_data.values()),
        "fat": sum(v["fat"] for v in day_data.values()),
        "steps": sum(v["steps"] for v in day_data.values()),
    }


# -----------------------------
# Dialog
# -----------------------------

class HealthkitTotalsDialog(QDialog):
    def __init__(self, parent=None, on_result=None):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle("HealthKit Totals")
        self.resize(520, 420)

        daily_goal = None
        report_path = getattr(parent, "selected_prev_report_path", None)
        if report_path:
            daily_goal = _extract_daily_calorie_goal(Path(report_path))

        self.weekly_goal = daily_goal * 7 if daily_goal else None
        self.csv_path = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        if self.weekly_goal:
            header = QLabel(f"<b>Weekly Calorie Goal:</b> {int(self.weekly_goal):,} kcal")
        else:
            header = QLabel("<i>Weekly Calorie Goal: —</i>")
        layout.addWidget(header)

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
        path, _ = QFileDialog.getOpenFileName(
            self, "Select HealthKit CSV", "", "CSV Files (*.csv)"
        )
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

        text = (
            f"=== HealthKit Totals ===\n"
            f"Period: {totals['period']}\n"
            f"Days missed: {totals['days_missed']}\n"
            f"Calories: {totals['calories']:.0f}\n"
            f"Protein (g): {totals['protein']:.0f}\n"
            f"Carbs (g): {totals['carbs']:.0f}\n"
            f"Fat (g): {totals['fat']:.0f}\n"
            f"Steps: {totals['steps']:.0f}\n"
        )

        self.output.append(text)
        if self.on_result:
            self.on_result(text + "\n")
