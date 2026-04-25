"""
PyMOL Visualization Configuration — Publication Quality for Molecular Docking
==========================================================================
Based on comprehensive research:
  1. PyMOL Official Documentation (pymol.org/dokuwiki)
  2. Leipzig University PyMOL Tutorial (research.uni-leipzig.de/straeter)
  3. Oxford Protein Informatics Group — "Making Pretty Pictures with PyMOL"
  4. CB-Dock2 paper (PMC9252749) + platform cavity visualization
  5. PyMOL Wiki settings reference (dash, surface, ray, cartoon_*)
  6. Wilson Lab PyMOL — Cartoon Style Guide
  7. APBS Electrostatics Plugin documentation

Key findings applied:
  - dash_gap=0.4 / dash_radius=0.05 / dash_length=0.3 (Leipzig standard)
  - ligand C = gold, pocket C = bluewhite/gray50 (CB-Dock2 convention)
  - surface transparency=0.25, cartoon_transparency=0.15
  - ambient=0.5 (default too dark)
  - ray_trace_mode=1 for outline style, 0 for standard
  - cartoon_ring_mode=3 (oval rings)
  - stick_radius=0.2 (slightly thinner than default 0.25)
  - h_bond_max_angle=40 for geometry-based detection

Author: PrimeClaw (OpenClaw) — 2026-04-25
"""

# ─────────────────────────────────────────────────────────────────────────────
# RENDERING QUALITY PRESETS
# ─────────────────────────────────────────────────────────────────────────────

DRAFT = dict(
    antialias=1, ray=0,
    width=800, height=600, dpi=96
)

STANDARD = dict(
    antialias=2, ray=1,
    width=1200, height=900, dpi=150,
    ray_trace_mode=0, ray_shadow=0,
    ambient=0.5, specular=0.6, shininess=55
)

PUBLICATION = dict(
    antialias=4, ray=1,
    width=2400, height=1800, dpi=300,
    ray_trace_mode=0,            # 0=standard, 1=outline(推荐药学), 3=cartoon-quantized
    ray_opaque_background=1,      # 确保纯白/纯黑背景
    ray_shadow=0,                # 无阴影（复杂口袋图更清晰）
    ambient=0.5,                 # 默认0.15太暗，0.5使白色真正显示为白
    specular=0.6, shininess=55,
    reflect_power=0.2,
    light_count=2,
)

PUBLICATION_OUTLINE = dict(
    antialias=4, ray=1,
    width=2400, height=1800, dpi=300,
    ray_trace_mode=1,            # 带轮廓线的卡通风格（Nature/Science药学常用）
    ray_opaque_background=1,
    ray_shadow=0,
    ambient=0.5, specular=0.6, shininess=55,
    reflect_power=0.2,
    light_count=2,
)

# ─────────────────────────────────────────────────────────────────────────────
# INTERACTION DASH PARAMETERS  (Leipzig Lab Standard)
# ─────────────────────────────────────────────────────────────────────────────
# Source: https://research.uni-leipzig.de/straeter/pymol/pymol_hbond.html
#
# H-bond dashes:  dash_gap=0.4, dash_radius=0.05, dash_length=0.3
#   → 比默认(dash_gap=0.35, dash_radius=0.0)更精致，圆柱形虚线
# π-π dashes:    dash_gap=0.35, dash_color=magenta
# 疏水接触: 无标准虚线，用橙色球/面表示

DASH_PRESETS = {
    # 精细虚线（Leipzig 标准，推荐）
    'fine': dict(
        dash_gap=0.4,
        dash_radius=0.05,
        dash_length=0.3,
        dash_width=2.5,
        dash_as_cylinders=True,
        dash_round_ends=True,
    ),
    # 标准虚线
    'standard': dict(
        dash_gap=0.35,
        dash_radius=0.0,   # 默认=0，即用 dash_width 计算
        dash_length=0.15,
        dash_width=3.0,
        dash_as_cylinders=True,
        dash_round_ends=True,
    ),
    # 加粗虚线（交互密集时更醒目）
    'bold': dict(
        dash_gap=0.3,
        dash_radius=0.08,
        dash_length=0.25,
        dash_width=4.0,
        dash_as_cylinders=True,
        dash_round_ends=True,
    ),
}

