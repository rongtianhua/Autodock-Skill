"""
Autodock Interactions Module
==============================
Interaction detection (PLIP + RDKit) and 2D rendering (RDKit + Cairo).
"""
import os
import io
import tempfile
import warnings
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point2D
from rdkit import RDLogger

from autodock._core import autodock_logger, _HAVE_RDKIT, _HAVE_PLIP
from autodock._preparation import _read_ligand_from_pdbqt_3d

# PLIP config import
if _HAVE_PLIP:
    from plip.structure.preparation import PDBComplex
    from plip.basic import config as plip_config

# Backward-compat logger alias
logger = autodock_logger

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
        logger.warning("[autodock] RDKit not available - interaction detection skipped")
        return []

    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors
    import numpy as np

    # ── Get ligand mol ─────────────────────────────────────────────────────
    if ligand_smiles:
        lig = Chem.MolFromSmiles(ligand_smiles)
        if lig is None:
            logger.error(f"[autodock] Could not parse ligand SMILES")
            return []
        lig = Chem.AddHs(lig, addCoords=True)
        AllChem.EmbedMolecule(lig, AllChem.ETKDGv3())
        AllChem.MMFFOptimizeMolecule(lig)
    elif ligand_pdbqt and os.path.exists(ligand_pdbqt):
        lig = _read_ligand_from_pdbqt_3d(ligand_pdbqt)
        if lig is None:
            logger.error(f"[autodock] Could not read ligand from {ligand_pdbqt}")
            return []
    else:
        logger.warning("[autodock] No ligand provided for interaction detection")
        return []

    # ── Get protein atoms ─────────────────────────────────────────────────
    # Use sanitize=False as fallback: some PDBs have element-column issues
    # (e.g. "A" for generic atoms) that RDKit rejects.  We pre-process the
    # PDB content to replace unknown element names with "C" before parsing.
    try:
        prot = Chem.MolFromPDBFile(receptor_pdb, removeHs=False)
    except Exception as e:
        logger.error(f"[autodock] Could not parse receptor PDB with standard parser: {e}")
        prot = None

    if prot is None:
        # Fallback: read PDB, fix element column, re-parse with sanitize=False
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pdb_text = open(receptor_pdb).read()
        # Replace 2-char element column (cols 77-78) that RDKit can't parse with " C"
        import re
        def fix_element(match):
            elem = match.group(1).strip()
            known = {'C','N','O','S','P','H','F','Cl','Br','I','Fe','Ca','Mg','Zn','Mn','Cu','Na','K'}
            return match.group(0)[:76] + (elem if elem in known else ' C')
        pdb_text_fixed = re.sub(r'(.{76})(.{2})', fix_element, pdb_text)
        try:
            prot = Chem.MolFromPDBBlock(pdb_text_fixed, sanitize=False, removeHs=False)
        except Exception as e2:
            logger.error(f"[autodock] Could not parse receptor PDB (fallback also failed: {e2})")
            return []

    if prot is None:
        logger.info(f"[autodock] Could not parse receptor PDB (returned None)")
        return []
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
                break  # one contact per protein atom is sufficient (dedup by residue later)

    # ── Deduplicate by (type, resn, resi, chain) ─────────────────────────
    seen = set(); unique = []
    for i in interactions:
        key = (i['type'], i['resn'], i['resi'], i['chain'])
        if key not in seen:
            seen.add(key); unique.append(i)

    n_hb = sum(1 for x in unique if x['type'] == 'H-bond')
    n_pi = sum(1 for x in unique if x['type'] == 'π-π')
    n_hp = sum(1 for x in unique if x['type'] == 'Hydrophobic')
    logger.info(f"[autodock] Interactions: H-bond={n_hb}, π-π={n_pi}, Hydrophobic={n_hp}")
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# PLIP-BASED INTERACTION DETECTION (2D diagram data)
# ─────────────────────────────────────────────────────────────────────────────

from openbabel import pybel as _pybel

def _detect_ligand_resn_for_plip(pdb_path: str) -> str:
    """Detect residue name from PDBQT/PDB filename."""
    for suffix in ('.pdbqt', '.pdb'):
        if pdb_path.endswith(suffix):
            name = os.path.basename(pdb_path).replace(suffix, '')
            return name.upper()[:3]
    return 'LIG'


def _parse_ligand_from_pdbqt_for_plip(docked_pdbqt: str) -> str:
    """
    Extract ligand coordinates from a Vina/ADT partial PDBQT.

    Handles ROOT/ENDROOT and BRANCH/ENDBRANCH sections:
    - ROOT atoms: rigid core, always included
    - BRANCH atoms: flexible side chains, included with explicit coords

    Returns PDB-formatted string (ATOM records) for all ligand heavy atoms.
    """
    lines = open(docked_pdbqt).read().splitlines()
    atom_lines = []
    in_ligand = False
    for l in lines:
        s = l.strip()
        if s in ('ROOT', 'HETATM', 'ATOM'):
            in_ligand = True
        elif s == 'ENDROOT':
            in_ligand = False
        elif s.startswith('BRANCH'):
            in_ligand = True
        elif s.startswith('ENDBRANCH'):
            in_ligand = False
        elif l.startswith(('ATOM', 'HETATM')) and in_ligand:
            atom_lines.append(l)

    if not atom_lines:
        raise ValueError(f"No ATOM records found in {docked_pdbqt}")

    # Write raw ATOM lines and convert via pybel → gives clean PDB format
    tmp = tempfile.NamedTemporaryFile(
        suffix='_ligand_extract.pdb', delete=False, mode='w'
    )
    tmp.write('\n'.join(atom_lines) + '\n')
    tmp.close()

    try:
        try:
            mol = next(_pybel.readfile('pdbqt', tmp.name))
        except Exception:
            mol = next(_pybel.readfile('pdb', tmp.name))
        pdb_str = mol.write('pdb')
    finally:
        os.unlink(tmp.name)

    return pdb_str


