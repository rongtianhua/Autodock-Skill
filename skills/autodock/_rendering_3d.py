"""
Autodock 3D Rendering Module
============================
PyMOL-based 3D visualization: scenes, pockets, interactions, composite panels.
"""
import os
import tempfile
from pathlib import Path

from autodock._core import autodock_logger, _HAVE_PYMOL, _safe_color

# Backward-compat logger alias
logger = autodock_logger

# PyMOL cmd import
if _HAVE_PYMOL:
    from pymol import cmd as _pymol_cmd

from autodock._pymol_viz_config import (
    SCENE_PRESETS, get_scene_preset, DASH_PRESETS, DASH_COLOR_MAP,
    STICK_PRESETS, CARTOON_PUBLICATION, CARTOON_POCKET, CARTOON_INTERACTION,
    PUBLICATION, PUBLICATION_OUTLINE, STANDARD,
    BG_WHITE, BG_BLACK,
    apply_cartoon, apply_lighting, apply_ray_settings,
)

import numpy as np

def _apply_scene_to_cmd(cmd, scene: dict, pdb_path: str,
                        ligand_pdbqt: str, center: tuple, interactions: list):
    """
    Apply a scene preset to PyMOL cmd object.

    This is the core rendering engine that handles all scene types.
    """
    from autodock._pymol_viz_config import (
        apply_ray_settings, apply_lighting, apply_cartoon,
        apply_stick, apply_surface,
        color_element, color_by_scheme, get_scene_preset,
    )

    cmd.hide('everything', 'all')
    cmd.bg_color(scene.get('background', BG_WHITE))

    # ── Protein cartoon ─────────────────────────────────────────────────
    if scene.get('protein') == 'cartoon':
        cmd.show('cartoon', 'all')
        # Color scheme
        protein_color = scene.get('protein_color', 'cold')
        if protein_color == 'rainbow':
            try: cmd.spectrum('chain', 'rainbow', 'all', 'all')
            except Exception: pass
        elif protein_color == 'ss':
            try: cmd.color('ss', 'all')
            except Exception: pass
        else:
            color_by_scheme(cmd, 'elem C', protein_color)

        # Cartoon style
        cartoon_preset = scene.get('cartoon', 'PUBLICATION')
        apply_cartoon(cmd, cartoon_preset)

        # Per-scene transparency
        if scene.get('protein_transparency', 0) > 0:
            cmd.set('cartoon_transparency', scene['protein_transparency'], 'all')

    # ── Pocket ──────────────────────────────────────────────────────────
    pocket_sel = None
    pocket_distance = scene.get('pocket_distance', 5.0)

    if center is not None:
        cx, cy, cz = center
        pocket_sel = f'br. all and center {cx},{cy},{cz} around {pocket_distance}'
    elif ligand_pdbqt:
        pocket_sel = f'(docked_ligand) around {pocket_distance}'
    elif scene.get('pocket_repr'):
        pocket_sel = f'(br. all) around {pocket_distance}'

    # ── Pocket: surface ─────────────────────────────────────────────────
    if scene.get('pocket_repr') == 'surface' and pocket_sel:
        cmd.select('pocket_surf', pocket_sel)
        cmd.show('surface', 'pocket_surf')
        # Apply surface transparency
        surf_transp = scene.get('pocket_transparency', 0.25)
        cmd.set('transparency', surf_transp, 'pocket_surf')
        # Color pocket atoms
        pc = scene.get('pocket_color', 'bluewhite')
        color_by_scheme(cmd, 'pocket_surf and elem C', pc)
        cmd.set('surface_quality', 1)

    # ── Pocket: lines ───────────────────────────────────────────────────
    if scene.get('pocket_repr') == 'lines' and pocket_sel:
        cmd.select('pocket_lines', pocket_sel)
        cmd.show('lines', 'pocket_lines')
        lc = scene.get('pocket_lines_color', 'white')
        color_by_scheme(cmd, 'pocket_lines and elem C', lc)

    # ── Ligand ──────────────────────────────────────────────────────────
    ligand_sel = None
    if ligand_pdbqt and os.path.exists(ligand_pdbqt):
        cmd.load(ligand_pdbqt, object='docked_ligand')
        ligand_sel = 'docked_ligand'

    if scene.get('ligand_repr') in ('sticks', 'sticks_and_spheres'):
        ligand_target = ligand_sel or f'resn {scene.get("ligand_resn", "LIG")}'
        cmd.show('sticks', ligand_target)
        cmd.set('stick_radius', scene.get('stick_radius', 0.2))
        cmd.set('valence', 1)

        # Color ligand: gold C (key convention from research)
        ligand_color = scene.get('ligand_color', 'gold')
        if ligand_color == 'gold':
            _safe_color(cmd, 'gold', f'{ligand_target} and elem C')
            _safe_color(cmd, 'red',    f'{ligand_target} and elem O')
            _safe_color(cmd, 'blue',   f'{ligand_target} and elem N')
            _safe_color(cmd, 'yellow', f'{ligand_target} and elem S')
        elif ligand_color == 'cpk':
            color_element(cmd, ligand_target, 'cpk')
        else:
            color_by_scheme(cmd, f'{ligand_target} and elem C', ligand_color)

        # Spheres for ligand carbons
        if scene.get('ligand_sphere', False):
            sphere_scale = scene.get('ligand_sphere_scale', 0.3)
            cmd.show('spheres', f'{ligand_target} and name C')
            cmd.set('sphere_scale', sphere_scale, f'{ligand_target}')

    # ── Interaction dashed lines ─────────────────────────────────────────
    if scene.get('interaction_lines', False) and interactions and pocket_sel:
        cmd.select('pocket_int', pocket_sel)

        dash_preset = scene.get('interaction_dash_preset', 'fine')
        dash_params = DASH_PRESETS.get(dash_preset, DASH_PRESETS['fine'])

        # Leipzig standard dash parameters
        cmd.set('dash_gap', dash_params['dash_gap'])
        cmd.set('dash_radius', dash_params['dash_radius'])
        cmd.set('dash_length', dash_params['dash_length'])
        cmd.set('dash_as_cylinders', int(dash_params['dash_as_cylinders']))
        cmd.set('dash_round_ends', int(dash_params['dash_round_ends']))

        dash_width = scene.get('interaction_dash_width', 2.5)
        label_types = set(scene.get('label_types', ['H-bond', 'π-π', 'Hydrophobic']))

        for idx, inter in enumerate(interactions):
            if inter['type'] not in label_types:
                continue

            pair_name = f'int_{idx}'
            resn = inter.get('resn', '')
            resi = inter.get('resi', '')
            atom = inter.get('atom', 'CA')
            prot_sel = f'(receptor and resn {resn} and resi {resi} and name {atom})'

            lig_sel = ligand_sel or 'docked_ligand'

            try:
                cmd.distance(pair_name, prot_sel, lig_sel)
                color = DASH_COLOR_MAP.get(inter['type'], 'white')
                cmd.set('dash_color', color, pair_name)
                cmd.set('dash_width', dash_width, pair_name)
                cmd.hide('labels', pair_name)
            except Exception:
                pass

    # ── Labels ───────────────────────────────────────────────────────────
    if scene.get('labels', False) and pocket_sel:
        cmd.select('pocket_lab', pocket_sel)
        label_types = scene.get('label_types')
        label_max = scene.get('label_max', 6)
        label_color = scene.get('label_color', 'white')
        label_size = scene.get('label_size', 0.35)

        # Only label CA atoms of pocket residues
        lab_sel = 'pocket_lab and name CA'

        # Filter by interaction type if specified
        if label_types and interactions:
            # Build selection from interacting residues only
            resi_list = []
            for inter in interactions:
                if inter.get('type') in label_types:
                    resi_list.append(str(inter.get('resi', '')))
            if resi_list:
                lab_sel = f'pocket_lab and resi {"+".join(resi_list)} and name CA'

        try:
            cmd.label(lab_sel, '"%s-%s" % (resn, resi)')
            cmd.set('label_color', label_color)
            cmd.set('label_size', label_size)
            cmd.set('label_font_id', 9)
        except Exception:
            pass

    # ── Lighting ────────────────────────────────────────────────────────
    apply_lighting(cmd, 'DEFAULT')

    # ── Quality settings ─────────────────────────────────────────────────
    apply_ray_settings(cmd, 'PUBLICATION')

    # ── Zoom and orient ─────────────────────────────────────────────────
    if pocket_sel:
        cmd.zoom('pocket_surf', buffer=8)
    elif pocket_sel:
        cmd.zoom('pocket_int', buffer=8)
    elif ligand_sel:
        cmd.zoom(ligand_sel, buffer=8)
    else:
        cmd.zoom('all', buffer=8)


