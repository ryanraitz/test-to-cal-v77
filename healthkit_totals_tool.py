from datetime import datetime, timedelta
# healthkit_totals_tool.py
# PyQt5 HealthKit Totals dialog — REAL HEALTHKIT EXPORTS (row-based) + wide CSV fallback
#
# Features:
# - Reads client's DAILY calorie goal (weekly goal = daily * 7) from last_report.json (or latest_report.json if that's what you pass)
# - Reads client's DAILY protein goal (grams) from last_report.json (robust, searches for macroBars.labels/curr with "protein")
# - Parses HealthKit CSV exports (Start Date | Type | Value) and aggregates multiple rows per day
# - Computes missing-days (HealthKit omits days with no entries): days_present, expected_days, missing_dates, days_missed
# - Displays:
#     Calories Minus Weekly Goal: (weekly calories - weekly goal)
#     Protein goal achieved: x/7 days (calendar-based last 7 days; missing days count as 0g)

import json
import csv
import re
from pathlib import Path
from datetime import date

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


def _find_in_tree(obj, predicate, max_nodes=50000):
    """Depth-first search over nested dict/list structures; returns first node where predicate(node) is True."""
    stack = [obj]
    seen = 0
    while stack:
        node = stack.pop()
        seen += 1
        if seen > max_nodes:
            break
        try:
            if predicate(node):
                return node
        except Exception:
            pass

        if isinstance(node, dict):
            for v in node.values():
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(node, list):
            for v in node:
                if isinstance(v, (dict, list)):
                    stack.append(v)
    return None


def _extract_daily_calorie_goal(report_json: dict):
    """Best-effort extraction of DAILY calorie goal from your v77 report json."""
    if not isinstance(report_json, dict):
        return None

    tokens = report_json.get("tokens", {}) or {}
    for key in ("DAILY_CAL_GOAL", "CALORIES", "CICO"):
        if key in tokens:
            val = _num(tokens[key])
            if val:
                return val

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
    Extract DAILY protein goal (grams) from last_report/latest_report JSON.

    Canonical source (per Ryan): tokens["ROW_1_VALUE"] (e.g., "180 g" or "180").

    Falls back to prior robust heuristics if that token isn't present.
    """
    try:
        # Primary: tokens.ROW_1_VALUE
        toks = report_json.get("tokens") or {}
        row1 = toks.get("ROW_1_VALUE")
        if row1 is None:
            # Sometimes nested
            rd = report_json.get("REPORT_DATA") or report_json.get("report_data") or {}
            toks2 = rd.get("tokens") or {}
            row1 = toks2.get("ROW_1_VALUE")

        if row1 is not None:
            # Accept "180", "180g", "180 g", "180 grams"
            s = str(row1).strip().lower()
            m = re.search(r"(-?\d+(?:\.\d+)?)", s)
            if m:
                val = float(m.group(1))
                if val > 0:
                    return val

        # ---- Fallbacks (keep old behavior as backup) ----
        # Common direct keys
        for key in ("DAILY_PROTEIN_GOAL", "PROTEIN_GOAL", "PROTEIN_G", "PROTEIN"):
            if key in report_json and report_json[key] is not None:
                try:
                    return float(report_json[key])
                except Exception:
                    pass

        # macroBars: labels + curr
        mb = report_json.get("macroBars") or {}
        labels = (mb.get("labels") or [])
        curr = (mb.get("curr") or [])
        for i, lab in enumerate(labels):
            if str(lab).strip().lower() == "protein" and i < len(curr):
                try:
                    return float(curr[i])
                except Exception:
                    pass

        # macroBars.bars: [{"label":"Protein","curr":...}]
        bars = mb.get("bars") or []
        for b in bars:
            if str(b.get("label","")).strip().lower() == "protein":
                try:
                    return float(b.get("curr"))
                except Exception:
                    pass

    except Exception:
        pass
    return None

def _load_report_json(report_path_like):
    """
    Given:
      - a path to last_report.json (file), OR
      - a client folder, OR
      - a path to any report json
    returns parsed JSON.
    Priority:
      - if file == last_report.json -> use it
      - else if sibling latest_report.json exists -> use that
      - else use the file itself
      - if directory -> prefer latest_report.json then last_report.json
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

    # Calories
    "active energy (kcal)": "active",
    "active energy": "active",
    "dietary energy": "cal",
    "dietary energy (kcal)": "cal",
    "dietary energy (cal)": "cal",

    # Macros
    "dietary protein": "pro",
    "dietary protein (g)": "pro",
    "protein": "pro",

    "dietary carbohydrates": "carb",
    "dietary carbohydrates (g)": "carb",
    "carbohydrates": "carb",
    "carbs": "carb",

    "dietary fat": "fat",
    "dietary fat total": "fat",
    "dietary fat total (g)": "fat",
    "fat": "fat",
}


