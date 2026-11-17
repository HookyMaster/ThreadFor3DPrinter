# Fusion 360 3D 打印螺纹生成器

[![Release](https://img.shields.io/github/v/release/HookyMaster/ThreadFor3DPrinter)](https://github.com/HookyMaster/ThreadFor3DPrinter/releases/latest)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Platform](https://img.shields.io/badge/Autodesk-Fusion-orange)

[English README](README.md) · [下载最新版本](https://github.com/HookyMaster/ThreadFor3DPrinter/releases/latest/download/ThreadFor3DPrinter-v3.0.0.zip)

<img src="icon-v4.png" alt="用于生成适合 3D 打印的内外梯形螺纹的 Fusion 360 附加模块" width="160">

**ThreadFor3DPrinter** 是一个 Autodesk Fusion 附加模块，用于生成适合 3D 打印的粗牙梯形**外螺纹和内螺纹**。选择圆柱面后，工具会自动判断它属于螺杆外表面还是螺母/圆孔内表面。

## 主要功能

- 同时支持螺杆外螺纹和螺母/圆孔内螺纹。
- 使用适合 3D 打印的梯形牙型，**牙侧角可在 5°–45° 范围内调整**。
- 自动识别内、外圆柱面。
- 支持调整牙底宽度、牙高、牙侧角、采样精度和端面偏移。
- 自动计算牙顶宽度，并保留最小 `0.2 mm` 牙顶平宽，避免截面自相交。
- 可选**螺纹收口**：螺纹入口/出口各生成 1/8 圈渐变（牙高+牙宽 10%↔100%），便于螺母/螺杆对位旋入，且两端更易打印；可在对话框中关闭。
- 显示估算的螺旋总长和样条线点数，并对高风险采样设置给出提示。
- 生成完成后给出配合螺母或螺杆的建议直径及打印间隙。
- 支持 Windows 和 macOS 上的 Autodesk Fusion。

## 效果展示

| 外螺纹 | 内螺纹 | 旋盖罐示例 |
| --- | --- | --- |
| ![Fusion 360 外螺纹生成器完成适合 3D 打印的梯形螺杆螺纹](docs/images/fusion-360-external-thread-generator.png) | ![Fusion 360 内螺纹生成器完成螺母圆孔螺纹](docs/images/fusion-360-internal-thread-generator.png) | ![Fusion 360 中带配套螺纹盖的旋盖罐模型](docs/images/Screw-Top%20Jar.png) |

### 内外螺纹配合剖面

![Fusion 360 剖面分析显示内外 3D 打印螺纹的配合效果](docs/images/internal-external-thread-section.png)

### 螺纹收口特写

![Fusion 360 中 3D 打印螺纹的入口/出口收口特写](docs/images/收口1.png)

螺纹入口/出口各 1/8 圈将梯形截面（牙高+牙宽同步）从 10% 渐变到全尺寸，两端形成尖锥形导入。配合件可直接滑入收口定位，无需反复找牙起始位置；牙型渐变的两端比垂直薄壁更易打印——FDM 切片下垂直薄尖几乎会消失。对话框里的"螺纹收口"复选框（默认勾选）控制该行为；取消勾选则生成完整牙高的普通螺纹。

## 安装所需文件

请将以下三个文件放在同一个文件夹中：

```text
ThreadFor3DPrinter/
├── ThreadFor3DPrinter.py
├── ThreadFor3DPrinter.manifest
└── icon-v4.png
```

清单文件已经将 `icon-v4.png` 设置为 Fusion“脚本和附加模块”窗口中的图标。

## 安装方法

### Windows

将完整的 `ThreadFor3DPrinter` 文件夹复制到：

```text
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
```

### macOS

将完整的 `ThreadFor3DPrinter` 文件夹复制到：

```text
~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/
```

也可以在 Fusion 中打开 **实用程序 > 附加模块 > 脚本和附加模块**，切换到 **附加模块** 页，点击绿色 **+**，然后选择 `ThreadFor3DPrinter` 文件夹。

## 启动附加模块

1. 打开 Fusion，进入 **设计** 工作区。
2. 打开 **实用程序 > 附加模块 > 脚本和附加模块**。
3. 切换到 **附加模块** 页。
4. 选择 **ThreadFor3DPrinter**，点击 **运行**。
5. 启动成功后，**实体 > 创建** 面板中会出现 **ThreadFor3DPrinter** 命令。

如果希望每次启动 Fusion 时自动加载，可在“脚本和附加模块”窗口中启用 **启动时运行**。

## 建模准备

- 生成外螺纹：先创建实体圆柱，再选择圆柱的外侧圆柱面。
- 生成内螺纹：先创建圆孔，再选择圆孔的内侧圆柱面。
- 目标必须是真正的 BRep 圆柱面；不支持圆锥面、网格面、分段近似面或任意曲面。
- 圆柱轴向长度需要能够容纳螺纹尺寸和端面偏移。

## 操作方法

1. 从 **实体 > 创建** 中运行 **ThreadFor3DPrinter**。
2. 点击 **圆柱/圆孔面**，然后选择且仅选择一个圆柱面。
3. 在“自动计算”区域确认识别结果：
   - **外螺纹（螺杆）**：梯形牙型向外生长。
   - **内螺纹（螺母）**：梯形牙型向内生长。
4. 设置螺纹参数：
   - **长边 L（牙底宽度）**：梯形牙型根部沿轴向的宽度，默认 `3 mm`。
   - **梯形高度 H（牙高）**：螺纹牙型的径向高度/深度，默认 `1 mm`。
   - **牙侧角 α**：牙侧面与螺纹轴线之间的夹角，可在 `5°–45°` 范围内调整。
   - **每圈采样点数**：螺旋线的采样精度，默认 `16`，最小值为 `4`。对于大直径，工具会自动提高该值，使螺旋路径与圆柱面的偏差不超过牙高的四分之一；你输入的值作为下限使用。
   - **端面偏移**：从圆柱端面到螺旋线起点的距离，默认 `0 mm`。
   - **螺纹收口**：勾选（默认）后，螺纹入口/出口各生成 1/8 圈渐变收口（牙高+牙宽 10%↔100%），便于螺母/螺杆对位旋入，且两端更易打印；取消勾选则生成完整牙高的普通螺纹（旧版行为）。
   - **合并到圆柱体**：勾选（默认）后，螺纹体会通过布尔合并与所选圆柱体合并为单一实体；取消勾选则螺纹与圆柱体保持为两个独立实体。合并可消除放大时两实体之间的接缝。
   - **显示高级选项**：勾选后显示“路径偏差系数”输入框。
   - **路径偏差系数**（高级选项）：控制螺旋拟合样条偏离圆柱面的允许偏差，以牙高 H 的比例表示（允许偏差 = 系数 × H）。默认 `0.25`（即偏差不超过牙高的四分之一），推荐范围 `0.1–0.5`。系数越小，每圈采样点越多、牙侧面越光滑，但生成越慢；过大可能导致扫掠失败。鼠标悬浮在该输入框上可查看详细说明。
5. 检查工具自动计算的**牙顶宽度 S（牙顶平宽）**、螺距、圈数、螺旋高度和总长、样条线点数、圆柱尺寸及内外螺纹类型。H 和牙侧角下方的“截面状态”会直接显示自动修正提示。
6. 点击 **确定**。工具会创建螺旋路径、梯形截面，并扫掠生成螺纹实体。

## 参数约束

工具按以下公式计算：

```text
单侧轴向退让量 A = H / tan(α)
牙顶宽度 S       = L - 2A
螺距 P           = L + S = 2(L - A)
最大牙高 H       = (L - 0.2 mm) × tan(α) / 2
```

`L` 为牙底宽度，`S` 为牙顶宽度（牙顶平宽），`H` 为径向牙高，`A` 为每侧牙面的轴向退让量。修改 `H` 或 `α` 后，工具会重新计算 `S` 和螺距。为保证梯形牙型有效，`S` 最小为 `0.2 mm`；如果输入的牙高会使牙顶宽度低于该值，工具会在保持所选牙侧角的前提下，将 `H` 自动降低到允许的最大值。自动降低 `H` 不是程序出错，而是为避免牙型截面自相交而采取的几何保护。

参数必须满足：

- `L > 0.2 mm`
- `H > 0`
- `5° ≤ α ≤ 45°`
- `S = L - 2H / tan(α) ≥ 0.2 mm`
- 生成内螺纹时，`H` 必须小于圆孔半径。

工具会在轴向预留大约一整圈的空间，因此实际生成圈数可能小于“圆柱长度 ÷ 螺距”的简单计算结果。

## 生成后的处理

扫掠结果会生成为一个**新实体**。请使用 Fusion 的 **组合** 命令进行后续处理：

- 外螺纹：使用 **合并**，将螺纹实体与圆柱连接。
- 内螺纹：同样使用 **合并**，将螺纹实体与零件主体连接。

生成完成后，对话框还会显示配合零件的建议直径。该数值仅作为起点，请使用短测试件验证建议的单侧 `0.2 mm` 打印间隙（常用范围 `0.2–0.4 mm`）。

对于需要互相配合的 3D 打印螺纹，应根据打印机、材料、层高和喷嘴尺寸预留间隙。建议先打印一段短测试件，再制作最终零件。

## 无界面自动化 API

`ThreadFor3DPrinter.py` 提供两个公共 Python 函数，无需打开或操作
Fusion 命令对话框即可生成螺纹。

### 直接传入圆柱面

```python
import ThreadFor3DPrinter as thread_tool

result = thread_tool.generate_thread(
    face=target_cylindrical_face,
    tooth_width_mm=1.5,
    tooth_height_mm=0.5,
    end_offset_mm=1.0,
    samples_per_turn=16,
    join_to_target=True,
    feature_name='Lid_Internal_Thread',
    max_turns_per_sweep=4,
    flank_angle_degrees=30,
    deviation_ratio=0.25,
    enable_lead=True,
)
print(result)
```

### 使用 JSON 和实体令牌

```python
payload = {
    'face_token': target_cylindrical_face.entityToken,
    'tooth_width_mm': 1.5,
    'tooth_height_mm': 0.5,
    'end_offset_mm': 1.0,
    'samples_per_turn': 16,
    'join_to_target': True,
    'feature_name': 'Lid_Internal_Thread',
    'max_turns_per_sweep': 4,
    'flank_angle_degrees': 30,
    'deviation_ratio': 0.25,
    'enable_lead': True,
}

result = thread_tool.generate_thread_from_json(payload)
```

`generate_thread_from_json` 可以接收 Python 字典或 JSON 对象字符串。
返回值是可直接序列化为 JSON 的字典，包含：

- 检测到的螺纹类型（`external` 或 `internal`）；
- 牙底宽度、牙顶宽度、牙高、牙侧角和联动计算出的螺距；
- 圈数和实际生成的螺纹长度；
- 圆柱半径和高度；
- 采样数及端面偏移；
- 扫掠段数及每段最大圈数；
- 是否已与目标实体合并；
- Fusion 时间线组名称；
- 结果实体令牌。

### 自动化说明

- `face` 必须是真实的圆柱 BRep 面。
- 公共 API 的尺寸单位均为毫米。
- `flank_angle_degrees` 必须在 `5` 到 `45` 之间，默认值为 `45`。
- 计算得到的牙顶宽度 `tooth_width_mm - 2 * tooth_height_mm / tan(flank_angle_degrees)` 必须至少为 `0.2 mm`。
- `samples_per_turn` 的最小有效值为 `4`。该值作为下限使用：对于大半径
  圆柱，工具会自动提高每圈采样数，使拟合螺旋线与圆柱面的偏差不超过
  牙高的四分之一，从而让扫掠始终贴合引导面，避免 `ASM_SWEEP_ILLEGAL_SURFACE`。
  每圈采样数的有效值上限为 `360`。若自适应后的每圈密度会使总采样点数
  超过 `20000`，工具会减少圈数而非降低采样密度，以保证保留的每一圈都有
  完整精度。
- `max_turns_per_sweep` 默认为 `4`。长螺纹采用分段扫掠，以避免
  Fusion 几何内核在长路径上失败；螺距联动公式保持不变。
- `deviation_ratio` 默认值为 `0.25`（即 `HELIX_DEVIATION_TOLERANCE_RATIO`），
  取值范围为 `(0, 1]`。它表示螺旋拟合样条允许偏离圆柱面的最大距离占牙高
  H 的比例（允许偏差 = `deviation_ratio × tooth_height_mm`）。值越小，每圈
  采样点越多、牙侧面越光滑，但生成越慢；值过大可能导致
  `ASM_SWEEP_ILLEGAL_SURFACE`。推荐范围 `0.1–0.5`。返回结果字典中的
  `deviation_ratio` 字段为实际生效值。
- `enable_lead` 默认为 `True`：在螺纹入口/出口各生成 1/8 圈渐变收口
  （牙高+牙宽 10%↔100%），更易旋入且两端更易打印；设为 `False` 则生成
  完整牙高的普通螺纹（旧版行为）。
- 每次生成只创建一个螺旋草图、一个截面构造平面和一个截面草图。
  后续扫掠段在各自路径起点独立绘制梯形截面，并始终保留圆柱导向面；
  相邻段在接缝处有少量体积重叠，保证布尔合并稳定。
- 每次成功生成产生的所有特征都会放入一个名为
  `<feature_name>_Generation` 的 Fusion 时间线组；当 Fusion 允许分组时才会
  创建。如果无法分组（例如对应的时间线区间内已存在分组），生成仍会成功，
  只是跳过时间线分组这一步。
- `join_to_target=False` 保持 GUI 的原有行为，生成独立螺纹实体。
- `join_to_target=True` 会将螺纹合并到选中的目标实体。
- `feature_name` 用作草图、构造平面、扫掠、实体和组合特征的名称前缀。

## 常见问题

- **“确定”按钮不可用：** 确认只选择了一个圆柱面，并检查参数是否满足上述约束。
- **提示内螺纹牙高错误：** 减小 `H`，确保它小于圆孔半径。
- **H 被自动降低：** 当前 H 与牙侧角会使牙顶宽度小于 `0.2 mm`；工具采用允许的最大安全牙高，以避免截面自相交。
- **工具栏中没有命令：** 在“脚本和附加模块”中重新运行附加模块，或重启 Fusion。
- **图标没有更新：** 关闭并重新打开“脚本和附加模块”窗口，或重启 Fusion。
- **螺纹看起来有棱角：** 增加“每圈采样点数”。数值越高，几何量和计算时间越大；螺旋线总采样点数上限为 20000，超过后会减少圈数而非降低采样密度。
- **长螺纹、大直径时圈数比预期少：** 自适应后的每圈采样已达到 20000 点预算上限，为保证路径贴合圆柱而自动减少了圈数。请稍微降低“每圈采样点数”，或为螺纹提供更多可用长度。
- **扫掠失败（ASM_SWEEP_ILLEGAL_SURFACE）：** 通常是螺旋路径无法足够贴近圆柱面。工具已会根据半径自适应采样；若仍然失败，请稍微降低“每圈采样点数”，或缩短螺纹（减小高度或增大端面偏移）。

## 卸载

先在“脚本和附加模块”中停止附加模块，关闭 Fusion，然后从 AddIns 目录中删除 `ThreadFor3DPrinter` 文件夹。