# ─────────────────────────────────────────────────────────────────────────────
# GENERIC SCENE RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def render_scene(pdb_path: str,
                output_png: str,
                scene: str = 'pocket',
                center: tuple = None,
                interactions: list = None,
                ligand_pdbqt: str = None,
                width: int = 2400,
                height: int = 1800,
                dpi: int = 300,
                **scene_overrides) -> bool:
    """
    Render a molecular docking scene using a named scene preset.

    This is the primary rendering API that applies publication-quality
    parameters from the research-backed configuration.

    Scenes available:
      'complex'      — 全景图（白底，蛋白 cartoon，配体 sticks）
      'pocket'       — 口袋特写（黑底，cartoon + 口袋表面 + 配体）
      'interaction'  — 相互作用图（黑底，H键/π-π/疏水虚线）
      'electrostatic'— 静电势表面（白底，APBS 染色）
      'ligand_closeup'— 配体特写（黑底，球棍模型）

    Args:
        pdb_path: Protein PDB file (docked complex)
        output_png: Output PNG path
        scene: Scene preset name (above)
        center: (x, y, z) ligand/box center
        interactions: List from detect_interactions()
        ligand_pdbqt: Optional ligand PDBQT for better ligand display
        width, height, dpi: Image dimensions
        **scene_overrides: Override specific scene parameters

    Returns:
        True if successful
    """
    if not _HAVE_PYMOL:
        logger.info("[autodock] PyMOL not available - render_scene skipped")
        return False

    pdb_abs = os.path.abspath(pdb_path)
    png_abs = os.path.abspath(output_png)
    os.makedirs(os.path.dirname(png_abs) or '.', exist_ok=True)

    cmd = _pymol_cmd

    # Load structure(s)
    cmd.load(pdb_abs)
    if ligand_pdbqt and os.path.exists(ligand_pdbqt):
        cmd.load(os.path.abspath(ligand_pdbqt), object='docked_ligand')

    # Get scene config (with optional overrides)
    scene_cfg = dict(get_scene_preset(scene))
    scene_cfg.update(scene_overrides)

    # Apply scene
    _apply_scene_to_cmd(cmd, scene_cfg, pdb_abs, ligand_pdbqt,
                        center, interactions or [])

    # ── Self-check: verify PyMOL loaded the structure before ray tracing ──
    # get_model('all') queries PyMOL's internal atom store (not OpenGL).
    # Ray tracing itself is CPU-bound, but if PyMOL's state was reset
    # (e.g. module reload, cmd object overwritten, stale process), atoms
    # will be missing and we re-init rather than silently make a blank PNG.
    model = cmd.get_model('all')
    n_atom = model.nAtom if model else 0
    if n_atom == 0:
        logger.info(f"[autodock] ⚠️ PyMOL init check FAILED — no atoms loaded for {scene}. "
              "Re-initializing PyMOL instance...")
        # Force a fresh PyMOL instance
        import pymol
        pymol.cmd = pymol.Cmd()
        globals()['_pymol_cmd'] = pymol.cmd
        cmd = _pymol_cmd
        cmd.load(pdb_abs)
        if ligand_pdbqt and os.path.exists(ligand_pdbqt):
            cmd.load(os.path.abspath(ligand_pdbqt), object='docked_ligand')
        _apply_scene_to_cmd(cmd, scene_cfg, pdb_abs, ligand_pdbqt,
                            center, interactions or [])
        model2 = cmd.get_model('all')
        n_atom = model2.nAtom if model2 else 0
        if n_atom == 0:
            logger.info(f"[autodock] ❌ PyMOL re-init FAILED — rendering aborted for {scene}")
            return False
        logger.info(f"[autodock] ✅ PyMOL re-init OK — {n_atom} atoms loaded")

    # Ray trace + save
    cmd.png(png_abs, width=width, height=height, dpi=dpi, ray=1)

    ok = os.path.exists(png_abs) and os.path.getsize(png_abs) > 5000
    size = os.path.getsize(png_abs) // 1024 if ok else 0
    logger.info(f"[autodock] render_scene({scene}): {'OK' if ok else 'FAILED'} ({size}KB)")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# SPECIALIZED RENDERERS (for backward compatibility + specific use cases)