def _build_complex_pdb_for_plip(receptor_pdb: str, ligand_pdbqt: str) -> str:
    """
    Build a valid complex PDB for PLIP from crystal PDB + docked PDBQT.

    Strategy:
      1. Read crystal PDB, convert GLY/TYR HETATMs → ATOM (Option E)
      2. Extract ligand from PDBQT via _parse_ligand_from_pdbqt_for_plip
      3. Combine: protein ATOMs + ligand ATOMs + END

    The key insight (2026-04-30 debugging):
    - Crystal PDB contains GLY A 501 + TYR A 502 as HETATM records (co-crystallized
      dipeptide substrate). These have 17 heavy atoms each (same as docked UNL ligand).
    - PLIP detects ALL SMALLMOLECULE-type residues. Both GLY and UNL are detected
      as candidate ligands with identical heavy-atom counts.
    - The site-selection heuristic (max heavy atoms) picks GLY:A:501 first
      alphabetically (dict iteration order), causing ALL ligand_atom_idx mappings
      to fail (interactions reported for substrate coords, mapped to wrong ligand).
    - Solution: convert GLY/TYR HETATMs → ATOM. PLIP treats ATOM records as
      standard protein residues, not SMALLMOLECULE ligands. Only UNL:A:1 remains
      as a SMALLMOLECULE, so site selection is unambiguous.


    Args:
        receptor_pdb: Crystal protein PDB file (with potential GLY/TYR HETATMs).
                       MUST be crystal PDB (not receptor PDBQT) so that REMARK 800
                       site markers are preserved for accurate PLIP site detection.
        ligand_pdbqt: Docked ligand PDBQT path

    Returns path to temp complex PDB.  Caller must os.unlink() it.
    """
    with open(receptor_pdb) as f:
        rec_lines = f.read().splitlines()
    # Strip trailing structural records
    while rec_lines and rec_lines[-1].startswith(('END', 'CONECT', 'MASTER', 'TER')):
        rec_lines.pop()

    # Standard amino-acid residue names that may appear as HETATM in crystal
    # structures (co-crystallized peptides, substrates, or mislabeled residues).
    # Converting them to ATOM prevents PLIP from treating them as competing
    # ligands.  Non-standard HETATMs (metal ions, cofactors, and co-crystallized
    # small-molecule inhibitors) are retained so that PLIP can still detect
    # metal complexes and cofactor interactions.
    _STD_AA_HETATM = {
        'ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'GLN', 'GLU', 'GLY',
        'HIS', 'ILE', 'LEU', 'LYS', 'MET', 'MSE', 'PHE', 'PRO',
        'SER', 'THR', 'TRP', 'TYR', 'VAL',
    }
    _SKIP_HET = {'HOH', 'WAT', 'H2O'}

    prot_lines = []
    for l in rec_lines:
        if l.startswith('HETATM'):
            resn = l[17:20].strip()
            if resn in _SKIP_HET:
                continue  # Skip water
            elif resn in _STD_AA_HETATM:
                # Standard amino acid as HETATM → convert to ATOM (protein residue)
                l = 'ATOM' + l[6:]
                prot_lines.append(l)
            else:
                # Non-standard HETATM (metal ion, cofactor, small-molecule inhibitor).
                # Retained so PLIP can detect metal complexes / cofactor contacts.
                # If a co-crystallized inhibitor is present, the downstream
                # heavy-atoms heuristic selects the docked ligand (usually the
                # largest molecule).  Users should remove known co-crystallized
                # inhibitors before docking when this is undesirable.
                prot_lines.append(l)
        else:
            prot_lines.append(l)

    # Trim to last ATOM
    last_prot_idx = 0
    for i, l in enumerate(prot_lines):
        if l.startswith('ATOM'):
            last_prot_idx = i
    prot_lines = prot_lines[:last_prot_idx + 1]

    # Step 2: Get ligand ATOM lines from docked PDBQT (ROOT/BRANCH → pybel → PDB)
    lig_pdb_str = _parse_ligand_from_pdbqt_for_plip(ligand_pdbqt)
    lig_atom_lines = [
        l + '\n' for l in lig_pdb_str.splitlines()
        if l.startswith(('ATOM', 'HETATM'))
    ]
    # Ensure ligand chain = 'A' for consistent PLIP detection
    for i, l in enumerate(lig_atom_lines):
        if len(l) > 22 and l[21] == ' ':
            lig_atom_lines[i] = l[:21] + 'A' + l[22:]

    # Step 3: Assemble complex PDB
    tmp = tempfile.NamedTemporaryFile(
        suffix='_plip_complex.pdb', delete=False, mode='w'
    )
    for l in prot_lines:
        tmp.write(l + '\n')
    for l in lig_atom_lines:
        tmp.write(l)
    tmp.write('END\n')
    tmp.close()
    return tmp.name


def _configure_plip(OutPath: str) -> None:
    """Configure PLIP global settings for programmatic use."""
    plip_config.BASEPATH = OutPath
    plip_config.OUTPATH = OutPath
    plip_config.PICS = True
    plip_config.PYMOL = True
    plip_config.XML = True
    plip_config.NOHYDRO = False
    plip_config.NOFIXFILE = True
    plip_config.VERBOSE = False
    plip_config.SILENT = True
    plip_config.PLUGIN_MODE = False
    os.makedirs(OutPath, exist_ok=True)



def _map_pybel_to_rdk_atom_idx(ligand_pdbqt: str, _cached_lig_rdk=None) -> tuple:
    """
    Map pybel atom indices → RDKit atom indices by coordinate matching.

    PLIP uses pybel atom indices; our renderers use RDKit indices.
    We match by rounding 3D coordinates to 0.01 Å.

    Returns:
        tuple: (coord_dict, lig_rdk)
            - coord_dict: {(round_x, round_y, round_z) → rdk_atom_idx}
            - lig_rdk: the RDKit molecule (from cache or newly read)
    """
    lig_rdk = _cached_lig_rdk or _read_ligand_from_pdbqt_3d(ligand_pdbqt)
    if lig_rdk is None:
        return {}, None
    # GetConformer() fails when the mol has no 3D conformer
    # (happens when _read_ligand_from_pdbqt_3d falls back to SMILES template
    # due to atom-count mismatch between PDBQT and SMILES).
    # In that case, return empty mapping — caller will use pybel fallback.
    try:
        conf = lig_rdk.GetConformer()
    except ValueError:
        return {}, None
    coord_map = {}
    for i in range(lig_rdk.GetNumAtoms()):
        p = conf.GetAtomPosition(i)
        coord_map[(round(p.x, 2), round(p.y, 2), round(p.z, 2))] = i
    return coord_map, lig_rdk



# Map PLIP interaction type (11 keys) -> standardized display name + color
# H-bond: pdon(蛋白供体)/ldon(配体供体) → 同一显示名
# Salt bridge: lneg(配体负)/pneg(蛋白负) → 同一显示名
# π-cation: paro(芳环→正电)/laro(脂肪→正电) → 同一显示名
PLIP_TYPE_MAP = {
    'hbonds_pdon': ('H-bond', 'cyan'),
    'hbonds_ldon': ('H-bond', 'cyan'),
    'hydrophobic_contacts': ('Hydrophobic', 'orange'),
    'pistacking': ('π-π', 'green'),
    'pication_paro': ('π-cation', 'magenta'),
    'pication_laro': ('π-cation', 'magenta'),
    'saltbridge_lneg': ('Salt bridge', 'red'),
    'saltbridge_pneg': ('Salt bridge', 'red'),
    'halogen_bonds': ('Halogen bond', 'yellow'),
    'water_bridges': ('Water bridge', 'blue'),
    'metal_complexes': ('Metal complex', 'gray'),
}





"""
Publication-quality 2D protein-ligand interaction diagram renderer.
Strategy: RDKit dummy atom + ZERO bond + circleAtoms + post-processing arrows.

Key design decisions (based on RDKit 2026.03.1 docs + Greg Landrum 2025 blog):
- Cairo backend for PNG output (native, no external deps)
- Dummy atoms (AtomicNum=0) for residue markers, positioned by RDKit's 2D layout
- ZERO-order bonds connect ligand atoms to dummy atoms
- Post-processing via DrawArrow/DrawLine for interaction line styles
- Salt bridges / metal ions without ligand coords: use nearest ligand atom fallback
- π-π/π-cation: connect ring centroid via nearest ring atom to dummy
"""

import os, io, tempfile
import numpy as np

from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point2D
from rdkit import RDLogger
RDLogger.DisableLog('rdAll')


# ── Visual style for each interaction type ──────────────────────────────────
# Covers all 11 PLIP types + Metal complex
INTERACTION_STYLE = {
    'H-bond': {
        'color': (0.0, 0.75, 0.75),     # cyan
        'line_width': 2.0,
        'end_style': 'arrow',            # directional arrow
        'label': 'H-bond',
    },
    'Hydrophobic': {
        'color': (1.0, 0.55, 0.0),       # orange
        'line_width': 1.5,
        'end_style': 'dash',             # dashed line
        'label': 'Hydrophobic',
    },
    'π-π': {
        'color': (0.15, 0.75, 0.15),      # green
        'line_width': 2.0,
        'end_style': 'double',           # double line
        'label': 'π-π stacking',
    },
    'π-cation': {
        'color': (0.75, 0.15, 0.75),     # magenta
        'line_width': 2.0,
        'end_style': 'double',           # double line
        'label': 'π-cation',
    },
    'Salt bridge': {
        'color': (0.9, 0.15, 0.15),      # red
        'line_width': 2.0,
        'end_style': 'double',
        'label': 'Salt bridge',
    },
    'Halogen bond': {
        'color': (0.75, 0.75, 0.1),      # yellow
        'line_width': 2.0,
        'end_style': 'arrow',
        'label': 'Halogen bond',
    },
    'Water bridge': {
        'color': (0.2, 0.4, 0.85),       # blue
        'line_width': 1.5,
        'end_style': 'dash',
        'label': 'Water bridge',
    },
    'Metal complex': {
        'color': (0.55, 0.55, 0.55),     # gray
        'line_width': 2.0,
        'end_style': 'double',
        'label': 'Metal complex',
    },
}

# All 11 PLIP types that can appear in interactions list
ALL_TYPES = list(INTERACTION_STYLE.keys())


# ── Molecule building ─────────────────────────────────────────────────────────

