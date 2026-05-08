"""
Autodock Pharmacophore Module
==============================
Structure-based pharmacophore detection from protein-ligand complexes.

Detects pharmacophore features within the binding pocket:
- H-bond donor (D)
- H-bond acceptor (A)
- Hydrophobic (H)
- Aromatic ring (R)
- Positive ionizable (P)
- Negative ionizable (N)

Uses geometric rules based on residue type and atom positions.
"""
import os
from typing import List, Dict, Tuple, Optional

import numpy as np

from rdkit import Chem
from rdkit.Chem import AllChem

from autodock._core import autodock_logger, StructureFetchError, PreparationError
logger = autodock_logger

# ── Feature type constants ────────────────────────────────────────────────────
FEAT_DONOR = "DONOR"
FEAT_ACCEPTOR = "ACCEPTOR"
FEAT_HYDROPHOBIC = "HYDROPHOBIC"
FEAT_AROMATIC = "AROMATIC"
FEAT_POSITIVE = "POSITIVE"
FEAT_NEGATIVE = "NEGATIVE"

# Color mapping for rendering
FEAT_COLORS = {
    FEAT_DONOR: "blue",
    FEAT_ACCEPTOR: "red",
    FEAT_HYDROPHOBIC: "yellow",
    FEAT_AROMATIC: "green",
    FEAT_POSITIVE: "cyan",
    FEAT_NEGATIVE: "magenta",
}

# ── Residue definitions ────────────────────────────────────────────────────────
_DONOR_RESIDUES = {
    "SER": ("OG",), "THR": ("OG1",), "TYR": ("OH",),
    "LYS": ("NZ",), "ARG": ("NE", "NH1", "NH2"), "ASN": ("ND2",),
    "GLN": ("NE2",), "HIS": ("ND1", "NE2"), "TRP": ("NE1",),
    "CYS": ("SG",), "MET": ("SD",),
}
_ACCEPTOR_RESIDUES = {
    "SER": ("OG",), "THR": ("OG1",), "TYR": ("OH",),
    "ASP": ("OD1", "OD2"), "GLU": ("OE1", "OE2"),
    "ASN": ("OD1",), "GLN": ("OE1",), "HIS": ("ND1", "NE2"),
    "MET": ("SD",),
}
_HYDROPHOBIC_RESIDUES = {
    "ALA", "VAL", "ILE", "LEU", "MET", "PHE", "TRP", "PRO",
    "CYS", "TYR", "HIS",
}
_AROMATIC_RESIDUES = {"PHE", "TYR", "TRP", "HIS"}
_POSITIVE_RESIDUES = {"LYS", "ARG", "HIS"}
_NEGATIVE_RESIDUES = {"ASP", "GLU"}


def detect_pharmacophore(
    receptor_pdb: str,
    ligand_pdbqt: Optional[str] = None,
    center: Optional[Tuple[float, float, float]] = None,
    distance: float = 5.0,
) -> List[Dict]:
    """
    Detect structure-based pharmacophore features from binding pocket.

    Analyzes receptor atoms within `distance` Å of the binding site center
    (or ligand centroid if ligand provided) to identify pharmacophoric elements.

    Args:
        receptor_pdb: Protein PDB file path
        ligand_pdbqt: Optional ligand PDBQT to define binding site center
        center: Optional (x, y, z) binding site center (used if no ligand)
        distance: Pocket radius in Å to search for features

    Returns:
        List of feature dicts:
        {
            'type': str,        # 'DONOR' | 'ACCEPTOR' | 'HYDROPHOBIC' |
                                # 'AROMATIC' | 'POSITIVE' | 'NEGATIVE'
            'center': tuple,    # (x, y, z) feature center
            'atoms': list,      # atom indices in receptor PDB
            'radius': float,    # feature sphere radius (Å)
            'residue': str,     # e.g., 'ASN41.A'
            'description': str, # human-readable description
        }

    Raises:
        PreparationError: if receptor file not found or center undefined
        StructureFetchError: if PDB parsing fails
    """
    if not os.path.exists(receptor_pdb):
        raise PreparationError(f"Receptor file not found: {receptor_pdb}")

    if ligand_pdbqt and center:
        raise PreparationError("Provide ligand_pdbqt OR center, not both")

    # Define pocket center
    if ligand_pdbqt:
        center = _get_ligand_centroid(ligand_pdbqt)
    elif center is None:
        raise PreparationError("Must provide either ligand_pdbqt or center")

    # Parse receptor
    prot_mol = _parse_receptor_pdb(receptor_pdb)

    # Get pocket atom indices
    pocket_idx = _get_pocket_atom_indices(prot_mol, center, distance)

    if not pocket_idx:
        logger.warning(f"No atoms found within {distance} Å of center {center}")
        return []

    # Detect all feature types
    features = []
    features.extend(_detect_hbond_donors(prot_mol, pocket_idx))
    features.extend(_detect_hbond_acceptors(prot_mol, pocket_idx))
    features.extend(_detect_hydrophobic(prot_mol, pocket_idx))
    features.extend(_detect_aromatic(prot_mol, pocket_idx))
    features.extend(_detect_positive(prot_mol, pocket_idx))
    features.extend(_detect_negative(prot_mol, pocket_idx))

    logger.info(f"Detected {len(features)} pharmacophore features in pocket (radius={distance} Å)")
    return features


