from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import MISSING, fields
from math import isfinite
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Type, TypeVar


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from four_group_advanced import (  # noqa: E402
    DEFAULT_M3_SCAN_VALUES,
    compute_four_group_single_branch,
    scan_four_group_m3,
)
from zoom_core import (  # noqa: E402
    SIXTEEN_X_PRESET,
    CalculationError,
    FourGroupInputs,
    ThreeGroupInputs,
    calculate_preset,
    compute_four_group,
    compute_three_group,
)


ENGINE_VERSION = "2026-08-11"
T = TypeVar("T", ThreeGroupInputs, FourGroupInputs)

MODE_ALIASES = {
    "preset": "preset",
    "预设": "preset",
    "three": "three_group",
    "three_group": "three_group",
    "三组": "three_group",
    "four": "four_group",
    "four_group": "four_group",
    "四组": "four_group",
}

SOLVE_MODE_ALIASES = {
    "auto": "auto",
    "自动": "auto",
    "root_switch": "root_switch",
    "重根换支": "root_switch",
    "single_branch": "single_branch",
    "单支连续": "single_branch",
}

SUMMARY_KEYS = (
    "计算终端倍率",
    "相对目标倍率偏差",
    "相对名义倍率偏差",
    "毫米缩放系数",
    "计算长焦系统焦距",
    "长焦到短焦总位移 Delta2",
    "补偿组最大绝对位移 Delta3",
    "最小判别式 D",
    "最小 d12",
    "最小 d23",
    "最小 d34",
    "像面漂移",
    "最大 ABCD 焦距残差",
)