def compute_totals(csv_path: Path):
    """
    Supports:
      - HealthKit row-based exports (Start Date, Type, Value)
      - Wide daily totals (Calories, Protein (g), Carbs (g), Fat (g), Steps)
    Returns totals + per-day protein dict + missing-days metadata.
    """
    with csv_path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV contains no rows")

    is_healthkit = ("Type" in rows[0]) and ("Value" in rows[0])

    day_data = {}  # date -> dict

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
            ]:
                if col in r:
                    day[key] += _num(r.get(col))

    if not day_data:
        raise ValueError("No usable HealthKit rows found")

    dates = sorted(day_data)
    days_present = len(dates)
    expected_days = (dates[-1] - dates[0]).days + 1
    days_missed = max(expected_days - days_present, 0)

    # explicit missing dates list
    missing_dates = []
    present_set = {d for d in dates}
    cur = dates[0]
    while cur <= dates[-1]:
        if cur not in present_set:
            missing_dates.append(cur.isoformat())
        cur = cur.fromordinal(cur.toordinal() + 1)

    return {
        "period": ("WEEKLY" if days_present == 7 else "MONTHLY" if days_present in (30, 31) else f"CUSTOM ({days_present} days)"),
        "days_present": days_present,
        "expected_days": expected_days,
        "missing_dates": missing_dates,
        "days_missed": days_missed,
        "calories": sum(v["cal"] for v in day_data.values()),
        "active_energy": sum(v.get("active", 0.0) for v in day_data.values()),
        "protein": sum(v["pro"] for v in day_data.values()),
        "carbs": sum(v["carb"] for v in day_data.values()),
        "fat": sum(v["fat"] for v in day_data.values()),
        "steps": sum(v["steps"] for v in day_data.values()),
        "day_protein_by_date": {d.isoformat(): day_data[d]["pro"] for d in day_data},
        "day_cal_by_date": {d.isoformat(): day_data[d]["cal"] for d in day_data},
        "day_active_by_date": {d.isoformat(): day_data[d].get("active", 0.0) for d in day_data},
        "dates": [d.isoformat() for d in dates],
    }


# -----------------------------
# Dialog
# -----------------------------

