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

    # ---- Confidence (read-only from report.json) ----
    confidence = report.get("confidence", {
        "value": 55,
        "label": "Inconclusive"
    })
    report["confidence"] = confidence


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
    # if EXPORT_PY.exists():
    #    try:
    #        subprocess.run([sys.executable, str(EXPORT_PY), str(OUTPUT_HTML), str(OUTPUT_DIR)], cwd=str(SCRIPT_DIR), check=False)
    #    except Exception as e:
    #        print("(Non-fatal) export.py failed:", e)


if __name__ == "__main__":
    main()
