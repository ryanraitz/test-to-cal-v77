#!/usr/bin/env python3
# randomtest.py
#
# Two-run GUI automation for dietCalculator.py, then prints ONLY:
#   Prev + Curr Protein/Carbs/Fats (grams) extracted from JSON artifacts on disk.
#
# Run:
#   /Users/ryanraitz/.pyenv/versions/3.7.2/bin/python /Users/ryanraitz/Library/test-to-cal-v77/randomtest.py

import sys
import time
import random
import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ---------- Qt import (tries multiple bindings) ----------
QT_BINDING = None
QtCore = QtWidgets = QtGui = QTest = None

def _import_qt():
    global QT_BINDING, QtCore, QtWidgets, QtGui, QTest
    tried = []
    for binding in ("PyQt5", "PyQt6", "PySide6"):
        try:
            if binding == "PyQt5":
                from PyQt5 import QtCore, QtWidgets, QtGui
                from PyQt5.QtTest import QTest
            elif binding == "PyQt6":
                from PyQt6 import QtCore, QtWidgets, QtGui
                from PyQt6.QtTest import QTest
            else:
                from PySide6 import QtCore, QtWidgets, QtGui
                from PySide6.QtTest import QTest
            QT_BINDING = binding
            return
        except Exception as e:
            tried.append((binding, str(e)))
    raise RuntimeError(
        "Could not import PyQt5/PyQt6/PySide6.\nTried:\n"
        + "\n".join([f"- {b}: {err}" for b, err in tried])
    )

_import_qt()

# ---------- Config ----------
PROJECT_ROOT = Path(__file__).resolve().parent
TARGET_CLIENT_NAME = "Ryan Raitz"
WINDOW_CLASS_CANDIDATES = ["DietCalculator", "MainWindow", "AppWindow", "Window"]

WATCH_PATHS = [
    PROJECT_ROOT / "reports" / "output" / "latest.html",
    PROJECT_ROOT / "reports" / "output",
    PROJECT_ROOT / "reports",
    PROJECT_ROOT / "Clients",
    PROJECT_ROOT / "clients",
]

BUTTON_TEXTS = {
    "clear": ["clear"],
    "calculate": ["calculate"],
    "generate": ["generate"],
}

# ---------- Data ----------
@dataclass
class RunData:
    client: str
    gender: str
    age: int
    height: str
    weight_lb: float
    steps: int
    sessions_per_week: int
    bodyfat_pct: Optional[float]
    pullups: int
    pushups: int
    goal_weight_change_lb: int


# ---------- Utilities ----------
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def clamp(n, lo, hi):
    return max(lo, min(hi, n))

def show_popup(title: str, text: str):
    msg = QtWidgets.QMessageBox()
    msg.setWindowTitle(title)
    msg.setTextFormat(QtCore.Qt.TextFormat.RichText)
    msg.setIcon(QtWidgets.QMessageBox.Icon.Information)
    msg.setText(text.replace("\n", "<br>"))
    msg.exec()

def click_button_by_text(window, wanted_substrings: List[str]) -> Optional[str]:
    wanted = [norm(w) for w in wanted_substrings]
    btns = window.findChildren(QtWidgets.QAbstractButton)
    matches = []
    for b in btns:
        try:
            t = norm(b.text())
        except Exception:
            continue
        if any(w in t for w in wanted):
            matches.append((len(t), b, t))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    _, btn, t = matches[0]
    QTest.mouseClick(btn, QtCore.Qt.MouseButton.LeftButton)
    QTest.qWait(250)
    return t

def set_lineedit(le: QtWidgets.QLineEdit, value: str):
    le.setFocus()
    le.selectAll()
    QTest.keyClicks(le, value)
    QTest.qWait(60)

def combo_items(cb: QtWidgets.QComboBox) -> List[str]:
    out = []
    try:
        for i in range(cb.count()):
            out.append(cb.itemText(i) or "")
    except Exception:
        pass
    return out

