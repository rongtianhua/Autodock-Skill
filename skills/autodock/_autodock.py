"""
Autodock Molecular Docking Module
=================================
Complete molecular docking workflow for AutoDock Vina + PyMOL rendering.

Environment: autodock313 (Python 3.13)
  conda activate autodock313

Key replacements vs. openbabel-based workflow:
  - Receptor PDB → PDBQT: meeko.MoleculePreparation
  - Ligand SMILES → PDBQT: RDKit ETKDGv3 + meeko
  - 3D Rendering: pymol.cmd.png() (direct Python API)

PyMOL Visualization — based on comprehensive research (2026-04-25):
  - PyMOL Official Docs + Leipzig University Tutorial
  - Oxford Protein Informatics Group (OPIG) best practices
  - CB-Dock2 paper (PMC9252749)
  - APBS Electrostatics Plugin docs
  Key parameters: dash_gap=0.4/dash_radius=0.05（Leipzig标准），
  ligand C=gold, pocket C=bluewhite, surface transparency=0.25

Author: PrimeClaw (OpenClaw)
"""

import os
import warnings
from typing import Optional

# ─── Version checks ──────────────────────────────────────────────────────────────
try:
    from pymol import cmd as _pymol_cmd
    _HAVE_PYMOL = True
except ImportError:
    _HAVE_PYMOL = False
    warnings.warn("pymol not available - 3D rendering disabled")

try:
    from vina import Vina
    _HAVE_VINA = True
except ImportError:
    _HAVE_VINA = False
    warnings.warn("vina not available")

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Draw
    _HAVE_RDKIT = True
except ImportError:
    _HAVE_RDKIT = False
    warnings.warn("rdkit not available")

try:
    from meeko import MoleculePreparation, RDKitMolCreate, PDBQTWriterLegacy, Polymer
    _HAVE_MEEKO = True
except ImportError:
    _HAVE_MEEKO = False
    warnings.warn("meeko not available")


# ─── Safe color helper (PyMOL 3.x compatible) ──────────────────────────────────

def _safe_color(cmd, color, selection):
    """Set color on selection, skip if color not available in PyMOL version."""
    try:
        cmd.color(color, selection)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# RECEPTOR PREPARATION
# ─────────────────────────────────────────────────────────────────────────────

def prepare_receptor(pdb_file: str, output_pdbqt: str,
                    remove_waters: bool = True) -> str:
    """
    Prepare protein structure for docking (PDB → PDBQT).

    Uses meeko (Polymer + PDBQTWriterLegacy) instead of openbabel.

    Args:
        pdb_file: Input PDB file path
        output_pdbqt: Output PDBQT file path
        remove_waters: Remove HOH / WAT residues

    Returns:
        Path to output PDBQT file
    """
    from meeko import ResidueChemTemplates

    if not _HAVE_MEEKO or not _HAVE_RDKIT:
        raise RuntimeError("meeko and rdkit required: conda activate autodock313")

    with open(pdb_file, 'r') as f:
        pdb_content = f.read()

    _skip_res = {'HOH', 'WAT', 'H2O', 'PJE', '02J', '010', '03U', '03T', '02K', '02L'}
    if remove_waters:
        lines = [l for l in pdb_content.split('\n')
                 if not (l.startswith('ATOM') or l.startswith('HETATM'))
                 or l[17:20].strip() not in _skip_res]
        pdb_content = '\n'.join(lines)

    templates = ResidueChemTemplates.create_from_defaults()
    mk_prep = MoleculePreparation()
    polymer = Polymer.from_pdb_string(pdb_content, templates, mk_prep)
    rigid_pdbqt, _ = PDBQTWriterLegacy.write_from_polymer(polymer)

    os.makedirs(os.path.dirname(output_pdbqt) or '.', exist_ok=True)
    with open(output_pdbqt, 'w') as f:
        f.write(rigid_pdbqt)

    print(f"[autodock] Receptor prepared: {output_pdbqt}")
    return output_pdbqt