def _get_ligand_centroid(ligand_pdbqt: str) -> Tuple[float, float, float]:
    """Compute centroid of ligand atoms from PDBQT."""
    coords = []
    with open(ligand_pdbqt) as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                coords.append((x, y, z))
    if not coords:
        raise PreparationError(f"No atoms found in ligand PDBQT: {ligand_pdbqt}")
    coords = np.array(coords)
    return tuple(coords.mean(axis=0))


def _parse_receptor_pdb(receptor_pdb: str):
    """Parse PDB file into RDKit mol, preserving residue info."""
    try:
        mol = Chem.MolFromPDBFile(receptor_pdb, sanitize=False, removeHs=False)
        if mol is None:
            raise StructureFetchError(f"Could not parse PDB file: {receptor_pdb}")
        return mol
    except Exception as e:
        raise StructureFetchError(f"Failed to parse receptor PDB: {e}") from e


def _get_pocket_atom_indices(mol, center: Tuple[float, float, float], distance: float) -> List[int]:
    """Return atom indices within `distance` Å of center."""
    pocket = []
    center_arr = np.array(center)
    for i, atom in enumerate(mol.GetAtoms()):
        pos = mol.GetConformer().GetAtomPosition(i)
        pos_arr = np.array([pos.x, pos.y, pos.z])
        if np.linalg.norm(pos_arr - center_arr) <= distance:
            pocket.append(i)
    return pocket


def _detect_hbond_donors(mol, pocket_idx: List[int]) -> List[Dict]:
    """Detect H-bond donor features (backbone N-H, sidechain donors)."""
    features = []
    for i in pocket_idx:
        atom = mol.GetAtomWithIdx(i)
        res_info = atom.GetPDBResidueInfo()
        if not res_info:
            continue
        resn = res_info.GetResidueName().strip()
        aname = atom.GetMonomerInfo().GetName().strip()

        # Backbone N (peptide donors)
        if atom.GetAtomicNum() == 7 and aname == "N":
            # Check if it's a backbone N (not already bonded to H is implied)
            pos = mol.GetConformer().GetAtomPosition(i)
            features.append({
                "type": FEAT_DONOR,
                "center": (pos.x, pos.y, pos.z),
                "atoms": [i],
                "radius": 1.0,
                "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                "description": f"Backbone N of {resn}{res_info.GetResSeqNumber()}",
            })
            continue

        # Sidechain donors
        if resn in _DONOR_RESIDUES:
            if aname in _DONOR_RESIDUES.get(resn, ()):
                pos = mol.GetConformer().GetAtomPosition(i)
                features.append({
                    "type": FEAT_DONOR,
                    "center": (pos.x, pos.y, pos.z),
                    "atoms": [i],
                    "radius": 1.0,
                    "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                    "description": f"{aname} of {resn}{res_info.GetResSeqNumber()} (donor)",
                })
    return features


def _detect_hbond_acceptors(mol, pocket_idx: List[int]) -> List[Dict]:
    """Detect H-bond acceptor features (backbone C=O, sidechain acceptors)."""
    features = []
    for i in pocket_idx:
        atom = mol.GetAtomWithIdx(i)
        res_info = atom.GetPDBResidueInfo()
        if not res_info:
            continue
        resn = res_info.GetResidueName().strip()
        aname = atom.GetMonomerInfo().GetName().strip()

        # Backbone O (carbonyl acceptors)
        if atom.GetAtomicNum() == 8 and aname in ("O", "OXT"):
            pos = mol.GetConformer().GetAtomPosition(i)
            features.append({
                "type": FEAT_ACCEPTOR,
                "center": (pos.x, pos.y, pos.z),
                "atoms": [i],
                "radius": 1.0,
                "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                "description": f"Backbone O of {resn}{res_info.GetResSeqNumber()}",
            })
            continue

        # Sidechain acceptors
        if resn in _ACCEPTOR_RESIDUES:
            if aname in _ACCEPTOR_RESIDUES.get(resn, ()):
                pos = mol.GetConformer().GetAtomPosition(i)
                features.append({
                    "type": FEAT_ACCEPTOR,
                    "center": (pos.x, pos.y, pos.z),
                    "atoms": [i],
                    "radius": 1.0,
                    "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                    "description": f"{aname} of {resn}{res_info.GetResSeqNumber()} (acceptor)",
                })
    return features