def set_combo_to_text(cb: QtWidgets.QComboBox, wanted: str) -> Tuple[bool, int]:
    w = norm(wanted)
    items = combo_items(cb)
    for i, txt in enumerate(items):
        if norm(txt) == w:
            cb.setCurrentIndex(i)
            QTest.qWait(120)
            return True, i
    for i, txt in enumerate(items):
        if w in norm(txt):
            cb.setCurrentIndex(i)
            QTest.qWait(120)
            return True, i
    if cb.isEditable():
        cb.setEditText(wanted)
        QTest.qWait(120)
        return True, cb.currentIndex()
    return False, -1

def wait_for_combo_item(cb: QtWidgets.QComboBox, wanted: str, timeout_ms: int = 9000) -> bool:
    w = norm(wanted)
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        items = [norm(x) for x in combo_items(cb)]
        if any(x == w or w in x for x in items):
            return True
        QTest.qWait(150)
    return False

def select_client_from_dropdown(window, client_name: str) -> Tuple[bool, str]:
    combos = window.findChildren(QtWidgets.QComboBox)
    if not combos:
        return False, "No QComboBox widgets found."

    target = norm(client_name)

    best_cb = None
    best_score = -1
    best_reason = ""

    for cb in combos:
        items = [norm(x) for x in combo_items(cb)]
        cur = norm(cb.currentText() or "")

        has_select = any("select client" in x for x in items) or ("select client" in cur)
        has_target = any(x == target or target in x for x in items)

        score = 0
        if has_select:
            score += 50
        if has_target:
            score += 200

        try:
            y = cb.mapToGlobal(cb.rect().center()).y()
            score += max(0, 60 - min(60, int(y / 20)))
        except Exception:
            pass

        if score > best_score:
            best_score = score
            best_cb = cb
            best_reason = f"score={score} has_select={has_select} has_target={has_target} current='{cb.currentText()}' first_items={combo_items(cb)[:4]}"

    if best_cb is None:
        return False, "Could not identify client dropdown."

    if not wait_for_combo_item(best_cb, client_name, timeout_ms=9000):
        return False, f"Client list never populated with '{client_name}'. {best_reason}"

    ok, idx = set_combo_to_text(best_cb, client_name)

    # Emit signals (some apps rely on these to load client data)
    QTest.qWait(150)
    try:
        best_cb.activated.emit(idx)  # type: ignore
    except Exception:
        pass
    try:
        best_cb.currentIndexChanged.emit(idx)  # type: ignore
    except Exception:
        pass
    try:
        best_cb.currentTextChanged.emit(best_cb.currentText())  # type: ignore
    except Exception:
        pass
    QTest.qWait(250)

    cur = best_cb.currentText() or ""
    ok2 = ok and (target == norm(cur) or target in norm(cur))
    return ok2, f"Selected '{client_name}' idx={idx} current='{cur}'. {best_reason}"

def find_lineedit_by_placeholder_contains(window, needle: str) -> Optional[QtWidgets.QLineEdit]:
    n = norm(needle)
    for le in window.findChildren(QtWidgets.QLineEdit):
        try:
            ph = norm(le.placeholderText() or "")
        except Exception:
            ph = ""
        if n and n in ph:
            return le
    return None