def prepare_ligand(smiles: str, output_pdbqt: str, name: str = "LIG") -> str:
    """
    Prepare a ligand for docking (SMILES → PDBQT).

    Uses RDKit ETKDGv3 for 3D conformer + meeko for PDBQT export.

    Args:
        smiles: SMILES string of ligand
        output_pdbqt: Output PDBQT file path
        name: Residue name in PDBQT (default: LIG)

    Returns:
        Path to output PDBQT file
    """
    if not _HAVE_RDKIT or not _HAVE_MEEKO:
        raise RuntimeError("rdkit and meeko required: conda activate autodock313")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smiles}")
    mol = Chem.AddHs(mol, addCoords=True)
    AllChem.EmbedMolecule(mol, AllChem.ETKDGv3())
    AllChem.MMFFOptimizeMolecule(mol)

    params = MoleculePreparation()
    mol_setup = params.prepare(mol)
    setup = mol_setup[0] if isinstance(mol_setup, list) else mol_setup

    os.makedirs(os.path.dirname(output_pdbqt) or '.', exist_ok=True)
    pdbqt_str, success, err = PDBQTWriterLegacy.write_string(setup)
    if not success:
        raise RuntimeError(f"Meeko ligand prep failed: {err}")
    with open(output_pdbqt, 'w') as f:
        f.write(pdbqt_str)

    print(f"[autodock] Ligand prepared: {output_pdbqt}")
    return output_pdbqt


# ─────────────────────────────────────────────────────────────────────────────
# BINDING SITE DETECTION (fpocket)
# ─────────────────────────────────────────────────────────────────────────────

def find_binding_site(receptor_pdb: str,
                     ligand_pdb: str = None,
                     padding: float = 5.0,
                     top_n: int = 1) -> tuple:
    """
    Define docking search box using fpocket (cavity detection).

    Priority:
      1. ligand_pdb provided → center on ligand (most accurate)
      2. Otherwise → fpocket top druggable pocket

    Args:
        receptor_pdb: Protein PDB file (Apo or AlphaFold)
        ligand_pdb: Optional co-crystallized ligand PDB to center on
        padding: Padding around ligand/pocket (Angstroms)
        top_n: Which fpocket-ranked pocket to use (1 = top druggable)

    Returns:
        (center: tuple, box_size: tuple)
        center = (x, y, z)
        box_size = (sx, sy, sz)
    """
    if not _HAVE_RDKIT:
        raise RuntimeError("rdkit required: conda activate autodock313")

    # ── Option 1: co-crystallized ligand ─────────────────────────────────
    if ligand_pdb and os.path.exists(ligand_pdb):
        mol = Chem.MolFromPDBFile(ligand_pdb)
        conf = mol.GetConformer()
        coords = [conf.GetAtomPosition(i) for i in range(mol.GetNumAtoms())]
        xs = [c.x for c in coords]; ys = [c.y for c in coords]; zs = [c.z for c in coords]
        center = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        dims = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        box_size = tuple(int(d + 2 * padding) for d in dims)
        print(f"[autodock] Binding site from ligand: center={center}, box={box_size}")
        return center, box_size

    # ── Option 2: fpocket cavity detection ──────────────────────────────
    import subprocess, tempfile, shutil

    prep_pdb = tempfile.mktemp(suffix='_prep.pdb')
    _prepare_pdb_for_fpocket(receptor_pdb, prep_pdb)

    prep_pdb_abs = os.path.abspath(prep_pdb)
    prep_dir = os.path.dirname(prep_pdb_abs) or '.'
    base = os.path.splitext(os.path.basename(prep_pdb))[0]
    out_dir = os.path.join(prep_dir, base + '_out')

    try:
        result = subprocess.run(
            ['/opt/homebrew/Caskroom/miniconda/base/envs/autodock313/bin/fpocket', '-f', prep_pdb_abs],
            capture_output=True, text=True, timeout=120, cwd=prep_dir
        )
        if result.returncode != 0:
            raise RuntimeError(f"fpocket failed: {result.stderr}")

        info_file = os.path.join(out_dir, base + '_info.txt')
        if not os.path.exists(info_file):
            raise RuntimeError(f"fpocket did not produce info file: {info_file}")

        pockets = _parse_fpocket_info(info_file)
        if not pockets:
            raise RuntimeError(f"No pockets found by fpocket in {receptor_pdb}")

        pockets.sort(key=lambda p: p['druggability'], reverse=True)
        top_pocket = pockets[min(top_n - 1, len(pockets) - 1)]

        center = top_pocket['center']
        box_size = tuple(int(d + 2 * padding) for d in top_pocket['dims'])

        print(f"[autodock] Binding site (fpocket pocket {top_n}): "
              f"center={center}, box={box_size} "
              f"(druggability={top_pocket['druggability']:.3f})")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        if os.path.exists(prep_pdb):
            os.remove(prep_pdb)

    return center, box_size


