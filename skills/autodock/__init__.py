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

from autodock._autodock import (
    # Docking
    prepare_receptor,
    prepare_ligand,
    find_binding_site,
    dock_ligand,
    virtual_screen,
    # Interaction detection
    detect_interactions,
    # Visualization (primary API)
    render_scene,
    # Specialized renderers
    render_complex,
    render_pocket,
    render_interactions_pymol,
    render_ligand_2d,
    composite_summary,
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
    fetch_molecule_zinc,
)

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

__all__ = [
    # Docking workflow
    'prepare_receptor',
    'prepare_ligand',
    'find_binding_site',
    'dock_ligand',
    'virtual_screen',
    # Interaction analysis
    'detect_interactions',
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
    'fetch_molecule_zinc',
    # Scene presets
    'SCENE_PRESETS',
    'get_scene_preset',
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