class RequestError(ValueError):
    pass


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _read_request(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise RequestError(f"找不到请求文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RequestError(f"请求 JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列") from exc
    if not isinstance(payload, dict):
        raise RequestError("请求 JSON 顶层必须是对象。")
    return payload


def _finite_float(value: Any, name: str, allow_none: bool = False) -> Optional[float]:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise RequestError(f"{name} 必须是数值，不能是布尔值。")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RequestError(f"{name} 必须是数值。") from exc
    if not isfinite(number):
        raise RequestError(f"{name} 必须是有限数值。")
    return number


def _integer(value: Any, name: str) -> int:
    number = _finite_float(value, name)
    assert number is not None
    if not number.is_integer():
        raise RequestError(f"{name} 必须是整数。")
    return int(number)


def _build_inputs(cls: Type[T], raw: Any) -> T:
    if not isinstance(raw, dict):
        raise RequestError("parameters 必须是 JSON 对象。")
    expected = {item.name for item in fields(cls)}
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise RequestError(f"存在未知参数：{', '.join(unknown)}")

    missing = []
    values: Dict[str, Any] = {}
    for item in fields(cls):
        if item.name not in raw:
            if item.default is MISSING and item.default_factory is MISSING:
                missing.append(item.name)
            continue
        value = raw[item.name]
        if item.name == "sample_count":
            values[item.name] = _integer(value, item.name)
        elif item.name == "scale_mm_per_unit":
            values[item.name] = _finite_float(value, item.name, allow_none=True)
        else:
            values[item.name] = _finite_float(value, item.name)
    if missing:
        raise RequestError(f"缺少必填参数：{', '.join(missing)}")
    return cls(**values)


def _normalize_mode(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key not in MODE_ALIASES:
        raise RequestError("mode 必须是 preset、three_group 或 four_group。")
    return MODE_ALIASES[key]


def _normalize_solve_mode(value: Any) -> str:
    key = str(value or "auto").strip().lower()
    if key not in SOLVE_MODE_ALIASES:
        raise RequestError("solve_mode 必须是 auto、root_switch 或 single_branch。")
    return SOLVE_MODE_ALIASES[key]


def _scan_config(value: Any) -> Optional[Tuple[Sequence[float], bool]]:
    if value is None or value is False:
        return None
    include_root_switch = True
    raw_values: Any = DEFAULT_M3_SCAN_VALUES
    if value is True:
        pass
    elif isinstance(value, list):
        raw_values = value
    elif isinstance(value, dict):
        raw_values = value.get("values", DEFAULT_M3_SCAN_VALUES)
        include_root_switch = value.get("include_root_switch", True)
        if not isinstance(include_root_switch, bool):
            raise RequestError("m3_scan.include_root_switch 必须是布尔值。")
    else:
        raise RequestError("m3_scan 必须是布尔值、数值数组或配置对象。")
    if not isinstance(raw_values, (list, tuple)) or not raw_values:
        raise RequestError("m3_scan.values 必须是非空数值数组。")
    values = []
    for index, value_item in enumerate(raw_values):
        number = _finite_float(value_item, f"m3_scan.values[{index}]")
        assert number is not None
        if number >= 0 or abs(number) <= 1e-6:
            raise RequestError("M3 扫描值必须为负值且不能接近 0。")
        values.append(number)
    return values, include_root_switch


def _calculate(request: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    mode = _normalize_mode(request.get("mode"))
    if mode == "preset":
        preset = str(request.get("preset", "")).strip().lower()
        if preset not in {"3x", "4x", "16x"}:
            raise RequestError("preset 必须是 3x、4x 或 16x。")
        result = calculate_preset(preset)
        solve_mode = "root_switch" if preset == "16x" else "three_group"
        scan = _scan_config(request.get("m3_scan"))
        if scan is not None:
            if preset != "16x":
                raise RequestError("M3 扫描只适用于四组结构或 16x 四组预设。")
            result["m3扫描比较"] = scan_four_group_m3(
                SIXTEEN_X_PRESET,
                values=scan[0],
                include_root_switch=scan[1],
            )
        return result, mode, solve_mode

    parameters = request.get("parameters")
    if mode == "three_group":
        data = _build_inputs(ThreeGroupInputs, parameters)
        if _scan_config(request.get("m3_scan")) is not None:
            raise RequestError("M3 扫描只适用于四组结构。")
        return compute_three_group(data), mode, "three_group"

    data = _build_inputs(FourGroupInputs, parameters)
    solve_mode = _normalize_solve_mode(request.get("solve_mode"))
    if solve_mode == "auto":
        solve_mode = "root_switch" if abs(data.m3_middle + 1.0) <= 1e-9 else "single_branch"
    if solve_mode == "root_switch":
        if abs(data.m3_middle + 1.0) > 1e-9:
            raise RequestError("root_switch 模式要求 m3_middle=-1。")
        result = compute_four_group(data)
    else:
        result = compute_four_group_single_branch(data)

    scan = _scan_config(request.get("m3_scan"))
    if scan is not None:
        result["m3扫描比较"] = scan_four_group_m3(
            data,
            values=scan[0],
            include_root_switch=scan[1],
        )
    return result, mode, solve_mode


def _require_export_dependencies() -> None:
    missing = [name for name in ("matplotlib", "openpyxl") if importlib.util.find_spec(name) is None]
    if missing:
        names = ", ".join(missing)
        raise RequestError(
            f"导出结果缺少 Python 依赖：{names}。请使用 scripts/requirements.txt 安装后重试。"
        )


def _key_results(result: Dict[str, Any]) -> Dict[str, Any]:
    rows = {row.get("项目"): row.get("数值") for row in result.get("关键结果", [])}
    return {name: rows[name] for name in SUMMARY_KEYS if name in rows}


def _write_full_result(path: Path, result: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="变焦镜头一阶计算 Skill 命令行入口")
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 JSON 请求文件")
    parser.add_argument("--output-dir", type=Path, help="导出结果的父目录")
    parser.add_argument("--no-export", action="store_true", help="只计算，不生成 Excel/CSV/PNG")
    parser.add_argument("--result-json", type=Path, help="额外保存完整计算 JSON")
    return parser.parse_args()


def main() -> int:
    _configure_console()
    args = _parse_args()
    try:
        input_path = args.input.expanduser().resolve()
        request = _read_request(input_path)
        result, mode, solve_mode = _calculate(request)

        export_setting = request.get("export", True)
        if not isinstance(export_setting, bool):
            raise RequestError("export 必须是布尔值。")
        export_enabled = export_setting and not args.no_export
        output_files: Dict[str, str] = {}
        if export_enabled:
            _require_export_dependencies()
            from result_export import export_result

            requested_dir = args.output_dir or request.get("output_dir")
            output_parent = (
                Path(requested_dir).expanduser().resolve()
                if requested_dir
                else input_path.parent / "变焦计算结果"
            )
            output_parent.mkdir(parents=True, exist_ok=True)
            exported = export_result(result, output_parent)
            output_files = {name: str(path.resolve()) for name, path in exported.items()}

        if args.result_json is not None:
            _write_full_result(args.result_json.expanduser().resolve(), result)

        scan_rows = result.get("m3扫描比较", [])
        summary: Dict[str, Any] = {
            "ok": True,
            "engine_version": ENGINE_VERSION,
            "mode": mode,
            "solve_mode": solve_mode,
            "scheme": result.get("方案"),
            "status": result.get("综合状态"),
            "key_results": _key_results(result),
            "output_files": output_files,
        }
        if scan_rows:
            summary["m3_scan"] = {
                "rows": len(scan_rows),
                "valid": sum("一阶通过" in str(row.get("状态", "")) for row in scan_rows),
            }
        _print_json(summary)
        return 0
    except (RequestError, CalculationError, ValueError, ZeroDivisionError) as exc:
        _print_json({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 2
    except Exception as exc:
        _print_json({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())