def _prepare_pdb_for_fpocket(pdb_in: str, pdb_out: str) -> None:
    """Remove waters, keep only ATOM/HETATM."""
    from rdkit import Chem
    mol = Chem.MolFromPDBFile(pdb_in, removeHs=False)
    mol = Chem.RemoveHs(mol)
    with open(pdb_in) as fin, open(pdb_out, 'w') as fout:
        for line in fin:
            if line.startswith('ATOM') or line.startswith('HETATM'):
                if 'HOH' not in line[17:20]:
                    fout.write(line)


def _parse_fpocket_info(info_path: str) -> list:
    """Parse fpocket *_info.txt to extract pocket centroids and dims."""
    import re, numpy as np

    pockets = []
    blocks = re.split(r'(?=Pocket \d+ :)', open(info_path).read())

    for block in blocks:
        m = re.match(r'Pocket (\d+) :', block)
        if not m:
            continue
        pocket_num = int(m.group(1))
        dm = re.search(r'Druggability Score :\s+([\d.]+)', block)
        druggability = float(dm.group(1)) if dm else 0.0

        pocket_dir = os.path.dirname(info_path)
        pqr_path = os.path.join(pocket_dir, f'..', f'pocket{pocket_num}_vert.pqr')
        if not os.path.exists(pqr_path):
            pqr_path = os.path.join(pocket_dir, 'pockets', f'pocket{pocket_num}_vert.pqr')

        center = None; dims = None
        if os.path.exists(pqr_path):
            coords = []
            for line in open(pqr_path):
                if line.startswith(('ATOM', 'HETATM')):
                    x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
                    coords.append([x, y, z])
            if coords:
                ca = np.array(coords)
                center = (float(ca[:, 0].mean()), float(ca[:, 1].mean()), float(ca[:, 2].mean()))
                dims = (float(ca[:, 0].max() - ca[:, 0].min()),
                        float(ca[:, 1].max() - ca[:, 1].min()),
                        float(ca[:, 2].max() - ca[:, 2].min()))

        if center:
            pockets.append({
                'num': pocket_num, 'druggability': druggability,
                'center': center,
                'dims': dims if dims else (20.0, 20.0, 20.0),
            })
    return pockets


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTION DETECTION (RDKit geometry)
# ─────────────────────────────────────────────────────────────────────────────

def _read_ligand_from_pdbqt(pdbqt_path: str):
    """Parse PDBQT → RDKit mol (manual parse fallback)."""
    from rdkit import Chem

    coords, elements = [], []
    with open(pdbqt_path) as f:
        for line in f:
            if not (line.startswith('ATOM') or line.startswith('HETATM')):
                continue
            try:
                x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
            except ValueError:
                continue
            elem = line[77:79].strip().capitalize() or line[12:14].strip().capitalize()
            if elem == 'A': elem = 'C'
            if elem not in ('C', 'N', 'O', 'S', 'P', 'H', 'F', 'Cl', 'Br', 'I'):
                elem = 'C'
            coords.append((x, y, z)); elements.append(elem)

    if not coords:
        return None

    mol = Chem.RWMol()
    for elem in elements:
        mol.AddAtom(Chem.Atom(elem))
    mol = mol.GetMol()
    conf = Chem.Conformer(len(coords))
    conf.Set3D(True)
    for i, (x, y, z) in enumerate(coords):
        conf.SetAtomPosition(i, (x, y, z))
    mol.AddConformer(conf)
    return mol


