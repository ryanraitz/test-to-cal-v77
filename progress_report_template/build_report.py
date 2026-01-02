#!/usr/bin/env python3
"""
build_report.py (Recomp estimate wiring)

Key fix:
- If template.html includes <script src="./report-data.js"></script>, that external file can overwrite
  the freshly injected window.REPORT_DATA and cause the page to always show an old client (e.g., Lawson).
- This build writes reports/output/report-data.js EVERY RUN (from the selected REPORT_JSON) AND strips the
  report-data.js include from template.html before injecting inline REPORT_DATA, so there is no way for
  stale data to win.

It also stamps the JSON path into latest.html for easy verification.
"""

import os
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
REPORTS_DIR = (SCRIPT_DIR.parent / "reports").resolve()

ENV_REPORT_JSON = os.environ.get("REPORT_JSON")
REPORT_JSON = Path(ENV_REPORT_JSON).resolve() if ENV_REPORT_JSON else (REPORTS_DIR / "report.json")

print("[build_report] Using REPORT_JSON:", str(REPORT_JSON))

OUTPUT_DIR = REPORTS_DIR / "output"
OUTPUT_HTML = OUTPUT_DIR / "latest.html"
TEMPLATE_HTML = SCRIPT_DIR / "template.html"
EXPORT_PY = SCRIPT_DIR / "export.py"


# ------------------------- parsing helpers -------------------------

def _num(x: Any, default: Optional[float] = None) -> Optional[float]:
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return default
        s = s.replace(",", "")
        s = re.sub(r"[^0-9\.\-]+", "", s)
        if not s or s in {"-", ".", "-."}:
            return default
        try:
            return float(s)
        except Exception:
            return default
    return default

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _fmt_signed_lb(x: float) -> str:
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.1f} lb"

def _fmt_signed_pct(x: float) -> str:
    sign = "+" if x > 0 else ""
    return f"{sign}{x:.0f}%"

def _pretty_int(n: Optional[float], fallback: str = "—") -> str:
    if n is None or (isinstance(n, float) and math.isnan(n)):
        return fallback
    try:
        return f"{int(round(float(n))):,}"
    except Exception:
        return fallback


# ------------------------- bars mapping -------------------------

def _find_label_index(labels: List[Any], candidates: List[str]) -> int:
    cand = {c.strip().lower(): True for c in candidates}
    for i, raw in enumerate(labels or []):
        s = str(raw).strip().lower()
        if s in cand:
            return i
    return -1

def _get_bars_triplet(report: Dict[str, Any]) -> Tuple[List[Any], List[Any], List[Any]]:
    bars = report.get("bars")
    if isinstance(bars, dict):
        labels = bars.get("labels") or []
        prev = bars.get("prev") or []
        curr = bars.get("curr") or []
        if isinstance(labels, list) and isinstance(prev, list) and isinstance(curr, list):
            return labels, prev, curr
    return [], [], []


# ------------------------- strength model -------------------------

def compute_strength_pct(labels: List[Any], prev: List[Any], curr: List[Any]) -> float:
    idx_pull = _find_label_index(labels, ["Pull-Ups", "Pullups", "Pull Ups"])
    idx_push = _find_label_index(labels, ["Push-Ups", "Pushups", "Push Ups"])
    eps = 3.0

    p0 = _num(prev[idx_pull], 0.0) if 0 <= idx_pull < len(prev) else 0.0
    p1 = _num(curr[idx_pull], 0.0) if 0 <= idx_pull < len(curr) else 0.0
    s0 = _num(prev[idx_push], 0.0) if 0 <= idx_push < len(prev) else 0.0
    s1 = _num(curr[idx_push], 0.0) if 0 <= idx_push < len(curr) else 0.0

    pull_rel = (p1 + eps) / (p0 + eps)
    push_rel = (s1 + eps) / (s0 + eps)
    strength_rel = 0.6 * pull_rel + 0.4 * push_rel
    return (strength_rel - 1.0) * 100.0


# ------------------------- recomp calculations -------------------------

def compute_fat_loss_lb(labels: List[Any], prev: List[Any], curr: List[Any]) -> Tuple[float, bool]:
    idx_bfm = _find_label_index(labels, ["Body Fat Mass", "BFM", "Body Fat Mass (lb)", "Body Fat Mass (lbs)"])
    if 0 <= idx_bfm < len(prev) and 0 <= idx_bfm < len(curr):
        b0 = _num(prev[idx_bfm], None)
        b1 = _num(curr[idx_bfm], None)
        if b0 is not None and b1 is not None:
            return (b1 - b0), True

    idx_w = _find_label_index(labels, ["Weight", "Bodyweight"])
    idx_bf = _find_label_index(labels, ["Bodyfat %", "Body Fat %", "Bodyfat", "Body Fat"])

    w0 = _num(prev[idx_w], 0.0) if 0 <= idx_w < len(prev) else 0.0
    w1 = _num(curr[idx_w], 0.0) if 0 <= idx_w < len(curr) else 0.0
    bf0 = _num(prev[idx_bf], None) if 0 <= idx_bf < len(prev) else None
    bf1 = _num(curr[idx_bf], None) if 0 <= idx_bf < len(curr) else None

    if bf0 is not None and bf1 is not None and 2.0 <= bf0 <= 60.0 and 2.0 <= bf1 <= 60.0 and w0 > 0 and w1 > 0:
        fat0 = w0 * (bf0 / 100.0)
        fat1 = w1 * (bf1 / 100.0)
        return (fat1 - fat0), False

    return (0.0, False)

