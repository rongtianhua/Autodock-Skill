"""
Autodock Molecular Docking Skill
==================================
Complete molecular docking workflow: structure retrieval → preparation → docking → visualization.

Usage:
    import sys
    sys.path.insert(0, '~/.openclaw/workspace/skills/autodock/')
    from autodock import (
        fetch_protein_pdb, fetch_molecule_pubchem,
        prepare_receptor, prepare_ligand,
        find_binding_site, dock_ligand,
        detect_interactions, detect_interactions_plip,
        render_scene, render_complex, render_pocket,
        render_interactions_pymol, render_interactions_2d,
        composite_summary,
    )

Environment: conda activate autodock313
"""

# ─── Core ──────────────────────────────────────────────────────────────────────
from autodock._core import (
    autodock_logger,
    DockingResult, build_docking_result,
    _HAVE_PYMOL, _HAVE_VINA, _HAVE_RDKIT, _HAVE_PLIP, _HAVE_MEEKO, _HAVE_OBABEL,
    _detect_receptor_source, _RECEPTOR_SOURCE_LABELS,
)

# ─── Structure fetch (already separate) ──────────────────────────────────────
from autodock._structure_fetch import (
    fetch_protein, fetch_protein_pdb,
    fetch_protein_alphafold, fetch_protein_swissmodel, fetch_protein_swissmodel_advanced, fetch_protein_pdb_redo,
    fetch_molecule, fetch_molecule_pubchem,
    fetch_molecule_chembl, fetch_molecule_cactus, fetch_molecule_opsin, fetch_molecule_drugbank,
    fetch_bindingdb_affinity, fetch_bindingdb_by_target,
    fetch_ligand_ccd, fetch_ligand_smiles, fetch_ligand_from_pdb,
    swissmodel_get_token, swissmodel_clear_token,
    swissmodel_submit_alignment, swissmodel_check_status, swissmodel_download_result,
    clear_cache, get_cache_info,
)

# ─── Preparation ─────────────────────────────────────────────────────────────
from autodock._preparation import (
    prepare_receptor, prepare_ligand, prepare_ligand_conformers,
    find_top_pockets,
    _compute_box_size, _run_p2rank_rescore,
)

# ─── Docking ───────────────────────────────────────────────────────────────────
from autodock._docking import (
    find_binding_site,
    dock_ligand, dock_ligand_multi, dock_ligand_multi_conformer,
    virtual_screen,
    _detect_ligand_resn,
    # New Part A + B functions
    dock_ligand_flexible, prepare_receptor_with_waters,
    dock_single, screen_ligands, batch_docking,
)

# ─── Clustering ──────────────────────────────────────────────────────────────
from autodock._clustering import (
    cluster_poses,
)

# ─── Validation ────────────────────────────────────────────────────────────────
from autodock._validation import (
    compute_clash_score, compute_rmsd, validate_docking_protocol,
)

# ─── Interactions (detection + 2D) ───────────────────────────────────────────────
from autodock._interactions import (
    detect_interactions, detect_interactions_plip,
    render_interactions_2d, render_ligand_2d,
)

# ─── 3D Rendering ──────────────────────────────────────────────────────────────
from autodock._rendering_3d import (
    render_scene, render_complex, render_pocket, render_interactions_pymol,
    composite_summary,
)

# ─── LigPlot ─────────────────────────────────────────────────────────────────────
from autodock._ligplot import (
    render_ligplot_2d, render_ligplot_from_drw,
    parse_ligplot_drw,
)

# ─── MM/PBSA ───────────────────────────────────────────────────────────────────
from autodock._mmpbsa import (
    compute_mmpbsa, mmpbsa_rank_ligands,
    MMPBSAResult,
)

# ─── ADMET ─────────────────────────────────────────────────────────────────────
from autodock._admet import (
    predict_admet, filter_admet,
    _predict_admet_neurosnap, _predict_admet_rdkit,
)

# ─── Database ────────────────────────────────────────────────────────────────────
from autodock._database import (
    fetch_bioactivities, compute_enrichment, print_enrichment_report,
    sample_zinc_compounds, parse_zinc_tranche, lookup_zinc_id,
)

# ─── Scene presets (from existing config module) ────────────────────────────────
from autodock._pymol_viz_config import (
    SCENE_PRESETS, get_scene_preset,
    DASH_PRESETS, DASH_COLOR_MAP,
    STICK_PRESETS,
    CARTOON_PUBLICATION, CARTOON_POCKET, CARTOON_INTERACTION,
    PUBLICATION, PUBLICATION_OUTLINE, STANDARD,
)

__all__ = [
    # Docking workflow
    'prepare_receptor', 'prepare_ligand', 'prepare_ligand_conformers',
    'find_binding_site', 'find_top_pockets',
    'dock_ligand', 'dock_ligand_multi', 'dock_ligand_multi_conformer',
    'virtual_screen',
    'dock_ligand_flexible', 'prepare_receptor_with_waters',
    'dock_single', 'screen_ligands', 'batch_docking',
    'compute_clash_score', 'compute_rmsd', 'validate_docking_protocol', 'cluster_poses',
    # Interaction analysis
    'detect_interactions', 'detect_interactions_plip',
    'render_interactions_2d', 'render_ligand_2d',
    'render_ligplot_2d', 'render_ligplot_from_drw', 'parse_ligplot_drw',
    # Visualization (primary)
    'render_scene',
    # Specialized renderers
    'render_complex', 'render_pocket', 'render_interactions_pymol',
    'composite_summary',
    # Structure retrieval
    'fetch_protein', 'fetch_protein_pdb',
    'fetch_protein_alphafold', 'fetch_protein_swissmodel', 'fetch_protein_pdb_redo',
    'fetch_molecule', 'fetch_molecule_pubchem',
    'fetch_molecule_chembl', 'fetch_molecule_cactus', 'fetch_molecule_drugbank',
    # ADMET
    'predict_admet', 'filter_admet',
    # MM/PBSA
    'compute_mmpbsa', 'mmpbsa_rank_ligands',
    'MMPBSAResult',
    # Database
    'fetch_bioactivities', 'compute_enrichment', 'print_enrichment_report',
    'sample_zinc_compounds', 'parse_zinc_tranche', 'lookup_zinc_id',
    # Scene presets
    'SCENE_PRESETS', 'get_scene_preset',
    'DASH_PRESETS', 'DASH_COLOR_MAP',
    'STICK_PRESETS',
    'CARTOON_PUBLICATION', 'CARTOON_POCKET', 'CARTOON_INTERACTION',
    'PUBLICATION', 'PUBLICATION_OUTLINE', 'STANDARD',
    # Logger
    'autodock_logger',
    # Cache
    'clear_cache', 'get_cache_info',
    # Core types
    'DockingResult', 'build_docking_result',
]