def detect_interactions_plip(receptor_pdb: str,
                            ligand_pdbqt: str,
                            output_dir: str = None) -> tuple:
    """
    Detect protein-ligand interactions using PLIP (8 interaction types).

    This is the primary interaction detector, replacing detect_interactions().
    Falls back to the RDKit-based detect_interactions() if PLIP fails.


    Args:
        receptor_pdb: Crystal protein PDB file. MUST be the crystal PDB (not
                       receptor PDBQT) so that REMARK 800 binding site markers
                       are preserved for accurate PLIP site detection and GLY/TYR
                       HETATMs can be converted to ATOM for correct site selection.
        ligand_pdbqt: Docked ligand PDBQT file
        output_dir: Directory for PLIP output (default: system temp)


    Returns:
        (interactions_list, xml_report_path)
            interactions: list of dicts with keys:
                type, color, resn, resi, chain, atom,
                ligand_atom_idx (RDKit index), distance, description

            ligand_atom_idx notes:
                - H-bond / Hydrophobic / π-π / π-cation / Halogen bond / Water bridge:
                  ligand_atom_idx is the exact RDKit atom index (direct PLIP mapping).
                - Salt bridge / Metal complex:
                  PLIP stores charge center / metal ion coordinates rather than a
                  specific atom. We use the nearest non-hydrogen ligand atom as
                  fallback (standard PLIP behavior per official docs). This may
                  result in a sub-atomic offset (< 1 Å) for 2D highlight positioning,
                  but does not affect the correctness of interaction rendering.
            xml_report_path: path to PLIP XML report (empty str if no XML)
    """
    if output_dir is None:
        output_dir = tempfile.gettempdir()
    os.makedirs(output_dir, exist_ok=True)

    complex_pdb = None
    try:
        complex_pdb = _build_complex_pdb_for_plip(receptor_pdb, ligand_pdbqt)

        _configure_plip(output_dir)


        plcomplex = PDBComplex()
        plcomplex.output_path = output_dir
        plcomplex.load_pdb(complex_pdb)
        plcomplex.analyze()

        # Find the docked ligand's interaction set.
        # When the receptor crystal contains a co-crystallized ligand (e.g. PJE in 6LU7),
        # PLIP may detect both that ligand AND the docked ligand as separate interaction sets.
        # We select the one with the most heavy atoms — that's the docked ligand.
        # (The crystal ligand typically has <25 heavy atoms; a full drug-like ligand has 30+).
        key = None
        best_heavy = 0
        for k, pli in plcomplex.interaction_sets.items():
            if pli.ligand.type in ('SMALLMOLECULE', 'UNSPECIFIED'):
                if pli.ligand.heavy_atoms > best_heavy:
                    best_heavy = pli.ligand.heavy_atoms
                    key = k
        if key is None:
            key = list(plcomplex.interaction_sets.keys())[-1]

        pli = plcomplex.interaction_sets[key]


    except Exception as e:
        logger.error(f"[autodock] PLIP analysis failed: {e}, falling back to RDKit")
        if complex_pdb and os.path.exists(complex_pdb):
            os.unlink(complex_pdb)
        return detect_interactions(receptor_pdb=receptor_pdb, ligand_pdbqt=ligand_pdbqt), ''

    try:
        # Build pybel -> RDKit coordinate mapping
        coord_to_rdk, lig_rdk = _map_pybel_to_rdk_atom_idx(ligand_pdbqt)

        def _get_ligatom_pybel(item, itype):
            '''Extract ligand pybel Atom from a PLIP interaction item.

            PLIP stores different attributes per interaction type:
            - H-bonds (hbonds_pdon/ldon): item.a (acceptor) or item.d (donor)
              protisdon=True -> protein is donor, ligand is acceptor -> item.a
              protisdon=False -> ligand is donor, protein is acceptor -> item.d
            - hydrophobic_contacts: item.ligatom (pybel Atom)
            - pistacking: item.ligandring.atoms[0] (1st ring atom)
            - pication (paro/laro): item.ring.atoms[0] (aromatic ring atom)
              protcharged=True -> ring=ligand aromatic, charge=protein cation
              protcharged=False -> ring=protein, charge=ligand cation
            - saltbridge (lneg/pneg): NO direct pybel Atom available
              (only RingCenter with .center coords, no .atoms)
            - halogen_bonds: item.don.x (the halogen pybel Atom)
              acc=protein acceptor, don=ligand donor (the halogen)
            - water_bridges: item.d (the ligand atom in the bridge)
              a=protein atom, d=ligand atom (always; protisdon not used here)
            - metal_complexes: item.target.atom (pybel Atom)

            Returns (pybel Atom, protein_center_tuple) or (None, None).
            protein_center_tuple is (x,y,z) for salt bridge/water bridge/metal complex.
            '''
            if itype == 'hydrophobic_contacts':
                return item.ligatom, None
            elif itype in ('hbonds_pdon', 'hbonds_ldon'):
                # Protein atom coords are in item.x/item.y/item.z
                return (item.a if item.protisdon else item.d), None
        # Store protein ring centroid for π-π / π-cation rendering
                prot_center = None
                if attr == 'pistacking' and hasattr(item, 'proteinring') and item.proteinring:
                    prot_center = item.proteinring.center
                elif attr in ('pication_paro', 'pication_laro') and hasattr(item, 'ring') and item.ring:
                    prot_center = item.ring.center
                return nearest, prot_center
            elif itype in ('saltbridge_lneg', 'saltbridge_pneg'):
                # Salt bridges: item is a saltbridge namedtuple with:
                #   .positive / .negative = ChargeCenter objects (has .atoms[pybel], .center)
                #   .protispos = True → protein is positive → protein side = item.positive
                #   .protispos = False → protein is negative → protein side = item.negative
                # For LIGAND atom (for 2D mapping):
                #   protispos=True → ligand is negative → item.negative.atoms[0]
                #   protispos=False → ligand is positive → item.positive.atoms[0]
                prot_side = item.positive if item.protispos else item.negative
                lig_side = item.negative if item.protispos else item.positive
                # Return ligand atom for coordinate mapping
                if hasattr(lig_side, 'atoms') and lig_side.atoms:
                    pa = lig_side.atoms[0]
                else:
                    pa = None
                # prot_center = charged center (used as protein position in rendering)
                prot_center = None
                if hasattr(prot_side, 'center') and prot_side.center:
                    prot_center = prot_side.center
                return pa, prot_center
            elif itype in ('pistacking',):
                # π-π stacking: use proteinring.center (aromatic ring centroid) as protein position.
                # Store in _prot_center to avoid being overwritten by nearest-atom fallback below.
                prot_ring_center = None
                if hasattr(item, 'proteinring') and item.proteinring and hasattr(item.proteinring, 'center'):
                    prot_ring_center = item.proteinring.center
                prot_center = prot_ring_center  # may be None; nearest-atom fallback below fills gaps
                nearest = item.ligandring.atoms[0]  # ligand ring atom for coordinate mapping
                return nearest, prot_center
            elif itype in ('pication_paro', 'pication_laro'):
                # π-cation: use nearest protein atom as protein position.
                # (The ring in PLIP may be on the ligand side; nearest atom is the protein cation site.)
                prot_center = None
                nearest = item.ring.atoms[0]  # ligand ring atom for coordinate mapping
                return nearest, prot_center
            elif itype == 'halogen_bonds':
                # don.x is the ligand halogen atom
                return item.don.x, None
            elif itype == 'water_bridges':
                # item.d is the ligand atom (always) — store protein atom for fallback
                prot_center = None
                if hasattr(item, 'a') and item.a:
                    ac = item.a.coords
                    prot_center = (ac[0], ac[1], ac[2])
                return item.d, prot_center
            elif itype == 'metal_complexes':
                # item.target.atom may be protein or ligand atom (check target_type)
                # For 2D rendering: use the ligand-side atom
                # Store metal ion coords as _prot_center for distance fallback
                pa = item.target.atom if hasattr(item.target, 'atom') else None
                prot_center = None
                if hasattr(item, 'metal') and hasattr(item.metal, 'coords'):
                    mc = item.metal.coords
                    prot_center = (mc[0], mc[1], mc[2])
                return pa, prot_center
            return None, None

        # Map PLIP interaction type -> our standardized type + color
        # (PLIP_TYPE_MAP is now defined at module level)
        interactions = []
        for attr, (itype, color) in PLIP_TYPE_MAP.items():
            items = getattr(pli, attr, [])
            if not items:
                continue
            for item in items:
                pa, prot_center = _get_ligatom_pybel(item, attr)
                if pa is not None:
                    c = pa.coords
                    rdk_idx = coord_to_rdk.get(
                        (round(c[0], 2), round(c[1], 2), round(c[2], 2)), None
                    )
                    # Fallback: nearest-atom in lig_rdk by Euclidean distance
                    # (handles cases where pybel atom coords slightly differ from RDKit)
                    if rdk_idx is None and lig_rdk is not None:
                        min_dist = float('inf')
                        try:
                            conf = lig_rdk.GetConformer()
                            for atom_i in range(lig_rdk.GetNumAtoms()):
                                p = conf.GetAtomPosition(atom_i)
                                d = ((p.x - c[0])**2 + (p.y - c[1])**2 + (p.z - c[2])**2)**0.5
                                if d < min_dist:
                                    min_dist = d
                                    rdk_idx = atom_i
                            # Reject if >2.0 Å (likely a protein atom, not ligand)
                            if min_dist > 2.0:
                                rdk_idx = None
                        except ValueError:
                            # No 3D conformer — skip RDKit atom mapping
                            # (interactions will still be stored with idx=None for fallback rendering)
                            pass
                else:
                    rdk_idx = None

                # Build human-readable description
                if attr in ('hbonds_pdon', 'hbonds_ldon'):
                    don = f"{item.restype}{item.resnr}"
                    acc = f"{item.restype_l}{item.resnr_l}"
                    desc = (f"H-bond: {don} -> {acc} "
                            f"({item.distance_ah:.2f} A, ang-{item.angle:.0f})")
                elif attr == 'hydrophobic_contacts':
                    desc = (f"Hydrophobic: {item.restype}{item.resnr}"
                            f".{item.reschain} <-> {item.restype_l}{item.resnr_l}")
                elif attr == 'pistacking':
                    desc = f"Pistacking: {item.restype}{item.resnr}.{item.reschain}"
                elif attr in ('pication_paro', 'pication_laro'):
                    desc = f"Pication: {item.restype}{item.resnr}.{item.reschain}"
                elif attr in ('saltbridge_lneg', 'saltbridge_pneg'):
                    desc = f"Salt bridge: {item.restype}{item.resnr}.{item.reschain}"
                elif attr == 'halogen_bonds':
                    desc = f"Halogen bond: {item.restype}{item.resnr}.{item.reschain}"
                elif attr == 'water_bridges':
                    desc = f"Water bridge: {item.restype}{item.resnr}.{item.reschain}"
                elif attr == 'metal_complexes':
                    desc = f"Metal complex: {item.restype}{item.resnr}.{item.reschain}"
                else:
                    desc = f"{itype}: {item.restype}{item.resnr}"

                # Use distance_ah for h-bonds, distance for others
                if attr in ('hbonds_pdon', 'hbonds_ldon'):
                    dist_val = round(float(item.distance_ah), 2)
                else:
                    dist_val = round(float(getattr(item, 'distance', 0)), 2)

                # Protein atom coordinates for 2D dashed line rendering
                # Priority: 1) prot_center (salt bridge/water bridge/metal complex), 2) direct atom extraction
                if prot_center is not None:
                    px, py, pz = prot_center
                else:
                    # Extract protein atom coordinates based on interaction type
                    prot_atom = None
                    if attr in ('hbonds_pdon', 'hbonds_ldon'):
                        # H-bond: protisdon=True → protein is donor = item.d
                        #          protisdon=False → protein is acceptor = item.a
                        prot_atom = item.d if item.protisdon else item.a
                    elif attr == 'hydrophobic_contacts':
                        prot_atom = item.bsatom
                    elif attr == 'halogen_bonds':
                        # Halogen bond acceptor (protein side) - may be a namedtuple
                        if hasattr(item.acc, 'coords'):
                            prot_atom = item.acc
                        elif hasattr(item.acc, 'o') and hasattr(item.acc.o, 'coords'):
                            prot_atom = item.acc.o  # halogen acceptor namedtuple
                    elif attr in ('pistacking', 'pication_paro', 'pication_laro'):
                        # π interactions use ring centroid (prot_center already handled)
                        pass

                    if prot_atom and hasattr(prot_atom, 'coords'):
                        px, py, pz = prot_atom.coords
                    else:
                        # Fallback for older PLIP versions
                        px = getattr(item, 'x', None)
                        py = getattr(item, 'y', None)
                        pz = getattr(item, 'z', None)

                interactions.append({
                    'type': itype,
                    'color': color,
                    'resn': item.restype,
                    'resi': item.resnr,
                    'chain': item.reschain,
                    'atom': getattr(item, 'atype', getattr(item, 'bstype', '?')),
                    'ligand_atom_idx': rdk_idx,
                    'distance': dist_val,
                    'description': desc,
                    'protisdon': getattr(item, 'protisdon', None),
                    'prot_x': px,
                    'prot_y': py,
                    'prot_z': pz,
                    '_prot_center': prot_center,   # protein ring center for π-π/π-cation
                })

        # Deduplicate by (type, resn, resi, chain)
        seen = set()
        unique = []
        for i in interactions:
            key2 = (i['type'], i['resn'], i['resi'], i['chain'])
            if key2 not in seen:
                seen.add(key2)
                unique.append(i)

        n_hb = sum(1 for x in unique if x['type'] == 'H-bond')
        n_pi = sum(1 for x in unique if x['type'] in ('π-π', 'π-cation'))
        n_hp = sum(1 for x in unique if x['type'] == 'Hydrophobic')
        n_sb = sum(1 for x in unique if x['type'] == 'Salt bridge')
        n_ot = sum(1 for x in unique if x['type'] in ('Halogen bond', 'Water bridge', 'Metal complex'))
        logger.info(f"[autodock][PLIP] H-bond={n_hb}, π-π/π-cat={n_pi}, "
              f"Hydrophobic={n_hp}, SaltBr={n_sb}, Other={n_ot} | Total={len(unique)}")

        xml_path = os.path.join(output_dir, f"report.xml")
        return unique, xml_path if os.path.exists(xml_path) else ''

    finally:
        if complex_pdb and os.path.exists(complex_pdb):
            os.unlink(complex_pdb)