class HealthkitTotalsDialog(QDialog):
    def __init__(self, parent=None, on_result=None, selected_prev_report_path=None, prev_report_path=None, **kwargs):
        super().__init__(parent)
        self.on_result = on_result
        self.setWindowTitle("HealthKit Totals")
        self.resize(520, 460)

        report_hint = selected_prev_report_path or prev_report_path or getattr(parent, "selected_prev_report_path", None)
        report_json = _load_report_json(report_hint)
        self.header_chip_1 = _extract_header_chip_1(report_json) if report_json else None

        daily_cal = _extract_daily_calorie_goal(report_json) if report_json else None
        daily_pro = _extract_daily_protein_goal(report_json) if report_json else None

        self.daily_calorie_goal = daily_cal
        self.weekly_goal = daily_cal * 7 if daily_cal else None
        self.daily_protein_goal = daily_pro  # grams

        sw, gw = _extract_weights(report_json) if report_json else (None, None)
        self.start_weight = sw
        self.goal_weight = gw
        self.phase = None
        if sw is not None and gw is not None:
            delta = sw - gw
            if delta > 0:
                self.phase = "Cut"
            elif delta < 0:
                self.phase = "Bulk"
            else:
                self.phase = "Maintenance"
        self.csv_path = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        if self.weekly_goal is not None:
            header = QLabel(f"<b>Weekly Calorie Goal:</b> {int(self.weekly_goal):,} kcal")
        else:
            header = QLabel("<i>Weekly Calorie Goal: —</i>")
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
        # Period display as mm/dd - mm/dd (7 days ago to today)
        try:
            today = datetime.now()
            start = (today - timedelta(days=7)).strftime("%m/%d")
            end = today.strftime("%m/%d")
            lines.append(f"Period: {start} - {end}")
        except Exception:
            lines.append("Period: —")
# Plan (from last_report.json tokens.HEADER_CHIP_1)
        chip = (getattr(self, "header_chip_1", None) or "").strip().upper()
        if chip in ("CUT", "BULK"):
            lines.append(f"Plan: {chip.title()}")
        elif chip:
            lines.append(f"Plan: {chip}")
        else:
            lines.append("Plan: —")
        lines.append(f"Days logged: {int(totals.get('days_present', 0) or 0)}/7")

        # Day-by-day: Daily Caloric Goal - Active Energy (kcal) (per CSV day)
        # Creates one row per logged day in the (up to) last 7-day window.
        # If Plan is CUT and the diff is negative, append " over".
        if self.daily_calorie_goal is not None:
            try:
                goal = float(self.daily_calorie_goal)
                day_active = totals.get("day_active_by_date", {}) or {}
                dates_present = totals.get("dates", []) or []
                last7 = dates_present[-7:] if len(dates_present) >= 7 else dates_present
        
                plan = (getattr(self, "header_chip_1", None) or "").strip().upper()  # CUT/BULK
        
                for idx, dk in enumerate(last7):
                    label = f"Day {idx+1}:"
                    active = _num(day_active.get(dk, 0))
                    diff = active - goal
                    suffix = (" calorie surplus" if (plan == "CUT" and diff > 0) else (" calorie deficit" if diff < 0 else ""))
                    lines.append(f"{label} {active:.0f} - {goal:.0f} = {diff:.0f}{suffix}")
            except Exception:
                pass
        
        lines.append(f"Days without logs: {max(0, 7 - int(totals.get('days_present', 0) or 0))}")

        missing = totals.get("missing_dates") or []
        if missing:
            lines.append("Missing dates: " + ", ".join(missing))
        # Weekly calories: prefer Dietary Energy (kcal) if present, otherwise fall back to Active Energy (kcal)
        weekly_cal = float(totals.get("calories", 0) or 0)
        weekly_active = float(totals.get("active_energy", 0) or 0)
        weekly_cal_display = weekly_cal if weekly_cal > 0 else weekly_active

        # Total weekly calorie balance: sum(Active Energy) - sum(Daily Calorie Goal)
        try:
            day_active = totals.get("day_active_by_date", {}) or {}
            dates_present = totals.get("dates", []) or []
            last7 = dates_present[-7:] if len(dates_present) >= 7 else dates_present

            total_active = 0.0
            total_goal = 0.0
            goal = float(self.daily_calorie_goal)

            for dk in last7:
                total_active += _num(day_active.get(dk, 0))
                total_goal += goal

            weekly_balance = total_active - total_goal

            suffix = ""
            plan = (getattr(self, "header_chip_1", None) or "").strip().upper()
            if weekly_balance > 0 and plan == "CUT":
                suffix = " calorie surplus"
            elif weekly_balance < 0:
                suffix = " calorie deficit"

            lines.append(f"Total weekly calorie balance: {total_active:.0f} - {total_goal:.0f} = {weekly_balance:.0f}{suffix}")
        except Exception:
            pass

        
        # Protein goal achieved: x/7 days (x counts only days present in the CSV; denominator always 7)
        if self.daily_protein_goal is not None:
            try:
                day_pro = totals.get("day_protein_by_date", {}) or {}
                dates_present = totals.get("dates", []) or []
                achieved = 0
                denom = 7

                # Compare only the days that exist in the CSV (HealthKit omits unlogged days)
                last7_present = dates_present[-7:] if len(dates_present) >= 7 else dates_present
                for dk in last7_present:
                    grams = _num(day_pro.get(dk, 0))
                    if grams >= float(self.daily_protein_goal):
                        achieved += 1

                lines.append(f"Protein goal achieved: {achieved}/{denom} days")
            except Exception:
                pass



        # Calorie goal achieved: x/7 days using Active Energy (kcal) vs Daily Calorie Goal,
        # direction depends on HEADER_CHIP_1 (CUT/BULK) from last_report.json tokens.
        if self.daily_calorie_goal is not None:
            try:
                day_active = totals.get("day_active_by_date", {}) or {}
                dates_present = totals.get("dates", []) or []
                met_days = 0
                denom = 7
                goal = float(self.daily_calorie_goal)

                chip = (getattr(self, "header_chip_1", None) or "").strip().upper()
                last7_present = dates_present[-7:] if len(dates_present) >= 7 else dates_present
                for dk in last7_present:
                    active = _num(day_active.get(dk, 0))
                    if chip == "BULK":
                        # BULK: Active Energy must be >= goal to count
                        if active >= goal:
                            met_days += 1
                    elif chip == "CUT":
                        # CUT: Active Energy must be <= goal to count
                        if active <= goal:
                            met_days += 1
                    else:
                        # If chip missing/unknown, don't count (keeps it strict)
                        pass

                lines.append(f"Calorie goal achieved: {met_days}/{denom} days")
            except Exception:
                pass

        text = "\n".join(lines) + "\n"
        self.output.append(text)
        if self.on_result:
            self.on_result(text + "\n")