DASH_COLOR_MAP = {
    'H-bond':      'cyan',    # 青色（经典）
    'H-bond-alt':  'green',   # 绿色（生化文献常见）
    'π-π':         'magenta', # 品红（区分 H 键）
    'π-π-alt':     'green',   # 绿色备选
    'Hydrophobic': 'orange',   # 橙色（疏水）
    'Ionic':       'yellow',  # 离子键
    'Halogen':     'skyblue', # 卤键
    'Metal':       'gray50',  # 金属配位
}

# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT COLORS (CPK + Docking Literature)
# ─────────────────────────────────────────────────────────────────────────────

CPK_COLORS = {
    'C':  'gray70',
    'O':  'red',
    'N':  'blue',
    'S':  'yellow',
    'P':  'orange',
    'H':  'white',
    'F':  'brightgreen',
    'Cl': 'green',
    'Br': 'brown',
    'I':  'purple',
    'FE': 'orange',   # Iron (heme)
    'ZN': 'gray50',   # Zinc (metal)
    'MG': 'green',    # Magnesium
    'CA': 'lime',     # Calcium
}

# ─────────────────────────────────────────────────────────────────────────────
# PROTEIN CARTOON COLOR SCHEMES
# ─────────────────────────────────────────────────────────────────────────────

CARTOON_COLORS = {
    # 白底 publication 标准（蓝白渐变）
    'cold':     'palecyan',      # 冷色系，最常用
    'blue':     'bluewhite',     # CB-Dock2 风格
    # 暖色系（适合膜蛋白）
    'warm':     'palegreen',
    # 中性灰（交互图专用，弱化蛋白背景）
    'neutral':  'gray80',
    # 彩虹链（多链复合物）
    'rainbow':  'rainbow',
    # 按二级结构（helix=red, sheet=yellow, loop=gray）
    'ss':       'ss',
}

# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND PRESETS
# ─────────────────────────────────────────────────────────────────────────────

BG_WHITE = 'white'   # 复合体全景图、期刊常规要求
BG_BLACK = 'black'   # 口袋特写、配体突出（药物化学期刊偏好）
BG_GRAY  = 'gray20'  # 深灰（柔和对比）

# ─────────────────────────────────────────────────────────────────────────────
# CARTOON STYLE PRESETS
# ─────────────────────────────────────────────────────────────────────────────

CARTOON_PUBLICATION = dict(
    cartoon_fancy_helices=1,    # 精美螺旋（椭圆截面）
    cartoon_fancy_sheets=1,      # 箭头状 β 片层
    cartoon_smooth_loops=1,       # 平滑 loop 区
    cartoon_ring_mode=3,          # 3=椭圆侧链环（比默认更美观）
    cartoon_ring_width=0.1,
    cartoon_ring_transparency=30, # 30% 透明（透出后方结构）
    cartoon_transparency=0.0,     # 蛋白整体不透明
    cartoon_side_chain_helper=1,  # 口袋区域自动显示侧链
    cartoon_discrete_colours=1,   # 防止 strand 颜色渗入 loop
    cartoon_gap_cutoff=20,
)

CARTOON_POCKET = dict(
    cartoon_fancy_helices=1,
    cartoon_fancy_sheets=1,
    cartoon_smooth_loops=1,
    cartoon_ring_mode=3,
    cartoon_ring_width=0.1,
    cartoon_ring_transparency=30,
    cartoon_transparency=0.15,   # 口袋蛋白半透明（透视配体周围）
    cartoon_side_chain_helper=1,
    cartoon_discrete_colours=1,
    cartoon_gap_cutoff=20,
)

CARTOON_INTERACTION = dict(
    cartoon_fancy_helices=1,
    cartoon_fancy_sheets=1,
    cartoon_smooth_loops=1,
    cartoon_ring_mode=3,
    cartoon_ring_width=0.1,
    cartoon_ring_transparency=40,
    cartoon_transparency=0.25,   # 更透明（重点是虚线和配体）
    cartoon_side_chain_helper=1,
    cartoon_discrete_colours=1,
    cartoon_gap_cutoff=20,
)

# ─────────────────────────────────────────────────────────────────────────────
# SURFACE PRESETS
# ─────────────────────────────────────────────────────────────────────────────