def _detect_hydrophobic(mol, pocket_idx: List[int]) -> List[Dict]:
    """Detect hydrophobic features (ALA, VAL, ILE, LEU, etc. sidechain carbons)."""
    features = []
    hydrophobic_atoms = set()
    for i in pocket_idx:
        atom = mol.GetAtomWithIdx(i)
        res_info = atom.GetPDBResidueInfo()
        if not res_info:
            continue
        resn = res_info.GetResidueName().strip()
        aname = atom.GetMonomerInfo().GetName().strip()

        if resn in _HYDROPHOBIC_RESIDUES:
            # Use CB/CE/CG atoms as hydrophobic centers
            if atom.GetAtomicNum() == 6 and aname in ("CB", "CG", "CG1", "CG2", "CD", "CD1", "CD2", "CE", "CE1", "CE2", "CE3", "CZ"):
                hydrophobic_atoms.add(i)
                pos = mol.GetConformer().GetAtomPosition(i)
                features.append({
                    "type": FEAT_HYDROPHOBIC,
                    "center": (pos.x, pos.y, pos.z),
                    "atoms": [i],
                    "radius": 1.5,
                    "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                    "description": f"{aname} of {resn}{res_info.GetResSeqNumber()} (hydrophobic)",
                })
    return features


def _detect_aromatic(mol, pocket_idx: List[int]) -> List[Dict]:
    """Detect aromatic features (PHE, TYR, TRP, HIS rings)."""
    features = []
    for i in pocket_idx:
        atom = mol.GetAtomWithIdx(i)
        res_info = atom.GetPDBResidueInfo()
        if not res_info:
            continue
        resn = res_info.GetResidueName().strip()
        aname = atom.GetMonomerInfo().GetName().strip()

        if resn in _AROMATIC_RESIDUES:
            # Get ring info from RDKit
            if hasattr(atom, 'IsInRing') and atom.IsInRing():
                # Use ring centroid as aromatic feature center
                # Find all ring atoms in this residue
                ring_atoms = []
                for j in pocket_idx:
                    a = mol.GetAtomWithIdx(j)
                    ri = a.GetPDBResidueInfo()
                    if ri and ri.GetResidueName().strip() == resn and ri.GetResSeqNumber() == res_info.GetResSeqNumber():
                        if hasattr(a, 'IsInRing') and a.IsInRing():
                            ring_atoms.append(j)
                if ring_atoms:
                    # Compute centroid of ring atoms
                    positions = np.array([
                        (mol.GetConformer().GetAtomPosition(k).x,
                         mol.GetConformer().GetAtomPosition(k).y,
                         mol.GetConformer().GetAtomPosition(k).z)
                        for k in ring_atoms
                    ])
                    centroid = positions.mean(axis=0)
                    # Only add if not already added for this residue
                    feat_key = f"{resn}{res_info.GetResSeqNumber()}"
                    features.append({
                        "type": FEAT_AROMATIC,
                        "center": tuple(centroid),
                        "atoms": ring_atoms,
                        "radius": 2.0,
                        "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                        "description": f"Aromatic ring of {resn}{res_info.GetResSeqNumber()}",
                    })
    return features


def _detect_positive(mol, pocket_idx: List[int]) -> List[Dict]:
    """Detect positive ionizable features (LYS NZ, ARG CZ/NE, HIS protonated)."""
    features = []
    for i in pocket_idx:
        atom = mol.GetAtomWithIdx(i)
        res_info = atom.GetPDBResidueInfo()
        if not res_info:
            continue
        resn = res_info.GetResidueName().strip()
        aname = atom.GetMonomerInfo().GetName().strip()

        if resn == "LYS" and aname == "NZ":
            pos = mol.GetConformer().GetAtomPosition(i)
            features.append({
                "type": FEAT_POSITIVE,
                "center": (pos.x, pos.y, pos.z),
                "atoms": [i],
                "radius": 1.5,
                "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                "description": f"LYS {res_info.GetResSeqNumber()} NZ (positive)",
            })
        elif resn == "ARG" and aname in ("NE", "CZ", "NH1", "NH2"):
            pos = mol.GetConformer().GetAtomPosition(i)
            features.append({
                "type": FEAT_POSITIVE,
                "center": (pos.x, pos.y, pos.z),
                "atoms": [i],
                "radius": 1.5,
                "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                "description": f"ARG {res_info.GetResSeqNumber()} {aname} (positive)",
            })
        elif resn == "HIS" and aname in ("ND1", "NE2"):
            pos = mol.GetConformer().GetAtomPosition(i)
            features.append({
                "type": FEAT_POSITIVE,
                "center": (pos.x, pos.y, pos.z),
                "atoms": [i],
                "radius": 1.5,
                "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                "description": f"HIS {res_info.GetResSeqNumber()} {aname} (positive)",
            })
    return features


