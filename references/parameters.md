# 参数与输入格式

## 目录

- 通用字段
- 预设方案
- 三组两动组
- 四组两动组
- M3 扫描
- 命令行选项

## 通用字段

请求文件必须是 UTF-8 JSON 对象。

| 字段 | 含义 |
|---|---|
| `mode` | `preset`、`three_group` 或 `four_group` |
| `parameters` | 自定义方案的参数对象 |
| `solve_mode` | 四组求解方式：`auto`、`root_switch`、`single_branch` |
| `m3_scan` | `true`、扫描值数组或扫描配置对象 |
| `export` | 是否导出 Excel、CSV、PNG、JSON 和摘要，默认 `true` |
| `output_dir` | 可选结果父目录；命令行 `--output-dir` 优先 |

## 预设方案

只在用户明确要求基准方案或演示时使用。预设包括三组 `3x`、三组 `4x` 和四组 `16x`。

```json
{
  "mode": "preset",
  "preset": "16x",
  "m3_scan": true,
  "export": true
}
```

## 三组两动组

| 参数 | 含义与限制 |
|---|---|
| `nominal_zoom` | 名义变焦倍率，必须大于 0 |
| `f2` | 变倍组等效焦距，归一单位，必须小于 0 |
| `d23_long` | 长焦位置 G2 到 G3 主平面间距 |
| `f3` | 补偿组等效焦距，归一单位，必须大于 0 |
| `m2_long` | 长焦位置变倍组横向倍率，不能为 0 |
| `d12_short` | 短焦位置 G1 到 G2 主平面间距 |
| `total_travel` | 变倍组从长焦到短焦的总位移，符号按程序光轴约定 |
| `scale_mm_per_unit` | 可选毫米缩放系数；留空时只输出归一量 |
| `sample_count` | 运动表采样点数，默认 21，范围 5 到 501 |

```json
{
  "mode": "three_group",
  "parameters": {
    "nominal_zoom": 3.0,
    "f2": -1.0,
    "d23_long": 0.5,
    "f3": 1.2,
    "m2_long": -1.1,
    "d12_short": 0.5,
    "total_travel": -0.908,
    "scale_mm_per_unit": null,
    "sample_count": 21
  },
  "export": true
}
```

## 四组两动组

| 参数 | 含义与限制 |
|---|---|
| `m2_middle` | M 参考构型的变倍组倍率，不能为 0 |
| `f2` | 变倍组等效焦距，归一单位，必须小于 0 |
| `d23_middle` | M 参考构型 G2 到 G3 主平面间距 |
| `m2_long` | 长焦位置变倍组倍率，不能为 0 |
| `target_zoom` | 目标变焦倍率，必须大于 1 |
| `d12_short` | 短焦位置 G1 到 G2 主平面间距 |
| `d34_short` | 短焦位置 G3 到 G4 主平面间距 |
| `m4` | 后固定组倍率，不能为 0 或 1 |
| `short_system_focal_mm` | 短焦系统焦距，毫米，用于建立统一物理尺度 |
| `m3_middle` | M 参考构型补偿组倍率；重根换支取 `-1`，单支模式取其他负值 |
| `sample_count` | 运动表采样点数，默认 21，范围 5 到 501 |

重根换支示例：

```json
{
  "mode": "four_group",
  "solve_mode": "root_switch",
  "parameters": {
    "m2_middle": -1.0,
    "f2": -1.0,
    "d23_middle": 0.8,
    "m2_long": -1.2,
    "target_zoom": 16.0,
    "d12_short": 0.2,
    "d34_short": 0.154,
    "m4": 0.7,
    "short_system_focal_mm": 10.5,
    "m3_middle": -1.0,
    "sample_count": 21
  },
  "export": true
}
```

单支连续并扫描 M3 示例：

```json
{
  "mode": "four_group",
  "solve_mode": "single_branch",
  "parameters": {
    "m2_middle": -1.0,
    "f2": -1.0,
    "d23_middle": 0.8,
    "m2_long": -1.2,
    "target_zoom": 16.0,
    "d12_short": 0.2,
    "d34_short": 0.154,
    "m4": 0.7,
    "short_system_focal_mm": 10.5,
    "m3_middle": -0.8,
    "sample_count": 21
  },
  "m3_scan": {
    "values": [-1.2, -1.0, -0.8, -0.67, -0.5],
    "include_root_switch": true
  },
  "export": true
}
```

## M3 扫描

- `"m3_scan": true` 使用默认值 `[-2.0, -1.5, -1.2, -1.0, -0.8, -0.67, -0.5]`。
- 数组形式只指定扫描值，并默认加入 `m3=-1` 重根换支基准。
- 配置对象可通过 `include_root_switch` 控制是否加入该基准。
- 扫描值必须为负值且不能接近 0。无连续单支解的值会保留在结果中。

## 命令行选项

```text
--input <request.json>       必填，请求文件
--output-dir <folder>        导出结果父目录
--no-export                  只计算并返回摘要
--result-json <file.json>    额外保存完整计算结果
```