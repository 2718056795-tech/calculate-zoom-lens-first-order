from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from four_group_advanced import compute_four_group_single_branch, scan_four_group_m3
from zoom_core import SIXTEEN_X_PRESET, calculate_preset


def _status_ok(result: dict) -> bool:
    return "一阶通过" in str(result.get("综合状态", ""))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    three = calculate_preset("3x")
    root_switch = calculate_preset("16x")
    single_branch = compute_four_group_single_branch(
        replace(SIXTEEN_X_PRESET, m3_middle=-0.8)
    )
    scan = scan_four_group_m3(SIXTEEN_X_PRESET)
    valid_scan = [row for row in scan if "一阶通过" in str(row.get("状态", ""))]

    checks = {
        "3x_preset": _status_ok(three),
        "16x_root_switch": _status_ok(root_switch),
        "16x_single_branch_m3_-0.8": _status_ok(single_branch),
        "m3_scan_row_count": len(scan) == 8,
        "m3_scan_valid_count": len(valid_scan) == 5,
    }
    payload = {"ok": all(checks.values()), "checks": checks}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())