def fill_form(window, data: RunData) -> Dict[str, str]:
    set_map: Dict[str, str] = {}

    ok, details = select_client_from_dropdown(window, data.client)
    set_map["client_ok"] = str(ok)
    set_map["client_details"] = details
    if not ok:
        return set_map

    # Gender combo = combo with Male/Female, excluding client dropdown
    gender_cb = None
    for cb in window.findChildren(QtWidgets.QComboBox):
        items = [norm(x) for x in combo_items(cb)]
        cur = norm(cb.currentText() or "")
        if any("select client" in x for x in items) or ("select client" in cur):
            continue
        if any(x == "male" for x in items) and any(x == "female" for x in items):
            gender_cb = cb
            break
    if gender_cb:
        okg, _ = set_combo_to_text(gender_cb, data.gender)
        set_map["gender_ok"] = str(okg)

    # Age = first QLineEdit with empty placeholder
    age_le = None
    for le in window.findChildren(QtWidgets.QLineEdit):
        try:
            ph = (le.placeholderText() or "").strip()
        except Exception:
            ph = ""
        if ph == "":
            age_le = le
            break
    if age_le:
        set_lineedit(age_le, str(data.age))

    # Height by placeholder
    height_le = find_lineedit_by_placeholder_contains(window, "e.g. 5'3")
    if height_le:
        set_lineedit(height_le, data.height)

    # The next two empty-placeholder edits after height are typically: weight, steps
    edits = window.findChildren(QtWidgets.QLineEdit)
    def next_empty_after(widget, skip=None):
        if widget not in edits:
            return None
        i = edits.index(widget)
        for le in edits[i+1:]:
            if le is skip:
                continue
            try:
                ph = (le.placeholderText() or "").strip()
            except Exception:
                ph = ""
            if ph == "":
                return le
        return None

    weight_le = next_empty_after(height_le, skip=age_le) if height_le else None
    if weight_le:
        set_lineedit(weight_le, f"{data.weight_lb:.1f}")

    steps_le = next_empty_after(weight_le, skip=age_le) if weight_le else None
    if steps_le:
        set_lineedit(steps_le, str(data.steps))

    # Training sessions/week: placeholder "e.g. 3"
    sess_le = find_lineedit_by_placeholder_contains(window, "e.g. 3")
    if sess_le:
        set_lineedit(sess_le, str(data.sessions_per_week))

    # Body fat: placeholder "e.g. 18"
    bf_le = find_lineedit_by_placeholder_contains(window, "e.g. 18")
    if bf_le and data.bodyfat_pct is not None:
        set_lineedit(bf_le, f"{data.bodyfat_pct:.1f}")

    # Pull-ups: placeholder "e.g. 12"
    pu_le = find_lineedit_by_placeholder_contains(window, "e.g. 12")
    if pu_le:
        set_lineedit(pu_le, str(data.pullups))

    # Push-ups: placeholder "e.g. 35"
    push_le = find_lineedit_by_placeholder_contains(window, "e.g. 35")
    if push_le:
        set_lineedit(push_le, str(data.pushups))

    # Goal weight change: placeholder "e.g. -10"
    goal_le = find_lineedit_by_placeholder_contains(window, "e.g. -10")
    if goal_le:
        set_lineedit(goal_le, str(int(data.goal_weight_change_lb)))

    return set_map

# ---------- Data generation ----------
def gen_run1(seed: int = 1337) -> RunData:
    rnd = random.Random(seed)
    gender = rnd.choice(["Male", "Female"])
    age = rnd.randint(24, 46)

    height_in = rnd.randint(66, 75)
    ft, inch = divmod(height_in, 12)
    height = f"{ft}'{inch}\""

    weight = rnd.uniform(160, 230) if gender == "Male" else rnd.uniform(120, 180)
    steps = rnd.randint(5500, 12000)
    sessions = rnd.randint(2, 5)
    bodyfat = rnd.uniform(12, 24) if gender == "Male" else rnd.uniform(18, 32)
    pullups = rnd.randint(1, 18) if gender == "Male" else rnd.randint(0, 10)
    pushups = rnd.randint(15, 60) if gender == "Male" else rnd.randint(8, 40)
    goal = -rnd.randint(5, 20) if rnd.random() < 0.8 else rnd.randint(3, 12)

    return RunData(
        client=TARGET_CLIENT_NAME,
        gender=gender,
        age=age,
        height=height,
        weight_lb=round(weight, 1),
        steps=steps,
        sessions_per_week=sessions,
        bodyfat_pct=round(bodyfat, 1),
        pullups=pullups,
        pushups=pushups,
        goal_weight_change_lb=goal,
    )

