"""
Autodock Molecular Docking Module — Backward Compatibility Wrapper
==================================================================
This file re-exports all functions from the new modular sub-packages.
For new code, import directly from the submodules:
    from autodock._core import DockingResult
    from autodock._docking import dock_ligand
    from autodock._interactions import detect_interactions_plip
"""

# ─── Core infrastructure ─────────────────────────────────────────────────────
from autodock._core import (
    autodock_logger,
    _HAVE_PYMOL, _HAVE_VINA, _HAVE_RDKIT, _HAVE_PLIP, _HAVE_MEEKO,
    _SKIP_RES, _P2RANK_DIR, _P2RANK_PRANK, _P2RANK_JAR, _JAVA_HOME,
    _detect_receptor_source, _RECEPTOR_SOURCE_LABELS,
    DockingResult, build_docking_result,
    _safe_color,
    _log_info, _log_warning, _log_error, _log_debug,
)

# ─── Preparation ───────────────────────────────────────────────────────────────
from autodock._preparation import (
    prepare_receptor, prepare_ligand, prepare_ligand_conformers,
    _compute_box_size, _run_p2rank_rescore, find_top_pockets,
    _read_ligand_from_pdbqt_3d,
    _prepare_pdb_for_fpocket, _parse_fpocket_info,
)

# ─── Validation ────────────────────────────────────────────────────────────────
from autodock._validation import (
    compute_rmsd, validate_docking_protocol,
    compute_clash_score,
)

# ─── Docking ───────────────────────────────────────────────────────────────────
from autodock._docking import (
    find_binding_site,
    dock_ligand, dock_ligand_multi, dock_ligand_multi_conformer,
    virtual_screen,
    _detect_ligand_resn,
)

# ─── Interactions (detection + 2D rendering) ───────────────────────────────────
from autodock._interactions import (
    detect_interactions,
    detect_interactions_plip,
    render_interactions_2d, render_ligand_2d,
    _detect_ligand_resn_for_plip, _parse_ligand_from_pdbqt_for_plip,
    _build_complex_pdb_for_plip, _configure_plip,
    _map_pybel_to_rdk_atom_idx,
    _build_interaction_mol, _get_mol_2d_bounds,
    _inject_svg_legend, _render_svg_vector,
    _recover_bonds_from_openbabel,
    PLIP_TYPE_MAP,
)

# ─── 3D Rendering ──────────────────────────────────────────────────────────────
from autodock._rendering_3d import (
    _apply_scene_to_cmd,
    render_scene, render_complex, render_pocket, render_interactions_pymol,
    composite_summary,
)

# ─── LigPlot ───────────────────────────────────────────────────────────────────
from autodock._ligplot import (
    parse_ligplot_drw, render_ligplot_from_drw,
    _get_ligand_smiles, render_ligplot_2d,
    _optimize_label_positions, _boxes_overlap,
    _parse_ligplot_hhb, _parse_ligplot_nnb, _draw_dashed_line,
)

# ─── ADMET ─────────────────────────────────────────────────────────────────────
from autodock._admet import (
    predict_admet, _predict_admet_neurosnap,
    _load_neurosnap_key, _run_admetlab_browser,
    _parse_admetlab_csv, _predict_admet_rdkit, filter_admet,
)

# ─── Database ────────────────────────────────────────────────────────────────────
from autodock._database import (
    fetch_bioactivities, compute_enrichment, print_enrichment_report,
    parse_zinc_tranche, _zinc_tranche_url, sample_zinc_compounds, lookup_zinc_id,
)

# ─── MM/PBSA ─────────────────────────────────────────────────────────────────
from autodock._mmpbsa import (
    compute_mmpbsa, mmpbsa_rank_ligands,
    MMPBSAResult,
)
