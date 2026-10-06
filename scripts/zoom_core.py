from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, sqrt
from typing import Any, Dict, List, Optional, Sequence


TOL = 1e-10


class CalculationError(ValueError):
    pass


@dataclass(frozen=True)
class ThreeGroupInputs:
    nominal_zoom: float
    f2: float
    d23_long: float
    f3: float
    m2_long: float
    d12_short: float
    total_travel: float
    scale_mm_per_unit: Optional[float] = None
    sample_count: int = 21


@dataclass(frozen=True)
class FourGroupInputs:
    m2_middle: float
    f2: float
    d23_middle: float
    m2_long: float
    target_zoom: float
    d12_short: float
    d34_short: float
    m4: float
    short_system_focal_mm: float
    m3_middle: float = -1.0
    sample_count: int = 21


def _nonzero(value: float, name: str) -> float:
    if abs(value) <= TOL:
        raise CalculationError(f"{name} 不能为 0。")
    return value


def _root(discriminant: float, name: str) -> float:
    if discriminant < -TOL:
        raise CalculationError(f"{name} 小于 0，没有实数解：{discriminant:.8g}")
    return sqrt(max(0.0, discriminant))


def _validate(data: Any) -> None:
    for name, value in asdict(data).items():
        if value is not None and not isfinite(value):
            raise CalculationError(f"{name} 必须是有限数值。")
    if data.sample_count < 5 or data.sample_count > 501:
        raise CalculationError("采样点数必须在 5 到 501 之间。")


def _mul(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> List[List[float]]:
    return [
        [a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]],
        [a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]],
    ]


def _matrix_metrics(focals: Sequence[float], gaps: Sequence[float]) -> Dict[str, float]:
    matrix = [[1.0, 0.0], [0.0, 1.0]]
    for index, focal in enumerate(focals):
        matrix = _mul([[1.0, 0.0], [-1.0 / _nonzero(focal, "组焦距"), 1.0]], matrix)
        if index < len(gaps):
            matrix = _mul([[1.0, gaps[index]], [0.0, 1.0]], matrix)
    a, c = matrix[0][0], matrix[1][0]
    efl = -1.0 / _nonzero(c, "系统光焦度")
    bfl = -a / c
    return {"系统焦距": efl, "像面位置": sum(gaps) + bfl}


def _key(name: str, value: Any, unit: str = "", note: str = "") -> Dict[str, Any]:
    return {"项目": name, "数值": value, "单位": unit, "说明": note}


def _input_rows(data: Any, labels: Dict[str, tuple]) -> List[Dict[str, Any]]:
    return [
        {"参数": labels.get(name, (name, ""))[0], "数值": value, "单位": labels.get(name, (name, ""))[1]}
        for name, value in asdict(data).items()
    ]


def _status(minimum_d: float, gaps: Sequence[tuple], image_drift: float, abcd_error: float, branch: bool) -> str:
    if minimum_d < -TOL:
        return "无实数解"
    for name, value in gaps:
        if value <= 0:
            return f"{name}<=0"
    if image_drift > 1e-7 or abcd_error > 1e-7:
        return "ABCD复核未通过"
    return "一阶通过（重根换支）" if branch else "一阶通过"


def _three_row(p: float, values: Dict[str, float], use_plus: bool) -> Dict[str, Any]:
    f1, f2, f3 = values["f1"], values["f2"], values["f3"]
    m2l, m3l = values["m2l"], values["m3l"]
    delta2 = values["travel"] * p
    m2 = 1.0 / _nonzero(1.0 / m2l - delta2 / f2, "变倍组倍率分母")
    b = -f2 / f3 * (1.0 / m2 - 1.0 / m2l + m2 - m2l) + 1.0 / m3l + m3l
    d = b * b - 4.0
    sd = _root(d, "补偿组判别式 D")
    plus, minus = (b + sd) / 2.0, (b - sd) / 2.0
    m3, other_m3 = (plus, minus) if use_plus else (minus, plus)
    delta3, other_delta3 = f3 * (m3 - m3l), f3 * (other_m3 - m3l)
    d12 = values["d12l"] + delta2
    d23 = values["d23l"] - delta2 + delta3
    metrics = _matrix_metrics([f1, f2, f3], [d12, d23])
    return {
        "位置": p, "Delta2": delta2, "m2": m2, "b": b,
        "D": 0.0 if abs(d) <= TOL else d,
        "m3_推荐": m3, "Delta3_推荐": delta3,
        "倍率_推荐": m2l * m3l / (m2 * m3),
        "d12": d12, "d23_推荐": d23,
        "m3_另一根": other_m3, "Delta3_另一根": other_delta3,
        "倍率_另一根": m2l * m3l / (m2 * other_m3),
        "d23_另一根": values["d23l"] - delta2 + other_delta3,
        "系统焦距": metrics["系统焦距"], "像面位置": metrics["像面位置"],
        "ABCD焦距残差": metrics["系统焦距"] - f1 * m2 * m3,
        "状态": "OK" if d12 > 0 and d23 > 0 else ("d12<=0" if d12 <= 0 else "d23<=0"),
    }