def gen_run2(prev: RunData, seed: int = 2026) -> RunData:
    rnd = random.Random(seed)
    gender = prev.gender
    age = prev.age
    height = prev.height

    if prev.goal_weight_change_lb < 0:
        weight = prev.weight_lb - rnd.uniform(2.0, 6.0)
    elif prev.goal_weight_change_lb > 0:
        weight = prev.weight_lb + rnd.uniform(2.0, 6.0)
    else:
        weight = prev.weight_lb + rnd.uniform(-2.0, 2.0)

    steps = int(clamp(prev.steps + rnd.randint(-1200, 2500), 3000, 16000))
    sessions = int(clamp(prev.sessions_per_week + rnd.choice([-1, 0, 0, 1]), 1, 7))
    pullups = int(clamp(prev.pullups + rnd.randint(0, 4), 0, 40))
    pushups = int(clamp(prev.pushups + rnd.randint(1, 10), 0, 150))
    goal = int(clamp(prev.goal_weight_change_lb + rnd.choice([0, 0, 0, -2, 2]), -30, 30))

    bodyfat = prev.bodyfat_pct
    if bodyfat is not None:
        bodyfat = round(clamp(bodyfat + rnd.uniform(-1.0, 1.0), 6.0, 45.0), 1)

    return RunData(
        client=prev.client,
        gender=gender,
        age=age,
        height=height,
        weight_lb=round(weight, 1),
        steps=steps,
        sessions_per_week=sessions,
        bodyfat_pct=bodyfat,
        pullups=pullups,
        pushups=pushups,
        goal_weight_change_lb=goal,
    )

# ---------- JSON macro extraction (best-effort across different schemas) ----------
def _try_get_number(x) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        s = re.sub(r"[^\d\.\-]", "", s)  # keep digits/./-
        if s in ("", "-", ".", "-."):
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None

def extract_macros_from_obj(obj: Any) -> Optional[Dict[str, float]]:
    """
    Returns dict with keys: protein_g, carbs_g, fat_g if found.
    Handles shapes like:
      {"macros":{"protein_g":180,"carbs_g":240,"fat_g":60}}
      {"protein":180,"carbs":240,"fat":60}
      {"macros":[{"name":"Protein","grams":180},...]}
      {"REPORT_DATA":{"macros":...}}
    """
    if obj is None:
        return None

    # unwrap common nesting
    for key in ("REPORT_DATA", "report_data", "data", "payload"):
        if isinstance(obj, dict) and key in obj and isinstance(obj[key], (dict, list)):
            found = extract_macros_from_obj(obj[key])
            if found:
                return found

    if isinstance(obj, dict):
        # direct keys
        direct_sets = [
            ("protein_g", "carbs_g", "fat_g"),
            ("protein", "carbs", "fat"),
            ("proteinGrams", "carbGrams", "fatGrams"),
            ("protein_grams", "carb_grams", "fat_grams"),
        ]
        for a, b, c in direct_sets:
            if a in obj and b in obj and c in obj:
                p = _try_get_number(obj.get(a))
                ca = _try_get_number(obj.get(b))
                f = _try_get_number(obj.get(c))
                if p is not None and ca is not None and f is not None:
                    return {"protein_g": p, "carbs_g": ca, "fat_g": f}

        # nested "macros" dict
        for mk in ("macros", "macro", "macroTargets", "targets", "macro_targets"):
            if mk in obj:
                found = extract_macros_from_obj(obj[mk])
                if found:
                    return found

        # sometimes tokens contain rows like ROW_1_MID etc; skip (not macro grams reliably)
        # try scan dict values recursively
        for v in obj.values():
            found = extract_macros_from_obj(v)
            if found:
                return found

    if isinstance(obj, list):
        # list of macro objects: [{name:"Protein", grams:180}, ...]
        # or [{label:"Protein", value:180}, ...]
        prot = carb = fat = None
        for item in obj:
            if not isinstance(item, dict):
                continue
            name = norm(str(item.get("name") or item.get("label") or item.get("macro") or ""))
            grams = item.get("grams", None)
            if grams is None:
                grams = item.get("g", None)
            if grams is None:
                grams = item.get("value", None)
            g = _try_get_number(grams)
            if g is None:
                continue
            if "protein" in name:
                prot = g
            elif "carb" in name:
                carb = g
            elif name == "fat" or "fat" in name:
                fat = g
        if prot is not None and carb is not None and fat is not None:
            return {"protein_g": prot, "carbs_g": carb, "fat_g": fat}

        # otherwise recurse
        for v in obj:
            found = extract_macros_from_obj(v)
            if found:
                return found

    return None