def detect_interactions(receptor_pdb: str,
                       ligand_smiles: str = None,
                       ligand_pdbqt: str = None,
                       center: tuple = None,
                       distance: float = 6.0,
                       h_bond_max_angle: float = 40.0) -> list:
    """
    Detect non-covalent interactions (H-bond / π-π / Hydrophobic).

    Uses RDKit geometry. No external dependencies required.

    Args:
        receptor_pdb: Protein PDB file
        ligand_smiles: OR ligand PDBQT file path
        ligand_pdbqt: Ligand PDBQT file path
        center: (x, y, z) ligand center for distance-based detection
        distance: Max distance (Å) for protein-ligand interactions
        h_bond_max_angle: Max donor-H-acceptor angle (degrees, default 40°)

    Returns:
        list of dicts: type, color, resn, resi, chain, atom,
                       ligand_atom_idx, distance, description
    """
    if not _HAVE_RDKIT:
        print("[autodock] RDKit not available - interaction detection skipped")
        return []

    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    import numpy as np

    # ── Get ligand mol ─────────────────────────────────────────────────────
    if ligand_smiles:
        lig = Chem.MolFromSmiles(ligand_smiles)
        if lig is None:
            print(f"[autodock] Could not parse ligand SMILES")
            return []
        lig = Chem.AddHs(lig, addCoords=True)
        AllChem.EmbedMolecule(lig, AllChem.ETKDGv3())
        AllChem.MMFFOptimizeMolecule(lig)
    elif ligand_pdbqt and os.path.exists(ligand_pdbqt):
        lig = _read_ligand_from_pdbqt(ligand_pdbqt)
        if lig is None:
            print(f"[autodock] Could not read ligand from {ligand_pdbqt}")
            return []
    else:
        print("[autodock] No ligand provided for interaction detection")
        return []

    # ── Get protein atoms ─────────────────────────────────────────────────
    prot = Chem.MolFromPDBFile(receptor_pdb, removeHs=False)
    prot_conf = prot.GetConformer()

    interactions = []

    # ── H-bond geometry parameters (Leipzig standard) ────────────────────
    HBOND_DIST = 3.2   # Å (strong H-bond distance)
    PI_DIST = 6.0      # Å (π-π centroid distance)
    HYDROPHOBIC_DIST = 4.5  # Å (hydrophobic contact)

    # ── Collect protein H-bond donors ────────────────────────────────────
    backbone_n = []   # (resn, resi, chain, atom, x, y, z)
    sidechain_hbd = [] # (resn, resi, chain, atom, x, y, z) for SER/THR/TYR OH

    for a in prot.GetAtoms():
        res = a.GetPDBResidueInfo()
        if not res:
            continue
        resn = res.GetResidueName().strip()
        resi = res.GetResidueNumber()
        chain = res.GetChainId()
        aname = (a.GetMonomerInfo().GetName().strip()
                 if a.GetMonomerInfo() else '?')
        pos = prot_conf.GetAtomPosition(a.GetIdx())

        if a.GetAtomicNum() == 7:  # N — backbone donor
            backbone_n.append((resn, resi, chain, aname, pos.x, pos.y, pos.z))
        elif a.GetAtomicNum() == 8 and resn in ('SER', 'THR', 'TYR'):  # OH sidechain
            sidechain_hbd.append((resn, resi, chain, aname, pos.x, pos.y, pos.z))

    # ── Collect ligand H-bond acceptors (N, O) ────────────────────────────
    lig_hba = []
    for a in lig.GetAtoms():
        if a.GetAtomicNum() in (7, 8):  # N, O
            pos = lig.GetConformer().GetAtomPosition(a.GetIdx())
            lig_hba.append((a.GetIdx(), a.GetAtomicNum(), (pos.x, pos.y, pos.z)))

    # ── H-bond detection ─────────────────────────────────────────────────
    for la_idx, la_an, (lax, lay, laz) in lig_hba:
        # Backbone N-H donors
        for resn, resi, chain, aname, px, py, pz in backbone_n:
            d = np.sqrt((px - lax)**2 + (py - lay)**2 + (pz - laz)**2)
            if d < HBOND_DIST:
                interactions.append({
                    'type': 'H-bond', 'color': 'cyan',
                    'resn': resn, 'resi': resi, 'chain': chain, 'atom': aname,
                    'ligand_atom_idx': la_idx,
                    'distance': round(d, 2),
                    'description': f"H-bond: {resn}{resi}.{chain} {aname} → {('N' if la_an==7 else 'O')}{la_idx}"
                })
                break
        # Sidechain OH donors
        if not any(i['type'] == 'H-bond' and i['resi'] == resi
                   for i in interactions if i.get('ligand_atom_idx') == la_idx):
            for resn, resi, chain, aname, px, py, pz in sidechain_hbd:
                d = np.sqrt((px - lax)**2 + (py - lay)**2 + (pz - laz)**2)
                if d < HBOND_DIST:
                    interactions.append({
                        'type': 'H-bond', 'color': 'cyan',
                        'resn': resn, 'resi': resi, 'chain': chain, 'atom': aname,
                        'ligand_atom_idx': la_idx,
                        'distance': round(d, 2),
                        'description': f"H-bond: {resn}{resi}.{chain} {aname} → {('N' if la_an==7 else 'O')}{la_idx}"
                    })
                    break

    # ── π-π stacking (aromatic rings) ────────────────────────────────────
    ring_info = lig.GetRingInfo()
    aromatic_rings = [list(r) for r in ring_info.AtomRings() if ring_info.IsAtomInRingOfSize(r[0], 6)]

    if aromatic_rings:
        aromatics_map = {'PHE': 'Phe', 'TYR': 'Tyr', 'TRP': 'Trp', 'HIS': 'His'}
        for ring_atoms in aromatic_rings[:3]:
            ring_coords = [lig.GetConformer().GetAtomPosition(i) for i in ring_atoms]
            cx = sum(c.x for c in ring_coords) / len(ring_coords)
            cy = sum(c.y for c in ring_coords) / len(ring_coords)
            cz = sum(c.z for c in ring_coords) / len(ring_coords)
            ring_center = np.array([cx, cy, cz])

            for pa in prot.GetAtoms():
                res = pa.GetPDBResidueInfo()
                if not res:
                    continue
                if pa.GetAtomicNum() != 6:
                    continue
                resn = res.GetResidueName().strip()
                if resn not in aromatics_map:
                    continue
                ppos = prot_conf.GetAtomPosition(pa.GetIdx())
                d = np.linalg.norm(np.array([ppos.x, ppos.y, ppos.z]) - ring_center)
                if d < PI_DIST:
                    interactions.append({
                        'type': 'π-π', 'color': 'green',
                        'resn': resn, 'resi': res.GetResidueNumber(),
                        'chain': res.GetChainId(),
                        'atom': (pa.GetMonomerInfo().GetName().strip()
                                 if pa.GetMonomerInfo() else 'CA'),
                        'distance': round(float(d), 2),
                        'description': f"π-π: ligand ring ↔ {aromatics_map[resn]}{res.GetResidueNumber()}"
                    })

    # ── Hydrophobic contacts ──────────────────────────────────────────────
    hydrophobic_res = {'ALA', 'VAL', 'ILE', 'LEU', 'MET', 'PHE', 'TRP', 'PRO', 'GLY'}
    for pa in prot.GetAtoms():
        res = pa.GetPDBResidueInfo()
        if not res:
            continue
        if res.GetResidueName().strip() not in hydrophobic_res:
            continue
        if pa.GetAtomicNum() != 6:
            continue
        ppos = prot_conf.GetAtomPosition(pa.GetIdx())
        for i in range(lig.GetNumAtoms()):
            lpos = lig.GetConformer().GetAtomPosition(i)
            d = np.sqrt((ppos.x - lpos.x)**2 + (ppos.y - lpos.y)**2 + (ppos.z - lpos.z)**2)
            if d < HYDROPHOBIC_DIST:
                interactions.append({
                    'type': 'Hydrophobic', 'color': 'orange',
                    'resn': res.GetResidueName().strip(),
                    'resi': res.GetResidueNumber(),
                    'chain': res.GetChainId(),
                    'atom': (pa.GetMonomerInfo().GetName().strip()
                             if pa.GetMonomerInfo() else 'CA'),
                    'distance': round(d, 2),
                    'description': f"Hydrophobic: {res.GetResidueName().strip()}{res.GetResidueNumber()}"
                })
                break

    # ── Deduplicate by (type, resn, resi, chain) ─────────────────────────
    seen = set(); unique = []
    for i in interactions:
        key = (i['type'], i['resn'], i['resi'], i['chain'])
        if key not in seen:
            seen.add(key); unique.append(i)

    n_hb = sum(1 for x in unique if x['type'] == 'H-bond')
    n_pi = sum(1 for x in unique if x['type'] == 'π-π')
    n_hp = sum(1 for x in unique if x['type'] == 'Hydrophobic')
    print(f"[autodock] Interactions: H-bond={n_hb}, π-π={n_pi}, Hydrophobic={n_hp}")
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# PYMOL RENDERING — SCENE-PRESET SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