def compute_estimated_lean_muscle_lb(labels: List[Any], prev: List[Any], curr: List[Any], strength_pct: float, fat_change_lb: float) -> Tuple[float, bool]:
    idx_smm = _find_label_index(labels, ["Skeletal Muscle Mass", "SMM", "Skeletal Muscle Mass (lb)", "Skeletal Muscle Mass (lbs)"])
    if 0 <= idx_smm < len(prev) and 0 <= idx_smm < len(curr):
        m0 = _num(prev[idx_smm], None)
        m1 = _num(curr[idx_smm], None)
        if m0 is not None and m1 is not None:
            return (m1 - m0), True

    idx_w = _find_label_index(labels, ["Weight", "Bodyweight"])
    w0 = _num(prev[idx_w], 0.0) if 0 <= idx_w < len(prev) else 0.0
    w1 = _num(curr[idx_w], 0.0) if 0 <= idx_w < len(curr) else 0.0
    dw = w1 - w0

    nonfat_change = dw - fat_change_lb

    strength_score = _clamp(strength_pct / 100.0, 0.0, 2.5)
    baseline_gain = _clamp(1.2 * strength_score, 0.0, 2.8)

    if nonfat_change > 0:
        frac = _clamp(0.40 + 0.20 * strength_score, 0.40, 0.75)
        muscle_from_nonfat = nonfat_change * frac
        est = max(baseline_gain, muscle_from_nonfat)
    else:
        est = baseline_gain

    fat_dropped = (fat_change_lb < -0.2)
    weight_dropped = (dw < -0.2)
    if not fat_dropped and not weight_dropped:
        est *= 0.6

    est = _clamp(est, 0.0, 3.0)

    if strength_pct < -5:
        est = _clamp(nonfat_change * 0.2, -2.0, 0.0)

    return (float(est), False)


# ------------------------- confidence scoring + HTML patching -------------------------
# (Your original functions exist in your version; they are not required for the Lawson bug fix.)
# Keep your existing compute_recomp_confidence / patch_recomp_confidence / patch_recomp_tiles if you want.
# For now, we only guarantee correct REPORT_DATA data flow.


# ------------------------- REPORT_DATA injection -------------------------

def inject_report_data(html: str, report_data: Dict[str, Any]) -> str:
    js = "window.REPORT_DATA = " + json.dumps(report_data, ensure_ascii=False) + ";"
    pattern = re.compile(r"window\.REPORT_DATA\s*=\s*\{.*?\};", re.DOTALL)
    if pattern.search(html):
        return pattern.sub(js, html)

    insert_point = html.lower().find("</head>")
    if insert_point != -1:
        # Stamp path comment for debugging
        stamp = f"<!-- REPORT_JSON_PATH: {REPORT_JSON} -->\n"
        return html[:insert_point] + stamp + f"\n<script>\n{js}\n</script>\n" + html[insert_point:]
    return html + f"\n<script>\n{js}\n</script>\n"

def strip_report_data_js_include(html: str) -> str:
    # remove any <script src="./report-data.js..."></script> anywhere
    return re.sub(r'<script\s+src=["\']\./report-data\.js[^"\']*["\']\s*>\s*</script>\s*', '', html, flags=re.IGNORECASE)

def write_report_data_js(out_dir: Path, report_data: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    js_path = out_dir / "report-data.js"
    js_payload = "window.REPORT_DATA = " + json.dumps(report_data, ensure_ascii=False) + ";\n"
    js_path.write_text(js_payload, encoding="utf-8")


def main() -> None:
    if not REPORT_JSON.exists():
        raise FileNotFoundError(f"Missing report.json at: {REPORT_JSON}")
    if not TEMPLATE_HTML.exists():
        raise FileNotFoundError(f"Missing template.html at: {TEMPLATE_HTML}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))

    # IMPORTANT: keep output/report-data.js in sync (so it never stays stuck on Lawson)
    write_report_data_js(OUTPUT_DIR, report)

    html = TEMPLATE_HTML.read_text(encoding="utf-8")

    # IMPORTANT: remove external script include so stale output/report-data.js can never overwrite the inline REPORT_DATA
    html = strip_report_data_js_include(html)

    # Inject inline REPORT_DATA (authoritative)
    html = inject_report_data(html, report)

    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print("Wrote:", str(OUTPUT_HTML))
    print("Wrote:", str(OUTPUT_DIR / "report-data.js"))

    # Optional export
    if EXPORT_PY.exists():
        try:
            subprocess.run([sys.executable, str(EXPORT_PY), str(OUTPUT_HTML), str(OUTPUT_DIR)], cwd=str(SCRIPT_DIR), check=False)
        except Exception as e:
            print("(Non-fatal) export.py failed:", e)


if __name__ == "__main__":
    main()