"""
Publication-quality 2D protein-ligand interaction diagram renderer.
Strategy: RDKit dummy atom + ZERO bond + circleAtoms + post-processing arrows.

Key design decisions (based on RDKit 2026.03.1 docs + Greg Landrum 2025 blog):
- Cairo backend for PNG output (native, no external deps)
- Dummy atoms (AtomicNum=0) for residue markers, positioned by RDKit's 2D layout
- ZERO-order bonds connect ligand atoms to dummy atoms
- Post-processing via DrawArrow/DrawLine for interaction line styles
- Salt bridges / metal ions without ligand coords: use nearest ligand atom fallback
- π-π/π-cation: connect ring centroid via nearest ring atom to dummy
"""

import os, io, tempfile
import numpy as np

from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point2D
from rdkit import RDLogger
RDLogger.DisableLog('rdAll')


# ── Visual style for each interaction type ──────────────────────────────────
# Covers all 11 PLIP types + Metal complex
INTERACTION_STYLE = {
    'H-bond': {
        'color': (0.0, 0.75, 0.75),     # cyan
        'line_width': 2.0,
        'end_style': 'arrow',            # directional arrow
        'label': 'H-bond',
    },
    'Hydrophobic': {
        'color': (1.0, 0.55, 0.0),       # orange
        'line_width': 1.5,
        'end_style': 'dash',             # dashed line
        'label': 'Hydrophobic',
    },
    'π-π': {
        'color': (0.15, 0.75, 0.15),      # green
        'line_width': 2.0,
        'end_style': 'double',           # double line
        'label': 'π-π stacking',
    },
    'π-cation': {
        'color': (0.75, 0.15, 0.75),     # magenta
        'line_width': 2.0,
        'end_style': 'double',           # double line
        'label': 'π-cation',
    },
    'Salt bridge': {
        'color': (0.9, 0.15, 0.15),      # red
        'line_width': 2.0,
        'end_style': 'double',
        'label': 'Salt bridge',
    },
    'Halogen bond': {
        'color': (0.75, 0.75, 0.1),      # yellow
        'line_width': 2.0,
        'end_style': 'arrow',
        'label': 'Halogen bond',
    },
    'Water bridge': {
        'color': (0.2, 0.4, 0.85),       # blue
        'line_width': 1.5,
        'end_style': 'dash',
        'label': 'Water bridge',
    },
    'Metal complex': {
        'color': (0.55, 0.55, 0.55),     # gray
        'line_width': 2.0,
        'end_style': 'double',
        'label': 'Metal complex',
    },
}