# ─────────────────────────────────────────────────────────────────────────────

def render_complex(pdb_path: str,
                  output_png: str,
                  width: int = 2400,
                  height: int = 1800,
                  dpi: int = 300,
                  ligand_pdbqt: str = None,
                  **kwargs) -> bool:
    """
    Render protein-ligand full complex (publication quality).

    Preset: 'complex' scene with refined parameters.
    Protein: rainbow cartoon / Ligand: gold sticks / Background: white
    """
    return render_scene(
        pdb_path, output_png,
        scene='complex',
        ligand_pdbqt=ligand_pdbqt,
        width=width, height=height, dpi=dpi,
        **kwargs
    )


def render_pocket(pdb_path: str,
                 output_png: str,
                 center: tuple,
                 width: int = 2400,
                 height: int = 1800,
                 dpi: int = 300,
                 ligand_pdbqt: str = None,
                 ligand_resn: str = None,
                 distance: float = 5.0,
                 show_labels: bool = True,
                 **kwargs) -> bool:
    """
    Render binding pocket close-up (CB-Dock2 inspired style).

    Preset: 'pocket' scene
      - Black background
      - Protein cartoon (transparency=0.15)
      - Pocket surface (transparency=0.25, bluewhite)
      - Ligand: gold sticks + spheres
      - Optional residue labels

    Args:
        pdb_path: Protein PDB file
        output_png: Output PNG
        center: (x, y, z) ligand center
        ligand_pdbqt: Docked ligand PDBQT
        ligand_resn: Ligand residue name (auto-detected if None)
        distance: Pocket radius (Å)
        show_labels: Show residue labels
    """
    if ligand_resn is None:
        ligand_resn = _detect_ligand_resn(pdb_path)

    return render_scene(
        pdb_path, output_png,
        scene='pocket',
        center=center,
        ligand_pdbqt=ligand_pdbqt,
        ligand_resn=ligand_resn,
        width=width, height=height, dpi=dpi,
        pocket_distance=distance,
        labels=show_labels,
        **kwargs
    )


