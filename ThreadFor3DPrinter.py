import adsk.core, adsk.fusion
import json, math, traceback

_app      = None
_ui       = None
_handlers = []
CMD_ID    = 'threadTool_pitch_crest_test_v1'
CMD_NAME  = 'ThreadFor3DPrinter [TEST P/S]'
PRIVACY_URL = 'https://github.com/HookyMaster/ThreadFor3DPrinter/blob/master/docs/PRIVACY.md'
MIN_FLANK_ANGLE_DEG = 5.0
MAX_FLANK_ANGLE_DEG = 45.0
PROFILE_TOLERANCE_CM = 1e-7
MIN_SHORT_EDGE_CM = 0.008  # 0.08 mm; minimum permitted tooth crest flat
# Recommended radial clearance (per side, mm) for 3D-printed mating threads.
# FDM prints typically need 0.2-0.4 mm per side to assemble without force;
# 0.2 mm is the default starting point (tighter fit, still printable on a
# well-calibrated machine). Shown as a suggestion in the result dialog.
# NOTE: every derived figure (diametral clearance = 2 x this, suggested mating
# diameter, dialog text) is computed from this constant - change it here only.
RECOMMENDED_CLEARANCE_MM = 0.2
# Maximum allowed deviation between the fitted helix spline and the true
# cylinder surface, expressed as a fraction of the tooth height H.  The sweep
# guides the profile along the cylinder face; if the path strays further than
# roughly H from the surface the profile can no longer follow the guide and
# the kernel rejects the sweep (ASM_SWEEP_ILLEGAL_SURFACE).  0.5 used to be
# the default, but MCP-verified tests on a CLEAN full cylinder face offset
# from the origin (e.g. a jar body at x=12.5 cm) showed the exit-ramp sweep
# failing with ASM_SWEEP_ILLEGAL_SURFACE at 36 pts/turn while succeeding at
# ~51 pts/turn (ratio 0.25).  Tighter ratio = denser sampling = smoother
# spline that hugs the guide face.  Keep 0.25 as the default.
HELIX_DEVIATION_TOLERANCE_RATIO = 0.25
MIN_SAMPLES_PER_TURN = 16
MAX_SAMPLES_PER_TURN = 360
# Hard cap on the total number of spline points for one helix. When the
# adaptive per-turn sampling would exceed this for a long thread, the turn
# count is reduced instead of the sampling density, so the path always stays
# close to the cylinder surface.
MAX_HELIX_POINTS = 20000
# Entrance/exit ramps (TESTING, not final): the thread starts and ends with a
# short ramp where the trapezoid section grows/shrinks between
# LEAD_IN_START_SCALE and 100% of full size (both tooth height and tooth
# width), so a mating part slides in instead of hitting a full-height wall and
# both ends stay print-friendly (no vertical thin walls).
LEAD_IN_TURNS = 0.125          # entrance ramp length: 1/8 of a turn
LEAD_OUT_TURNS = 0.125         # exit ramp length: 1/8 of a turn
LEAD_IN_START_SCALE = 0.10     # section scale at the very tip (10%)
LEAD_IN_SECTIONS = 5           # loft sections across each ramp
LEAD_IN_MIN_POINTS = 12        # minimum spline points for a ramp arc
# The loft ramp's last full-size section is placed slightly PAST the sweep
# junction (into the main body), so the loft body overlaps the sweep body
# with real volume instead of sharing a coincident face. A pure face-to-face
# join (surfaces exactly coplanar) makes the boolean fail with
# ASM_INCONS_FACE on large diameters (flatter helix, harder to distinguish
# the coincident faces). 0.03 turns of overlap disappears into the main
# thread visually and does not change the thread dimensions (union keeps
# the outer surface, the overlapping full-size section is fully contained).
LEAD_OVERLAP_TURNS = 0.10  # ramp bodies overlap the main body / adjacent
                           # segments by this many turns. 0.03 was too small:
                           # on some EXTERNAL geometries (D34.6/H10 L3/H1) the
                           # loft only edge-touches the sweep, and the boolean
                           # join fails silently (the combine feature turns
                           # red while add() still returns, leaving disjoint
                           # bodies). 0.10 gives a solid ~0.4 mm overlap.
LEAD_OVERLAP_TURNS_INTERNAL = 0.05  # INTERNAL threads need a SMALLER overlap:
                                    # with 0.10 the loft/main-sweep join of a
                                    # D110/H33 L1.6/H0.6 internal thread fails
                                    # with ASM_NULL_PARTNER_LOOP, while 0.05
                                    # and 0.03 both pass (verified via MCP).
THREAD_ROOT_EMBED_CM = 0.002   # 0.02 mm: loft root sinks below the cylinder
                               # face so the union has real volume overlap
# A sweep segment shorter than this is merged into its neighbour. With the
# full-fill non-integer turn count, the last whole-turn boundary can land
# just barely before the lead-out junction (e.g. [0.125, 4, 4.075]), leaving
# a ~0.075-turn stub with only 2-3 spline samples: the stub spline degrades
# and its body overlaps the lead-out loft by almost nothing, so the internal
# boolean join fails (ASM_INCONS_REL). Merging restores a healthy tail.
MIN_SEGMENT_TURNS = 1.0


def _profile_dimensions(L, H, angle_degrees):
    """Return axial flank inset, short edge, and max H for the minimum S."""
    tangent = math.tan(math.radians(angle_degrees))
    flank_run = H / tangent
    short_edge = L - 2.0 * flank_run
    max_height = max(0.0, 0.5 * (L - MIN_SHORT_EDGE_CM) * tangent)
    return flank_run, short_edge, max_height


def _profile_from_edges(long_edge, crest, height):
    """Resolve flank geometry from independently selected L, S and H."""
    if long_edge <= 0 or crest <= 0 or height <= 0:
        raise ValueError('tooth-root width, crest width and height must be positive')
    if long_edge <= crest:
        raise ValueError('tooth-root width must be greater than crest width')
    flank_run = 0.5 * (long_edge - crest)
    angle_degrees = math.degrees(math.atan2(height, flank_run))
    return flank_run, angle_degrees


def _samples_per_turn_for_radius(radius_cm, requested, tooth_height_mm,
                                 deviation_ratio=None):
    """Return the effective samples-per-turn for a cylinder radius.

    A circle of radius R sampled at n points per turn has a maximum chord-to-arc
    (sagitta) deviation of R * (1 - cos(pi / n)). The sweep guides the profile
    along the cylinder face, so this deviation must stay within
    deviation_ratio * tooth_height_mm or the kernel rejects the sweep. We raise
    the sample count until the sagitta is within tolerance. The caller's
    requested value is honoured as a lower bound.

    deviation_ratio defaults to HELIX_DEVIATION_TOLERANCE_RATIO when None.
    """
    radius_mm = radius_cm * 10.0
    base = max(MIN_SAMPLES_PER_TURN, int(requested))
    if radius_mm <= 0 or tooth_height_mm <= 0:
        return base
    if deviation_ratio is None:
        deviation_ratio = HELIX_DEVIATION_TOLERANCE_RATIO
    tol_mm = deviation_ratio * tooth_height_mm
    # sagitta <= tol  =>  n >= pi / acos(1 - tol / R)
    ratio = tol_mm / radius_mm
    if ratio >= 1.0:
        return base  # tiny radius; tolerance already met
    required = math.pi / math.acos(max(-1.0, min(1.0, 1.0 - ratio)))
    required = int(math.ceil(required))
    return int(max(base, min(required, MAX_SAMPLES_PER_TURN)))