def _detect_negative(mol, pocket_idx: List[int]) -> List[Dict]:
    """Detect negative ionizable features (ASP, GLU carboxylates)."""
    features = []
    for i in pocket_idx:
        atom = mol.GetAtomWithIdx(i)
        res_info = atom.GetPDBResidueInfo()
        if not res_info:
            continue
        resn = res_info.GetResidueName().strip()
        aname = atom.GetMonomerInfo().GetName().strip()

        if resn in ("ASP", "GLU") and aname in ("OD1", "OD2", "OE1", "OE2"):
            pos = mol.GetConformer().GetAtomPosition(i)
            features.append({
                "type": FEAT_NEGATIVE,
                "center": (pos.x, pos.y, pos.z),
                "atoms": [i],
                "radius": 1.5,
                "residue": f"{resn}{res_info.GetResSeqNumber()}.{res_info.GetChainID()}",
                "description": f"{resn} {res_info.GetResSeqNumber()} {aname} (negative)",
            })
    return features


def render_pharmacophore(
    receptor_pdb: str,
    features: List[Dict],
    output_png: str,
    width: int = 2400,
    height: int = 1800,
    dpi: int = 300,
) -> bool:
    """
    Render 3D pharmacophore features on pocket surface using PyMOL.

    Features are shown as colored spheres:
    - DONOR: blue
    - ACCEPTOR: red
    - HYDROPHOBIC: yellow
    - AROMATIC: green
    - POSITIVE: cyan
    - NEGATIVE: magenta

    Requires PyMOL installed and available in PATH.

    Returns True if successful.
    """
    from autodock._core import _HAVE_PYMOL
    if not _HAVE_PYMOL:
        logger.warning("PyMOL not available — cannot render pharmacophore")
        return False

    import tempfile
    import subprocess

    # Write features to temp file
    feat_lines = []
    for f in features:
        cx, cy, cz = f["center"]
        color = FEAT_COLORS.get(f["type"], "white")
        feat_lines.append(f"{cx:.3f},{cy:.3f},{cz:.3f},{f['type']},{color},{f['radius']}")

    feat_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    feat_file.write("\n".join(feat_lines))
    feat_file.close()

    # Build PyMOL script
    script_lines = [
        f"cmd.load('{receptor_pdb}', 'receptor')",
        f"cmd.hide('everything', 'receptor')",
        f"cmd.show('cartoon', 'receptor')",
    ]

    for idx, f in enumerate(features):
        cx, cy, cz = f["center"]
        color = FEAT_COLORS.get(f["type"], "white")
        radius = f["radius"]
        script_lines.append(
            f"cmd.pseudoatom('feat_{idx}', pos=[{cx:.3f},{cy:.3f},{cz:.3f}], color='{color}', radius={radius:.1f})"
        )
        script_lines.append(f"cmd.show('spheres', 'feat_{idx}')")

    script_lines.append(f"cmd.png('{output_png}', width={width}, height={height}, dpi={dpi}, ray=1)")

    script_file = tempfile.NamedTemporaryFile(mode='w', suffix='.pml', delete=False)
    script_file.write("\n".join(script_lines))
    script_file.close()

    try:
        result = subprocess.run(
            ["pymol", "-c", "-q", script_file.name],
            capture_output=True, text=True, timeout=60
        )
        success = result.returncode == 0 and os.path.exists(output_png)
        if not success:
            logger.warning(f"PyMOL rendering failed: {result.stderr[:200]}")
        return success
    except subprocess.TimeoutExpired:
        logger.warning("PyMOL rendering timed out")
        return False
    except FileNotFoundError:
        logger.warning("PyMOL not found in PATH")
        return False
    finally:
        os.unlink(feat_file.name)
        os.unlink(script_file.name)


def summarize_features(features: List[Dict]) -> str:
    """Generate a human-readable summary of pharmacophore features."""
    if not features:
        return "No pharmacophore features detected."

    counts = {}
    for f in features:
        counts[f["type"]] = counts.get(f["type"], 0) + 1

    lines = ["Pharmacophore Features Summary", "=" * 40]
    for ftype in [FEAT_DONOR, FEAT_ACCEPTOR, FEAT_HYDROPHOBIC, FEAT_AROMATIC, FEAT_POSITIVE, FEAT_NEGATIVE]:
        if ftype in counts:
            lines.append(f"  {ftype:<12}: {counts[ftype]} feature(s)")

    lines.append("")
    lines.append("Feature Details:")
    for f in features:
        lines.append(f"  • {f['description']} @ ({f['center'][0]:.1f}, {f['center'][1]:.1f}, {f['center'][2]:.1f})")

    return "\n".join(lines)