def _extract_header_chip_1(report_json: dict):
    """Return normalized HEADER_CHIP_1 token string (e.g., 'CUT' or 'BULK') or None."""
    try:
        toks = report_json.get("tokens") or {}
        v = toks.get("HEADER_CHIP_1")
        if v is None:
            # fallback: sometimes tokens nested under REPORT_DATA
            rd = report_json.get("REPORT_DATA") or report_json.get("report_data") or {}
            toks2 = rd.get("tokens") or {}
            v = toks2.get("HEADER_CHIP_1")
        if v is None:
            return None
        v = str(v).strip().upper()
        if v in ("CUT", "BULK", "MAINTENANCE"):
            return v
        return v or None
    except Exception:
        return None


def _extract_weights(report_json: dict):
    """Return (start_weight, goal_weight) floats when present; else (None, None)."""
    if not isinstance(report_json, dict):
        return None, None
    # Common top-level keys
    for sk, gk in (("startWeight", "goalWeight"), ("start_weight", "goal_weight"), ("START_WEIGHT", "GOAL_WEIGHT")):
        if sk in report_json and gk in report_json:
            sw = _num(report_json.get(sk))
            gw = _num(report_json.get(gk))
            return (sw, gw)
    # Sometimes stored in tokens
    tokens = report_json.get("tokens", {}) or {}
    for sk, gk in (("START_WEIGHT", "GOAL_WEIGHT"), ("START_WT", "GOAL_WT"), ("START", "GOAL")):
        if sk in tokens and gk in tokens:
            sw = _num(tokens.get(sk))
            gw = _num(tokens.get(gk))
            return (sw, gw)
    return None, None

