import adsk.core, adsk.fusion
import math, traceback

_app      = None
_ui       = None
_handlers = []
CMD_ID    = 'threadTool_v1'


# ══════════════════════════════════════════════════════
#  工具函数
# Utility functions
# ══════════════════════════════════════════════════════

def _get_cyl_info(face):
    """提取圆柱面参数"""
    # Extract cylinder face parameters
    geom   = face.geometry
    axis   = geom.axis
    origin = geom.origin
    radius = geom.radius
    bb     = face.boundingBox
    corners = [
        bb.minPoint, bb.maxPoint,
        adsk.core.Point3D.create(bb.minPoint.x, bb.minPoint.y, bb.maxPoint.z),
        adsk.core.Point3D.create(bb.minPoint.x, bb.maxPoint.y, bb.minPoint.z),
        adsk.core.Point3D.create(bb.maxPoint.x, bb.minPoint.y, bb.minPoint.z),
    ]
    ax = adsk.core.Vector3D.create(axis.x, axis.y, axis.z)
    ax.normalize()
    projs = []
    for c in corners:
        v = adsk.core.Vector3D.create(c.x - origin.x, c.y - origin.y, c.z - origin.z)
        projs.append(v.x * ax.x + v.y * ax.y + v.z * ax.z)
    return radius, max(projs) - min(projs), min(projs), ax, origin


def _is_external_face(face):
    """判断圆柱面是外表面还是内表面（通过法线方向）"""
    # Determine whether the cylinder face is external or internal (via normal direction)
    g = face.geometry
    eva = face.evaluator
    (_, pt) = eva.getPointAtParameter(adsk.core.Point2D.create(0.5, 0.5))
    (_, normal) = eva.getNormalAtPoint(pt)
    rad = adsk.core.Vector3D.create(pt.x - g.origin.x, pt.y - g.origin.y, pt.z - g.origin.z)
    rad.normalize()
    return normal.dotProduct(rad) > 0


def _radial_dir(ax):
    """垂直于轴线的径向方向"""
    # Radial direction perpendicular to the axis
    ref = adsk.core.Vector3D.create(0, 1, 0)
    if abs(ax.dotProduct(ref)) > 0.9:
        ref = adsk.core.Vector3D.create(1, 0, 0)
    u = ref.crossProduct(ax)
    u.normalize()
    return u


def _build_helix(face, L, H, pts_per_turn, offset_cm=0):
    """生成螺旋线点列。offset_cm: 螺旋线起点距圆柱底端的偏移"""
    # Generate helix point sequence. offset_cm: offset from cylinder bottom to helix start
    radius, height, h_min, ax, origin = _get_cyl_info(face)
    P = 2.0 * (L - H)
    usable = height - offset_cm
    N = max(1, int(usable / P) - 1)  # 留一圈空间
    # Reserve one full turn of space
    hh = N * P
    h_start = h_min + offset_cm       # 偏移后的起始高度
    # Adjusted starting height after offset
    n_pts = min(max(4, int(N * pts_per_turn)), 400)
    u = _radial_dir(ax)
    v = ax.crossProduct(u)
    v.normalize()
    pts = adsk.core.ObjectCollection.create()
    for i in range(n_pts + 1):
        t = i / n_pts
        angle = t * N * 2 * math.pi
        hz = h_start + t * hh
        pts.add(adsk.core.Point3D.create(
            origin.x + hz * ax.x + radius * (math.cos(angle) * u.x + math.sin(angle) * v.x),
            origin.y + hz * ax.y + radius * (math.cos(angle) * u.y + math.sin(angle) * v.y),
            origin.z + hz * ax.z + radius * (math.cos(angle) * u.z + math.sin(angle) * v.z)))
    return pts, N, hh, P, radius


