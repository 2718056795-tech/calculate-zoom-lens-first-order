from __future__ import annotations

from dataclasses import asdict
from math import sqrt
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from zoom_core import (
    TOL,
    CalculationError,
    FourGroupInputs,
    _input_rows,
    _key,
    _matrix_metrics,
    _nonzero,
    _root,
    _status,
    _validate,
    compute_four_group,
)


DEFAULT_M3_SCAN_VALUES = (-2.0, -1.5, -1.2, -1.0, -0.8, -0.67, -0.5)
AUDIT_POINT_COUNT = 2001


def _roots(b: float, label: str) -> Tuple[float, float, float]:
    d = b * b - 4.0
    if abs(d) <= 1e-12:
        return b / 2.0, b / 2.0, 0.0
    sd = _root(d, label)
    return (b + sd) / 2.0, (b - sd) / 2.0, 0.0 if abs(d) <= TOL else d


def _single_branch_row(p: float, values: Dict[str, float], branch: str) -> Dict[str, Any]:
    delta2 = values["travel"] * p
    m2 = 1.0 / _nonzero(1.0 / values["m2l"] - delta2 / values["f2"], "变倍组倍率分母")
    b = (
        -values["f2"]
        / values["f3"]
        * (1.0 / m2 - 1.0 / values["m2l"] + m2 - values["m2l"])
        + 1.0 / values["m3l"]
        + values["m3l"]
    )
    plus, minus, d = _roots(b, "补偿组判别式 D")
    m3 = plus if branch == "正根" else minus
    delta3 = values["f3"] * (m3 - values["m3l"])
    d12 = values["d12l"] + delta2
    d23 = values["d23l"] - delta2 + delta3
    d34 = values["d34l"] - delta3
    metrics = _matrix_metrics(
        [values["f1"], values["f2"], values["f3"], values["f4"]],
        [d12, d23, d34],
    )
    status = "OK" if min(d12, d23, d34) > 0 else (
        "d12<=0" if d12 <= 0 else "d23<=0" if d23 <= 0 else "d34<=0"
    )
    return {
        "位置": p,
        "Delta2": delta2,
        "m2": m2,
        "b": b,
        "D": d,
        "m3_正根": plus,
        "m3_负根": minus,
        "m3_连续": m3,
        "Delta3_连续": delta3,
        "相对倍率": values["m2l"] * values["m3l"] / (m2 * m3),
        "d12": d12,
        "d23": d23,
        "d34": d34,
        "系统焦距": metrics["系统焦距"],
        "像面位置": metrics["像面位置"],
        "ABCD焦距残差": metrics["系统焦距"] - values["f1"] * m2 * m3 * values["m4"],
        "状态": status,
    }


def _close(left: float, right: float, tolerance: float = 2e-7) -> bool:
    return abs(left - right) <= tolerance * max(1.0, abs(left), abs(right))