def render_interactions_pymol(receptor_pdb: str,
                             ligand_pdbqt: str,
                             interactions: list,
                             output_png: str,
                             center: tuple,
                             distance: float = 5.0,
                             width: int = 2400,
                             height: int = 1800,
                             dpi: int = 300,
                             dash_preset: str = 'fine',
                             **kwargs) -> bool:
    """
    Render protein-ligand complex with interaction dashed lines.

    Publication-standard preset (Leipzig Lab parameters, verified 2026-04-25):
      - Black background
      - Protein cartoon (gray, transparency=0.2)
      - Pocket lines (white)
      - Ligand: gold sticks
      - Hydrophobic: orange sticks + 1 orange dash per residue via ligand centroid
      - H-bond: cyan dashes (cutoff=4.0 A)
      - pi-pi: green dashes (cutoff=6.0 A)
      - Residue labels in white (ALA85, PHE231, etc.)
      - Leipzig dash: dash_gap=0.4 / dash_radius=0.05 / dash_length=0.3

    Key fixes (2026-04-25):
      - Ligand centroid pseudoatom avoids PyMOL mode=0 dash explosion (N*M lines)
      - Exact residue targeting via resi=XXX (not byres CA->ligand atoms)
      - Per-residue dash with cutoff=10.0 (above max centroid distance)
      - Hydrophobic residue sticks (orange) + CA labels for identification

    Args:
        receptor_pdb: Protein PDB file
        ligand_pdbqt: Docked ligand PDBQT
        interactions: List from detect_interactions()
        center: (x, y, z) ligand center
        distance: Pocket radius (A)
        dash_preset: 'fine' (Leipzig, default) | 'standard' | 'bold'
    """
    if not _HAVE_PYMOL:
        logger.info("[autodock] PyMOL not available")
        return False

    rec_abs = os.path.abspath(receptor_pdb)
    lig_abs = os.path.abspath(ligand_pdbqt)
    png_abs = os.path.abspath(output_png)
    os.makedirs(os.path.dirname(png_abs) or '.', exist_ok=True)

    cmd = _pymol_cmd

    # Load structures
    cmd.load(rec_abs)
    cmd.load(lig_abs, object='docked_ligand')

    cmd.hide('everything', 'all')
    cmd.bg_color('black')

    # -- Ligand centroid pseudoatom --
    # Centroid -> 1 dash per residue (not N*M). mode=0 with centroid
    # gives clean lines without PyMOL dash explosion.
    _model = cmd.get_model('docked_ligand')
    _coords = np.array([a.coord for a in _model.atom])
    _cent = np.mean(_coords, axis=0).tolist()
    cmd.pseudoatom('lig_cent', pos=_cent)

    # -- Protein cartoon --
    cmd.show('cartoon', 'all')
    _safe_color(cmd, 'gray80', 'elem C')
    apply_cartoon(cmd, 'INTERACTION')
    cmd.set('cartoon_transparency', 0.2, 'all')

    # -- Pocket selection --
    cx, cy, cz = center
    pocket_sel = f'br. all and center {cx},{cy},{cz} around {distance}'
    cmd.select('pocket_sel', pocket_sel)

    # -- Ligand sticks (gold) --
    cmd.show('sticks', 'docked_ligand')
    cmd.set('stick_radius', 0.2)
    cmd.set('valence', 1)
    _safe_color(cmd, 'gold',    'docked_ligand and elem C')
    _safe_color(cmd, 'red',     'docked_ligand and elem O')
    _safe_color(cmd, 'blue',    'docked_ligand and elem N')
    _safe_color(cmd, 'yellow',  'docked_ligand and elem S')
    cmd.show('spheres', 'docked_ligand and name C')
    cmd.set('sphere_scale', 0.25, 'docked_ligand')

    # -- Leipzig dash parameters --
    dash_params = DASH_PRESETS.get(dash_preset, DASH_PRESETS['fine'])
    cmd.set('dash_gap', dash_params['dash_gap'])
    cmd.set('dash_radius', dash_params['dash_radius'])
    cmd.set('dash_length', dash_params['dash_length'])
    cmd.set('dash_as_cylinders', int(dash_params['dash_as_cylinders']))
    cmd.set('dash_round_ends', int(dash_params['dash_round_ends']))

    # -- Interaction dashes (centroid approach) --
    # Key fix: centroid approach (mode=0, cutoff=10.0) avoids PyMOL explosion.
    # Old code used mode=2 with byres CA -> ligand atoms -> N*M dashes.
    _n_hb, _n_pi, _n_hp = 0, 0, 0
    _seen_hydro_residues = set()
    for idx, inter in enumerate(interactions):
        pair_name = f'int_{idx}'
        resn = inter.get('resn', '')
        resi = inter.get('resi', '')
        atom = inter.get('atom', 'CA')
        itype = inter.get('type', '').lower()

        # Exact residue atom selection (resi for exact targeting)
        prot_sel = f'resn {resn} and name {atom} and chain A and resi {resi}'
        dash_color = DASH_COLOR_MAP.get(inter['type'], 'white')

        if 'h-bond' in itype or 'hbond' in itype or 'hydrogen' in itype:
            d = cmd.distance(pair_name, prot_sel, 'lig_cent', mode=0, cutoff=4.0)
            if d is not None and d > 0:
                cmd.set('dash_color', 'cyan', pair_name)
                _n_hb += 1
        elif 'pi' in itype:
            d = cmd.distance(pair_name, prot_sel, 'lig_cent', mode=0, cutoff=6.0)
            if d is not None and d > 0:
                cmd.set('dash_color', 'green', pair_name)
                _n_pi += 1
        elif 'hydrophobic' in itype:
            # One dash per residue via centroid. cutoff=10.0 covers all
            # hydrophobic contacts (max dist ~= 9.5 A in METTL8 test).
            d = cmd.distance(pair_name, prot_sel, 'lig_cent', mode=0, cutoff=10.0)
            if d is not None and d > 0:
                cmd.set('dash_color', 'orange', pair_name)
                cmd.set('dash_gap', 0.4, pair_name)
                cmd.set('dash_radius', 0.05, pair_name)
                cmd.set('dash_length', 0.25, pair_name)
                cmd.set('dash_width', 2.5, pair_name)
                _seen_hydro_residues.add((resn, resi))
                _n_hp += 1

    # -- Hydrophobic residue sticks (orange) + white residue labels --
    # Show hydrophobic interacting residues as orange sticks for clarity.
    for resn, resi in _seen_hydro_residues:
        sel = f'resn {resn} and chain A and resi {resi}'
        cmd.show('sticks', sel)
        cmd.color('orange', sel)

    # White labels on CA atoms of hydrophobic residues
    labeled = []
    for resn, resi in sorted(_seen_hydro_residues, key=lambda x: x[1]):
        labeled.append(f'resn {resn} and chain A and resi {resi} and name CA')
    if labeled:
        cmd.label(' or '.join(labeled), '"%s%s" % (resn, resi)')
        cmd.set('label_color', 'white')
        cmd.set('label_size', 20)
        cmd.set('label_font_id', 16)

    # -- Quality + lighting (Leipzig) --
    apply_lighting(cmd, 'DEFAULT')
    apply_ray_settings(cmd, 'PUBLICATION')

    # -- Zoom --
    cmd.zoom('pocket_sel', buffer=8)
    cmd.orient('pocket_sel')

    cmd.png(png_abs, width=width, height=height, dpi=dpi, ray=1)

    ok = os.path.exists(png_abs) and os.path.getsize(png_abs) > 5000
    size = os.path.getsize(png_abs) // 1024 if ok else 0
    logger.info(f"[autodock] Interactions: H-bond={_n_hb}, pi-pi={_n_pi}, Hydro={_n_hp}")
    logger.info(f"[autodock] Interaction render: {'OK' if ok else 'FAILED'} ({size}KB)")
    return ok