SURFACE_POCKET = dict(
    surface_quality=1,           # 默认0，1=更平滑
    transparency=0.25,            # 25% 透明（配体轮廓清晰可见）
    solvent_radius=1.4,           # 探针半径 1.4 Å（溶剂可及表面）
    color='white',               # 可被 ramp 替换为静电势色
    type='surface',              # connolly surface
)

# ─────────────────────────────────────────────────────────────────────────────
# LIGHTING PRESETS
# ─────────────────────────────────────────────────────────────────────────────

LIGHTING_DEFAULT = dict(
    light_count=2,
    ambient=0.5,                 # 关键：默认太暗
    specular=0.6,
    shininess=55,
    reflect_power=0.2,
    ray_shadow=0,                # 无阴影（杂乱场景避免干扰）
)

LIGHTING_FLAT = dict(
    light_count=1,
    ambient=0.8,
    specular=0.0,
    shininess=0,
    reflect_power=0.0,
    ray_shadow=0,
)

LIGHTING_SPECULAR = dict(
    light_count=2,
    ambient=0.3,
    specular=1.0,
    shininess=80,
    reflect_power=0.3,
    ray_shadow=0,
)

# ─────────────────────────────────────────────────────────────────────────────
# STICK / SPHERE PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────

STICK_PRESETS = {
    'fine': dict(               # Leipzig 标准（配体/口袋）
        stick_radius=0.2,       # 默认0.25，略微变细更精致
        stick_quality=8,
        valence=1,              # 显示双键区分
        stick_ball=0,           # 不显示端点球
    ),
    'bold': dict(              # 粗棍（药物化学宣传图）
        stick_radius=0.35,
        stick_quality=12,
        valence=1,
        stick_ball=0,
    ),
    'ball_and_stick': dict(     # 球棍模型（配体特写）
        stick_radius=0.15,
        stick_quality=10,
        valence=1,
        stick_ball=1,
        stick_ball_ratio=1.5,
    ),
}

