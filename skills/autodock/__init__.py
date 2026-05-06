"""
Autodock Molecular Docking Skill
================================
Complete molecular docking workflow: structure retrieval → preparation → docking → visualization.

Usage:
    import sys
    sys.path.insert(0, '~/.openclaw/workspace/skills/autodock/')
    from autodock import (
        fetch_protein_pdb, fetch_molecule_pubchem,
        prepare_receptor, prepare_ligand,
        find_binding_site, dock_ligand,
        detect_interactions, render_scene,
        render_complex, render_pocket, render_interactions_pymol,
        composite_summary,
    )

Environment: conda activate autodock313
"""

# Import _pymol_viz_config FIRST to break circular dependency
# (_autodock.py does: from autodock._pymol_viz_config import ...)
from autodock._pymol_viz_config import (
    SCENE_PRESETS,
    get_scene_preset,
    DASH_PRESETS,
    DASH_COLOR_MAP,
    STICK_PRESETS,
    CARTOON_PUBLICATION,
    CARTOON_POCKET,
    CARTOON_INTERACTION,
    PUBLICATION,
    PUBLICATION_OUTLINE,
    STANDARD,
)

from autodock._structure_fetch import (
    fetch_protein,
    fetch_protein_pdb,
    fetch_protein_alphafold,
    fetch_protein_swissmodel,
    fetch_protein_pdb_redo,
    fetch_molecule,
    fetch_molecule_pubchem,
    fetch_molecule_chembl,
    fetch_molecule_cactus,
    fetch_molecule_drugbank,
    clear_cache,
    get_cache_info,
)

from autodock._autodock import (
    # Logger (for CLI control)
    autodock_logger,
    # Docking
    prepare_receptor,
    prepare_ligand,
    prepare_ligand_conformers,
    find_binding_site,
    find_top_pockets,
    dock_ligand,
    dock_ligand_multi,
    dock_ligand_multi_conformer,
    virtual_screen,
    compute_clash_score,
    compute_rmsd,
    validate_docking_protocol,
    # Interaction detection
    detect_interactions,
    detect_interactions_plip,
    render_interactions_2d,
    render_ligplot_2d,
    # Visualization (primary API)
    render_scene,
    # Specialized renderers
    render_complex,
    render_pocket,
    render_interactions_pymol,
    render_ligand_2d,
    composite_summary,
)

__all__ = [
    # Docking workflow
    'prepare_receptor',
    'prepare_ligand',
    'prepare_ligand_conformers',
    'find_binding_site',
    'find_top_pockets',
    'dock_ligand',
    'dock_ligand_multi',
    'dock_ligand_multi_conformer',
    'virtual_screen',
    'compute_clash_score',
    'compute_rmsd',
    'validate_docking_protocol',
    # Interaction analysis
    'detect_interactions',
    'detect_interactions_plip',
    'render_interactions_2d',
    'render_ligplot_2d',
    'render_ligplot_2d',
    'render_ligplot_2d',
    # Visualization (primary)
    'render_scene',
    # Specialized renderers
    'render_complex',
    'render_pocket',
    'render_interactions_pymol',
    'render_ligand_2d',
    'composite_summary',
    # Structure retrieval
    'fetch_protein',
    'fetch_protein_pdb',
    'fetch_protein_alphafold',
    'fetch_protein_swissmodel',
    'fetch_protein_pdb_redo',
    'fetch_molecule',
    'fetch_molecule_pubchem',
    'fetch_molecule_chembl',
    'fetch_molecule_cactus',
    'fetch_molecule_drugbank',
    # Scene presets
    'SCENE_PRESETS',
    'get_scene_preset',
    # Logger (for CLI control)
    'autodock_logger',
    # Cache management
    'clear_cache',
    'get_cache_info',
    # Parameter presets (for advanced users)
    'DASH_PRESETS',
    'DASH_COLOR_MAP',
    'STICK_PRESETS',
    'CARTOON_PUBLICATION',
    'CARTOON_POCKET',
    'CARTOON_INTERACTION',
    'PUBLICATION',
    'PUBLICATION_OUTLINE',
    'STANDARD',
]