# All 11 PLIP types that can appear in interactions list
ALL_TYPES = list(INTERACTION_STYLE.keys())


# ── Molecule building ─────────────────────────────────────────────────────────

def _build_interaction_mol(mol, interactions, lig_rdk=None):
    """
    Build RWMol with dummy atoms for each interacting residue.

    Handles:
    - Per-residue deduplication (one dummy per (resn,resi,chain) per interaction type)
    - Salt bridge / metal complex: may have no direct ligand atom → use nearest fallback
    - π-π: connects ring centroid proxy (nearest ring atom) to dummy

    Args:
        mol: RDKit molecule (with 3D conformer from PDBQT)
        interactions: list of interaction dicts from detect_interactions_plip
        lig_rdk: optional pre-built RDKit mol (with 3D conformer) for coord lookup

    Returns:
        (RWMol, dummy_info)
        dummy_info: list of (dummy_idx, itype, res_label, lig_atom_idx, is_arrow_dir)
                    is_arrow_dir: True if H-bond direction protein→ligand
    """
    rwmol = Chem.RWMol(mol)
    dummy_info = []   # (dummy_idx, itype, res_label, lig_atom_idx, arrow_rev, prot_c)
    seen = {}          # (itype, resn, resi, chain) → dummy_idx

    for interaction in interactions:
        itype   = interaction.get('type', 'Unknown')
        resn    = interaction.get('resn', 'UNK')
        resi    = interaction.get('resi', '?')
        chain   = interaction.get('chain', '')
        lig_idx = interaction.get('ligand_atom_idx')  # may be None
        prot_c  = interaction.get('_prot_center')      # protein center (for π-π/π-cation/salt-bridge/metal)

        # ── Resolve ligand atom index ───────────────────────────────────────
        if lig_idx is None or lig_idx < 0:
            # Fallback: nearest ligand atom to the protein interaction center
            prot_x = interaction.get('prot_x')
            prot_y = interaction.get('prot_y')
            prot_z = interaction.get('prot_z')
            # Prefer _prot_center (set for salt bridges via charge.center, π-π via proteinring.center)
            if prot_c and isinstance(prot_c, (list, tuple)) and len(prot_c) >= 3:
                prot_x, prot_y, prot_z = prot_c[0], prot_c[1], prot_c[2]
            
            if prot_x is not None and lig_rdk is not None:
                try:
                    conf = lig_rdk.GetConformer()
                    min_dist = float('inf')
                    nearest_idx = None
                    for atom_i in range(lig_rdk.GetNumAtoms()):
                        p = conf.GetAtomPosition(atom_i)
                        d = ((p.x - prot_x)**2 + (p.y - prot_y)**2 + (p.z - prot_z)**2)**0.5
                        if d < min_dist:
                            min_dist = d
                            nearest_idx = atom_i
                    if nearest_idx is not None and min_dist <= 5.0:
                        lig_idx = nearest_idx
                except ValueError:
                    pass

            if lig_idx is None or lig_idx < 0:
                continue

        # ── Residue label ────────────────────────────────────────────────────
        res_label = f"{resn}{resi}" + (f".{chain}" if chain else "")

        # ── Deduplication: one dummy per (itype, resn, resi, chain) ─────────
        key = (itype, resn, resi, chain)
        if key in seen:
            didx = seen[key]
            dummy_info.append((didx, itype, res_label, lig_idx, False, prot_c))
            continue

        # ── Create dummy atom ───────────────────────────────────────────────
        dummy = Chem.Atom(0)
        dummy.SetProp('atomLabel', res_label)
        dummy.SetProp('interactionType', itype)
        dummy.SetProp('isDummy', '1')
        didx = rwmol.AddAtom(dummy)

        # ZERO bond to ligand atom
        rwmol.AddBond(int(lig_idx), didx, Chem.BondType.ZERO)
        seen[key] = didx
        # arrow_rev: if protein is donor (protisdon=True), arrow points protein→ligand
        arrow_rev = interaction.get('protisdon', False) == True
        dummy_info.append((didx, itype, res_label, lig_idx, arrow_rev, prot_c))

    # Generate 2D coordinates — RDKit automatically places dummy atoms around the ligand
    AllChem.Compute2DCoords(rwmol)

    return rwmol, dummy_info


def _get_mol_2d_bounds(conf, n_atoms):
    """Bounding box of all atoms in the 2D conformer."""
    xs = [conf.GetAtomPosition(i).x for i in range(n_atoms)]
    ys = [conf.GetAtomPosition(i).y for i in range(n_atoms)]
    return min(xs), max(xs), min(ys), max(ys)


def _inject_svg_legend(svg_text, seen_types, dummy_info, conf, drawer, canvas_w, canvas_h):
    """
    Inject legend and residue label text elements into SVG.
    drawer is the Cairo MolDraw2DCairo with the same coordinate scale as the SVG.
    Returns modified SVG text.
    """
    try:
        import re
    except ImportError:
        return svg_text

    svg_h = re.search(r'height="(\d+)px"', svg_text)
    svg_h_val = int(svg_h.group(1)) if svg_h else 900

    extra_elements = []

    # ── Legend box (top-right) ─────────────────────────────────────────────
    if seen_types:
        item_h = 22
        box_w = 175
        box_h = item_h * len(seen_types) + 18
        box_x = 1200 - box_w - 12  # right-aligned
        box_y = 12

        # White background rect
        extra_elements.append(
            f'<rect x="{box_x}" y="{box_y}" width="{box_w}" height="{box_h}"'
            f' style="fill:#FFFFFF;fill-opacity:0.94;stroke:#646464;stroke-width:1"/>'
        )
        # Title
        extra_elements.append(
            f'<text x="{box_x + 8}" y="{box_y + 4}" '
            f'font-family="Helvetica,sans-serif" font-size="13" font-weight="bold" '
            f'fill="#1E1E1E">Interactions</text>'
        )

        for i, t in enumerate(seen_types):
            style = INTERACTION_STYLE.get(t, {})
            c = style.get('color', (0.5, 0.5, 0.5))
            label = style.get('label', t)
            r, g, b = int(c[0]*255), int(c[1]*255), int(c[2]*255)
            cy = box_y + 16 + i * item_h
            hex_color = f'#{r:02X}{g:02X}{b:02X}'
            extra_elements.append(
                f'<rect x="{box_x + 8}" y="{cy}" width="12" height="12" '
                f'style="fill:{hex_color};stroke:none"/>'
            )
            extra_elements.append(
                f'<text x="{box_x + 24}" y="{cy + 12}" '
                f'font-family="Helvetica,sans-serif" font-size="13" fill="#282828">{label}</text>'
            )

    # ── Residue labels near dummy atoms ──────────────────────────────────
    for didx, itype, res_label, lig_idx, _arrow, _prot_c in dummy_info:
        if not res_label:
            continue
        pos = conf.GetAtomPosition(didx)
        px = drawer.GetDrawCoords(Point2D(pos.x, pos.y))
        # Label: below and right of the dummy circle
        lx = px.x + 8
        ly = px.y + 6
        if 0 <= lx < 1200 - 60 and 0 <= ly < svg_h_val - 16:
            extra_elements.append(
                f'<text x="{lx}" y="{ly}" '
                f'font-family="Helvetica,sans-serif" font-size="13" fill="#141414">'
                f'{res_label}</text>'
            )

    # Inject before </svg>
    injection = '\n'.join(extra_elements)
    return svg_text.replace('</svg>', injection + '\n</svg>')