def read_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def collect_candidate_json_files(project_root: Path) -> List[Path]:
    """
    Search common places for JSON files related to reports/client history.
    """
    roots = [
        project_root / "reports",
        project_root / "Clients",
        project_root / "clients",
        project_root,
    ]
    cand: List[Path] = []
    seen = set()
    for r in roots:
        if not r.exists():
            continue
        for fp in r.rglob("*.json"):
            s = str(fp)
            if s in seen:
                continue
            seen.add(s)
            name = norm(fp.name)
            # prioritize likely report/history files, but still include others (we'll parse best-effort)
            if any(tok in name for tok in ["report", "prev", "history", "client", "latest", "output", "data"]):
                cand.append(fp)
    # newest first
    cand.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return cand

def pick_curr_prev_macro_files(project_root: Path) -> Tuple[Optional[Path], Optional[Path], Dict[str, str]]:
    """
    Heuristic:
    - curr: newest JSON that contains macros
    - prev: next newest JSON that contains macros and is not the same file
    """
    candidates = collect_candidate_json_files(project_root)
    debug = {"scanned_json_count": str(len(candidates))}
    macro_files: List[Tuple[Path, Dict[str, float]]] = []
    for fp in candidates[:250]:  # cap for speed
        obj = read_json(fp)
        if obj is None:
            continue
        macros = extract_macros_from_obj(obj)
        if macros:
            macro_files.append((fp, macros))
        if len(macro_files) >= 8:
            # enough
            pass

    if not macro_files:
        debug["macro_files_found"] = "0"
        return None, None, debug

    debug["macro_files_found"] = str(len(macro_files))
    curr_fp = macro_files[0][0]
    prev_fp = macro_files[1][0] if len(macro_files) > 1 else None
    return curr_fp, prev_fp, debug

def get_macros_from_file(fp: Path) -> Tuple[Optional[Dict[str, float]], str]:
    obj = read_json(fp)
    if obj is None:
        return None, "Failed to parse JSON"
    macros = extract_macros_from_obj(obj)
    if macros:
        return macros, "OK"
    # show some top-level keys to help debugging
    if isinstance(obj, dict):
        keys = list(obj.keys())[:25]
        return None, "No macros found. Top-level keys: " + ", ".join(map(str, keys))
    return None, "No macros found (non-dict root)."

# ---------- Import and launch ----------
def import_window_class():
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        import dietCalculator  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Failed to import dietCalculator.py from {PROJECT_ROOT}\n\n{e}")

    for name in WINDOW_CLASS_CANDIDATES:
        if hasattr(dietCalculator, name):
            return getattr(dietCalculator, name)
    raise RuntimeError(
        "Could not find window class. Tried: "
        + ", ".join(WINDOW_CLASS_CANDIDATES)
        + "\nEdit WINDOW_CLASS_CANDIDATES to match your actual QMainWindow class."
    )