def _create_trapezoid(root, perp_plane, face, L, H, start_pt, is_external):
    """在路径垂面上画梯形截面。
    is_external=True  → 向外长肉（外螺纹）
    is_external=False → 向内长肉（内螺纹）
    """
    # Draw trapezoid cross-section on the plane perpendicular to the path
    _, _, h_min, ax, origin = _get_cyl_info(face)

    # 径向方向：start_pt 在轴上的投影点 → 消除偏移影响
    # Radial direction: project start_pt onto the axis → eliminate offset effect
    proj_len = ((start_pt.x - origin.x) * ax.x +
                (start_pt.y - origin.y) * ax.y +
                (start_pt.z - origin.z) * ax.z)
    axis_pt = adsk.core.Point3D.create(
        origin.x + proj_len * ax.x,
        origin.y + proj_len * ax.y,
        origin.z + proj_len * ax.z)
    rad_vec = adsk.core.Vector3D.create(
        start_pt.x - axis_pt.x,
        start_pt.y - axis_pt.y,
        start_pt.z - axis_pt.z)
    rad_vec.normalize()

    sign = 1.0 if is_external else -1.0

    # 梯形四点（世界坐标）
    # Four trapezoid points (world coordinates)
    B_world = start_pt
    A_world = adsk.core.Point3D.create(
        B_world.x + L * ax.x, B_world.y + L * ax.y, B_world.z + L * ax.z)
    P_bot_world = adsk.core.Point3D.create(
        B_world.x + sign * H * rad_vec.x + H * ax.x,
        B_world.y + sign * H * rad_vec.y + H * ax.y,
        B_world.z + sign * H * rad_vec.z + H * ax.z)
    P_top_world = adsk.core.Point3D.create(
        A_world.x + sign * H * rad_vec.x - H * ax.x,
        A_world.y + sign * H * rad_vec.y - H * ax.y,
        A_world.z + sign * H * rad_vec.z - H * ax.z)

    sketch = root.sketches.add(perp_plane)
    sketch.name = 'ThreadProfile'

    B_sk     = sketch.modelToSketchSpace(B_world)
    A_sk     = sketch.modelToSketchSpace(A_world)
    P_bot_sk = sketch.modelToSketchSpace(P_bot_world)
    P_top_sk = sketch.modelToSketchSpace(P_top_world)

    lines = sketch.sketchCurves.sketchLines
    lines.addByTwoPoints(B_sk, A_sk)
    lines.addByTwoPoints(A_sk, P_top_sk)
    lines.addByTwoPoints(P_top_sk, P_bot_sk)
    lines.addByTwoPoints(P_bot_sk, B_sk)

    short_len = max(0.0, L - 2.0 * H)
    return sketch, short_len