from autodock._pymol_viz_config import (
    PUBLICATION, PUBLICATION_OUTLINE, STANDARD,
    CPK_COLORS, DASH_PRESETS, DASH_COLOR_MAP,
    CARTOON_COLORS, CARTOON_PUBLICATION, CARTOON_POCKET, CARTOON_INTERACTION,
    SURFACE_POCKET, LIGHTING_DEFAULT, LIGHTING_SPECULAR,
    STICK_PRESETS, SPHERE_PRESETS,
    LABEL_PRESETS,
    BG_WHITE, BG_BLACK,
    SCENE_PRESETS,
    apply_ray_settings, apply_lighting, apply_cartoon,
    apply_stick, apply_dash, apply_surface,
    color_element, color_by_scheme,
    get_scene_preset,
)


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
        print("[autodock] PyMOL not available - render_scene skipped")
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

    # Ray trace + save
    cmd.png(png_abs, width=width, height=height, dpi=dpi, ray=1)

    ok = os.path.exists(png_abs) and os.path.getsize(png_abs) > 5000
    size = os.path.getsize(png_abs) // 1024 if ok else 0
    print(f"[autodock] render_scene({scene}): {'OK' if ok else 'FAILED'} ({size}KB)")
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

    Preset: 'interaction' scene (Leipzig Lab standard parameters)
      - Black background
      - Protein cartoon (gray80, transparency=0.2)
      - Pocket lines (white)
      - Ligand: gold sticks
      - Dashed lines: H-bond=cyan, π-π=green, Hydrophobic=orange
        dash_gap=0.4 / dash_radius=0.05 / dash_length=0.3 (Leipzig)

    Args:
        receptor_pdb: Protein PDB file
        ligand_pdbqt: Docked ligand PDBQT
        interactions: List from detect_interactions()
        center: (x, y, z) ligand center
        distance: Pocket radius (Å)
        dash_preset: 'fine' (Leipzig, default) | 'standard' | 'bold'
    """
    if not _HAVE_PYMOL:
        print("[autodock] PyMOL not available")
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

    # ── Protein cartoon (neutral gray, slightly transparent) ─────────────
    cmd.show('cartoon', 'all')
    _safe_color(cmd, 'gray80', 'elem C')
    apply_cartoon(cmd, 'INTERACTION')
    cmd.set('cartoon_transparency', 0.2, 'all')

    # ── Pocket selection ─────────────────────────────────────────────────
    cx, cy, cz = center
    pocket_sel = f'br. all and center {cx},{cy},{cz} around {distance}'
    cmd.select('pocket_sel', pocket_sel)

    # Pocket lines (white)
    cmd.show('lines', 'pocket_sel')
    _safe_color(cmd, 'white', 'pocket_sel and elem C')

    # ── Ligand sticks (gold) ─────────────────────────────────────────────
    cmd.show('sticks', 'docked_ligand')
    cmd.set('stick_radius', 0.2)
    cmd.set('valence', 1)
    _safe_color(cmd, 'gold',    'docked_ligand and elem C')
    _safe_color(cmd, 'red',     'docked_ligand and elem O')
    _safe_color(cmd, 'blue',    'docked_ligand and elem N')
    _safe_color(cmd, 'yellow',  'docked_ligand and elem S')
    cmd.show('spheres', 'docked_ligand and name C')
    cmd.set('sphere_scale', 0.25, 'docked_ligand')

    # ── Interaction dashed lines (Leipzig standard) ─────────────────────
    dash_params = DASH_PRESETS.get(dash_preset, DASH_PRESETS['fine'])
    cmd.set('dash_gap', dash_params['dash_gap'])
    cmd.set('dash_radius', dash_params['dash_radius'])
    cmd.set('dash_length', dash_params['dash_length'])
    cmd.set('dash_as_cylinders', int(dash_params['dash_as_cylinders']))
    cmd.set('dash_round_ends', int(dash_params['dash_round_ends']))

    for idx, inter in enumerate(interactions):
        pair_name = f'int_{idx}'
        resn = inter.get('resn', '')
        resi = inter.get('resi', '')
        atom = inter.get('atom', 'CA')
        prot_sel = f'(receptor and resn {resn} and resi {resi} and name {atom})'

        try:
            cmd.distance(pair_name, prot_sel, 'docked_ligand')
            color = DASH_COLOR_MAP.get(inter['type'], 'white')
            cmd.set('dash_color', color, pair_name)
            cmd.set('dash_width', 2.5, pair_name)
            cmd.hide('labels', pair_name)
        except Exception:
            pass

    # ── Labels for H-bond and π-π (not hydrophobic) ────────────────────
    try:
        labeled_resi = []
        for inter in interactions:
            if inter['type'] in ('H-bond', 'π-π'):
                labeled_resi.append(str(inter.get('resi', '')))
        if labeled_resi:
            lab_sel = f'pocket_sel and resi {"+".join(labeled_resi)} and name CA'
            cmd.label(lab_sel, '"%s-%s" % (resn, resi)')
            cmd.set('label_color', 'white')
            cmd.set('label_size', 0.35)
            cmd.set('label_font_id', 9)
    except Exception:
        pass

    # ── Quality + lighting ──────────────────────────────────────────────
    apply_lighting(cmd, 'DEFAULT')
    apply_ray_settings(cmd, 'PUBLICATION')

    # ── Zoom ─────────────────────────────────────────────────────────────
    cmd.zoom('pocket_sel', buffer=8)
    cmd.orient('pocket_sel')

    cmd.png(png_abs, width=width, height=height, dpi=dpi, ray=1)

    ok = os.path.exists(png_abs) and os.path.getsize(png_abs) > 5000
    size = os.path.getsize(png_abs) // 1024 if ok else 0
    print(f"[autodock] Interaction render: {'OK' if ok else 'FAILED'} ({size}KB)")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# 2D LIGAND RENDERING (RDKit)
# ─────────────────────────────────────────────────────────────────────────────

def render_ligand_2d(smiles_or_pdbqt: str,
                     output_png: str,
                     width: int = 500,
                     height: int = 500,
                     dpi: int = 150) -> bool:
    """
    Render small molecule as 2D structure diagram (RDKit).

    Args:
        smiles_or_pdbqt: SMILES string or path to ligand PDBQT/PDB file
        output_png: Output PNG
        width, height, dpi: Image settings

    Returns:
        True if successful
    """
    if not _HAVE_RDKIT:
        print("[autodock] RDKit not available - render_ligand_2d skipped")
        return False

    mol = None
    input_is_smiles = False

    if os.path.isfile(smiles_or_pdbqt):
        if smiles_or_pdbqt.endswith('.pdbqt'):
            # Extract PDB block from PDBQT (multi-MODEL aware)
            pdb_lines = []
            for line in open(smiles_or_pdbqt):
                if line.startswith('MODEL') or line.startswith('ENDMDL'):
                    continue
                if line.startswith('ATOM') or line.startswith('HETATM'):
                    pdb_lines.append(line[:66] + '\n')
            if pdb_lines:
                mol = Chem.MolFromPDBBlock(''.join(pdb_lines), removeHs=False)
        else:
            try:
                mol = Chem.MolFromPDBFile(smiles_or_pdbqt)
            except Exception:
                pass
    else:
        input_is_smiles = True
        mol = Chem.MolFromSmiles(smiles_or_pdbqt)

    if mol is None:
        print(f"[autodock] Could not read ligand: {smiles_or_pdbqt}")
        return False

    mol = Chem.RemoveHs(mol)
    if input_is_smiles:
        AllChem.Compute2DCoords(mol)

    img = Draw.MolToImage(mol, size=(width, height))
    os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)
    img.save(output_png)

    ok = os.path.exists(output_png) and os.path.getsize(output_png) > 2000
    print(f"[autodock] 2D render: {'OK' if ok else 'FAILED'} "
          f"({os.path.getsize(output_png)//1024}KB)")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# COMPOSITE FIGURE (matplotlib panels)
# ─────────────────────────────────────────────────────────────────────────────

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
        print("[autodock] No valid panels to composite")
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
    print(f"[autodock] Composite: {'OK' if ok else 'FAILED'} "
          f"({os.path.getsize(output_png)//1024}KB)")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# DOCKING
# ─────────────────────────────────────────────────────────────────────────────

def dock_ligand(receptor_pdbqt: str,
                ligand_pdbqt: str,
                center: tuple,
                box_size: tuple,
                exhaustiveness: int = 8,
                n_poses: int = 10) -> tuple:
    """
    Dock a single ligand into a protein binding site (AutoDock Vina).

    Args:
        receptor_pdbqt: Prepared receptor PDBQT
        ligand_pdbqt: Prepared ligand PDBQT
        center: (x, y, z) center of binding box
        box_size: (sx, sy, sz) box dimensions (Å)
        exhaustiveness: Search thoroughness (8=quick, 32=production)
        n_poses: Number of poses to return

    Returns:
        (energies: ndarray, poses: list of PDBQT strings)
        energies[n][0] = total affinity (kcal/mol, more negative = tighter)
    """
    if not _HAVE_VINA:
        raise RuntimeError("vina required: conda activate autodock313")

    v = Vina(sf_name='vina')
    v.set_receptor(receptor_pdbqt)
    v.set_ligand_from_file(ligand_pdbqt)
    v.compute_vina_maps(center=center, box_size=box_size)
    v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses)

    energies = v.energies()
    poses_raw = v.poses(n_poses=energies.shape[0], energy_range=20.0)

    if isinstance(poses_raw, str):
        parts = poses_raw.split('MODEL ')
        pose_list = []
        for i, part in enumerate(parts[1:]):
            end_idx = part.find('ENDMDL')
            pose_str = (f'MODEL {i+1}\n{part[:end_idx+6]}\n'
                        if end_idx >= 0 else f'MODEL {i+1}\n{part}\n')
            pose_list.append(pose_str)
        poses = pose_list
    else:
        poses = list(poses_raw)

    best = float(energies[0][0]) if energies.size > 0 else None
    print(f"[autodock] Best affinity: {best} kcal/mol ({len(poses)} poses)")
    return energies, poses


def virtual_screen(receptor_pdbqt: str,
                  ligand_smiles_dict: dict,
                  center: tuple,
                  box_size: tuple,
                  output_dir: str = "./docking_results",
                  exhaustiveness: int = 8,
                  n_poses: int = 3):
    """
    Screen a compound library against a protein target.

    Returns:
        DataFrame sorted by binding affinity
    """
    if not all([_HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO]):
        raise RuntimeError("vina + rdkit + meeko required")

    import pandas as pd
    os.makedirs(output_dir, exist_ok=True)

    v = Vina(sf_name='vina')
    v.set_receptor(receptor_pdbqt)
    v.compute_vina_maps(center=center, box_size=box_size)

    results = []
    for name, smiles in ligand_smiles_dict.items():
        try:
            ligand_pdbqt = os.path.join(output_dir, f"{name}.pdbqt")
            prepare_ligand(smiles, ligand_pdbqt)
            v.set_ligand_from_file(ligand_pdbqt)
            v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses)
            energies = v.energies()
            best = float(energies[0][0]) if energies.size > 0 else None
            pose_file = os.path.join(output_dir, f"{name}_poses.pdbqt")
            if best is not None:
                v.write_poses(pose_file, n_poses=n_poses)
            else:
                pose_file = None
            results.append({'name': name, 'smiles': smiles,
                            'affinity_kcal_mol': best, 'poses_file': pose_file})
            print(f"[autodock] {name}: {best} kcal/mol")
        except Exception as e:
            print(f"[autodock] {name}: FAILED - {e}")
            results.append({'name': name, 'smiles': smiles,
                            'affinity_kcal_mol': None, 'error': str(e)})

    return pd.DataFrame(results).sort_values('affinity_kcal_mol')


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _detect_ligand_resn(pdb_path: str) -> str:
    """Auto-detect ligand residue name from PDB HETATM records."""
    skip = {'HOH', 'WAT', 'H2O', 'NA', 'CL', 'MG', 'ZN', 'FE',
            'CA', 'MN', 'K', 'NA+', 'CL-', 'CU', 'NI', 'CO',
            'ATP', 'ADP', 'NAD', 'HEM', 'SAM', 'GSH', 'GDP', 'COV'}
    het = set()
    try:
        for line in open(pdb_path):
            if line.startswith('HETATM'):
                resn = line[17:20].strip()
                if resn not in skip:
                    het.add(resn)
    except Exception:
        pass
    return sorted(het)[0] if het else 'LIG'


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== autodock module ===")
    print(f"  PyMOL: {'OK' if _HAVE_PYMOL else 'MISSING'}")
    print(f"  Vina:  {'OK' if _HAVE_VINA else 'MISSING'}")
    print(f"  RDKit: {'OK' if _HAVE_RDKIT else 'MISSING'}")
    print(f"  Meeko: {'OK' if _HAVE_MEEKO else 'MISSING'}")
    if all([_HAVE_PYMOL, _HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO]):
        print("\nAll dependencies available — ready for docking!")
    else:
        print("\nSome dependencies missing — run: conda activate autodock313")