def compute_three_group(data: ThreeGroupInputs) -> Dict[str, Any]:
    _validate(data)
    if data.f2 >= 0 or data.f3 <= 0:
        raise CalculationError("三组模型要求 f2<0 且 f3>0。")
    if data.nominal_zoom <= 0:
        raise CalculationError("名义变焦倍率必须大于 0。")
    if data.scale_mm_per_unit is not None and data.scale_mm_per_unit <= 0:
        raise CalculationError("毫米缩放系数必须大于 0，或留空。")
    _nonzero(data.m2_long, "m2L")

    m3l = data.f3 / _nonzero(data.f2 * (1.0 - data.m2_long) - data.d23_long + data.f3, "m3L 分母")
    m2s = 1.0 / _nonzero(1.0 / data.m2_long - data.total_travel / data.f2, "m2S 分母")
    f1 = data.d12_short + data.f2 * (1.0 / m2s - 1.0)
    d12l = f1 - data.f2 * (1.0 / data.m2_long - 1.0)
    b0 = 1.0 / m3l + m3l
    sd0 = _root(b0 * b0 - 4.0, "长焦判别式")
    use_plus = abs((b0 + sd0) / 2.0 - m3l) <= abs((b0 - sd0) / 2.0 - m3l)
    values = {"f1": f1, "f2": data.f2, "f3": data.f3, "m2l": data.m2_long,
              "m3l": m3l, "d12l": d12l, "d23l": data.d23_long, "travel": data.total_travel}
    rows = []
    for i in range(data.sample_count):
        row = {"序号": i + 1, **_three_row(i / (data.sample_count - 1), values, use_plus)}
        if data.scale_mm_per_unit:
            scale = data.scale_mm_per_unit
            row.update({"Delta2_mm": row["Delta2"] * scale, "Delta3_mm": row["Delta3_推荐"] * scale,
                        "d12_mm": row["d12"] * scale, "d23_mm": row["d23_推荐"] * scale})
        rows.append(row)
    if abs(rows[0]["m3_推荐"] - m3l) > 1e-7:
        raise CalculationError("推荐根没有与长焦参考点连续。")

    min_d = min(row["D"] for row in rows)
    min_d12 = min(row["d12"] for row in rows)
    min_d23 = min(row["d23_推荐"] for row in rows)
    drift = max(row["像面位置"] for row in rows) - min(row["像面位置"] for row in rows)
    abcd = max(abs(row["ABCD焦距残差"]) for row in rows)
    final_zoom = rows[-1]["倍率_推荐"]
    overall = _status(min_d, [("d12", min_d12), ("d23", min_d23)], drift, abcd, False)
    endpoints = []
    for name, index in zip(["长焦", "中焦", "短焦"], [0, (data.sample_count - 1) // 2, data.sample_count - 1]):
        row = rows[index]
        endpoint = {"位置名称": name, **{k: row[k] for k in ["位置", "Delta2", "m2", "系统焦距", "像面位置"]},
                    "Delta3": row["Delta3_推荐"], "m3": row["m3_推荐"], "相对倍率": row["倍率_推荐"],
                    "d12": row["d12"], "d23": row["d23_推荐"]}
        if data.scale_mm_per_unit:
            endpoint.update({"Delta2_mm": row["Delta2_mm"], "Delta3_mm": row["Delta3_mm"],
                             "d12_mm": row["d12_mm"], "d23_mm": row["d23_mm"]})
        endpoints.append(endpoint)
    focals = [{"光学组": "前固定组", "符号": "f1'", "归一焦距": f1},
              {"光学组": "变倍组", "符号": "f2'", "归一焦距": data.f2},
              {"光学组": "补偿组", "符号": "f3'", "归一焦距": data.f3}]
    if data.scale_mm_per_unit:
        for row in focals:
            row["物理焦距_mm"] = row["归一焦距"] * data.scale_mm_per_unit
    keys = [
        _key("长焦补偿组倍率 m3L", m3l, "无量纲", "由长焦共轭关系求得"),
        _key("短焦变倍组倍率 m2S", m2s, "无量纲", "由总位移反算"),
        _key("前固定组焦距 f1'", f1, "归一单位"), _key("长焦间隔 d12L", d12l, "归一单位"),
        _key("计算终端倍率", final_zoom, "x"),
        _key("相对名义倍率偏差", final_zoom / data.nominal_zoom - 1.0, "%"),
        _key("最小判别式 D", min_d), _key("最小 d12", min_d12, "归一单位"),
        _key("最小 d23", min_d23, "归一单位"), _key("像面漂移", drift, "归一单位", "ABCD 复核"),
        _key("最大 ABCD 焦距残差", abcd, "归一单位"), _key("综合状态", overall),
    ]
    labels = {"nominal_zoom": ("名义变焦倍率", "x"), "f2": ("变倍组焦距 f2'", "归一单位"),
              "d23_long": ("长焦间隔 d23L", "归一单位"), "f3": ("补偿组焦距 f3'", "归一单位"),
              "m2_long": ("长焦变倍组倍率 m2L", "无量纲"), "d12_short": ("短焦间隔 d12S", "归一单位"),
              "total_travel": ("变倍组总位移 Delta2S", "归一单位"),
              "scale_mm_per_unit": ("毫米缩放系数", "mm/归一单位"), "sample_count": ("输出采样点数", "点")}
    return {"方案": f"三组/两动组 {data.nominal_zoom:g}x", "模型": "三组结构（两个移动组）",
            "输入参数": _input_rows(data, labels), "关键结果": keys, "组焦距": focals,
            "长中短焦": endpoints, "运动表": rows, "物理结构": [], "综合状态": overall,
            "说明": ["焦距为光学组等效焦距，d12/d23 为组主平面间距。",
                     "推荐根自动选择为与长焦参考点连续的数学支路。",
                     "填写毫米缩放系数后，全部长度使用同一系数换算。"]}


def _four_row(p: float, v: Dict[str, float]) -> Dict[str, Any]:
    delta2 = v["travel"] * p
    m2 = 1.0 / _nonzero(1.0 / v["m2l"] - delta2 / v["f2"], "变倍组倍率分母")
    b = -v["f2"] / v["f3"] * (1.0 / m2 - 1.0 / v["m2l"] + m2 - v["m2l"]) + 1.0 / v["m3l"] + v["m3l"]
    d = b * b - 4.0
    sd = _root(d, "补偿组判别式 D")
    plus, minus = (b + sd) / 2.0, (b - sd) / 2.0
    m3 = minus if m2 <= v["m2m"] else plus
    delta3 = v["f3"] * (m3 - v["m3l"])
    d12, d23, d34 = v["d12l"] + delta2, v["d23l"] - delta2 + delta3, v["d34l"] - delta3
    metrics = _matrix_metrics([v["f1"], v["f2"], v["f3"], v["f4"]], [d12, d23, d34])
    status = "OK" if min(d12, d23, d34) > 0 else ("d12<=0" if d12 <= 0 else "d23<=0" if d23 <= 0 else "d34<=0")
    return {"位置": p, "Delta2": delta2, "m2": m2, "b": b, "D": 0.0 if abs(d) <= TOL else d,
            "m3_正根": plus, "m3_负根": minus, "m3_连续": m3, "Delta3_连续": delta3,
            "相对倍率": v["m2l"] * v["m3l"] / (m2 * m3), "d12": d12, "d23": d23, "d34": d34,
            "系统焦距": metrics["系统焦距"], "像面位置": metrics["像面位置"],
            "ABCD焦距残差": metrics["系统焦距"] - v["f1"] * m2 * m3 * v["m4"], "状态": status}


def compute_four_group(data: FourGroupInputs) -> Dict[str, Any]:
    _validate(data)
    if abs(data.m3_middle + 1.0) > 1e-9:
        raise CalculationError("四组换支模型要求中焦 m3M 固定为 -1。")
    if data.f2 >= 0 or data.target_zoom <= 1 or data.short_system_focal_mm <= 0:
        raise CalculationError("要求 f2<0、目标倍率>1、短焦系统焦距>0。")
    for value, name in [(data.m2_middle, "m2M"), (data.m2_long, "m2L"), (data.m4, "m4")]:
        _nonzero(value, name)
    _nonzero(1.0 / data.m4 - 1.0, "后固定组焦距分母")

    f3 = ((1.0 - data.m2_middle) * data.f2 - data.d23_middle) * data.m3_middle / (1.0 - data.m3_middle)
    if f3 <= 0:
        raise CalculationError("推导得到的 f3 不是正值。")
    l2m = data.f2 * (1.0 / data.m2_middle - 1.0)
    l3mi = f3 * (1.0 - data.m3_middle)
    g1 = l2m - data.f2 * (1.0 / data.m2_long - 1.0)
    a_l = (1.0 - data.m2_long) * data.f2 + g1 - data.d23_middle
    d_l = (a_l + l3mi) ** 2 - 4.0 * (a_l * l3mi - (a_l - l3mi) * f3)
    delta3_l = (-a_l - l3mi + _root(d_l, "长焦补偿位移判别式")) / 2.0
    m3l = (l3mi + delta3_l) / _nonzero(a_l + delta3_l, "m3L 分母")
    d23l = data.d23_middle - g1 - delta3_l
    c_inv = data.f2 * (data.m2_middle + 1.0 / data.m2_middle) + f3 * (data.m3_middle + 1.0 / data.m3_middle)
    product = data.m2_long * m3l / data.target_zoom
    d_s = c_inv**2 * product**2 - 4.0 * (data.f2 * product + f3) * (data.f2 * product + f3 * product**2)
    sd_s = _root(d_s, "短焦变倍组判别式")
    den_s = _nonzero(2.0 * (data.f2 * product + f3), "m2S 分母")
    m2s, other_m2s = (c_inv * product - sd_s) / den_s, (c_inv * product + sd_s) / den_s
    if m2s >= 0:
        raise CalculationError("推荐短焦变倍组倍率不是负值。")
    m3s = product / _nonzero(m2s, "m2S")
    travel = -g1 + (l2m - data.f2 * (1.0 / m2s - 1.0))
    _nonzero(travel, "总位移")
    delta3s = f3 * (m3s - m3l)
    f1 = data.d12_short + data.f2 * (1.0 / m2s - 1.0)
    f4 = (f3 * (1.0 - m3s) - data.d34_short) / _nonzero(1.0 / data.m4 - 1.0, "f4 分母")
    if f1 <= 0 or f4 <= 0:
        raise CalculationError("推导得到的固定组焦距不是正值。")
    fs_norm = f1 * m2s * m3s * data.m4
    scale = data.short_system_focal_mm / _nonzero(fs_norm, "归一短焦系统焦距")
    d12l, d34l = data.d12_short - travel, data.d34_short + delta3s
    switch = -g1 / travel
    if not 0.0 <= switch <= 1.0:
        raise CalculationError("精确重根换支点不在行程内。")
    v = {"f1": f1, "f2": data.f2, "f3": f3, "f4": f4, "m2m": data.m2_middle, "m2l": data.m2_long,
         "m3l": m3l, "m4": data.m4, "d12l": d12l, "d23l": d23l, "d34l": d34l, "travel": travel}
    rows = []
    for i in range(data.sample_count):
        row = {"序号": i + 1, **_four_row(i / (data.sample_count - 1), v)}
        row.update({"Delta2_mm": row["Delta2"] * scale, "Delta3_mm": row["Delta3_连续"] * scale,
                    "d12_mm": row["d12"] * scale, "d23_mm": row["d23"] * scale, "d34_mm": row["d34"] * scale})
        rows.append(row)
    switch_d = _four_row(switch, v)["D"]
    switch_d = 0.0 if abs(switch_d) <= 1e-8 else switch_d
    min_d = min(min(row["D"] for row in rows), switch_d)
    min_gaps = [min(row[name] for row in rows) for name in ["d12", "d23", "d34"]]
    drift = max(row["像面位置"] for row in rows) - min(row["像面位置"] for row in rows)
    abcd = max(abs(row["ABCD焦距残差"]) for row in rows)
    overall = _status(min_d, list(zip(["d12", "d23", "d34"], min_gaps)), drift, abcd, True)
    endpoints = []
    for name, index in zip(["长焦", "中焦", "短焦"], [0, (data.sample_count - 1) // 2, data.sample_count - 1]):
        row = rows[index]
        endpoints.append({"位置名称": name, "位置": row["位置"], "Delta2": row["Delta2"], "Delta3": row["Delta3_连续"],
                          "m2": row["m2"], "m3": row["m3_连续"], "相对倍率": row["相对倍率"],
                          "d12": row["d12"], "d23": row["d23"], "d34": row["d34"],
                          "系统焦距": row["系统焦距"], "像面位置": row["像面位置"],
                          "Delta2_mm": row["Delta2_mm"], "Delta3_mm": row["Delta3_mm"],
                          "d12_mm": row["d12_mm"], "d23_mm": row["d23_mm"], "d34_mm": row["d34_mm"]})
    focals = [{"光学组": name, "符号": symbol, "归一焦距": focal, "物理焦距_mm": focal * scale}
              for name, symbol, focal in [("前固定组", "f1'", f1), ("变倍组", "f2'", data.f2),
                                           ("补偿组", "f3'", f3), ("后固定组", "f4'", f4)]]
    physical = [{"位置": row["位置名称"], "f1_mm": f1 * scale, "d12_mm": row["d12_mm"],
                 "f2_mm": data.f2 * scale, "d23_mm": row["d23_mm"], "f3_mm": f3 * scale,
                 "d34_mm": row["d34_mm"], "f4_mm": f4 * scale} for row in endpoints]
    final_zoom = rows[-1]["相对倍率"]
    keys = [_key("补偿组焦距 f3'", f3, "归一单位"), _key("长焦补偿组倍率 m3L", m3l),
            _key("长焦间隔 d23L", d23l, "归一单位"), _key("短焦变倍组倍率 m2S", m2s),
            _key("短焦变倍组另一根", other_m2s), _key("长焦到短焦总位移 Delta2", travel, "归一单位"),
            _key("短焦补偿组倍率 m3S", m3s), _key("短焦补偿位移 Delta3", delta3s, "归一单位"),
            _key("前固定组焦距 f1'", f1, "归一单位"), _key("后固定组焦距 f4'", f4, "归一单位"),
            _key("归一短焦系统焦距", fs_norm, "归一单位"), _key("毫米缩放系数", scale, "mm/归一单位"),
            _key("计算长焦系统焦距", f1 * data.m2_long * m3l * data.m4 * scale, "mm"),
            _key("计算终端倍率", final_zoom, "x"), _key("相对目标倍率偏差", final_zoom / data.target_zoom - 1.0, "%"),
            _key("精确重根换支位置", switch, "行程比例"), _key("最小判别式 D", min_d),
            _key("最小 d12", min_gaps[0], "归一单位"), _key("最小 d23", min_gaps[1], "归一单位"),
            _key("最小 d34", min_gaps[2], "归一单位"), _key("像面漂移", drift, "归一单位", "ABCD 复核"),
            _key("最大 ABCD 焦距残差", abcd, "归一单位"), _key("综合状态", overall)]
    labels = {"m2_middle": ("中焦变倍组倍率 m2M", "无量纲"), "f2": ("变倍组焦距 f2'", "归一单位"),
              "d23_middle": ("中焦间隔 d23M", "归一单位"), "m2_long": ("长焦变倍组倍率 m2L", "无量纲"),
              "target_zoom": ("目标变焦倍率", "x"), "d12_short": ("短焦间隔 d12S", "归一单位"),
              "d34_short": ("短焦间隔 d34S", "归一单位"), "m4": ("后固定组倍率 m4", "无量纲"),
              "short_system_focal_mm": ("短焦系统焦距", "mm"), "m3_middle": ("中焦补偿组倍率 m3M", "固定 -1"),
              "sample_count": ("输出采样点数", "点")}
    return {"方案": f"四组/两动组 {data.target_zoom:g}x", "模型": "四组结构（两个移动组）",
            "输入参数": _input_rows(data, labels), "关键结果": keys, "组焦距": focals,
            "长中短焦": endpoints, "运动表": rows, "物理结构": physical, "综合状态": overall,
            "说明": ["焦距为光学组等效焦距，d12/d23/d34 为组主平面间距。",
                     "中焦 m3M 固定为 -1；重根前用负根，重根后用正根。",
                     "物理尺寸由短焦系统焦距自动建立统一毫米尺度。"]}


THREE_X_PRESET = ThreeGroupInputs(3.0, -1.0, 0.5, 1.2, -1.1, 0.5, -0.908, None, 21)
FOUR_X_PRESET = ThreeGroupInputs(4.0, -1.0, 0.5, 1.2, -1.1, 0.5, -1.205, None, 21)
SIXTEEN_X_PRESET = FourGroupInputs(-1.0, -1.0, 0.8, -1.2, 16.0, 0.2, 0.154, 0.7, 10.5, -1.0, 21)


def calculate_preset(name: str) -> Dict[str, Any]:
    if name == "3x":
        return compute_three_group(THREE_X_PRESET)
    if name == "4x":
        return compute_three_group(FOUR_X_PRESET)
    if name == "16x":
        return compute_four_group(SIXTEEN_X_PRESET)
    raise CalculationError(f"未知预设：{name}")