LIGPLOT_BIN = os.path.expanduser('~/LigPlus/lib/exe_mac64/ligplot')
LIGPLOT_PRM = os.path.expanduser('~/LigPlus/lib/params/ligplot.prm')
HAVE_LIGPLOT = os.path.exists(LIGPLOT_BIN)


def composite_summary(panels: list,
                     output_png: str,
                     ncols: int = 2,
                     dpi: int = 150,
                     panel_titles: list = None,
                     figure_title: str = None) -> bool:
    """
    Combine multiple PNG panels into a publication-quality summary figure.

    Uses matplotlib Agg backend (no display required).
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import image as mpimg

    if not panels:
        return False

    valid = [(i, p) for i, p in enumerate(panels)
             if os.path.exists(p) and os.path.getsize(p) > 5000]
    if not valid:
        logger.info("[autodock] No valid panels to composite")
        return False

    n = len(valid)
    ncols = max(1, ncols)
    nrows = (n + ncols - 1) // ncols

    sample = mpimg.imread(valid[0][1])
    h, w = sample.shape[:2]
    aspect = (h / w) if w > 0 else 1.0

    cell_w = 4.5
    fig_w = ncols * cell_w + 0.4
    fig_h = nrows * (cell_w * aspect) + (0.5 if figure_title else 0.2)

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(fig_w, fig_h), dpi=100)
    fig.patch.set_facecolor('white')

    # Normalize axes to 2D list
    if nrows == 1 and ncols == 1:
        axes = [[axes]]
    elif nrows == 1:
        axes = [axes.tolist()]
    elif ncols == 1:
        axes = [[a] for a in axes]
    else:
        axes = axes.tolist()

    for idx, (orig_idx, panel_path) in enumerate(valid):
        row, col = idx // ncols, idx % ncols
        ax = axes[row][col]
        ax.imshow(mpimg.imread(panel_path))
        ax.axis('off')
        if panel_titles and orig_idx < len(panel_titles):
            ax.set_title(panel_titles[orig_idx], fontsize=9, pad=3,
                        fontweight='bold', loc='left')

    for idx in range(n, nrows * ncols):
        row, col = idx // ncols, idx % ncols
        try:
            axes[row][col].axis('off')
            axes[row][col].set_facecolor('white')
        except Exception:
            pass

    if figure_title:
        fig.suptitle(figure_title, fontsize=12, fontweight='bold', y=0.99)

    rect = [0, 0, 1, 0.95] if figure_title else [0, 0, 1, 1]
    plt.tight_layout(rect=rect)

    os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)
    fig.savefig(output_png, dpi=dpi, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    plt.close(fig)

    ok = os.path.exists(output_png) and os.path.getsize(output_png) > 5000
    logger.info(f"[autodock] Composite: {'OK' if ok else 'FAILED'} "
          f"({os.path.getsize(output_png)//1024}KB)")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# DOCKING
# ─────────────────────────────────────────────────────────────────────────────