def _plan_helix_sampling(radius_cm, requested_ppt, turns, tooth_height_mm,
                         deviation_ratio=None):
    """Plan effective sampling for a helix of the given radius and turn count.

    Returns a tuple (eff_ppt, turns, n_points, capped):
      - eff_ppt: effective samples per turn (adaptive, never reduced for budget)
      - turns: the number of turns that fit within the point budget
      - n_points: total spline point count (excluding the closing duplicate)
      - capped: True if turns were reduced because of the point budget

    The sampling density is never sacrificed to fit the budget. If the adaptive
    per-turn density would push the total beyond MAX_HELIX_POINTS, the turn
    count is reduced so every retained turn keeps full precision.

    deviation_ratio defaults to HELIX_DEVIATION_TOLERANCE_RATIO when None.
    """
    eff_ppt = _samples_per_turn_for_radius(
        radius_cm, requested_ppt, tooth_height_mm, deviation_ratio)
    capped = False
    if turns > 0 and eff_ppt > 0 and turns * eff_ppt > MAX_HELIX_POINTS:
        turns = max(1, int(MAX_HELIX_POINTS // eff_ppt))
        capped = True
    n_points = max(4, int(turns * eff_ppt)) if turns > 0 else 0
    return eff_ppt, turns, n_points, capped


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
    # 统一 axis 方向：用 bb.minPoint/bb.maxPoint 判断，确保 axis 从物理底面指向顶面
    v_min = adsk.core.Vector3D.create(
        bb.minPoint.x - origin.x, bb.minPoint.y - origin.y, bb.minPoint.z - origin.z)
    v_max = adsk.core.Vector3D.create(
        bb.maxPoint.x - origin.x, bb.maxPoint.y - origin.y, bb.maxPoint.z - origin.z)
    if v_min.dotProduct(ax) > v_max.dotProduct(ax):
        ax.scaleBy(-1)  # 翻转，使 axis 从底面指向顶面
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


def _build_helix(face, L, flank_run, pts_per_turn, offset_cm=0,
                 tooth_height_mm=1.0, deviation_ratio=None,
                 fill_end=False, pitch_cm=None):
    """生成螺旋线点列。offset_cm: 螺旋线起点距圆柱底端的偏移
    fill_end=True: 满算模式（无收口）——圈数取非整数 (height-offset-L)/P，
    螺纹材料末端（螺旋终点 + 牙宽 L）恰好落在上端面、绝不超出；
    矮圆柱（不足 1 圈）回退旧逻辑。
    """
    # Generate helix point sequence. offset_cm: offset from cylinder bottom to helix start
    radius, height, h_min, ax, origin = _get_cyl_info(face)
    P = float(pitch_cm) if pitch_cm is not None else 2.0 * (L - flank_run)
    usable = height - offset_cm
    if fill_end:
        # Full-fill mode (no lead ramps): the thread MATERIAL (which extends
        # one tooth width L past the helix end because the trapezoid's long
        # edge runs along the axis) must end exactly on the top face, so the
        # helix itself stops L short of the face:
        #   material_end = offset + N*P + L <= height
        #   -> N = (height - offset - L) / P
        # The turn count is floored to 4 decimals: that is sub-micron
        # precision on the material end and keeps the value tidy, while the
        # floor guarantees the path never crosses the top face.
        N_frac = math.floor((usable - L) / P * 1e4) / 1e4
        if N_frac >= 1.0:
            N = N_frac
        else:
            N = max(1, int(usable / P + 1e-9) - 1)  # too short: fall back
    else:
        N = max(1, int(usable / P + 1e-9) - 1)  # 留一圈空间；+1e-9防浮点截断
    # Reserve one full turn of space
    # Adapt sample density to the radius; if the point budget is exceeded the
    # turn count is reduced (not the sampling density) so the path always hugs
    # the cylinder surface.
    eff_ppt, N, n_pts, capped = _plan_helix_sampling(
        radius, pts_per_turn, N, tooth_height_mm, deviation_ratio)
    hh = N * P
    h_start = h_min + offset_cm       # 偏移后的起始高度
    # Adjusted starting height after offset
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


def _create_trapezoid(root, perp_plane, face, L, H, angle_degrees,
                      start_pt, is_external, center_on_anchor=False,
                      anchor_offset_cm=0.0, root_embed_cm=0.0):
    """在路径垂面上画梯形截面。
    is_external=True  → 向外长肉（外螺纹）
    is_external=False → 向内长肉（内螺纹）

    start_pt 是锚点（螺旋线上的采样点）。
    - 扫掠（center_on_anchor=False, anchor_offset_cm=0）：长边起点 =
      start_pt，梯形沿轴向延伸 L——螺纹从路径起点开始，不超出端面。
    - 放样（center_on_anchor=True）：锚点先沿轴向平移 anchor_offset_cm
      （通常 = L/2），梯形长边中点落在平移后的锚点上，于是长边起点回到
      原始螺旋线采样点——每个放样截面的长边起点都穿过同一条螺旋线，
      与扫掠梯形几何一致，放样体才不会歪。

    root_embed_cm > 0 时（仅放样）：牙根（长边）沿径向向圆柱实体内部
    沉入该距离，牙顶（短边）位置不动。外螺纹向轴心、内螺纹向孔壁外侧。
    放样体的牙根面若精确贴合圆柱面（零体积接触），布尔求并会失败
    （ASM_INCONS_REL / ASM_EDGECOIN_PROBLEM）；沉入后两体有真实体积
    重叠，求并成功，且螺纹外径 r+H 不变（牙顶未动）。
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
    flank_run, short_len, _ = _profile_dimensions(
        L, H, angle_degrees)

    # 放样模式：锚点先沿轴向平移，再让长边中点落在锚点上
    # Loft mode: shift the anchor axially first, then centre the long edge
    # on the shifted anchor so its START lands back on the helix sample.
    if anchor_offset_cm:
        start_pt = adsk.core.Point3D.create(
            start_pt.x + anchor_offset_cm * ax.x,
            start_pt.y + anchor_offset_cm * ax.y,
            start_pt.z + anchor_offset_cm * ax.z)

    if center_on_anchor:
        half = 0.5 * L
        B_world = adsk.core.Point3D.create(
            start_pt.x - half * ax.x,
            start_pt.y - half * ax.y,
            start_pt.z - half * ax.z)
        A_world = adsk.core.Point3D.create(
            start_pt.x + half * ax.x,
            start_pt.y + half * ax.y,
            start_pt.z + half * ax.z)
    else:
        # 扫掠模式：长边起点 = 锚点（原方法，螺纹不偏移）
        # Sweep mode: long-edge START is the anchor (original behaviour)
        B_world = start_pt
        A_world = adsk.core.Point3D.create(
            start_pt.x + L * ax.x,
            start_pt.y + L * ax.y,
            start_pt.z + L * ax.z)
    P_bot_world = adsk.core.Point3D.create(
        B_world.x + sign * H * rad_vec.x + flank_run * ax.x,
        B_world.y + sign * H * rad_vec.y + flank_run * ax.y,
        B_world.z + sign * H * rad_vec.z + flank_run * ax.z)
    P_top_world = adsk.core.Point3D.create(
        A_world.x + sign * H * rad_vec.x - flank_run * ax.x,
        A_world.y + sign * H * rad_vec.y - flank_run * ax.y,
        A_world.z + sign * H * rad_vec.z - flank_run * ax.z)

    # Loft root embed: sink the long edge (root) radially INTO the target
    # solid (towards -sign*rad). The tooth top P_bot/P_top keeps its r+H
    # position, so the outer thread diameter is unchanged. Without this the
    # loft root face lies exactly on the cylinder face (zero-volume contact)
    # and the boolean union fails with ASM_INCONS_REL / ASM_EDGECOIN_PROBLEM
    # even though a pure sweep body is tolerated.
    if root_embed_cm:
        B_world = adsk.core.Point3D.create(
            B_world.x - sign * root_embed_cm * rad_vec.x,
            B_world.y - sign * root_embed_cm * rad_vec.y,
            B_world.z - sign * root_embed_cm * rad_vec.z)
        A_world = adsk.core.Point3D.create(
            A_world.x - sign * root_embed_cm * rad_vec.x,
            A_world.y - sign * root_embed_cm * rad_vec.y,
            A_world.z - sign * root_embed_cm * rad_vec.z)

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

    return sketch, short_len


def _do_sweep(root, profile, helix_spline, guide_face, occurrence=None,
              operation=adsk.fusion.FeatureOperations.NewBodyFeatureOperation):
    """扫掠：轮廓沿螺旋线路径，圆柱面做引导曲面"""
    # Sweep: profile along helix path, using cylinder face as guide surface
    path = root.features.createPath(helix_spline, False)
    sweeps = root.features.sweepFeatures
    sweep_input = sweeps.createInput(
        profile, path, operation)
    fv = adsk.fusion.BRepFaceVector()
    fv.push_back(guide_face)
    sweep_input.guideSurfaces = fv
    if occurrence:
        sweep_input.creationOccurrence = occurrence
    return sweeps.add(sweep_input)


def _ramp_helix_points(face, L, flank_run, ramp_turns, n_points,
                       offset_cm, total_turns, from_end=False, pitch_cm=None):
    """在螺旋线入口段或出口段均匀采样（世界坐标）。
    from_end=False：从起点开始采样 ramp_turns 圈（入口收口）。
    from_end=True：从终点往前采样 ramp_turns 圈（出口收口），
    采样顺序仍从靠近终点处开始，便于放样从出口端向主段方向进行。
    与 _build_helix 使用相同的螺旋参数化，保证两段几何对齐。
    """
    # Uniformly sample the entrance or exit portion of the helix.
    # Same parameterisation as _build_helix so both segments stay aligned.
    radius, height, h_min, ax, origin = _get_cyl_info(face)
    P = float(pitch_cm) if pitch_cm is not None else 2.0 * (L - flank_run)
    h_start = h_min + offset_cm
    hh = ramp_turns * P
    if from_end:
        # Start sampling at the ramp start (which is ramp_turns before the end)
        ramp_start_turn = total_turns - ramp_turns
        h_base = h_start + ramp_start_turn * P
        angle_base = ramp_start_turn * 2 * math.pi
    else:
        h_base = h_start
        angle_base = 0.0
    u = _radial_dir(ax)
    v = ax.crossProduct(u)
    v.normalize()
    pts = adsk.core.ObjectCollection.create()
    for i in range(n_points + 1):
        t = i / n_points
        angle = angle_base + t * ramp_turns * 2 * math.pi
        hz = h_base + t * hh
        pts.add(adsk.core.Point3D.create(
            origin.x + hz * ax.x + radius * (math.cos(angle) * u.x + math.sin(angle) * v.x),
            origin.y + hz * ax.y + radius * (math.cos(angle) * u.y + math.sin(angle) * v.y),
            origin.z + hz * ax.z + radius * (math.cos(angle) * u.z + math.sin(angle) * v.z)))
    return pts


def generate_thread(face, tooth_width_mm, tooth_height_mm,
                    end_offset_mm=0.0, samples_per_turn=16,
                    join_to_target=False, feature_name='GeneratedThread',
                    max_turns_per_sweep=4, flank_angle_degrees=45.0,
                    deviation_ratio=None, enable_lead=True,
                    pitch_mm=None, crest_width_mm=None):
    """Generate a printable trapezoidal thread without opening the GUI.

    Args:
        face: Cylindrical BRepFace (native face or assembly-context proxy).
        tooth_width_mm: Trapezoid long edge / tooth width in millimetres.
        tooth_height_mm: Radial tooth height in millimetres.
        end_offset_mm: Axial offset from the detected cylinder start.
        samples_per_turn: Spline sample count per turn (minimum 4).
        join_to_target: Join the generated thread body to the selected body.
        feature_name: Browser name for generated sketches/features.
        max_turns_per_sweep: Maximum turns in each sweep segment.
        flank_angle_degrees: Angle between either flank and the thread axis.
        deviation_ratio: Helix deviation as a fraction of tooth height
            (default HELIX_DEVIATION_TOLERANCE_RATIO = 0.25). Lower values
            increase sampling density and surface smoothness.
        enable_lead: If True (default), entrance and exit lead-in/lead-out
            ramps are applied (1/8 turn each, section scaled from
            LEAD_IN_START_SCALE up to full size and back). If False, a
            full-height legacy thread is generated.
        pitch_mm: Optional explicit thread pitch, independent of the profile.
        crest_width_mm: Optional explicit tooth crest flat width. When pitch
            and crest are supplied, tooth_width_mm is the independently
            selected tooth-root width and flank_angle_degrees is ignored.

    Note:
        The ramps are lofted with LEAD_IN_SECTIONS sections; the loft helix
        is shifted by L/2 along the axis so the loft trapezoids ride the
        sweep helix, and the tooth root is embedded
        (THREAD_ROOT_EMBED_CM) below the cylinder surface for a robust
        boolean join.

    Returns:
        A JSON-serialisable dict describing the generated thread.

    Raises:
        ValueError: Invalid face or dimensions.
        RuntimeError: Fusion failed to construct or join the thread.
    """
    face = adsk.fusion.BRepFace.cast(face)
    if not face:
        raise ValueError('face must be a BRepFace')
    if not adsk.core.Cylinder.cast(face.geometry):
        raise ValueError('face must be a true cylindrical BRep face')

    H_cm = float(tooth_height_mm) / 10.0
    offset_cm = float(end_offset_mm) / 10.0
    pts_per_turn = max(4, int(samples_per_turn))
    segment_turn_limit = max(1, int(max_turns_per_sweep))
    explicit_profile = pitch_mm is not None or crest_width_mm is not None
    if explicit_profile:
        if pitch_mm is None or crest_width_mm is None:
            raise ValueError('pitch_mm and crest_width_mm must be supplied together')
        pitch_cm = float(pitch_mm) / 10.0
        crest_cm = float(crest_width_mm) / 10.0
        L_cm = float(tooth_width_mm) / 10.0
        flank_run_cm, angle_degrees = _profile_from_edges(
            L_cm, crest_cm, H_cm)
        short_cm = crest_cm
    else:
        L_cm = float(tooth_width_mm) / 10.0
        angle_degrees = float(flank_angle_degrees)
    if deviation_ratio is None:
        deviation_ratio = HELIX_DEVIATION_TOLERANCE_RATIO
    deviation_ratio = float(deviation_ratio)
    if not (0.0 < deviation_ratio <= 1.0):
        raise ValueError('deviation_ratio must be in (0, 1]')
    if L_cm <= 0 or H_cm <= 0:
        raise ValueError('tooth_width_mm and tooth_height_mm must be positive')
    if (not explicit_profile and
            not MIN_FLANK_ANGLE_DEG <= angle_degrees <= MAX_FLANK_ANGLE_DEG):
        raise ValueError('flank_angle_degrees must be between 5 and 45 degrees')
    if not explicit_profile:
        flank_run_cm, short_cm, _ = _profile_dimensions(
            L_cm, H_cm, angle_degrees)
    if (not explicit_profile and
            short_cm < MIN_SHORT_EDGE_CM - PROFILE_TOLERANCE_CM):
        raise ValueError('short edge must be at least 0.08 mm')
    if explicit_profile and pitch_cm <= 0:
        raise ValueError('pitch_mm must be positive')
    if offset_cm < 0:
        raise ValueError('end_offset_mm must be non-negative')

    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise RuntimeError('No active Fusion design')

    is_external = _is_external_face(face)
    # External threads need a LARGER ramp overlap (0.10) or the loft can
    # edge-touch the sweep and the join fails silently (D34.6/H10 L3/H1);
    # internal threads instead fail with ASM_NULL_PARTNER_LOOP when the
    # overlap is 0.10 (D110/H33 L1.6/H0.6) and pass at 0.05. Split the
    # constant per thread type.
    overlap_turns = (
        LEAD_OVERLAP_TURNS if is_external
        else LEAD_OVERLAP_TURNS_INTERNAL)
    radius, cylinder_height, _, _, _ = _get_cyl_info(face)
    if not is_external and H_cm >= radius:
        raise ValueError('Internal thread tooth height must be smaller than the hole radius')

    occurrence = adsk.fusion.Occurrence.cast(face.body.assemblyContext)
    if occurrence:
        comp = occurrence.component
        target_body = face.body.nativeObject
    else:
        target_body = face.body
        comp = target_body.parentComponent

    pts, turns, helix_height, pitch, radius = _build_helix(
        face, L_cm, flank_run_cm, pts_per_turn, offset_cm,
        tooth_height_mm=H_cm * 10.0, deviation_ratio=deviation_ratio,
        fill_end=True, pitch_cm=pitch_cm if explicit_profile else None)
    if turns < 1 or helix_height <= 0:
        raise ValueError('Selected cylinder is too short for the requested thread and offset')

    if occurrence:
        inv = occurrence.transform2.copy()
        inv.invert()
        local_pts = adsk.core.ObjectCollection.create()
        for i in range(pts.count):
            pt = pts.item(i).copy()
            pt.transformBy(inv)
            local_pts.add(pt)
        pts = local_pts

    safe_name = feature_name or 'GeneratedThread'
    created_sketches = []  # all sketches created during generation, hidden at the end
    timeline_start_index = design.timeline.count
    total_points = pts.count - 1

    # ── Entrance/exit ramps (TESTING): short ramps where the trapezoid grows
    # from a small tip section to full size, so a mating part slides in and
    # both ends stay print-friendly. ──
    lead_in_turns = LEAD_IN_TURNS if (enable_lead and LEAD_IN_TURNS > 0) else 0.0
    lead_in_turns = min(lead_in_turns, max(0.0, turns - 0.5))
    use_lead_in = lead_in_turns > 1e-6
    lead_out_turns = LEAD_OUT_TURNS if (enable_lead and LEAD_OUT_TURNS > 0) else 0.0
    lead_out_turns = min(lead_out_turns, max(0.0, turns - lead_in_turns - 0.5))
    use_lead_out = lead_out_turns > 1e-6
    lead_body = None
    lead_out_body = None
    lead_pts = None
    # The loft ramps ride a helix that is SHIFTED by L/2 along the axis
    # relative to the sweep helix. Rationale: the sweep trapezoid starts its
    # long edge ON the sweep helix, so the long-edge MIDPOINT of a sweep
    # section sits at helix + L/2. We shift the loft helix by the same L/2
    # and centre each loft trapezoid's long edge on the shifted helix, so the
    # loft long-edge START lands back on the sweep helix and both ends match.
    # The shift uses the FULL tooth width L/2 (not scaled per section).
    _, _, _, ax_shift, _ = _get_cyl_info(face)
    ramp_shift_cm = 0.5 * L_cm

    def _shift_points(obj, shift_cm):
        """沿轴向平移一组世界坐标点，返回新 ObjectCollection。"""
        shifted = adsk.core.ObjectCollection.create()
        for i in range(obj.count):
            pt = obj.item(i)
            shifted.add(adsk.core.Point3D.create(
                pt.x + shift_cm * ax_shift.x,
                pt.y + shift_cm * ax_shift.y,
                pt.z + shift_cm * ax_shift.z))
        return shifted

    if use_lead_in:
        # Fit one spline through a densely sampled copy of the ramp arc.
        # The main helix point list only contributes ~2 points over 1/8 turn,
        # which would degenerate into a straight line; sample it independently.
        # The sample arc is extended by LEAD_OVERLAP_TURNS past the sweep
        # junction so the loft's last (full-size) section lands INSIDE the
        # main body: the two bodies then overlap with volume and the boolean
        # join succeeds (a face-to-face seam would fail with ASM_INCONS_FACE).
        lead_pts_world = _ramp_helix_points(
            face, L_cm, flank_run_cm,
            lead_in_turns + overlap_turns, LEAD_IN_MIN_POINTS,
            offset_cm, turns,
            pitch_cm=pitch_cm if explicit_profile else None)
        lead_pts_shift_world = _shift_points(lead_pts_world, ramp_shift_cm)
        if occurrence:
            lead_pts = adsk.core.ObjectCollection.create()
            lead_shifted = adsk.core.ObjectCollection.create()
            for i in range(lead_pts_world.count):
                pt = lead_pts_world.item(i).copy()
                pt.transformBy(inv)
                lead_pts.add(pt)
                sp = lead_pts_shift_world.item(i).copy()
                sp.transformBy(inv)
                lead_shifted.add(sp)
        else:
            lead_pts = lead_pts_world
            lead_shifted = lead_pts_shift_world
        # The junction is where the ramp reaches full size (lead_in_turns),
        # NOT the last sample: the sample arc extends LEAD_OVERLAP_TURNS
        # beyond it so the loft can overlap the main body.
        junc_frac = lead_in_turns / (lead_in_turns + overlap_turns)
    if use_lead_out:
        # Exit ramp: samples run from BEFORE the junction (overlapping the
        # main sweep body) towards the helix end. The first sample sits
        # LEAD_OVERLAP_TURNS before the junction so the loft's first full-size
        # section lands INSIDE the main body and the boolean join has volume
        # overlap (a face-to-face seam would fail with ASM_INCONS_FACE).
        exit_pts_world = _ramp_helix_points(
            face, L_cm, flank_run_cm,
            lead_out_turns + overlap_turns, LEAD_IN_MIN_POINTS,
            offset_cm, turns, from_end=True,
            pitch_cm=pitch_cm if explicit_profile else None)
        exit_pts_shift_world = _shift_points(exit_pts_world, ramp_shift_cm)
        if occurrence:
            exit_pts = adsk.core.ObjectCollection.create()
            exit_shifted = adsk.core.ObjectCollection.create()
            for i in range(exit_pts_world.count):
                pt = exit_pts_world.item(i).copy()
                pt.transformBy(inv)
                exit_pts.add(pt)
                sp = exit_pts_shift_world.item(i).copy()
                sp.transformBy(inv)
                exit_shifted.add(sp)
        else:
            exit_pts = exit_pts_world
            exit_shifted = exit_pts_shift_world

    # ── Main sweep path: every segment is built from the NATIVE helix sample
    # points only (no ramp/junction point is inserted into any spline). The
    # lead-in loft ends at the first segment's start sample and the lead-out
    # loft starts inside the last segment's overlap region, so the sweep
    # splines stay as smooth as the no-ramp case and the guided sweep never
    # rejects them (an inserted ramp point near the spline end degrades the
    # fit and triggers ASM_SWEEP_ILLEGAL_SURFACE on clean full cylinder
    # faces; verified via Fusion MCP on a 130 mm jar body). ──
    # Points are laid out uniformly across all turns, so map turn boundaries
    # to point indices proportionally. Indexing by the requested pts_per_turn
    # would be wrong once adaptive sampling raises the effective density.
    main_start_turn = lead_in_turns if use_lead_in else 0.0
    main_end_turn = turns - lead_out_turns if use_lead_out else turns
    # Segment boundaries fall on WHOLE turns (multiples of segment_turn_limit)
    # wherever possible, exactly like the pre-ramp version. At a whole-turn
    # boundary the shared sample's angular direction matches the helix start
    # (0 deg), so two independently fitted splines are tangent-continuous at
    # that point and the guided sweep stays legal. Only the FIRST segment
    # starts at the lead-in junction and the LAST segment ends at the lead-out
    # junction (both non-integer; unavoidable, and handled by the lofts).
    boundaries = [main_start_turn]
    b = float(
        math.ceil(main_start_turn / segment_turn_limit - 1e-9)
        * segment_turn_limit)
    while b < main_end_turn - 1e-9:
        # Guard against a duplicate boundary (e.g. main_start_turn=0 gives
        # ceil(-1e-9)=0 -> b=0, which already equals boundaries[0]).
        if b > boundaries[-1] + 1e-9:
            boundaries.append(b)
        b += segment_turn_limit
    boundaries.append(main_end_turn)
    # De-duplicate the closing boundary as well, then drop any empty segment
    # (happens when main_start_turn is itself a whole turn).
    cleaned = []
    for t in boundaries:
        if not cleaned or t > cleaned[-1] + 1e-9:
            cleaned.append(t)
    boundaries = cleaned
    # Short-segment guard: merge any tail segment shorter than one turn into
    # the previous one (the final main_end_turn boundary is always kept; only
    # interior whole-turn boundaries are dropped). Prevents the degenerate
    # stub segment described at MIN_SEGMENT_TURNS.
    merged = [boundaries[0]]
    for t in boundaries[1:-1]:
        if t - merged[-1] >= MIN_SEGMENT_TURNS - 1e-9:
            merged.append(t)
    while (len(merged) > 1 and
           boundaries[-1] - merged[-1] < MIN_SEGMENT_TURNS - 1e-9):
        merged.pop()
    merged.append(boundaries[-1])
    boundaries = merged
    segment_count = len(boundaries) - 1
    # First main-sweep segment starts at the first native sample at/after the
    # main start turn. Computed here so the lead-in loft's final full-size
    # section and the main profile can share this exact point.
    main_start_index = int(math.ceil(
        main_start_turn / turns * total_points)) if use_lead_in else 0
    sketch_helix = comp.sketches.add(comp.xYConstructionPlane)
    sketch_helix.name = safe_name + '_Helix'
    created_sketches.append(sketch_helix)
    sketch_helix.isComputeDeferred = True
    segment_splines = []
    segment_start_pts = []
    for segment_index in range(segment_count):
        # Each segment's path OVERLAPS its neighbours by LEAD_OVERLAP_TURNS on
        # the shared boundary: segment i-1 ends past the boundary and segment
        # i starts before it, so the two swept bodies have real volume overlap
        # and the boolean join succeeds. A seam where the two end faces are
        # exactly coplanar fails with ASM_INCONS_FACE on large diameters. The
        # first segment's start (lead-in junction) and the last segment's end
        # (lead-out junction) stay exact.
        if segment_index == 0:
            first_turn = boundaries[segment_index]
        else:
            first_turn = boundaries[segment_index] - overlap_turns
        if segment_index == segment_count - 1:
            last_turn = boundaries[segment_index + 1]
        else:
            last_turn = boundaries[segment_index + 1] + overlap_turns
        # floor: the last coarse sample must never land past a non-integer
        # turn boundary. With round() the last sample of the exit ramp can sit
        # AFTER the exit junction (e.g. 3.9 turns vs the 3.875 junction),
        # which makes the fitted path fold back on itself and the guided sweep
        # is rejected (ASM_SWEEP_ILLEGAL_SURFACE).
        last_point = min(total_points,
                         int(math.floor(last_turn / turns * total_points)))
        segment_points = adsk.core.ObjectCollection.create()
        if segment_index == 0:
            # First segment starts at the first NATIVE sample at/after the
            # main start turn (no ramp junction point is inserted into the
            # spline). The lead-in loft body overlaps this start region, so
            # the seam is a volume overlap, exactly like the no-ramp case.
            start_index = main_start_index
        else:
            # Segment boundaries are non-integer turns (e.g. 4.125 with a
            # lead-in ramp); floor keeps this segment's first sample exactly
            # shared with the previous segment's last sample (which is also
            # computed with floor), so consecutive splines share one point
            # and the sweep end-face aligns with the next path start.
            start_index = int(math.floor(
                first_turn / turns * total_points))
        for point_index in range(start_index, last_point + 1):
            segment_points.add(pts.item(point_index))
        segment_start_pts.append(segment_points.item(0))
        segment_splines.append(
            sketch_helix.sketchCurves.sketchFittedSplines.add(
                segment_points))

    sketch_helix.isComputeDeferred = False

    # Profile plane: perpendicular to the main path at its true start point.
    # The lead-in loft's last section reuses this very plane so both segments
    # share one identical seam.
    plane_input = comp.constructionPlanes.createInput()
    plane_input.setByDistanceOnPath(
        segment_splines[0], adsk.core.ValueInput.createByReal(0))
    perp_plane = comp.constructionPlanes.add(plane_input)
    perp_plane.name = safe_name + '_ProfilePlane'

    if use_lead_in:
        sketch_lead = comp.sketches.add(comp.xYConstructionPlane)
        sketch_lead.name = safe_name + '_LeadIn_Helix'
        created_sketches.append(sketch_lead)
        sketch_lead.isComputeDeferred = True
        lead_spline = sketch_lead.sketchCurves.sketchFittedSplines.add(
            lead_shifted)
        sketch_lead.isComputeDeferred = False

        # Entrance scale, raised if needed so the tiny section keeps a
        # printable short edge.
        entrance_scale = LEAD_IN_START_SCALE
        if entrance_scale * short_cm < MIN_SHORT_EDGE_CM:
            entrance_scale = min(1.0, MIN_SHORT_EDGE_CM / max(short_cm, 1e-9))

        # The sample arc runs lead_in + LEAD_OVERLAP_TURNS; the trapezoid
        # ramps from entrance_scale up to 1.0 over the lead_in part and the
        # LAST section (full size) sits past the junction, inside the main
        # sweep body, so the boolean join has real volume overlap instead of
        # two coincident faces (ASM_INCONS_FACE).
        junc_frac = lead_in_turns / (lead_in_turns + overlap_turns)
        n_grad = LEAD_IN_SECTIONS - 1
        loft_profiles = []
        for k in range(LEAD_IN_SECTIONS):
            if k < n_grad:
                frac = (k / float(n_grad - 1)) * junc_frac
                scale = entrance_scale + (
                    1.0 - entrance_scale) * (k / float(n_grad - 1))
            else:
                # Overlap section: full size, inside the main body.
                frac = 1.0
                scale = 1.0
            plane_input_k = comp.constructionPlanes.createInput()
            plane_input_k.setByDistanceOnPath(
                lead_spline, adsk.core.ValueInput.createByReal(frac))
            section_plane = comp.constructionPlanes.add(plane_input_k)
            section_plane.name = safe_name + '_LeadIn_Plane_' + str(k)
            # Anchors come from the SHIFTED helix (original helix + L/2);
            # centring the long edge on them puts the long-edge START back on
            # the original (sweep) helix, matching the sweep profile exactly.
            anchor = lead_shifted.item(
                int(round(frac * LEAD_IN_MIN_POINTS)))
            section_sketch, _ = _create_trapezoid(
                comp, section_plane, face, L_cm * scale, H_cm * scale,
                angle_degrees, anchor, is_external,
                center_on_anchor=True,
                root_embed_cm=THREAD_ROOT_EMBED_CM)
            section_sketch.name = safe_name + '_LeadIn_Section_' + str(k)
            created_sketches.append(section_sketch)
            if section_sketch.profiles.count == 0:
                raise RuntimeError(
                    'Lead-in section did not form a closed region')
            loft_profiles.append(section_sketch.profiles.item(0))

        loft_features = comp.features.loftFeatures
        loft_input = loft_features.createInput(
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        for profile in loft_profiles:
            loft_input.loftSections.add(profile)
        loft_input.isSolid = True
        loft_feature = loft_features.add(loft_input)
        loft_feature.name = safe_name + '_LeadIn_Loft'
        if loft_feature.bodies.count != 1:
            raise RuntimeError('Lead-in loft did not produce a single body')
        lead_body = loft_feature.bodies.item(0)
        lead_body.name = safe_name + '_LeadIn_Body'

    main_anchor = pts.item(main_start_index)
    sketch_trap, short_cm = _create_trapezoid(
        comp, perp_plane, face, L_cm, H_cm, angle_degrees,
        main_anchor, is_external,
        root_embed_cm=THREAD_ROOT_EMBED_CM)
    sketch_trap.name = safe_name + '_Profile'
    created_sketches.append(sketch_trap)
    if sketch_trap.profiles.count == 0:
        raise RuntimeError('Thread profile did not form a closed region')

    segment_bodies = []
    sweep_profile = sketch_trap.profiles.item(0)
    for segment_index, spline in enumerate(segment_splines):
        suffix = (
            '' if segment_count == 1
            else '_Segment_' + str(segment_index + 1))
        segment_name = safe_name + suffix

        if segment_index > 0:
            # Draw a fresh full-size trapezoid on a plane perpendicular to
            # THIS segment's path at its exact start point. The sweep endFaces
            # are NOT reused as the next profile: their order is not reliable
            # (endFaces.item(0) can be the START face, making the next sweep
            # begin at the wrong end). With whole-turn segment boundaries the
            # two fitted splines are tangent-continuous at the shared start
            # point, so this profile is exactly aligned with the previous
            # segment's end section.
            seg_plane_input = comp.constructionPlanes.createInput()
            seg_plane_input.setByDistanceOnPath(
                spline, adsk.core.ValueInput.createByReal(0))
            seg_plane = comp.constructionPlanes.add(seg_plane_input)
            seg_plane.name = safe_name + '_SegPlane_' + str(segment_index)
            seg_sketch, _ = _create_trapezoid(
                comp, seg_plane, face, L_cm, H_cm, angle_degrees,
                segment_start_pts[segment_index], is_external,
                root_embed_cm=THREAD_ROOT_EMBED_CM)
            seg_sketch.name = safe_name + '_SegProfile_' + str(segment_index)
            created_sketches.append(seg_sketch)
            if seg_sketch.profiles.count == 0:
                raise RuntimeError(
                    'Segment profile did not form a closed region')
            sweep_profile = seg_sketch.profiles.item(0)
            source_body = None
        else:
            source_body = (
                sweep_profile.body
                if adsk.fusion.BRepFace.cast(sweep_profile)
                else None)
        try:
            sweep_feature = _do_sweep(
                comp, sweep_profile, spline, face, occurrence)
        except RuntimeError as e:
            npts = 0
            try:
                npts = spline.fitPoints.count
            except Exception:
                pass
            raise RuntimeError(
                'Sweep failed at segment %d/%d (turns %.4f..%.4f, %d fit '
                'points): %s' % (
                    segment_index + 1, segment_count,
                    first_turn, last_turn, npts, e))
        sweep_feature.name = segment_name + '_Sweep'
        new_bodies = []
        for body_index in range(sweep_feature.bodies.count):
            candidate = sweep_feature.bodies.item(body_index)
            if not source_body or candidate.entityToken != source_body.entityToken:
                new_bodies.append(candidate)
        if len(new_bodies) != 1:
            raise RuntimeError(
                'Expected one new body in sweep segment ' +
                str(segment_index + 1) + ', got ' +
                str(len(new_bodies)))
        segment_body = new_bodies[0]
        segment_body.name = segment_name + '_Body'
        segment_bodies.append(segment_body)
        # NO chaining via sweep_feature.endFaces: with per-segment profiles the
        # next segment already has its own aligned profile above.

    # ── Exit ramp (TESTING): mirrors the entrance ramp. The first loft
    # section is a FULL-SIZE trapezoid in the overlap arc BEFORE the sweep's
    # end junction (i.e. inside the main body), so the boolean join has real
    # volume overlap; the shrink then happens over the lead_out part and the
    # last section reaches exit_scale at the helix end. ──
    if use_lead_out:
        sketch_exit = comp.sketches.add(comp.xYConstructionPlane)
        sketch_exit.name = safe_name + '_LeadOut_Helix'
        created_sketches.append(sketch_exit)
        sketch_exit.isComputeDeferred = True
        exit_spline = sketch_exit.sketchCurves.sketchFittedSplines.add(
            exit_shifted)
        sketch_exit.isComputeDeferred = False

        exit_scale = LEAD_IN_START_SCALE
        if exit_scale * short_cm < MIN_SHORT_EDGE_CM:
            exit_scale = min(1.0, MIN_SHORT_EDGE_CM / max(short_cm, 1e-9))

        # k=0 (full size) sits in the overlap arc BEFORE the junction, i.e.
        # inside the main sweep body; k=1 sits exactly at the junction, still
        # full size; the remaining sections shrink down to exit_scale.
        junc_frac_exit = overlap_turns / (
            lead_out_turns + overlap_turns)
        n_grad = LEAD_IN_SECTIONS - 1
        loft_profiles = []
        for k in range(LEAD_IN_SECTIONS):
            if k == 0:
                # Overlap section: full size, inside the main body.
                frac = 0.0
                scale = 1.0
            else:
                frac = junc_frac_exit + (
                    (k - 1) / float(n_grad - 1)) * (1.0 - junc_frac_exit)
                scale = 1.0 - (1.0 - exit_scale) * (
                    (k - 1) / float(n_grad - 1))
            plane_input_k = comp.constructionPlanes.createInput()
            plane_input_k.setByDistanceOnPath(
                exit_spline, adsk.core.ValueInput.createByReal(frac))
            section_plane = comp.constructionPlanes.add(plane_input_k)
            section_plane.name = safe_name + '_LeadOut_Plane_' + str(k)
            # Anchors come from the SHIFTED helix (original helix + L/2);
            # centring the long edge on them puts the long-edge START back on
            # the original (sweep) helix, matching the sweep profile exactly.
            anchor = exit_shifted.item(
                int(round(frac * LEAD_IN_MIN_POINTS)))
            section_sketch, _ = _create_trapezoid(
                comp, section_plane, face, L_cm * scale, H_cm * scale,
                angle_degrees, anchor, is_external,
                center_on_anchor=True,
                root_embed_cm=THREAD_ROOT_EMBED_CM)
            section_sketch.name = safe_name + '_LeadOut_Section_' + str(k)
            created_sketches.append(section_sketch)
            if section_sketch.profiles.count == 0:
                raise RuntimeError(
                    'Exit section did not form a closed region')
            loft_profiles.append(section_sketch.profiles.item(0))

        loft_features = comp.features.loftFeatures
        loft_input = loft_features.createInput(
            adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        for profile in loft_profiles:
            loft_input.loftSections.add(profile)
        loft_input.isSolid = True
        loft_feature = loft_features.add(loft_input)
        loft_feature.name = safe_name + '_LeadOut_Loft'
        if loft_feature.bodies.count != 1:
            raise RuntimeError('Exit loft did not produce a single body')
        lead_out_body = loft_feature.bodies.item(0)
        lead_out_body.name = safe_name + '_LeadOut_Body'

    all_bodies = []
    if use_lead_in:
        all_bodies.append(lead_body)
    all_bodies.extend(segment_bodies)
    if use_lead_out:
        all_bodies.append(lead_out_body)
    # Use the FIRST SEGMENT body (the large main sweep) as the boolean
    # target. The ramp lofts are smaller and can be almost fully contained
    # by it, which the kernel handles reliably. Using a small ramp loft as
    # the target fails silently on some geometries (the combine feature
    # turns red while add() still returns, so the bodies stay separate and
    # the thread looks disjoint, e.g. D34.6/H10 with L3/H1).
    if segment_bodies:
        thread_body = segment_bodies[0]
        tool_bodies = []
        if use_lead_in:
            tool_bodies.append(lead_body)
        tool_bodies.extend(segment_bodies[1:])
        if use_lead_out:
            tool_bodies.append(lead_out_body)
    else:
        thread_body = all_bodies[0]
        tool_bodies = all_bodies[1:]
    if tool_bodies:
        tools = adsk.core.ObjectCollection.create()
        for tool_body in tool_bodies:
            tools.add(tool_body)
        combine_input = comp.features.combineFeatures.createInput(
            thread_body, tools)
        combine_input.operation = (
            adsk.fusion.FeatureOperations.JoinFeatureOperation)
        combine_input.isKeepToolBodies = False
        combine_feature = comp.features.combineFeatures.add(combine_input)
        combine_feature.name = safe_name + '_Segments_Join'
    thread_body.name = safe_name + '_Body'

    joined = False
    result_body = thread_body
    if join_to_target:
        tools = adsk.core.ObjectCollection.create()
        tools.add(thread_body)
        combine_input = comp.features.combineFeatures.createInput(
            target_body, tools)
        combine_input.operation = (
            adsk.fusion.FeatureOperations.JoinFeatureOperation)
        combine_input.isKeepToolBodies = False
        combine_feature = comp.features.combineFeatures.add(combine_input)
        combine_feature.name = safe_name + '_Join'
        result_body = target_body
        joined = True

    timeline_group_name = ''
    try:
        timeline_end_index = design.timeline.count - 1
        if timeline_end_index >= timeline_start_index:
            timeline_group = design.timeline.timelineGroups.add(
                timeline_start_index, timeline_end_index)
            if timeline_group:
                timeline_group.name = safe_name + '_Generation'
                timeline_group_name = timeline_group.name
    except Exception:
        pass  # timeline grouping is cosmetic; never fail the generation

    # Hide all sketches created during generation (cosmetic; never fail).
    # The sketches stay in the timeline/browser and can be re-shown there.
    try:
        for sk in created_sketches:
            if sk:
                sk.isVisible = False
    except Exception:
        pass

    app.activeViewport.fit()
    return {
        'success': True,
        'thread_type': 'external' if is_external else 'internal',
        'tooth_width_mm': L_cm * 10.0,
        'short_edge_mm': short_cm * 10.0,
        'tooth_height_mm': H_cm * 10.0,
        'flank_angle_degrees': angle_degrees,
        'pitch_mm': pitch * 10.0,
        'turns': turns,
        'thread_length_mm': helix_height * 10.0,
        'end_offset_mm': offset_cm * 10.0,
        'samples_per_turn': pts_per_turn,
        'deviation_ratio': deviation_ratio,
        'lead_in_turns': lead_in_turns,
        'lead_out_turns': lead_out_turns,
        'segment_count': segment_count,
        'max_turns_per_sweep': segment_turn_limit,
        'cylinder_radius_mm': radius * 10.0,
        'cylinder_height_mm': cylinder_height * 10.0,
        'joined_to_target': joined,
        'timeline_group_name': timeline_group_name,
        'result_body_token': result_body.entityToken,
    }


def generate_thread_from_json(payload):
    """JSON-friendly automation entry point.

    Required payload field:
        face_token

    Optional fields:
        tooth_width_mm, tooth_height_mm, end_offset_mm,
        samples_per_turn, join_to_target, feature_name,
        max_turns_per_sweep, flank_angle_degrees, enable_lead,
        pitch_mm, crest_width_mm
    """
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError('payload must be a dict or JSON object string')
    token = payload.get('face_token')
    if not token:
        raise ValueError('payload.face_token is required')

    design = adsk.fusion.Design.cast(
        adsk.core.Application.get().activeProduct)
    if not design:
        raise RuntimeError('No active Fusion design')
    entities = design.findEntityByToken(token)
    if not entities:
        raise ValueError('face_token did not resolve in the active design')
    face = adsk.fusion.BRepFace.cast(entities[0])
    if not face:
        raise ValueError('face_token does not identify a BRepFace')

    return generate_thread(
        face=face,
        tooth_width_mm=payload.get('tooth_width_mm', 3.0),
        tooth_height_mm=payload.get('tooth_height_mm', 1.0),
        end_offset_mm=payload.get('end_offset_mm', 0.0),
        samples_per_turn=payload.get('samples_per_turn', 16),
        join_to_target=bool(payload.get('join_to_target', False)),
        feature_name=payload.get('feature_name', 'GeneratedThread'),
        max_turns_per_sweep=payload.get('max_turns_per_sweep', 4),
        flank_angle_degrees=payload.get('flank_angle_degrees', 45.0),
        deviation_ratio=payload.get('deviation_ratio', None),
        enable_lead=bool(payload.get('enable_lead', True)),
        pitch_mm=payload.get('pitch_mm', None),
        crest_width_mm=payload.get('crest_width_mm', None),
    )


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
                '<b>【TEST P/S】螺纹生成工具（外/内螺纹自动识别）</b><br/>'
                '选择圆柱外表面（螺杆）或圆孔内表面（螺母），自动识别。<br/>'
                f'<a href="{PRIVACY_URL}">隐私政策 / Privacy Policy</a>', 3, True)

            sel = inputs.addSelectionInput('face', '圆柱/圆孔面', '请点击圆柱外表面或圆孔内表面')
            sel.addSelectionFilter('CylindricalFaces')
            sel.setSelectionLimits(1, 1)

            inputs.addTextBoxCommandInput('sep1', '',
                '<b>── 梯形截面参数 ──</b>', 1, True)
            expert_inp = inputs.addBoolValueInput(
                'expert_mode', '专家模式（独立 P / S / L / H）', True, '', False)
            expert_inp.tooltip = '关闭时使用原参数联动；开启后四个尺寸可独立设置'
            pitch_inp = inputs.addValueInput('pitch_P', '螺距 P', 'mm',
                adsk.core.ValueInput.createByString('4 mm'))
            crest_inp = inputs.addValueInput('crest_S', '牙顶宽度 S', 'mm',
                adsk.core.ValueInput.createByString('1 mm'))
            pitch_inp.isVisible = False
            crest_inp.isVisible = False
            inputs.addValueInput('root_L', '牙底宽度 L', 'mm',
                adsk.core.ValueInput.createByString('3 mm'))
            inputs.addValueInput('trap_H', '梯形高度 H（径向牙高）', 'mm',
                adsk.core.ValueInput.createByString('1 mm'))
            inputs.addValueInput('flank_angle', '牙侧角度 α（普通模式）', 'deg',
                adsk.core.ValueInput.createByString('45 deg'))
            inputs.addTextBoxCommandInput(
                'profile_status', '截面状态',
                '<b>普通模式：S=1.000 mm　P=4.000 mm</b><br/>'
                '<font color="green">参数由 L / H / α 安全联动</font>', 2, True)

            inputs.addTextBoxCommandInput('sep2', '',
                '<b>── 路径参数 ──</b>', 1, True)
            inputs.addValueInput('ppt', '每圈采样点数', '',
                adsk.core.ValueInput.createByReal(16))
            inputs.addValueInput('offset', '端面偏移', 'mm',
                adsk.core.ValueInput.createByString('0 mm'))

            lead_inp = inputs.addBoolValueInput(
                'enable_lead', '螺纹收口', True, '', True)
            lead_inp.tooltip = '在螺纹两端生成 1/8 圈渐变收口，更易旋入'
            lead_inp.tooltipDescription = (
                '勾选后，螺纹入口/出口各生成 1/8 圈渐变收口'
                '（牙高+牙宽 10%↔100%），便于螺母/螺杆对位旋入，'
                '且两端更易打印。<br/><br/>'
                '取消勾选则生成完整牙高的普通螺纹（旧版行为）。')

            join_inp = inputs.addBoolValueInput(
                'join_target', '合并到圆柱体', True, '', True)
            join_inp.tooltip = '将生成的螺纹与所选圆柱体合并为一个实体'
            join_inp.tooltipDescription = (
                '勾选后，螺纹体会通过布尔合并与所选圆柱体合并为单一实体。<br/><br/>'
                '取消勾选则螺纹与圆柱体保持为两个独立实体（仅贴合）。<br/><br/>'
                '合并可消除放大时两实体之间的接缝。')

            inputs.addBoolValueInput(
                'show_advanced', '显示高级选项', False, '', False)

            ratio_inp = inputs.addValueInput(
                'dev_ratio', '路径偏差系数', '',
                adsk.core.ValueInput.createByReal(
                    HELIX_DEVIATION_TOLERANCE_RATIO))
            ratio_inp.isVisible = False
            ratio_inp.tooltip = '路径偏差占牙高的比例（0.1–1.0）'
            ratio_inp.tooltipDescription = (
                '控制螺旋拟合样条偏离圆柱面的允许偏差，'
                '以牙高 H 的比例表示。<br/><br/>'
                '允许偏差 = 系数 × H。系数越小，每圈采样点越多，'
                '牙侧面越光滑，但生成越慢。<br/><br/>'
                '默认 0.5（允许偏差 = 牙高的一半），推荐范围 0.2–0.5。'
                '过小会显著增加生成时间，过大可能导致扫掠失败。')

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
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            ea       = adsk.core.InputChangedEventArgs.cast(args)
            all_ins  = ea.firingEvent.sender.commandInputs
            sel_inp  = adsk.core.SelectionCommandInput.cast(all_ins.itemById('face'))
            P_inp    = adsk.core.ValueCommandInput.cast(all_ins.itemById('pitch_P'))
            S_inp    = adsk.core.ValueCommandInput.cast(all_ins.itemById('crest_S'))
            L_inp    = adsk.core.ValueCommandInput.cast(all_ins.itemById('root_L'))
            H_inp    = adsk.core.ValueCommandInput.cast(all_ins.itemById('trap_H'))
            angle_inp = adsk.core.ValueCommandInput.cast(
                all_ins.itemById('flank_angle'))
            expert_inp = adsk.core.BoolValueCommandInput.cast(
                all_ins.itemById('expert_mode'))
            ppt_inp  = adsk.core.ValueCommandInput.cast(all_ins.itemById('ppt'))
            off_inp  = adsk.core.ValueCommandInput.cast(all_ins.itemById('offset'))
            adv_inp  = adsk.core.BoolValueCommandInput.cast(
                all_ins.itemById('show_advanced'))
            ratio_inp = adsk.core.ValueCommandInput.cast(
                all_ins.itemById('dev_ratio'))
            calc_box = adsk.core.TextBoxCommandInput.cast(all_ins.itemById('calc_info'))
            profile_box = adsk.core.TextBoxCommandInput.cast(
                all_ins.itemById('profile_status'))

            has_face = sel_inp.selectionCount > 0
            L_val = L_inp.value
            H_val    = H_inp.value
            ppt      = max(4, int(ppt_inp.value))
            offset   = off_inp.value
            expert_mode = bool(expert_inp.value)

            P_inp.isVisible = expert_mode
            S_inp.isVisible = expert_mode
            angle_inp.isVisible = not expert_mode

            if expert_mode:
                P = P_inp.value
                S = S_inp.value
                angle_deg = 0.0
                try:
                    _, angle_deg = _profile_from_edges(L_val, S, H_val)
                except ValueError:
                    pass
            else:
                angle_deg = math.degrees(angle_inp.value)
                try:
                    _, S, _ = _profile_dimensions(L_val, H_val, angle_deg)
                except (ValueError, ZeroDivisionError):
                    S = -1.0
                P = L_val + S
                # Keep the expert fields synchronised so switching modes starts
                # from the profile currently shown in normal mode.
                if P > 0 and abs(P_inp.value - P) > PROFILE_TOLERANCE_CM:
                    P_inp.value = P
                if S > 0 and abs(S_inp.value - S) > PROFILE_TOLERANCE_CM:
                    S_inp.value = S

            # Toggle the advanced ratio input visibility
            ratio_inp.isVisible = bool(adv_inp.value)
            # Clamp the ratio to a sane range; use the default when invalid
            ratio_val = float(ratio_inp.value)
            if not (0.0 < ratio_val <= 1.0):
                ratio_val = HELIX_DEVIATION_TOLERANCE_RATIO
                if adv_inp.value:
                    ratio_inp.value = ratio_val

            lines = []

            warnings = []
            if expert_mode:
                if P <= 0 or S <= 0 or L_val <= 0 or H_val <= 0:
                    warnings.append('危险：P、S、L、H 应大于 0。')
                if L_val <= S:
                    warnings.append('危险：牙底宽度 L 应大于牙顶宽度 S，否则无法形成普通梯形。')
                if P < L_val:
                    warnings.append('危险：螺距 P 小于牙底宽度 L，相邻牙可能重叠。')
                if angle_deg > 45.0:
                    warnings.append('危险：梯形底角大于 45°，牙侧过陡，打印和扫掠失败风险较高。')
                if 0.008 <= S < 0.02:
                    warnings.append('牙顶宽度在 0.08–0.20 mm：打印时请降低层高并调整线宽。')
                elif 0 < S < 0.008:
                    warnings.append('危险：牙顶宽度小于 0.08 mm，通常难以可靠打印；请降低层高并调整线宽。')
            else:
                if not MIN_FLANK_ANGLE_DEG <= angle_deg <= MAX_FLANK_ANGLE_DEG:
                    warnings.append('普通模式牙侧角必须在 5°–45°。')
                if S < MIN_SHORT_EDGE_CM - PROFILE_TOLERANCE_CM:
                    warnings.append('普通模式牙顶宽度不得小于 0.08 mm，请减小 H 或增大 L。')
                if L_val <= 0 or H_val <= 0:
                    warnings.append('L 和 H 必须大于 0。')

            if warnings:
                mode_label = '专家模式' if expert_mode else '普通模式'
                profile_box.formattedText = (
                    f'<b>{mode_label}　底角: {angle_deg:.2f}°</b><br/>'
                    '<font color="orange"><b>⚠ ' +
                    '<br/>⚠ '.join(warnings) + '</b></font>')
            else:
                if expert_mode:
                    profile_box.formattedText = (
                        f'<b>专家模式　梯形底角: {angle_deg:.2f}°</b><br/>'
                        '<font color="green">四个尺寸独立设置</font>')
                else:
                    profile_box.formattedText = (
                        f'<b>普通模式：S={S*10:.3f} mm　P={P*10:.3f} mm</b><br/>'
                        '<font color="green">参数由 L / H / α 安全联动</font>')

            if has_face and P > 0:
                face = adsk.fusion.BRepFace.cast(sel_inp.selection(0).entity)
                radius, height, _, _, _ = _get_cyl_info(face)
                is_ext = _is_external_face(face)
                typ_label = '外螺纹（螺杆）' if is_ext else '内螺纹（螺母）'
                dir_label = '向外长肉' if is_ext else '向内长肉'

                N = max(1, int((height - offset) / P + 1e-9) - 1)  # 留一圈空间；+1e-9防浮点截断
                # Reserve one full turn of space
                if N * P > height - offset and N > 1:
                    N -= 1
                eff_ppt, N, n_pts, capped = _plan_helix_sampling(
                    radius, ppt, N, H_val * 10.0, ratio_val)
                act_h = N * P
                n_total = n_pts + 1 if N > 0 else 0
                # 螺旋路径总长度（考虑螺距）
                circle_mm = 2 * math.pi * radius * 10  # 每圈周长 mm
                P_mm = P * 10
                path_m = N * math.sqrt(circle_mm**2 + P_mm**2) / 1000 if N > 0 else 0

                lines.append(f'<b>类型:</b> {typ_label}（{dir_label}）')
                lines.append(f'<b>长边 L:</b> {L_val*10:.2f} mm　'
                             f'<b>牙顶宽度 S:</b> {S*10:.2f} mm')
                lines.append(f'<b>梯形高度 H:</b> {H_val*10:.2f} mm　'
                             f'<b>螺距 P:</b> {P*10:.2f} mm')
                lines.append(f'<b>梯形底角:</b> {angle_deg:.2f}°')
                lines.append(f'<b>圆柱 R={radius*10:.2f} mm  H={height*10:.2f} mm</b>')
                lines.append(f'<b>转数:</b> {N}　螺旋高度={act_h*10:.2f} mm　偏移={offset*10:.1f} mm')
                lines.append(f'<b>螺旋总长:</b> 约 {path_m:.0f} m　<b>样条线点数:</b> {n_pts}（每圈 {eff_ppt} 点）')
                if adv_inp.value:
                    lines.append(
                        f'<b>路径偏差系数:</b> {ratio_val:.2f} '
                        f'（允许偏差 ≤ {ratio_val * H_val * 10:.3f} mm）')
                if capped:
                    lines.append('<font color="orange">⚠ 圈数已达样条点数预算上限，为保证路径贴合圆柱已自动减少圈数；如需更多圈数请增大端面偏移以外的可用长度或降低每圈采样</font>')
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
            expert = adsk.core.BoolValueCommandInput.cast(
                inputs.itemById('expert_mode')).value
            valid = sel.selectionCount == 1
            if valid and not expert:
                L_val = inputs.itemById('root_L').value
                H_val = inputs.itemById('trap_H').value
                angle_deg = math.degrees(inputs.itemById('flank_angle').value)
                try:
                    _, S_val, _ = _profile_dimensions(
                        L_val, H_val, angle_deg)
                    valid = (
                        L_val > 0 and H_val > 0
                        and MIN_FLANK_ANGLE_DEG <= angle_deg <= MAX_FLANK_ANGLE_DEG
                        and S_val >= MIN_SHORT_EDGE_CM - PROFILE_TOLERANCE_CM)
                except (ValueError, ZeroDivisionError):
                    valid = False
            # Expert-mode risks are warnings only and do not disable OK.
            ea.areInputsValid = valid
        except:
            pass


class MyExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        """Read GUI inputs and delegate all modelling to the public API."""
        try:
            inputs = adsk.core.CommandEventArgs.cast(
                args).command.commandInputs
            selection = adsk.core.SelectionCommandInput.cast(
                inputs.itemById('face'))
            pitch = adsk.core.ValueCommandInput.cast(
                inputs.itemById('pitch_P'))
            crest_width = adsk.core.ValueCommandInput.cast(
                inputs.itemById('crest_S'))
            root_width = adsk.core.ValueCommandInput.cast(
                inputs.itemById('root_L'))
            tooth_height = adsk.core.ValueCommandInput.cast(
                inputs.itemById('trap_H'))
            flank_angle = adsk.core.ValueCommandInput.cast(
                inputs.itemById('flank_angle'))
            expert_mode = bool(adsk.core.BoolValueCommandInput.cast(
                inputs.itemById('expert_mode')).value)
            samples = adsk.core.ValueCommandInput.cast(
                inputs.itemById('ppt'))
            ratio_inp = adsk.core.ValueCommandInput.cast(
                inputs.itemById('dev_ratio'))
            join_inp = adsk.core.BoolValueCommandInput.cast(
                inputs.itemById('join_target'))
            lead_inp = adsk.core.BoolValueCommandInput.cast(
                inputs.itemById('enable_lead'))

            ratio_val = float(ratio_inp.value)
            if not (0.0 < ratio_val <= 1.0):
                ratio_val = HELIX_DEVIATION_TOLERANCE_RATIO

            result = generate_thread(
                face=adsk.fusion.BRepFace.cast(
                    selection.selection(0).entity),
                tooth_width_mm=root_width.value * 10.0,
                tooth_height_mm=tooth_height.value * 10.0,
                end_offset_mm=inputs.itemById('offset').value * 10.0,
                samples_per_turn=max(4, int(samples.value)),
                join_to_target=bool(join_inp.value),
                feature_name='GeneratedThread',
                flank_angle_degrees=math.degrees(flank_angle.value),
                deviation_ratio=ratio_val,
                enable_lead=bool(lead_inp.value),
                pitch_mm=pitch.value * 10.0 if expert_mode else None,
                crest_width_mm=(
                    crest_width.value * 10.0 if expert_mode else None),
            )

            thread_label = (
                '外螺纹（螺杆）'
                if result['thread_type'] == 'external'
                else '内螺纹（螺母）')
            lead_msg = (
                f"入口/出口各 {result['lead_in_turns'] * 8:.0f}/8 圈渐变"
                '（牙高+牙宽 10%↔100%）'
                if result['lead_in_turns'] > 0
                else '未启用（完整牙高螺纹）')
            message = (
                f'✓ {thread_label}生成完成！\n\n'
                f"【截面】L={result['tooth_width_mm']:.2f} mm  "
                f"S={result['short_edge_mm']:.2f} mm  "
                f"H={result['tooth_height_mm']:.2f} mm\n"
                f"牙侧角度={result['flank_angle_degrees']:.2f}°\n"
                f"【螺旋】P={result['pitch_mm']:.2f} mm  "
                f"转数={result['turns']}  "
                f"高度={result['thread_length_mm']:.2f} mm\n"
                f"【收口】{lead_msg}\n"
                f"【结果】{'已合并到圆柱体（实体=1）' if result['joined_to_target'] else '独立螺纹体（实体=2：螺纹+圆柱）'}"
            )
            radius_mm = result['cylinder_radius_mm']
            height_mm = result['tooth_height_mm']
            clr = RECOMMENDED_CLEARANCE_MM
            dia_clr = 2 * clr  # per-side clearance -> diametral clearance
            if result['thread_type'] == 'external':
                base_diameter = 2 * radius_mm + 2 * height_mm
                suggested = base_diameter + dia_clr
                message += (
                    '\n\n📌 配合螺母建议内径：\n'
                    f'  圆柱外径（{2 * radius_mm:.1f} mm）+ '
                    f'{2 * height_mm:.1f} mm（2 × H）+ 间隙\n'
                    f'  = {base_diameter:.1f} mm + 间隙\n'
                    f'  建议间隙（单侧）≈ {clr:.1f} mm → 内径 ≈ {suggested:.1f} mm\n'
                    f'  （FDM 打印常用单侧间隙 0.2–0.4 mm，可按打印机精度调整）')
            else:
                base_diameter = 2 * radius_mm - 2 * height_mm
                suggested = base_diameter - dia_clr
                message += (
                    '\n\n📌 配合螺杆建议外径：\n'
                    f'  圆孔内径（{2 * radius_mm:.1f} mm）- '
                    f'{2 * height_mm:.1f} mm（2 × H）- 间隙\n'
                    f'  = {base_diameter:.1f} mm - 间隙\n'
                    f'  建议间隙（单侧）≈ {clr:.1f} mm → 外径 ≈ {suggested:.1f} mm\n'
                    f'  （FDM 打印常用单侧间隙 0.2–0.4 mm，可按打印机精度调整）')
            _ui.messageBox(message, '生成成功')
        except:
            _ui.messageBox(
                traceback.format_exc(), '执行失败')

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
        ws = _ui.workspaces.itemById('FusionSolidEnvironment')
        if ws:
            panel = ws.toolbarPanels.itemById('SolidCreatePanel')
            if panel:
                ctrl = panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()
        old = _ui.commandDefinitions.itemById(CMD_ID)
        if old:
            old.deleteMe()

        # 注册命令定义
        # Register command definition
        cmd_def = _ui.commandDefinitions.addButtonDefinition(
            CMD_ID, CMD_NAME,
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
        # 先移除工具栏上的控件
        ws = _ui.workspaces.itemById('FusionSolidEnvironment')
        if ws:
            panel = ws.toolbarPanels.itemById('SolidCreatePanel')
            if panel:
                ctrl = panel.controls.itemById(CMD_ID)
                if ctrl:
                    ctrl.deleteMe()
        # 再删除命令定义
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except:
        pass