SPHERE_PRESETS = {
    'cpk': dict(
        sphere_scale=0.25,     # CPK 比例
        sphere_quality=2,
    ),
    'vdw': dict(                # 范德华半径（原子接触面）
        sphere_scale=1.0,
        sphere_quality=3,
    ),
    'lite': dict(               # 轻量（口袋球）
        sphere_scale=0.15,
        sphere_quality=1,
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# SCENE PRESETS — 完整参数集，适配不同工况
# ─────────────────────────────────────────────────────────────────────────────

# ── Scene 1: 复合体全景 ────────────────────────────────────────────────────
SCENE_COMPLEX = {
    'description': '蛋白-配体复合体全景（TOC / Fig.1 风格）',

    # 背景
    'background': BG_WHITE,

    # 蛋白表征
    'protein': 'cartoon',
    'protein_color': 'cold',     # palecyan
    'cartoon': CARTOON_PUBLICATION,

    # 配体表征
    'ligand_repr': 'sticks',
    'ligand_color': 'gold',      # 配体碳用金色（与蛋白区分）
    'stick_preset': 'fine',
    'ligand_sphere': False,       # 配体不加球（clean）

    # 口袋
    'pocket_repr': None,         # 全景图不开口袋表面

    # 相互作用
    'interaction_lines': False,

    # 标签
    'labels': False,

    # 质量
    'quality': PUBLICATION,
    'lighting': LIGHTING_DEFAULT,
}

# ── Scene 2: 口袋特写 ─────────────────────────────────────────────────────
SCENE_POCKET = {
    'description': '结合口袋特写（黑底，蛋白 cartoon + 口袋表面 + 配体 sticks）',

    'background': BG_BLACK,

    # 蛋白整体 cartoon（半透明以显示口袋）
    'protein': 'cartoon',
    'protein_color': 'cold',
    'cartoon': CARTOON_POCKET,

    # 口袋表面（核心区域）
    'pocket_repr': 'surface',
    'pocket_distance': 5.0,      # Å 半径
    'pocket_transparency': 0.25,  # 口袋表面透明度
    'pocket_color': 'bluewhite',  # 口袋表面色（配体用 gold 对比）

    # 配体（金色 gold = 与 bluewhite 对比鲜明）
    'ligand_repr': 'sticks',
    'ligand_color': 'gold',
    'stick_preset': 'fine',
    'ligand_sphere': True,        # 加配体 C 球增强立体感
    'ligand_sphere_scale': 0.3,

    # 关键残基标注
    'labels': True,
    'label_selection': 'pocket',  # 标注口袋 CA 原子
    'label_max': 6,
    'label_color': 'white',
    'label_size': 0.35,           # PyMOL label size unit
    'label_font_id': 9,

    # 质量
    'quality': PUBLICATION,
    'lighting': LIGHTING_DEFAULT,
}

# ── Scene 3: 相互作用图 ───────────────────────────────────────────────────
SCENE_INTERACTION = {
    'description': '氢键 / π-π / 疏水相互作用标注图（黑底，虚线 + 配体 CPK）',

    'background': BG_BLACK,

    # 蛋白弱化（灰色 cartoon，重点是虚线和配体）
    'protein': 'cartoon',
    'protein_color': 'neutral',   # gray80（弱化蛋白，强化交互线）
    'protein_transparency': 0.2,
    'cartoon': CARTOON_INTERACTION,

    # 口袋 lines/wireframe（更清晰显示接触面）
    'pocket_repr': 'lines',
    'pocket_distance': 5.0,
    'pocket_lines_color': 'white',  # 白线在黑底上清晰

    # 配体
    'ligand_repr': 'sticks',
    'ligand_color': 'gold',
    'stick_preset': 'fine',
    'ligand_sphere': True,
    'ligand_sphere_scale': 0.25,

    # 相互作用虚线（核心）
    'interaction_lines': True,
    'interaction_dash_preset': 'fine',
    'interaction_dash_width': 2.5,   # 比默认略粗（交互密集时可见）
    'show_hbond': True,
    'show_pistack': True,
    'show_hydrophobic': True,        # 疏水也显示（可单独关掉）

    # 只标注 H 键和 π-π（疏水不加标签）
    'labels': True,
    'label_types': ['H-bond', 'π-π'],  # 不标疏水
    'label_selection': 'pocket',
    'label_max': 8,
    'label_color': 'white',
    'label_size': 0.35,
    'label_font_id': 9,

    # 质量
    'quality': PUBLICATION,
    'lighting': LIGHTING_DEFAULT,
}

# ── Scene 4: 静电势表面 ───────────────────────────────────────────────────
SCENE_ELECTROSTATIC = {
    'description': 'APBS 静电势表面渲染（口袋表面染色红→蓝 ±5 kT/e）',

    'background': BG_WHITE,

    'protein': 'cartoon',
    'protein_color': 'cold',
    'cartoon': CARTOON_PUBLICATION,

    # 口袋静电势表面
    'pocket_repr': 'surface',
    'pocket_distance': 6.0,
    'pocket_transparency': 0.3,
    'surface_ramp': 'apbs',        # 启用 APBS ramp 染色
    'surface_ramp_range': [-5, 0, 5],  # ±5 kT/e 标准范围

    # 配体
    'ligand_repr': 'sticks',
    'ligand_color': 'gold',
    'stick_preset': 'fine',
    'ligand_sphere': False,

    'labels': True,
    'label_max': 4,
    'label_color': 'black',        # 白底用黑色标签
    'label_size': 0.35,
    'label_font_id': 9,

    'quality': PUBLICATION,
    'lighting': LIGHTING_DEFAULT,
}

# ── Scene 5: 配体特写（球棍模型）──────────────────────────────────────────
SCENE_LIGAND_CLOSEUP = {
    'description': '配体球棍模型特写（无蛋白背景，适合药物化学结构说明）',

    'background': BG_BLACK,

    # 蛋白完全隐藏
    'protein': None,

    # 只显示配体（球棍）
    'ligand_repr': 'sticks_and_spheres',
    'ligand_color': 'cpk',         # 元素标准色
    'stick_preset': 'ball_and_stick',
    'ligand_sphere': True,
    'ligand_sphere_scale': 1.0,    # 真实原子半径

    # 标签（残基名+编号）
    'labels': True,
    'label_max': 12,
    'label_color': 'white',
    'label_size': 0.4,
    'label_font_id': 9,

    'quality': PUBLICATION,
    'lighting': LIGHTING_SPECULAR,  # 高光增强立体感
}

# ─────────────────────────────────────────────────────────────────────────────
# LABEL SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

LABEL_PRESETS = {
    'small': dict(
        label_size=0.3,
        label_font_id=9,     # bold
        label_color='white',
        label_outline=1,
    ),
    'medium': dict(
        label_size=0.4,
        label_font_id=9,
        label_color='white',
        label_outline=1,
    ),
    'large': dict(
        label_size=0.5,
        label_font_id=12,
        label_color='white',
        label_outline=1,
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# APPLY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def apply_ray_settings(cmd, preset='PUBLICATION'):
    """Apply ray tracing + quality settings from preset dict."""
    table = {
        'DRAFT': DRAFT,
        'STANDARD': STANDARD,
        'PUBLICATION': PUBLICATION,
        'PUBLICATION_OUTLINE': PUBLICATION_OUTLINE,
    }
    q = table.get(preset, PUBLICATION)
    for key, val in q.items():
        try:
            cmd.set(key, val)
        except Exception:
            pass


def apply_lighting(cmd, preset='DEFAULT'):
    """Apply lighting settings from preset."""
    table = {
        'DEFAULT': LIGHTING_DEFAULT,
        'FLAT': LIGHTING_FLAT,
        'SPECULAR': LIGHTING_SPECULAR,
    }
    params = table.get(preset, LIGHTING_DEFAULT)
    for key, val in params.items():
        try:
            cmd.set(key, val)
        except Exception:
            pass


def apply_cartoon(cmd, preset='PUBLICATION'):
    """Apply cartoon representation settings."""
    table = {
        'PUBLICATION': CARTOON_PUBLICATION,
        'POCKET': CARTOON_POCKET,
        'INTERACTION': CARTOON_INTERACTION,
    }
    params = table.get(preset, CARTOON_PUBLICATION)
    for key, val in params.items():
        try:
            cmd.set(key, val)
        except Exception:
            pass


def apply_stick(cmd, preset='fine'):
    """Apply stick representation settings."""
    params = STICK_PRESETS.get(preset, STICK_PRESETS['fine'])
    for key, val in params.items():
        try:
            cmd.set(key, val)
        except Exception:
            pass


def apply_dash(cmd, preset='fine', width=None, color_map=None):
    """Apply dashed line (distance object) settings."""
    params = DASH_PRESETS.get(preset, DASH_PRESETS['fine'])
    for key, val in params.items():
        try:
            cmd.set(key, val)
        except Exception:
            pass
    if width is not None:
        cmd.set('dash_width', width)


def apply_surface(cmd, preset='POCKET'):
    """Apply surface representation settings."""
    params = SURFACE_POCKET if preset == 'POCKET' else SURFACE_POCKET
    for key, val in params.items():
        try:
            cmd.set(key, val)
        except Exception:
            pass


def color_element(cmd, selection, scheme='cpk', override=None):
    """
    Color atoms by element using CPK scheme.

    Args:
        cmd: PyMOL command object
        selection: PyMOL selection string
        scheme: 'cpk' (standard) or 'cpk_gold' (ligands)
        override: dict of {element: color} to override defaults
    """
    colors = dict(CPK_COLORS)
    if scheme == 'cpk_gold':
        colors['C'] = 'gold'    # 关键：配体碳用金色
    if override:
        colors.update(override)

    for element, color in colors.items():
        try:
            cmd.color(color, f'({selection}) and elem {element}')
        except Exception:
            pass


def color_by_scheme(cmd, selection, scheme):
    """Apply named color scheme to a selection."""
    scheme_map = {
        'gold':     ('gold', 'elem'),
        'bluewhite':('bluewhite', 'elem'),
        'gray50':   ('gray50', 'elem'),
        'gray80':   ('gray80', 'elem'),
        'white':    ('white', 'elem'),
        'neutral':  ('gray80', 'elem'),  # neutral = gray80
    }
    if scheme not in scheme_map:
        return
    color, _ = scheme_map[scheme]
    try:
        cmd.color(color, selection)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: GET PRESET
# ─────────────────────────────────────────────────────────────────────────────

SCENE_PRESETS = {
    'complex':      SCENE_COMPLEX,
    'pocket':       SCENE_POCKET,
    'interaction':  SCENE_INTERACTION,
    'electrostatic': SCENE_ELECTROSTATIC,
    'ligand_closeup': SCENE_LIGAND_CLOSEUP,
}


def get_scene_preset(name: str) -> dict:
    """Get a scene preset by name."""
    return SCENE_PRESETS.get(name, SCENE_COMPLEX)