def _do_sweep(root, profile, helix_spline, guide_face):
    """扫掠：轮廓沿螺旋线路径，圆柱面做引导曲面"""
    # Sweep: profile along helix path, using cylinder face as guide surface
    path = root.features.createPath(helix_spline)
    sweeps = root.features.sweepFeatures
    sweep_input = sweeps.createInput(
        profile, path,
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    fv = adsk.fusion.BRepFaceVector()
    fv.push_back(guide_face)
    sweep_input.guideSurfaces = fv
    return sweeps.add(sweep_input)


# ══════════════════════════════════════════════════════
#  Command 事件处理器
# Command event handlers
# ══════════════════════════════════════════════════════

class MyCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd    = adsk.core.CommandCreatedEventArgs.cast(args).command
            inputs = cmd.commandInputs

            inputs.addTextBoxCommandInput('hdr', '',
                '<b>螺纹生成工具（外/内螺纹自动识别）</b><br/>'
                '选择圆柱外表面（螺杆）或圆孔内表面（螺母），自动识别。', 2, True)

            sel = inputs.addSelectionInput('face', '圆柱/圆孔面', '请点击圆柱外表面或圆孔内表面')
            sel.addSelectionFilter('CylindricalFaces')
            sel.setSelectionLimits(1, 1)

            inputs.addTextBoxCommandInput('sep1', '',
                '<b>── 梯形截面参数 ──</b>', 1, True)
            inputs.addValueInput('long_L', '长边 L（齿宽）', 'mm',
                adsk.core.ValueInput.createByString('8 mm'))
            inputs.addValueInput('trap_H', '梯形高度 H（径向牙高）', 'mm',
                adsk.core.ValueInput.createByString('3 mm'))

            inputs.addTextBoxCommandInput('sep2', '',
                '<b>── 路径参数 ──</b>', 1, True)
            inputs.addValueInput('ppt', '每圈采样点数', '',
                adsk.core.ValueInput.createByReal(16))
            inputs.addValueInput('offset', '端面偏移', 'mm',
                adsk.core.ValueInput.createByString('5 mm'))

            inputs.addTextBoxCommandInput('calc_info', '自动计算',
                '<i>选择面后自动计算...</i>', 6, True)

            on_exec     = MyExecuteHandler()
            on_change   = MyInputChangedHandler()
            on_validate = MyValidateHandler()
            on_destroy  = MyDestroyHandler()
            cmd.execute.add(on_exec)
            cmd.inputChanged.add(on_change)
            cmd.validateInputs.add(on_validate)
            cmd.destroy.add(on_destroy)
            _handlers.extend([on_exec, on_change, on_validate, on_destroy])
        except:
            _ui.messageBox(traceback.format_exc(), '初始化失败')


class MyInputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs   = adsk.core.InputChangedEventArgs.cast(args).inputs
            sel_inp  = adsk.core.SelectionCommandInput.cast(inputs.itemById('face'))
            L_inp    = adsk.core.ValueCommandInput.cast(inputs.itemById('long_L'))
            H_inp    = adsk.core.ValueCommandInput.cast(inputs.itemById('trap_H'))
            ppt_inp  = adsk.core.ValueCommandInput.cast(inputs.itemById('ppt'))
            off_inp  = adsk.core.ValueCommandInput.cast(inputs.itemById('offset'))
            calc_box = adsk.core.TextBoxCommandInput.cast(inputs.itemById('calc_info'))

            has_face = sel_inp.selectionCount > 0
            L_val    = L_inp.value
            H_val    = H_inp.value
            ppt      = max(4, int(ppt_inp.value))
            offset   = off_inp.value

            S = max(0.0, L_val - 2.0 * H_val)
            P = L_val + S
            lines = []

            if has_face and P > 0:
                face = adsk.fusion.BRepFace.cast(sel_inp.selection(0).entity)
                radius, height, _, _, _ = _get_cyl_info(face)
                is_ext = _is_external_face(face)
                typ_label = '外螺纹（螺杆）' if is_ext else '内螺纹（螺母）'
                dir_label = '向外长肉' if is_ext else '向内长肉'

                N = max(1, int((height - offset) / P) - 1)  # 留一圈空间
                # Reserve one full turn of space
                if N * P > height - offset and N > 1:
                    N -= 1
                act_h = N * P
                n_total = min(max(4, int(N * ppt)), 400) + 1 if N > 0 else 0

                lines.append(f'<b>类型:</b> {typ_label}（{dir_label}）')
                lines.append(f'<b>长边 L:</b> {L_val*10:.2f} mm　'
                             f'<b>短边 S:</b> {S*10:.2f} mm')
                lines.append(f'<b>梯形高度 H:</b> {H_val*10:.2f} mm　'
                             f'<b>螺距 P:</b> {P*10:.2f} mm')
                lines.append(f'<b>圆柱 R={radius*10:.2f} mm  H={height*10:.2f} mm</b>')
                lines.append(f'<b>转数:</b> {N}　螺旋高度={act_h*10:.2f} mm　偏移={offset*10:.1f} mm')
                if not is_ext and H_val >= radius:
                    lines.append('<font color="red">⚠ H 必须 < 圆孔半径</font>')
            else:
                lines.append('<i>选择圆柱面后自动识别内外螺纹...</i>')

            calc_box.formattedText = '<br/>'.join(lines)
        except:
            pass


class MyValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            ea     = adsk.core.ValidateInputsEventArgs.cast(args)
            inputs = ea.inputs
            sel   = adsk.core.SelectionCommandInput.cast(inputs.itemById('face'))
            L_inp = adsk.core.ValueCommandInput.cast(inputs.itemById('long_L'))
            H_inp = adsk.core.ValueCommandInput.cast(inputs.itemById('trap_H'))

            L_val = L_inp.value
            H_val = H_inp.value
            valid = (
                sel.selectionCount == 1
                and L_val > 0 and H_val > 0
                and (L_val - 2.0 * H_val) > 0
            )

            # 内螺纹额外校验：H < radius
            # Additional internal thread validation: H < radius
            if valid and sel.selectionCount == 1:
                face = adsk.fusion.BRepFace.cast(sel.selection(0).entity)
                if not _is_external_face(face):
                    radius, _, _, _, _ = _get_cyl_info(face)
                    if H_val >= radius:
                        valid = False

            ea.areInputsValid = valid
        except:
            pass


class MyExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inputs = adsk.core.CommandEventArgs.cast(args).command.commandInputs
            sel_inp = adsk.core.SelectionCommandInput.cast(inputs.itemById('face'))
            L_inp   = adsk.core.ValueCommandInput.cast(inputs.itemById('long_L'))
            H_inp   = adsk.core.ValueCommandInput.cast(inputs.itemById('trap_H'))
            ppt_inp = adsk.core.ValueCommandInput.cast(inputs.itemById('ppt'))

            face         = adsk.fusion.BRepFace.cast(sel_inp.selection(0).entity)
            L_cm         = L_inp.value
            H_cm         = H_inp.value
            pts_per_turn = max(4, int(ppt_inp.value))
            offset_cm    = inputs.itemById('offset').value
            is_external  = _is_external_face(face)

            design = adsk.fusion.Design.cast(_app.activeProduct)
            root   = design.rootComponent

            # ── 步骤1：螺旋线路径 ──
            # ── Step 1: Helix path ──
            pts, turns, helix_height, P, radius = _build_helix(
                face, L_cm, H_cm, pts_per_turn, offset_cm)
            sname = f'Helix_R{radius:.2f}_P{P:.2f}'
            sketch_helix = root.sketches.add(root.xYConstructionPlane)
            sketch_helix.name = sname
            sketch_helix.isComputeDeferred = True
            spline = sketch_helix.sketchCurves.sketchFittedSplines.add(pts)
            sketch_helix.isComputeDeferred = False

            # ── 步骤2：路径起点处垂直平面 ──
            # ── Step 2: Perpendicular plane at path start ──
            pi = root.constructionPlanes.createInput()
            pi.setByDistanceOnPath(spline, adsk.core.ValueInput.createByReal(0))
            perp_plane = root.constructionPlanes.add(pi)
            perp_plane.name = 'PerpPlane'

            # ── 步骤3：梯形截面 ──
            # ── Step 3: Trapezoid cross-section ──
            sketch_trap, short_cm = _create_trapezoid(
                root, perp_plane, face, L_cm, H_cm, pts[0], is_external)

            # ── 步骤4：获取轮廓 ──
            # ── Step 4: Get profile ──
            if sketch_trap.profiles.count == 0:
                raise RuntimeError('梯形未形成封闭轮廓，请检查 L > H')
            profile = sketch_trap.profiles.item(0)

            # ── 步骤5：Sweep ──
            # ── Step 5: Sweep ──
            sweep_feature = _do_sweep(root, profile, spline, face)

            _app.activeViewport.fit()

            S_mm = short_cm * 10
            typ_label = '外螺纹（螺杆）' if is_external else '内螺纹（螺母）'
            _ui.messageBox(
                f'✅ {typ_label} 生成完成！\n\n'
                f'【截面】 L={L_cm*10:.2f} mm  S={S_mm:.2f} mm  H={H_cm*10:.2f} mm\n'
                f'【螺旋】 P={P*10:.2f} mm  转数={turns}  高度={helix_height*10:.2f} mm\n'
                f'【结果】 实体={sweep_feature.bodies.count}',
                '生成成功')
        except:
            _ui.messageBox(traceback.format_exc(), '执行失败')


class MyDestroyHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        # 只清理命令执行相关的 handler，保留 commandCreated handler 以支持下次点击
        global _handlers
        _handlers[:] = [h for h in _handlers if isinstance(h, MyCommandCreatedHandler)]


# ══════════════════════════════════════════════════════
#  入口（Add-In 模式）
# Entry (Add-In mode)
# ══════════════════════════════════════════════════════

def run(_context: str):
    """注册命令到工具栏（Add-In 启动时调用）"""
    # Register command to toolbar (called when Add-In starts)
    global _app, _ui
    _app = adsk.core.Application.get()
    _ui  = _app.userInterface
    try:
        # 删除旧命令（如有）
        # Delete old command (if any)
        old = _ui.commandDefinitions.itemById(CMD_ID)
        if old:
            old.deleteMe()

        # 注册命令定义
        # Register command definition
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, 'ThreadFor3DPrinter',
            '适配3D打印的螺纹生成工具，自动识别内外表面')
        on_created = MyCommandCreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        # 添加到工具栏（SOLID → 创建 面板）
        # Add to toolbar (SOLID → Create panel)
        ws = _ui.workspaces.itemById('FusionSolidEnvironment')
        if ws:
            panel = ws.toolbarPanels.itemById('SolidCreatePanel')
            if panel:
                panel.controls.addCommand(cmd_def)
    except:
        if _ui:
            _ui.messageBox(traceback.format_exc(), '启动失败')


def stop(_context: str):
    """清理命令（Add-In 卸载时调用）"""
    # Clean up command (called when Add-In is unloaded)
    global _ui, _handlers
    _handlers.clear()
    try:
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except:
        pass