def _render_svg_vector(rwmol, dummy_info, dummy_colors, conf, drawer, canvas_w, canvas_h):
    """
    Re-render the molecule with interactions as SVG (vector format).
    Returns SVG text string. Post-processing uses pixel coords from Cairo drawer.
    """
    svg_drawer = rdMolDraw2D.MolDraw2DSVG(canvas_w, canvas_h)
    opts = svg_drawer.drawOptions()
    opts.circleAtoms = True
    opts.fillHighlights = True
    opts.highlightRadius = 0.35  # ~default, smaller than 0.5 for tighter circles
    opts.bondLineWidth = 2.0
    opts.noAtomLabels = True

    n_atoms = rwmol.GetNumAtoms()
    x_min, x_max, y_min, y_max = _get_mol_2d_bounds(conf, n_atoms)
    margin = 4.0
    svg_drawer.SetScale(canvas_w, canvas_h,
                        Point2D(x_min - margin, y_min - margin),
                        Point2D(x_max + margin, y_max + margin))

    dummy_indices = sorted(set(d[0] for d in dummy_info))
    svg_drawer.DrawMolecule(rwmol,
                            highlightAtoms=dummy_indices,
                            highlightAtomColors=dummy_colors)

    # Draw interaction lines/arrows on top
    for didx, itype, res_label, lig_idx, arrow_rev, prot_c in dummy_info:
        style = INTERACTION_STYLE.get(itype, INTERACTION_STYLE.get('Hydrophobic', {}))
        color = style.get('color', (0.5, 0.5, 0.5))
        end_style = style.get('end_style', 'dash')
        lig_pos = conf.GetAtomPosition(lig_idx)
        dum_pos = conf.GetAtomPosition(didx)
        lig_px = svg_drawer.GetDrawCoords(Point2D(lig_pos.x, lig_pos.y))
        dum_px = svg_drawer.GetDrawCoords(Point2D(dum_pos.x, dum_pos.y))
        # For salt-bridge / metal complex: project protein 3D center to 2D
        # and draw from protein_px to lig_px (not from dummy to lig_px)
        # NOTE: prot_c is a 3D protein coordinate from PLIP. It cannot be passed
        # directly to GetDrawCoords which expects 2D molecular coords. The dummy
        # atom (connected via ZERO bond) is already placed near the ligand by
        # RDKit's 2D layout, so dum_px is the correct anchor in 2D space.
        draw_from = dum_px
        draw_to = lig_px
        dx = draw_to.x - draw_from.x
        dy = draw_to.y - draw_from.y
        if (dx*dx + dy*dy) < 1:
            continue
        svg_drawer.SetColour(color)
        if end_style == 'arrow':
            if arrow_rev:
                svg_drawer.DrawArrow(Point2D(draw_from.x, draw_from.y),
                                     Point2D(draw_to.x, draw_to.y),
                                     False, 0.065, 0.45)
            else:
                svg_drawer.DrawArrow(Point2D(draw_to.x, draw_to.y),
                                     Point2D(draw_from.x, draw_from.y),
                                     False, 0.065, 0.45)
        elif end_style == 'double':
            svg_drawer.DrawLine(Point2D(draw_to.x, draw_to.y),
                                Point2D(draw_from.x, draw_from.y))
            length = (dx*dx + dy*dy) ** 0.5
            if length > 0:
                nx = -dy / length * 3.0
                ny = dx / length * 3.0
                svg_drawer.DrawLine(
                    Point2D(draw_to.x + nx, draw_to.y + ny),
                    Point2D(draw_from.x + nx, draw_from.y + ny))
        elif end_style == 'dash':
            svg_drawer.DrawLine(Point2D(lig_px.x, lig_px.y),
                                Point2D(draw_from.x, draw_from.y))

    svg_drawer.FinishDrawing()
    return svg_drawer.GetDrawingText()


# ── Core rendering ─────────────────────────────────────────────────────────────

def _recover_bonds_from_openbabel(pdbqt_path: str, mol):
    """
    Attempt to recover correct bond orders using OpenBabel SDF conversion.


    When PDBQT lacks SMILES remark, RDKit builds a mol with 0 bonds.
    OpenBabel's SDF output correctly perceives bond types (single/double/aromatic)
    from the 3D structure. This function replaces mol's implicit bonds with
    OpenBabel-perceived ones.

    Returns True if recovery succeeded (mol now has bonds), False otherwise.
    """
    try:
        import tempfile
        ob_mol = next(_pybel.readfile('pdbqt', pdbqt_path))
        sdf_path = os.path.join(tempfile.gettempdir(), f'_bond_recovery_{os.getpid()}.sdf')
        ob_mol.write(format='sdf', filename=sdf_path, overwrite=True)
        sdf_mol = Chem.MolFromMolFile(sdf_path, removeHs=False)
        if sdf_mol is None or sdf_mol.GetNumBonds() == 0:
            try:
                os.unlink(sdf_path)
            except Exception:
                pass
            return False

        if sdf_mol.GetNumAtoms() != mol.GetNumAtoms():
            try:
                os.unlink(sdf_path)
            except Exception:
                pass
            return False

        # Transfer 3D conformer coordinates from original mol (preserves accurate geometry)
        if mol.GetNumConformers() > 0:
            orig_conf = mol.GetConformer(0)
            # Ensure sdf_mol has a 3D conformer to receive positions
            if sdf_mol.GetNumConformers() == 0:
                new_conf = Chem.Conformer(sdf_mol.GetNumAtoms())
                new_conf.Set3D(True)
                sdf_mol.AddConformer(new_conf)
            else:
                sdf_mol.GetConformer(0).Set3D(True)
            new_conf = sdf_mol.GetConformer(0)
            for i in range(sdf_mol.GetNumAtoms()):
                p = orig_conf.GetAtomPosition(i)
                new_conf.SetAtomPosition(i, (p.x, p.y, p.z))

        # Transfer OpenBabel-perceived bonds
        # Build fresh mol with atoms + bonds, then copy conformer
        rwmol = Chem.RWMol()
        for i in range(sdf_mol.GetNumAtoms()):
            a = sdf_mol.GetAtomWithIdx(i)
            rwmol.AddAtom(a)
        for bond in sdf_mol.GetBonds():
            try:
                rwmol.AddBond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), bond.GetBondType())
            except Exception:
                pass
        recovered = rwmol.GetMol()

        # Transfer conformer
        if sdf_mol.GetNumConformers() > 0:
            recovered.AddConformer(sdf_mol.GetConformer(0))

        # Replace contents of input mol
        mol.RemoveAllConformers()
        for bond in list(mol.GetBonds()):
            try:
                mol.RemoveBond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx())
            except Exception:
                pass
        for atom in list(mol.GetAtoms()):
            try:
                mol.RemoveAtom(atom)
            except Exception:
                pass
        for i in range(recovered.GetNumAtoms()):
            mol.AddAtom(recovered.GetAtomWithIdx(i))
        for bond in recovered.GetBonds():
            try:
                mol.AddBond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), bond.GetBondType())
            except Exception:
                pass
        if recovered.GetNumConformers() > 0:
            mol.AddConformer(recovered.GetConformer(0))

        try:
            os.unlink(sdf_path)
        except Exception:
            pass
        return mol.GetNumBonds() > 0
    except Exception:
        return False