def main():
    run1 = gen_run1()
    run2 = gen_run2(run1)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    WindowClass = import_window_class()
    window = WindowClass()
    window.show()
    QTest.qWait(1100)

    # ------------ RUN #1 ------------
    click_button_by_text(window, BUTTON_TEXTS["clear"])
    QTest.qWait(250)

    m1 = fill_form(window, run1)
    if m1.get("client_ok") != "True":
        show_popup("Client selection FAILED (Run #1)", m1.get("client_details", "No details"))
        sys.exit(1)

    click_button_by_text(window, BUTTON_TEXTS["calculate"])
    QTest.qWait(900)

    click_button_by_text(window, BUTTON_TEXTS["generate"])
    QTest.qWait(2200)

    # ------------ RUN #2 ------------
    click_button_by_text(window, BUTTON_TEXTS["clear"])
    QTest.qWait(250)

    m2 = fill_form(window, run2)
    if m2.get("client_ok") != "True":
        show_popup("Client selection FAILED (Run #2)", m2.get("client_details", "No details"))
        sys.exit(1)

    click_button_by_text(window, BUTTON_TEXTS["calculate"])
    QTest.qWait(900)

    click_button_by_text(window, BUTTON_TEXTS["generate"])
    QTest.qWait(2600)

    # ------------ MACRO CHECK ------------
    curr_fp, prev_fp, dbg = pick_curr_prev_macro_files(PROJECT_ROOT)

    curr_macros = prev_macros = None
    curr_msg = prev_msg = ""

    if curr_fp:
        curr_macros, curr_msg = get_macros_from_file(curr_fp)
    if prev_fp:
        prev_macros, prev_msg = get_macros_from_file(prev_fp)

    def fmt(macros: Optional[Dict[str, float]]) -> str:
        if not macros:
            return "Protein: NOT FOUND\nCarbs:   NOT FOUND\nFats:    NOT FOUND"
        p = int(round(macros["protein_g"]))
        c = int(round(macros["carbs_g"]))
        f = int(round(macros["fat_g"]))
        return f"Protein: {p} g\nCarbs:   {c} g\nFats:    {f} g"

    def fmt_delta(curr: Optional[Dict[str, float]], prev: Optional[Dict[str, float]]) -> str:
        if not curr or not prev:
            return "Δ: (missing prev or curr macros)"
        dp = int(round(curr["protein_g"] - prev["protein_g"]))
        dc = int(round(curr["carbs_g"] - prev["carbs_g"]))
        df = int(round(curr["fat_g"] - prev["fat_g"]))
        return f"Δ (curr - prev)\nProtein: {dp:+d} g\nCarbs:   {dc:+d} g\nFats:    {df:+d} g"

    lines = []
    lines.append(f"<b>Qt:</b> {QT_BINDING}")
    lines.append(f"<b>Scanned JSON files:</b> {dbg.get('scanned_json_count','?')}")
    lines.append(f"<b>JSONs with macros found:</b> {dbg.get('macro_files_found','?')}")
    lines.append("")
    lines.append("<b>CURR macros</b>")
    lines.append(f"<i>File:</i> {curr_fp if curr_fp else '(not found)'}")
    lines.append(f"<i>Status:</i> {curr_msg if curr_fp else 'No curr macro file found'}")
    lines.append("")
    lines.append(fmt(curr_macros))
    lines.append("")
    lines.append("<b>PREV macros</b>")
    lines.append(f"<i>File:</i> {prev_fp if prev_fp else '(not found)'}")
    lines.append(f"<i>Status:</i> {prev_msg if prev_fp else 'No prev macro file found'}")
    lines.append("")
    lines.append(fmt(prev_macros))
    lines.append("")
    lines.append("<b>" + fmt_delta(curr_macros, prev_macros).replace("\n", "<br>") + "</b>")

    show_popup("Prev vs Curr Macro Sanity Check", "\n".join([l.replace("\n", "<br>") for l in lines]))

    # Keep app open so you can inspect sliders/bars manually.
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