def _build_candidate(
    data: FourGroupInputs,
    common: Dict[str, float],
    delta3_long: float,
    m2_short: float,
    other_m2_short: float,
) -> Dict[str, Any]:
    f3 = common["f3"]
    m3_long = (
        common["l3mi"] + delta3_long
    ) / _nonzero(common["a_long"] + delta3_long, "m3L 分母")
    d23_long = data.d23_middle - common["g1"] - delta3_long
    product = data.m2_long * m3_long / data.target_zoom
    m3_short = product / _nonzero(m2_short, "m2S")
    travel = -common["g1"] + (
        common["l2m"] - data.f2 * (1.0 / m2_short - 1.0)
    )
    _nonzero(travel, "总位移")
    reference_position = -common["g1"] / travel
    if not 0.0 <= reference_position <= 1.0:
        raise CalculationError("指定的 M 参考构型不在长焦到短焦行程内。")

    delta3_short = f3 * (m3_short - m3_long)
    f1 = data.d12_short + data.f2 * (1.0 / m2_short - 1.0)
    f4 = (
        f3 * (1.0 - m3_short) - data.d34_short
    ) / _nonzero(1.0 / data.m4 - 1.0, "f4 分母")
    if f1 <= 0 or f4 <= 0:
        raise CalculationError("推导得到的固定组焦距不是正值。")
    short_focal_normalized = f1 * m2_short * m3_short * data.m4
    scale = data.short_system_focal_mm / _nonzero(
        short_focal_normalized, "归一短焦系统焦距"
    )
    if scale <= 0:
        raise CalculationError("物理缩放系数不是正值。")

    d12_long = data.d12_short - travel
    d34_long = data.d34_short + delta3_short
    b_long = 1.0 / m3_long + m3_long
    plus_long, minus_long, _ = _roots(b_long, "长焦补偿组判别式")
    branch = "正根" if abs(plus_long - m3_long) <= abs(minus_long - m3_long) else "负根"
    values = {
        "f1": f1,
        "f2": data.f2,
        "f3": f3,
        "f4": f4,
        "m2l": data.m2_long,
        "m3l": m3_long,
        "m4": data.m4,
        "d12l": d12_long,
        "d23l": d23_long,
        "d34l": d34_long,
        "travel": travel,
    }

    reference_row = _single_branch_row(reference_position, values, branch)
    short_row = _single_branch_row(1.0, values, branch)
    if not _close(reference_row["m3_连续"], data.m3_middle):
        raise CalculationError("连续分支不能经过指定的 m3M 参考倍率。")
    if not _close(short_row["m3_连续"], m3_short):
        raise CalculationError("连续分支不能同时到达目标短焦端。")

    audit_positions = {i / (AUDIT_POINT_COUNT - 1) for i in range(AUDIT_POINT_COUNT)}
    audit_positions.add(reference_position)
    audit_rows = [
        _single_branch_row(position, values, branch)
        for position in sorted(audit_positions)
    ]
    min_d = min(row["D"] for row in audit_rows)
    min_gaps = [
        min(row[name] for row in audit_rows)
        for name in ("d12", "d23", "d34")
    ]
    drift = max(row["像面位置"] for row in audit_rows) - min(
        row["像面位置"] for row in audit_rows
    )
    abcd_error = max(abs(row["ABCD焦距残差"]) for row in audit_rows)
    max_delta3 = max(abs(row["Delta3_连续"]) for row in audit_rows)
    max_group_length = max(
        row["d12"] + row["d23"] + row["d34"] for row in audit_rows
    )
    m3_jump = max(
        abs(audit_rows[index]["m3_连续"] - audit_rows[index - 1]["m3_连续"])
        for index in range(1, len(audit_rows))
    )
    overall = _status(
        min_d,
        list(zip(("d12", "d23", "d34"), min_gaps)),
        drift,
        abcd_error,
        False,
    )
    if overall == "一阶通过":
        overall = "一阶通过（单支连续）"
    else:
        overall = f"{overall}（单支连续）"

    rows: List[Dict[str, Any]] = []
    for index in range(data.sample_count):
        row = {
            "序号": index + 1,
            **_single_branch_row(index / (data.sample_count - 1), values, branch),
        }
        row.update(
            {
                "Delta2_mm": row["Delta2"] * scale,
                "Delta3_mm": row["Delta3_连续"] * scale,
                "d12_mm": row["d12"] * scale,
                "d23_mm": row["d23"] * scale,
                "d34_mm": row["d34"] * scale,
            }
        )
        rows.append(row)

    endpoints = []
    for name, index in zip(
        ("长焦", "中焦", "短焦"),
        (0, (data.sample_count - 1) // 2, data.sample_count - 1),
    ):
        row = rows[index]
        endpoints.append(
            {
                "位置名称": name,
                "位置": row["位置"],
                "Delta2": row["Delta2"],
                "Delta3": row["Delta3_连续"],
                "m2": row["m2"],
                "m3": row["m3_连续"],
                "相对倍率": row["相对倍率"],
                "d12": row["d12"],
                "d23": row["d23"],
                "d34": row["d34"],
                "系统焦距": row["系统焦距"],
                "像面位置": row["像面位置"],
                "Delta2_mm": row["Delta2_mm"],
                "Delta3_mm": row["Delta3_mm"],
                "d12_mm": row["d12_mm"],
                "d23_mm": row["d23_mm"],
                "d34_mm": row["d34_mm"],
            }
        )

    focals = [
        {
            "光学组": name,
            "符号": symbol,
            "归一焦距": focal,
            "物理焦距_mm": focal * scale,
        }
        for name, symbol, focal in (
            ("前固定组", "f1'", f1),
            ("变倍组", "f2'", data.f2),
            ("补偿组", "f3'", f3),
            ("后固定组", "f4'", f4),
        )
    ]
    physical = [
        {
            "位置": row["位置名称"],
            "f1_mm": f1 * scale,
            "d12_mm": row["d12_mm"],
            "f2_mm": data.f2 * scale,
            "d23_mm": row["d23_mm"],
            "f3_mm": f3 * scale,
            "d34_mm": row["d34_mm"],
            "f4_mm": f4 * scale,
        }
        for row in endpoints
    ]
    final_zoom = rows[-1]["相对倍率"]
    keys = [
        _key("求解方式", "自定义单支连续"),
        _key("参考构型 m3M", data.m3_middle),
        _key("连续根分支", branch),
        _key("M 参考构型行程位置", reference_position, "行程比例"),
        _key("补偿组焦距 f3'", f3, "归一单位"),
        _key("长焦补偿组倍率 m3L", m3_long),
        _key("长焦间隔 d23L", d23_long, "归一单位"),
        _key("短焦变倍组倍率 m2S", m2_short),
        _key("短焦变倍组另一根", other_m2_short),
        _key("长焦到短焦总位移 Delta2", travel, "归一单位"),
        _key("补偿组最大绝对位移 Delta3", max_delta3, "归一单位"),
        _key("短焦补偿组倍率 m3S", m3_short),
        _key("短焦补偿位移 Delta3", delta3_short, "归一单位"),
        _key("前固定组焦距 f1'", f1, "归一单位"),
        _key("后固定组焦距 f4'", f4, "归一单位"),
        _key("归一短焦系统焦距", short_focal_normalized, "归一单位"),
        _key("毫米缩放系数", scale, "mm/归一单位"),
        _key(
            "计算长焦系统焦距",
            f1 * data.m2_long * m3_long * data.m4 * scale,
            "mm",
        ),
        _key("计算终端倍率", final_zoom, "x"),
        _key("相对目标倍率偏差", final_zoom / data.target_zoom - 1.0, "%"),
        _key("最小判别式 D", min_d),
        _key("最小 d12", min_gaps[0], "归一单位"),
        _key("最小 d23", min_gaps[1], "归一单位"),
        _key("最小 d34", min_gaps[2], "归一单位"),
        _key("像面漂移", drift, "归一单位", "ABCD 复核"),
        _key("最大 ABCD 焦距残差", abcd_error, "归一单位"),
        _key("最大相邻 m3 变化", m3_jump, "2001点审计"),
        _key("综合状态", overall),
    ]
    labels = {
        "m2_middle": ("M参考构型变倍组倍率 m2M", "无量纲"),
        "f2": ("变倍组焦距 f2'", "归一单位"),
        "d23_middle": ("M参考构型间隔 d23M", "归一单位"),
        "m2_long": ("长焦变倍组倍率 m2L", "无量纲"),
        "target_zoom": ("目标变焦倍率", "x"),
        "d12_short": ("短焦间隔 d12S", "归一单位"),
        "d34_short": ("短焦间隔 d34S", "归一单位"),
        "m4": ("后固定组倍率 m4", "无量纲"),
        "short_system_focal_mm": ("短焦系统焦距", "mm"),
        "m3_middle": ("M参考构型补偿组倍率 m3M", "可调负倍率"),
        "sample_count": ("输出采样点数", "点"),
    }
    result = {
        "方案": f"四组/两动组 {data.target_zoom:g}x",
        "模型": "四组结构（两个移动组，自定义单支连续）",
        "输入参数": _input_rows(data, labels),
        "关键结果": keys,
        "组焦距": focals,
        "长中短焦": endpoints,
        "运动表": rows,
        "物理结构": physical,
        "综合状态": overall,
        "说明": [
            "焦距为光学组等效焦距，d12/d23/d34 为组主平面间距。",
            f"m3M={data.m3_middle:g}；全行程固定跟踪{branch}，不进行强制换支。",
            "程序使用 2001 个审计位置复核实数解、最小间距、像面和连续性。",
            "物理尺寸由短焦系统焦距自动建立统一毫米尺度。",
        ],
        "求解信息": {
            "m3_middle": data.m3_middle,
            "branch": branch,
            "reference_position": reference_position,
            "travel": travel,
            "max_delta3": max_delta3,
            "min_d": min_d,
            "min_gaps": min_gaps,
            "max_group_length": max_group_length,
            "scale": scale,
            "image_drift": drift,
            "abcd_error": abcd_error,
            "m3_jump": m3_jump,
            "reference_m2": reference_row["m2"],
            "reference_m3": reference_row["m3_连续"],
            "reference_d23": reference_row["d23"],
        },
    }
    score = (
        1 if min(min_gaps) > 0 else 0,
        min(min_gaps),
        -abs(travel),
        -max_delta3,
    )
    return {"result": result, "score": score}


def compute_four_group_single_branch(data: FourGroupInputs) -> Dict[str, Any]:
    _validate(data)
    if data.f2 >= 0 or data.target_zoom <= 1 or data.short_system_focal_mm <= 0:
        raise CalculationError("要求 f2<0、目标倍率>1、短焦系统焦距>0。")
    if data.m3_middle >= 0 or abs(data.m3_middle) <= 1e-6:
        raise CalculationError("自定义单支模式要求 m3M 为负值且不能接近 0。")
    if data.sample_count < 3:
        raise CalculationError("输出采样点数不能少于 3。")
    for value, name in (
        (data.m2_middle, "m2M"),
        (data.m2_long, "m2L"),
        (data.m4, "m4"),
    ):
        _nonzero(value, name)
    _nonzero(1.0 / data.m4 - 1.0, "后固定组焦距分母")
    _nonzero(1.0 - data.m3_middle, "f3 分母")

    f3 = (
        ((1.0 - data.m2_middle) * data.f2 - data.d23_middle)
        * data.m3_middle
        / (1.0 - data.m3_middle)
    )
    if f3 <= 0:
        raise CalculationError("推导得到的 f3 不是正值。")
    l2m = data.f2 * (1.0 / data.m2_middle - 1.0)
    l3mi = f3 * (1.0 - data.m3_middle)
    g1 = l2m - data.f2 * (1.0 / data.m2_long - 1.0)
    a_long = (1.0 - data.m2_long) * data.f2 + g1 - data.d23_middle
    d_long = (a_long + l3mi) ** 2 - 4.0 * (
        a_long * l3mi - (a_long - l3mi) * f3
    )
    sd_long = _root(d_long, "长焦补偿位移判别式")
    common = {
        "f3": f3,
        "l2m": l2m,
        "l3mi": l3mi,
        "g1": g1,
        "a_long": a_long,
    }

    candidates: List[Dict[str, Any]] = []
    errors: List[str] = []
    for long_sign in (1.0, -1.0):
        delta3_long = (-a_long - l3mi + long_sign * sd_long) / 2.0
        try:
            m3_long = (
                l3mi + delta3_long
            ) / _nonzero(a_long + delta3_long, "m3L 分母")
            c_inv = (
                data.f2
                * (data.m2_middle + 1.0 / data.m2_middle)
                + f3
                * (data.m3_middle + 1.0 / data.m3_middle)
            )
            product = data.m2_long * m3_long / data.target_zoom
            d_short = (
                c_inv**2 * product**2
                - 4.0
                * (data.f2 * product + f3)
                * (data.f2 * product + f3 * product**2)
            )
            sd_short = _root(d_short, "短焦变倍组判别式")
            denominator = _nonzero(
                2.0 * (data.f2 * product + f3), "m2S 分母"
            )
            short_roots = (
                (c_inv * product - sd_short) / denominator,
                (c_inv * product + sd_short) / denominator,
            )
        except CalculationError as exc:
            errors.append(str(exc))
            continue

        for root_index, m2_short in enumerate(short_roots):
            if m2_short >= 0:
                continue
            other_m2_short = short_roots[1 - root_index]
            try:
                candidates.append(
                    _build_candidate(
                        data,
                        common,
                        delta3_long,
                        m2_short,
                        other_m2_short,
                    )
                )
            except CalculationError as exc:
                errors.append(str(exc))

    if not candidates:
        detail = errors[-1] if errors else "没有负倍率短焦候选。"
        raise CalculationError(
            f"m3M={data.m3_middle:g} 在当前约束下没有贯穿长短焦端的连续单支解。{detail}"
        )
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[0]["result"]


def _result_value(result: Dict[str, Any], name: str, default: Any = None) -> Any:
    for row in result.get("关键结果", []):
        if row.get("项目") == name:
            return row.get("数值")
    return default


def _comparison_row(
    result: Dict[str, Any],
    m3_middle: float,
    mode: str,
) -> Dict[str, Any]:
    focal_by_symbol = {
        row["符号"]: row for row in result.get("组焦距", [])
    }
    motion = result.get("运动表", [])
    scale = _result_value(result, "毫米缩放系数")
    max_delta3 = max(
        (abs(row.get("Delta3_连续", 0.0)) for row in motion),
        default=None,
    )
    max_length = max(
        (
            row.get("d12", 0.0)
            + row.get("d23", 0.0)
            + row.get("d34", 0.0)
            for row in motion
        ),
        default=None,
    )
    group_length = result.get("求解信息", {}).get("max_group_length", max_length)
    branch = (
        result.get("求解信息", {}).get("branch", "换支")
        if mode == "单支连续"
        else "负根→正根"
    )
    return {
        "m3M": m3_middle,
        "求解方式": mode,
        "连续根": branch,
        "状态": result.get("综合状态", ""),
        "f1'": focal_by_symbol.get("f1'", {}).get("归一焦距"),
        "f2'": focal_by_symbol.get("f2'", {}).get("归一焦距"),
        "f3'": focal_by_symbol.get("f3'", {}).get("归一焦距"),
        "f4'": focal_by_symbol.get("f4'", {}).get("归一焦距"),
        "Delta2总行程": _result_value(result, "长焦到短焦总位移 Delta2"),
        "Delta3最大绝对值": (
            result.get("求解信息", {}).get("max_delta3", max_delta3)
        ),
        "最小d12": _result_value(result, "最小 d12"),
        "最小d23": _result_value(result, "最小 d23"),
        "最小d34": _result_value(result, "最小 d34"),
        "最小D": _result_value(result, "最小判别式 D"),
        "最大组间总长": group_length,
        "最大组间总长_mm": (
            None if group_length is None or scale is None else group_length * scale
        ),
        "实际终端倍率": _result_value(result, "计算终端倍率"),
        "像面漂移": _result_value(result, "像面漂移"),
        "说明": "",
    }


def scan_four_group_m3(
    data: FourGroupInputs,
    values: Sequence[float] = DEFAULT_M3_SCAN_VALUES,
    include_root_switch: bool = True,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    scan_values = [float(value) for value in values]
    if not any(abs(value - data.m3_middle) <= 1e-12 for value in scan_values):
        scan_values.append(float(data.m3_middle))
    scan_values.sort()
    if include_root_switch:
        switch_data = FourGroupInputs(
            **{**asdict(data), "m3_middle": -1.0}
        )
        try:
            rows.append(
                _comparison_row(
                    compute_four_group(switch_data),
                    -1.0,
                    "重根换支",
                )
            )
        except CalculationError as exc:
            rows.append(
                {
                    "m3M": -1.0,
                    "求解方式": "重根换支",
                    "连续根": "",
                    "状态": "无有效解",
                    "说明": str(exc),
                }
            )

    for value in scan_values:
        custom_data = FourGroupInputs(
            **{**asdict(data), "m3_middle": float(value)}
        )
        try:
            result = compute_four_group_single_branch(custom_data)
            rows.append(
                _comparison_row(
                    result,
                    float(value),
                    "单支连续",
                )
            )
        except CalculationError as exc:
            f3 = None
            try:
                f3 = (
                    ((1.0 - custom_data.m2_middle) * custom_data.f2 - custom_data.d23_middle)
                    * custom_data.m3_middle
                    / (1.0 - custom_data.m3_middle)
                )
            except (ZeroDivisionError, ValueError):
                pass
            rows.append(
                {
                    "m3M": float(value),
                    "求解方式": "单支连续",
                    "连续根": "",
                    "状态": "无连续单支解",
                    "f3'": f3,
                    "说明": str(exc),
                }
            )
    return rows