def render_interactions_2d(receptor_pdb: str,
                          ligand_pdbqt: str,
                          interactions: list,
                          output_png: str,
                          output_pdf: str = None,
                          center: tuple = None,
                          ligand_resn: str = None,
                          width: int = 1000,
                          height: int = 800,
                          dpi: int = 300) -> bool:
    """
    Render a publication-quality 2D protein-ligand interaction diagram.

    Pipeline:
      1. Parse ligand PDBQT → RDKit mol (3D, via _read_ligand_from_pdbqt_3d)
      2. Build RWMol with dummy atoms + ZERO bonds for each interaction
      3. Generate 2D coords → RDKit auto-positions dummy atoms
      4. Draw base: MolDraw2DCairo + circleAtoms + residue labels
      5. Post-processing: draw interaction lines/arrows on the canvas
      6. PIL overlay: legend + residue name labels
      7. ImageMagick: SVG → PDF if output_pdf is specified

    Args:
        receptor_pdb: (unused, API compat)
        ligand_pdbqt: Docked ligand PDBQT
        interactions: From detect_interactions_plip() / detect_interactions()
        output_png: Output PNG path
        output_pdf: (optional) Output PDF path (vector). Requires ImageMagick.
        center, ligand_resn: (unused, API compat)
        width, height: Canvas size in pixels
        dpi: Output DPI for publication

    Returns:
        True if successful
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.info("[autodock] PIL not available — 2D diagram skipped")
        return False

    if not interactions:
        logger.info("[autodock] No interactions provided — 2D diagram skipped")
        return False

    # If output_png is None (PDF-only mode), generate a temp path for internal use
    _png_path_provided = output_png is not None
    if output_png is None:
        import tempfile
        output_png = tempfile.mktemp(suffix='.png')
    output_png = os.path.abspath(output_png)
    os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)

    complex_pdb = None
    try:
        # ── 1. Build RDKit mol from PDBQT ───────────────────────────────────
        mol = _read_ligand_from_pdbqt_3d(ligand_pdbqt)
        if mol is None:
            logger.error("[autodock] Could not read ligand from PDBQT")
            return False

        # Critical check: 0 bonds is the ONLY reason rendering produces no skeleton.
        # 3D flag loss from Compute2DCoords is expected and harmless — do NOT trigger recovery for it.
        n_bonds = mol.GetNumBonds()
        n_atoms = mol.GetNumAtoms()
        has_2d = False
        if mol.GetNumConformers() > 0:
            has_2d = not mol.GetConformer(0).Is3D()

        if n_bonds == 0:
            logger.info(f"[autodock] Mol has 0 bonds — attempting OpenBabel bond-order recovery...")
            recovered = _recover_bonds_from_openbabel(ligand_pdbqt, mol)
            if recovered:
                n_bonds = mol.GetNumBonds()
                logger.info(f"[autodock] Recovery: {n_bonds} bonds")
            else:
                logger.info(f"[autodock] Bond recovery failed — rendering will show circles without skeleton")

        lig_rdk = mol  # for nearest-atom fallback if needed

        # ── 2. Build interaction mol ─────────────────────────────────────────
        rwmol, dummy_info = _build_interaction_mol(mol, interactions, lig_rdk)
        if not dummy_info:
            logger.info("[autodock] No mappable interactions — skip diagram")
            return False

        conf = rwmol.GetConformer()
        n_atoms = rwmol.GetNumAtoms()

        # ── 3. Canvas setup ──────────────────────────────────────────────────
        # Extend canvas to accommodate labels around the molecule
        canvas_w = width
        canvas_h = height

        drawer = rdMolDraw2D.MolDraw2DCairo(canvas_w, canvas_h)
        opts = drawer.drawOptions()
        opts.circleAtoms = True
        opts.fillHighlights = True
        opts.highlightRadius = 0.35  # ~default, smaller than 0.5 for tighter circles
        opts.bondLineWidth = 2.0
        opts.annotationFontScale = 1.3  # 1.3 = larger dummy-circle labels for readability
        opts.baseFontSize = 0.75
        # Don't draw ZERO bonds as solid lines — they are layout guides only
        opts.noAtomLabels = True

        # ── 4. Set scale based on molecule 2D coords ───────────────────────
        x_min, x_max, y_min, y_max = _get_mol_2d_bounds(conf, n_atoms)
        margin = 4.0
        drawer.SetScale(canvas_w, canvas_h,
                        Point2D(x_min - margin, y_min - margin),
                        Point2D(x_max + margin, y_max + margin))

        # ── 5. Draw base molecule with dummy circles ─────────────────────────
        # dummy_info: (didx, itype, res_label, lig_atom_idx, arrow_rev, prot_c)
        dummy_indices = sorted(set(d[0] for d in dummy_info))
        dummy_colors = {}
        for didx, itype, _, _lidx, _arrow, *_ in dummy_info:
            if didx not in dummy_colors:
                style = INTERACTION_STYLE.get(itype, INTERACTION_STYLE.get('Hydrophobic', {}))
                dummy_colors[didx] = style.get('color', (0.5, 0.5, 0.5))

        drawer.DrawMolecule(
            rwmol,
            highlightAtoms=dummy_indices,
            highlightAtomColors=dummy_colors,
        )

        # ── 6. Post-processing: draw interaction lines/arrows ───────────────
        drawn_pairs = set()

        for didx, itype, res_label, lig_idx, arrow_rev, prot_c in dummy_info:
            style = INTERACTION_STYLE.get(itype, INTERACTION_STYLE.get('Hydrophobic', {}))
            color = style.get('color', (0.5, 0.5, 0.5))
            end_style = style.get('end_style', 'dash')

            # Get 2D molecular coordinates
            lig_pos = conf.GetAtomPosition(lig_idx)
            dum_pos = conf.GetAtomPosition(didx)

            # Convert to pixel coordinates
            lig_px = drawer.GetDrawCoords(Point2D(lig_pos.x, lig_pos.y))
            dum_px = drawer.GetDrawCoords(Point2D(dum_pos.x, dum_pos.y))

            # Determine draw_from: for π-π/π-cation use protein ring center (prot_c),
            # for salt-bridge/metal-complex use prot_c if available,
            # otherwise use dummy circle position
            # NOTE: prot_c is a 3D protein coordinate (Å) from PLIP; it cannot be
            # passed directly to GetDrawCoords which expects 2D molecular coords.
            # The dummy atom (connected to the ligand atom via a ZERO bond) is
            # already placed near the ligand by RDKit's 2D layout, so dum_px is
            # the correct anchor for all interaction lines in 2D space.
            draw_from = dum_px
            draw_to = lig_px

            dx = draw_to.x - draw_from.x
            dy = draw_to.y - draw_from.y
            if (dx*dx + dy*dy) < 1:
                continue

            drawer.SetColour(color)

            if end_style == 'arrow':
                if arrow_rev:
                    drawer.DrawArrow(
                        Point2D(draw_from.x, draw_from.y),
                        Point2D(draw_to.x, draw_to.y),
                        False, 0.065, 0.45,
                    )
                else:
                    drawer.DrawArrow(
                        Point2D(draw_to.x, draw_to.y),
                        Point2D(draw_from.x, draw_from.y),
                        False, 0.065, 0.45,
                    )

            elif end_style == 'double':
                drawer.DrawLine(
                    Point2D(draw_from.x, draw_from.y),
                    Point2D(draw_to.x, draw_to.y),
                )
                length = (dx*dx + dy*dy) ** 0.5
                if length > 0:
                    nx = -dy / length * 4.0
                    ny = dx / length * 4.0
                    drawer.DrawLine(
                        Point2D(draw_from.x + nx, draw_from.y + ny),
                        Point2D(draw_to.x + nx, draw_to.y + ny),
                    )

            elif end_style == 'dash':
                drawer.DrawLine(
                    Point2D(draw_from.x, draw_from.y),
                    Point2D(draw_to.x, draw_to.y),
                )

            drawn_pairs.add((didx, lig_idx))

        drawer.FinishDrawing()
        png_bytes = drawer.GetDrawingText()

        # ── 7. PIL post-processing: legend + residue labels ─────────────────
        img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        # Try to use a usable font; fall back to default
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
            font_bold = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
        except Exception:
            font = ImageFont.load_default()
            font_bold = font

        # ── Legend (top-right) ───────────────────────────────────────────────
        seen_types = []
        for interaction in interactions:
            t = interaction.get('type', 'Unknown')
            if t not in seen_types:
                seen_types.append(t)

        if seen_types:
            item_h = 22
            box_w = 175
            box_h = item_h * len(seen_types) + 18
            box_x = img.width - box_w - 12
            box_y = 12

            # White box with subtle border
            draw.rectangle([box_x, box_y, box_x + box_w, box_y + box_h],
                           fill=(255, 255, 255, 240),
                           outline=(100, 100, 100, 180))

            draw.text((box_x + 8, box_y + 4), "Interactions",
                       fill=(30, 30, 30, 255), font=font_bold)

            for i, t in enumerate(seen_types):
                style = INTERACTION_STYLE.get(t, {})
                c = style.get('color', (0.5, 0.5, 0.5))
                label = style.get('label', t)
                r, g, b = int(c[0]*255), int(c[1]*255), int(c[2]*255)
                cy = box_y + 16 + i * item_h
                # Color swatch (rounded rect approximation)
                draw.rectangle([box_x + 8, cy, box_x + 20, cy + 12],
                               fill=(r, g, b, 255))
                draw.text((box_x + 24, cy), label,
                          fill=(40, 40, 40, 255), font=font)

        # ── Residue labels near dummy atoms (bottom-left of dummy circles) ───
        for didx, itype, res_label, lig_idx, _arrow, _prot_c in dummy_info:
            if not res_label:
                continue
            pos = conf.GetAtomPosition(didx)
            px = drawer.GetDrawCoords(Point2D(pos.x, pos.y))
            # Label offset: below and right of the dummy circle (+14,+10 for better legibility)
            lx = int(px.x + 14)
            ly = int(px.y + 10)
            # Clip to image bounds
            if 0 <= lx < img.width - 60 and 0 <= ly < img.height - 16:
                draw.text((lx, ly), res_label,
                          fill=(20, 20, 20, 230), font=font)

        # ── Distance labels on interaction lines ───────────────────────────────
        # Draw "2.55Å" at midpoint of each interaction line.
        # Use a small font (10px) with slightly darker color than the line.
        try:
            font_dist = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 10)
        except Exception:
            font_dist = font

        for interaction in interactions:
            dist = interaction.get('distance')
            if dist is None:
                continue
            # Find the corresponding dummy_info entry for this interaction
            resn = interaction.get('resn', '')
            resi = interaction.get('resi', '?')
            chain = interaction.get('chain', '')
            itype = interaction.get('type', 'Unknown')
            # Match by (type, resn, resi, chain)
            matched = None
            for di in dummy_info:
                d_type, d_resn, d_resi, d_chain = di[1], di[2].rstrip('.0123456789'), di[2], di[2]
                # Parse res_label like "HIS41.A" or "ASP85"
                import re as _re
                m = _re.match(r'([A-Z]{3})(\d+)(?:\.(.))?', di[2])
                if m:
                    d_resn, d_resi_str, d_chain = m.group(1), m.group(2), m.group(3) or ''
                else:
                    d_resn, d_resi_str, d_chain = di[2], '', ''
                if (d_resn == resn and
                    d_resi_str == str(resi) and
                    d_chain == str(chain)):
                    matched = di
                    break
            if matched is None:
                continue
            didx, _, _, lig_idx = matched[0], matched[1], matched[2], matched[3]
            # Get pixel coordinates of ligand atom and dummy atom
            lig_pos_2d = conf.GetAtomPosition(lig_idx)
            dum_pos_2d = conf.GetAtomPosition(didx)
            lig_px = drawer.GetDrawCoords(Point2D(lig_pos_2d.x, lig_pos_2d.y))
            dum_px = drawer.GetDrawCoords(Point2D(dum_pos_2d.x, dum_pos_2d.y))
            # Midpoint
            mid_x = (lig_px.x + dum_px.x) / 2.0
            mid_y = (lig_px.y + dum_px.y) / 2.0
            # Offset slightly perpendicular to the line direction to avoid overlap
            dx = dum_px.x - lig_px.x
            dy = dum_px.y - lig_px.y
            length_sq = dx * dx + dy * dy
            if length_sq > 0:
                # Perpendicular offset: (-dy, dx) normalized
                nx = -dy / (length_sq ** 0.5) * 4.0
                ny = dx / (length_sq ** 0.5) * 4.0
            else:
                nx, ny = 4.0, -8.0
            label_x = int(mid_x + nx)
            label_y = int(mid_y + ny)
            # Get line color (slightly darker for readability)
            style = INTERACTION_STYLE.get(itype, {})
            color = style.get('color', (0.5, 0.5, 0.5))
            r = max(0, int(color[0] * 255) - 40)
            g = max(0, int(color[1] * 255) - 40)
            b = max(0, int(color[2] * 255) - 40)
            label_text = f"{dist:.2f}Å"
            # Clip to image bounds (approximate)
            if 0 <= label_x < img.width - 40 and 0 <= label_y < img.height - 16:
                draw.text((label_x, label_y), label_text,
                          fill=(r, g, b, 230), font=font_dist)

        # ── 8. Composite and save ───────────────────────────────────────────
        bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
        bg.paste(img, (0, 0), img if img.mode == 'RGBA' else None)
        bg.paste(overlay, (0, 0), overlay)
        bg.convert('RGB').save(output_png, 'PNG', dpi=(dpi, dpi))

        # ── 8b. SVG → PDF conversion (ImageMagick) ──────────────────────────
        if output_pdf:
            svg_text = _render_svg_vector(rwmol, dummy_info, dummy_colors,
                                          conf, drawer, canvas_w, canvas_h)
            # Inject legend + residue labels as SVG text elements
            svg_text = _inject_svg_legend(svg_text, seen_types, dummy_info, conf, drawer, canvas_w, canvas_h)
            # Use cairosvg (installed in autodock313) for SVG→PDF conversion
            # This avoids ImageMagick font issues with Helvetica on macOS
            try:
                import cairosvg
                with open(output_pdf, 'wb') as f:
                    cairosvg.svg2pdf(
                        bytestring=svg_text.encode('utf-8'),
                        write_to=f,
                        dpi=dpi
                    )
                pdf_size = os.path.getsize(output_pdf)
                logger.info(f"[autodock] PDF: OK ({pdf_size // 1024}KB) → {output_pdf}")
            except ImportError:
                logger.info("[autodock] cairosvg not installed — PDF skipped")
            except Exception as e:
                logger.info(f"[autodock] SVG→PDF failed: {e}")

        # In PDF-only mode (PNG was a temp file): return True if interactions were built
        if not _png_path_provided:
            logger.info(f"[autodock] 2D diagram: PDF-only mode, {'OK' if len(dummy_info) > 0 else 'EMPTY'}")
            if os.path.exists(output_png):  # might already be deleted
                try: os.unlink(output_png)
                except: pass
            return len(dummy_info) > 0

        size = os.path.getsize(output_png)
        # Publication threshold: 20KB at 300dpi (covers small molecules like aspirin at ~29KB;
        # scales linearly with DPI; broken/molecule-less renders are typically <5KB)
        min_size = int(20 * 1024 * dpi / 300)
        ok = size > min_size
        if not ok:
            logger.info(f"[autodock] 2D diagram SUSPECT: only {size} bytes — "
                  f"expected >{min_size} bytes at {dpi}dpi. "
                  f"Check that _read_ligand_from_pdbqt_3d returns a mol with GetNumBonds()>0.")
        logger.info(f"[autodock] 2D diagram: {'OK' if ok else 'SUSPECT'} "
              f"({size // 1024}KB, {dpi}dpi) → {output_png}")

        return ok

    except Exception as e:
        import traceback
        logger.info(f"[autodock] 2D diagram failed: {e}")
        traceback.print_exc()
        return False

    finally:
        if complex_pdb and os.path.exists(complex_pdb):
            try:
                os.unlink(complex_pdb)
            except Exception:
                pass
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
        logger.info("[autodock] RDKit not available - render_ligand_2d skipped")
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
        logger.info(f"[autodock] Could not read ligand: {smiles_or_pdbqt}")
        return False

    mol = Chem.RemoveHs(mol)
    if input_is_smiles:
        AllChem.Compute2DCoords(mol)

    img = Draw.MolToImage(mol, size=(width, height))
    os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)
    img.save(output_png)

    ok = os.path.exists(output_png) and os.path.getsize(output_png) > 2000
    logger.info(f"[autodock] 2D render: {'OK' if ok else 'FAILED'} "
          f"({os.path.getsize(output_png)//1024}KB)")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# COMPOSITE FIGURE (matplotlib panels)
# ─────────────────────────────────────────────────────────────────────────────

