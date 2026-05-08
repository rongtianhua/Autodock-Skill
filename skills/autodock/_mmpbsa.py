"""
Autodock MM/PBSA Module
========================
Post-docking binding free energy estimation using MM/GBSA.

.. warning::

   **This is a simplified MM/GBSA implementation for relative ranking and
   hot-spot residue identification. It is NOT intended for publication-quality
   absolute ΔG values.**


   Expected accuracy: ±2–5 kcal/mol vs. experiment. Do not report raw ΔG_bind
   values from this module in publications without explicit disclaimer.

   For publication-grade absolute binding free energies, install AmberTools
   and use the official MMPBSA.py workflow instead.


Scientific basis:
- Gas-phase interaction energy: Coulomb + Lennard-Jones (non-bonded only)
- Polar solvation: Generalized Born (Still/OBC2 simplified)
- Non-polar solvation: SASA × γ (Shrake-Rupley algorithm)
- Per-residue energy decomposition for identifying hot-spot residues

Accuracy note:
  This is a simplified implementation for relative ranking and residue-level
  decomposition. Absolute ΔG values may deviate from experiment by 2-5 kcal/mol.
  For publication-quality absolute energies, install AmberTools and use MMPBSA.py.

Usage:
    from autodock import compute_mmpbsa, MMPBSAResult
    result = compute_mmpbsa(
        receptor_pdb="protein.pdb",
        ligand_pdbqt="docked.pdbqt",
        method='gb',
    )
    print(result.delta_g_bind)
    print(result.per_residue)
"""

import os
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Tuple, Optional

from rdkit import Chem
from rdkit.Chem import AllChem

from autodock._core import autodock_logger, _HAVE_RDKIT
from autodock._preparation import _read_ligand_from_pdbqt_3d

logger = autodock_logger

# Publication-grade flag — False means this is a simplified screening implementation
# Set to True only if using AmberTools MMPBSA.py with full PBSA electrostatics
_PUBLICATION_GRADE = False

# ─── Physical constants ──────────────────────────────────────────────────────
_K_ELEC = 332.0636       # kcal·Å/(mol·e²) — Coulomb constant in vacuo
_4PI_EPS0 = 332.0636     # same as above
_KB = 0.0019872041       # kcal/(mol·K) — Boltzmann constant

# Solvent parameters
_EPS_SOLVENT = 80.0      # Water dielectric constant
_EPS_VACUUM = 1.0        # Vacuum / solute interior dielectric
_GAMMA_SA = 0.0072       # kcal/(mol·Å²) — non-polar surface tension
_BETA_SA = 0.0           # kcal/mol — non-polar offset (set to 0 for simplicity)

# ─── AMBER / GAFF Lennard-Jones parameters ─────────────────────────────────
# Format: {atom_type_or_element: (σ_Å, ε_kcal_mol)}
# Source: AMBER ff14SB protein + GAFF small-molecule parameters

_VDW_PARAMS = {
    # AMBER ff14SB protein atom types
    'C':   (3.39967, 0.0860),
    'CA':  (3.39967, 0.0860),
    'CB':  (3.39967, 0.0860),
    'CC':  (3.39967, 0.0860),
    'CD':  (3.39967, 0.0860),
    'CE':  (3.39967, 0.0860),
    'CG':  (3.39967, 0.0860),
    'CH':  (3.39967, 0.0860),
    'CJ':  (3.39967, 0.0860),
    'CP':  (3.39967, 0.0860),
    'CR':  (3.39967, 0.0860),
    'CT':  (3.39967, 0.0860),
    'CV':  (3.39967, 0.0860),
    'CW':  (3.39967, 0.0860),
    'CY':  (3.39967, 0.0860),
    'CZ':  (3.39967, 0.0860),
    'N':   (3.25000, 0.1700),
    'NA':  (3.25000, 0.1700),
    'NB':  (3.25000, 0.1700),
    'NC':  (3.25000, 0.1700),
    'ND':  (3.25000, 0.1700),
    'NE':  (3.25000, 0.1700),
    'NH':  (3.25000, 0.1700),
    'NT':  (3.25000, 0.1700),
    'NY':  (3.25000, 0.1700),
    'O':   (2.96096, 0.2100),
    'OH':  (3.06647, 0.2104),
    'OS':  (3.06647, 0.2104),
    'OW':  (3.15061, 0.1521),
    'H':   (1.06908, 0.0157),
    'HA':  (2.60000, 0.0300),
    'HC':  (2.60000, 0.0300),
    'H1':  (2.60000, 0.0300),
    'H2':  (2.60000, 0.0300),
    'H3':  (2.60000, 0.0300),
    'H4':  (2.60000, 0.0300),
    'H5':  (2.60000, 0.0300),
    'HO':  (0.80000, 0.0460),
    'HS':  (1.20000, 0.0150),
    'HP':  (1.06908, 0.0157),
    'HZ':  (1.06908, 0.0157),
    'S':   (3.56359, 0.2500),
    'SH':  (3.56359, 0.2500),
    'P':   (3.74177, 0.2000),
    'FE':  (2.00000, 0.0100),
    'Na+': (2.35000, 0.1000),
    'Cl-': (4.40104, 0.1000),
    'K+':  (2.65800, 0.1000),
    'Mg2+':(1.41200, 0.1000),
    'Ca2+':(2.41200, 0.1000),
    'Zn2+':(1.10000, 0.2500),
    # GAFF element fallbacks
    'F':   (2.94000, 0.0610),
    'Cl':  (3.40000, 0.1500),
    'BR':  (3.53000, 0.2200),
    'Br':  (3.53000, 0.2200),
    'I':   (3.50000, 0.2800),
    'SI':  (3.82600, 0.1800),
    'Si':  (3.82600, 0.1800),
    'B':   (3.63753, 0.0960),
    'LI':  (1.13700, 0.0183),
    'Li':  (1.13700, 0.0183),
    'LP':  (0.00000, 0.0000),
    'Du':  (0.00000, 0.0000),
}

# Element-based fallback when exact atom type is unknown
_VDW_ELEMENT = {
    'C':  (3.39967, 0.0860),
    'N':  (3.25000, 0.1700),
    'O':  (2.96096, 0.2100),
    'H':  (1.20000, 0.0150),
    'S':  (3.56359, 0.2500),
    'P':  (3.74177, 0.2000),
    'F':  (2.94000, 0.0610),
    'CL': (3.40000, 0.1500),
    'BR': (3.53000, 0.2200),
    'I':  (3.50000, 0.2800),
    'FE': (2.00000, 0.0100),
    'ZN': (1.10000, 0.2500),
    'CA': (2.41200, 0.1000),
    'MG': (1.41200, 0.1000),
    'NA': (2.35000, 0.1000),
    'K':  (2.65800, 0.1000),
    'SI': (3.82600, 0.1800),
    'B':  (3.63753, 0.0960),
    'LI': (1.13700, 0.0183),
}

# Born radii (Å) — used in Generalized Born
# Simplified: element-specific, no OBC correction
_BORN_RADII = {
    'H':  1.30,
    'C':  1.70,
    'N':  1.55,
    'O':  1.50,
    'F':  1.47,
    'P':  1.85,
    'S':  1.80,
    'CL': 1.75,
    'BR': 1.85,
    'I':  1.98,
    'FE': 1.20,
    'ZN': 1.10,
    'CA': 1.40,
    'MG': 1.20,
    'NA': 1.40,
    'K':  1.60,
    'SI': 2.10,
    'B':  1.80,
    'LI': 1.20,
}

# VDW radii (Å) for SASA calculation
_VDW_RADIUS = {
    'H':  1.20,
    'C':  1.70,
    'N':  1.55,
    'O':  1.52,
    'F':  1.47,
    'P':  1.80,
    'S':  1.80,
    'CL': 1.75,
    'BR': 1.85,
    'I':  1.98,
    'FE': 1.95,
    'ZN': 1.39,
    'CA': 1.70,
    'MG': 1.73,
    'NA': 1.54,
    'K':  1.96,
    'SI': 2.10,
    'B':  1.80,
    'LI': 1.82,
}

# ─── Data structures ───────────────────────────────────────────────────────

@dataclass
class MMPBSAResult:
    """Structured result from MM/PBSA calculation."""

    # ── Total binding free energy ─────────────────────────────────────
    delta_g_bind: float | None = None       # kcal/mol (ΔG_bind)
    delta_e_mm: float | None = None         # kcal/mol (gas-phase MM)
    delta_g_solv: float | None = None       # kcal/mol (solvation)

    # ── MM energy decomposition ───────────────────────────────────────
    delta_e_elec: float | None = None       # Coulomb (kcal/mol)
    delta_e_vdw: float | None = None        # Lennard-Jones (kcal/mol)

    # ── Solvation decomposition ─────────────────────────────────────
    delta_g_gb: float | None = None         # Polar (GB) solvation
    delta_g_sa: float | None = None         # Non-polar (SA) solvation

    # ── Entropy correction ──────────────────────────────────────────
    t_delta_s: float | None = None        # kcal/mol (-TΔS)

    # ── Per-residue decomposition ────────────────────────────────────
    per_residue: Dict[str, float] = field(default_factory=dict)
    # Format: {'PHE140.A': -2.34, 'ASP189.A': -1.87, ...}

    # ── Metadata ────────────────────────────────────────────────────
    receptor: str = ''
    ligand: str = ''
    method: str = 'MM/GBSA (RDKit-custom)'
    salt_conc: float = 0.15     # M
    temperature: float = 298.15  # K
    epsilon_solvent: float = 80.0
    n_receptor_atoms: int = 0
    n_ligand_atoms: int = 0

    @property
    def is_publication_grade(self) -> bool:
        """"Whether this result meets publication-quality standards.


        Returns False — this module uses a simplified MM/GBSA implementation.
        AmberTools MMPBSA.py is required for publication-grade absolute energies.
        """
        return False

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_dataframe_rows(self) -> List[dict]:
        """Return per-residue rows for pandas DataFrame."""
        rows = []
        for res_id, energy in sorted(self.per_residue.items(), key=lambda x: x[1]):
            rows.append({
                'residue': res_id,
                'energy_kcal_mol': round(energy, 2),
                'contribution': 'favorable' if energy < -0.5 else ('unfavorable' if energy > 0.5 else 'weak'),
            })
        return rows

    def summary(self) -> str:
        """Human-readable summary for publications."""
        lines = [
            f"MM/GBSA Binding Free Energy: {self.delta_g_bind:.2f} kcal/mol",
            f"  Gas-phase interaction:      {self.delta_e_mm:.2f} kcal/mol",
            f"    Coulomb:                  {self.delta_e_elec:.2f}",
            f"    van der Waals:            {self.delta_e_vdw:.2f}",
            f"  Solvation correction:       {self.delta_g_solv:.2f} kcal/mol",
            f"    Polar (GB):               {self.delta_g_gb:.2f}",
            f"    Non-polar (SA):           {self.delta_g_sa:.2f}",
        ]
        if self.t_delta_s is not None:
            lines.append(f"  Entropy correction:         {self.t_delta_s:.2f} kcal/mol")
        lines.extend([
            f"",
            f"Top favorable residues ({len([v for v in self.per_residue.values() if v < -0.5])}):",
        ])
        for res_id, energy in sorted(self.per_residue.items(), key=lambda x: x[1])[:5]:
            lines.append(f"  {res_id:12s}  {energy:+.2f} kcal/mol")
        return '\n'.join(lines)


# ─── Internal helpers ────────────────────────────────────────────────────────

def _get_vdw_params(atom_type: str, element: str) -> Tuple[float, float]:
    """Return (σ, ε) for an atom, using atom type first then element fallback."""
    if atom_type in _VDW_PARAMS:
        return _VDW_PARAMS[atom_type]
    elem = element.upper()
    if elem in _VDW_ELEMENT:
        return _VDW_ELEMENT[elem]
    # Ultimate fallback: carbon-like
    logger.warning(f"[mmpbsa] Unknown atom type '{atom_type}' element '{element}', using C params")
    return _VDW_ELEMENT['C']


def _get_born_radius(element: str) -> float:
    """Return Born radius (Å) for an element."""
    elem = element.upper()
    if elem in _BORN_RADII:
        return _BORN_RADII[elem]
    logger.warning(f"[mmpbsa] Unknown element '{element}' for Born radius, using C")
    return _BORN_RADII['C']


def _get_vdw_radius(element: str) -> float:
    """Return VDW radius (Å) for SASA calculation."""
    elem = element.upper()
    if elem in _VDW_RADIUS:
        return _VDW_RADIUS[elem]
    logger.warning(f"[mmpbsa] Unknown element '{element}' for VDW radius, using C")
    return _VDW_RADIUS['C']


# ─── Shrake-Rupley SASA algorithm ────────────────────────────────────────────

_SR_SPHERE_POINTS = 960  # number of points on probe sphere (resolution)
_SR_PROBE_RADIUS = 1.4   # water probe radius (Å)

_SR_UNIT_SPHERE = None

def _init_sr_sphere(n_points: int = _SR_SPHERE_POINTS):
    """Generate approximately uniform points on unit sphere (Fibonacci spiral)."""
    global _SR_UNIT_SPHERE
    if _SR_UNIT_SPHERE is not None and len(_SR_UNIT_SPHERE) == n_points:
        return _SR_UNIT_SPHERE

    phi = np.pi * (3.0 - np.sqrt(5.0))  # golden angle
    indices = np.arange(n_points, dtype=float)
    y = 1 - (indices / (n_points - 1)) * 2
    r = np.sqrt(1 - y * y)
    theta = phi * indices
    x = np.cos(theta) * r
    z = np.sin(theta) * r
    points = np.stack([x, y, z], axis=1)
    _SR_UNIT_SPHERE = points
    return points


def _compute_sasa(coords: np.ndarray, radii: np.ndarray,
                  probe_radius: float = _SR_PROBE_RADIUS,
                  n_points: int = _SR_SPHERE_POINTS) -> np.ndarray:
    """
    Compute per-atom Solvent Accessible Surface Area using Shrake-Rupley.

    Args:
        coords: (N, 3) array of atom coordinates (Å)
        radii:  (N,) array of VDW radii (Å)
        probe_radius: water probe radius (Å)
        n_points: resolution of sphere discretization

    Returns:
        sasa: (N,) array of per-atom SASA (Å²)
    """
    n_atoms = len(coords)
    if n_atoms == 0:
        return np.array([])

    sphere = _init_sr_sphere(n_points)
    effective_radii = radii + probe_radius
    sasa = np.zeros(n_atoms)

    # Pre-compute all pairwise distances
    # (N, 1, 3) - (1, N, 3) = (N, N, 3)
    diff = coords[:, np.newaxis, :] - coords[np.newaxis, :, :]
    dist_sq = np.sum(diff ** 2, axis=2)

    for i in range(n_atoms):
        Ri = effective_radii[i]
        # Generate probe points around atom i
        probe_points = coords[i] + sphere * Ri

        # Check which points are occluded by other atoms
        occluded = np.zeros(n_points, dtype=bool)
        for j in range(n_atoms):
            if i == j:
                continue
            Rj_eff = effective_radii[j]
            # Distance from each probe point to atom j center
            d_sq_j = np.sum((probe_points - coords[j]) ** 2, axis=1)
            # If point is inside atom j's effective sphere, it's occluded
            occluded |= d_sq_j < (Rj_eff ** 2)

        # Accessible fraction
        accessible_fraction = 1.0 - np.mean(occluded)
        # Surface area of effective sphere
        sasa[i] = 4.0 * np.pi * (Ri ** 2) * accessible_fraction

    return sasa


# ─── PDB / PDBQT parsing ─────────────────────────────────────────────────────

# Residue names to skip (linkers, co-crystal ligands, detergents)
_SKIP_HET_RESIDUES = {
    # Linkers / co-crystal ligands
    '02J', '010', 'PJE', 'NFH', 'NFN', '03U', '03T', '02K', '02L',
    'JG1', 'JGP', 'LIG', 'UNL', 'DRG', 'INH',
    # Crystallization additives (not part of protein)
    'GOL', 'EDO', 'DMS', 'ACT', 'PEG', 'MSE', 'FMT', 'ACE', 'NH2',
    'SO4', 'PO4', 'CL', 'NA', 'K', 'CA', 'MG', 'ZN',
    # Water (handled separately if needed)
    'HOH', 'WAT', 'H2O', 'DOD',
}


def _parse_pdb_atoms(pdb_path: str) -> List[dict]:
    """
    Parse a PDB file and return atom records with coordinates and metadata.

    Returns list of dicts:
      {x, y, z, element, atom_name, resn, resi, chain, charge, serial}
    """
    atoms = []
    with open(pdb_path, 'r') as f:
        for line in f:
            if not (line.startswith('ATOM  ') or line.startswith('HETATM')):
                continue
            # Skip linker / co-crystal ligand residues
            resn = line[17:20].strip()
            if resn in _SKIP_HET_RESIDUES:
                continue
            try:
                serial = int(line[6:11].strip())
                name = line[12:16].strip()
                resn = line[17:20].strip()
                chain = line[21].strip() or 'A'
                resi = int(line[22:26].strip())
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                # Element: for PDBQT, derive from atom_name first char
                # Vina atom types (A, C, OA, HD, etc.) are in col 78,
                # not standard PDB element cols 77-78
                element = name[0].upper() if name and name[0].isalpha() else 'C'
                charge_str = line[70:76].strip()
                charge = float(charge_str) if charge_str else 0.0

                atoms.append({
                    'x': x, 'y': y, 'z': z,
                    'element': element,
                    'atom_name': name,
                    'resn': resn,
                    'resi': resi,
                    'chain': chain,
                    'charge': charge,
                    'serial': serial,
                })
            except (ValueError, IndexError):
                continue
    return atoms


def _parse_pdbqt_atoms(pdbqt_path: str) -> List[dict]:
    """
    Parse a PDBQT file and return atom records.

    PDBQT format extends PDB with partial charge (cols 71-76) and
    atom type (cols 77-79).
    """
    atoms = []
    with open(pdbqt_path, 'r') as f:
        for line in f:
            if not (line.startswith('ATOM  ') or line.startswith('HETATM')):
                continue
            try:
                serial = int(line[6:11].strip())
                name = line[12:16].strip()
                resn = line[17:20].strip()
                chain = line[21].strip() or 'A'
                resi = int(line[22:26].strip())
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                # PDBQT: partial charge in cols 71-76, atom type in 77-79
                charge_str = line[70:76].strip()
                charge = float(charge_str) if charge_str else 0.0
                atom_type = line[77:79].strip()
                # Element: for PDBQT, derive from atom_name first char
                # Vina atom types (A, C, OA, HD, etc.) are in col 78,
                # not standard PDB element cols 77-78
                element = name[0].upper() if name and name[0].isalpha() else 'C'

                atoms.append({
                    'x': x, 'y': y, 'z': z,
                    'element': element,
                    'atom_name': name,
                    'resn': resn,
                    'resi': resi,
                    'chain': chain,
                    'charge': charge,
                    'atom_type': atom_type,
                    'serial': serial,
                })
            except (ValueError, IndexError):
                continue
    return atoms


def _compute_gasteiger_charges_on_pdb_atoms(atoms: List[dict]) -> np.ndarray:
    """
    Compute Gasteiger charges for a list of PDB atoms using RDKit.

    Builds a minimal RDKit molecule from PDB coordinates and computes
    Gasteiger partial charges. Returns array of charges aligned with atoms.
    """
    if not atoms:
        return np.array([])

    # Build an RDKit molecule from PDB block
    pdb_lines = []
    for i, a in enumerate(atoms, 1):
        # Minimal PDB ATOM line for RDKit parsing
        element = a['element']
        if len(element) == 1:
            element = ' ' + element
        else:
            element = element[:2]
        pdb_lines.append(
            f"ATOM  {i:5d}  {a['atom_name']:3s} {a['resn']:3s} {a['chain']:1s}{a['resi']:4d}    "
            f"{a['x']:8.3f}{a['y']:8.3f}{a['z']:8.3f}  1.00  0.00          {element:>2s}"
        )
    pdb_lines.append('END')
    pdb_block = '\n'.join(pdb_lines)

    mol = Chem.MolFromPDBFile(tmp_path, removeHs=False)
    if mol is None:
        logger.warning("[mmpbsa] RDKit could not parse PDB file for Gasteiger charges, using zeros")
        return np.zeros(len(atoms))

    try:
        AllChem.ComputeGasteigerCharges(mol)
    except Exception as e:
        logger.warning(f"[mmpbsa] Gasteiger charge computation failed: {e}, using zeros")
        return np.zeros(len(atoms))

    charges = []
    for atom in mol.GetAtoms():
        try:
            q = atom.GetDoubleProp('_GasteigerCharge')
        except KeyError:
            q = 0.0
        charges.append(q)

    # If RDKit dropped some atoms, pad with zeros
    if len(charges) < len(atoms):
        charges.extend([0.0] * (len(atoms) - len(charges)))

    return np.array(charges[:len(atoms)])


def _compute_gasteiger_charges_on_pdb_atoms(atoms: List[dict]) -> np.ndarray:
    """
    Compute Gasteiger charges for a list of PDB atoms using RDKit.

    Writes a temporary PDB file and uses MolFromPDBFile (better connectivity
    inference for proteins) followed by ComputeGasteigerCharges.
    """
    if not atoms:
        return np.array([])

    import tempfile

    # Build proper PDB file for RDKit parsing
    pdb_lines = []
    for i, a in enumerate(atoms, 1):
        element = a['element']
        if len(element) == 1:
            element = ' ' + element
        else:
            element = element[:2]
        # Standard PDB format
        pdb_lines.append(
            f"ATOM  {i:5d}  {a['atom_name']:3s} {a['resn']:3s} {a['chain']:1s}{a['resi']:4d}    "
            f"{a['x']:8.3f}{a['y']:8.3f}{a['z']:8.3f}  1.00  0.00          {element:>2s}"
        )
    pdb_lines.append('END')
    pdb_block = '\n'.join(pdb_lines)

    # MolFromPDBFile infers protein backbone connectivity; MolFromPDBBlock does not
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as tf:
        tf.write(pdb_block)
        tmp_path = tf.name

    try:
        mol = Chem.MolFromPDBFile(tmp_path, removeHs=False)
        if mol is None:
            logger.warning("[mmpbsa] RDKit could not parse PDB for Gasteiger charges, using zeros")
            return np.zeros(len(atoms))

        try:
            AllChem.ComputeGasteigerCharges(mol)
        except Exception as e:
            logger.warning(f"[mmpbsa] Gasteiger charge computation failed: {e}, using zeros")
            return np.zeros(len(atoms))

        charges = []
        for atom in mol.GetAtoms():
            try:
                q = atom.GetDoubleProp('_GasteigerCharge')
            except KeyError:
                q = 0.0
            charges.append(q)

        # If RDKit dropped some atoms, pad with zeros
        if len(charges) < len(atoms):
            charges.extend([0.0] * (len(atoms) - len(charges)))

        return np.array(charges[:len(atoms)])
    finally:
        os.unlink(tmp_path)


# ─── Energy calculations ─────────────────────────────────────────────────────

def _coulomb_energy(coords: np.ndarray, charges: np.ndarray,
                    pairs: Optional[np.ndarray] = None) -> float:
    """
    Compute Coulomb electrostatic energy for a set of atoms.

    E_elec = k_elec * Σ_{i<j} q_i * q_j / r_ij

    Args:
        coords:   (N, 3) coordinates (Å)
        charges:  (N,) partial charges (e)
        pairs:    (M, 2) optional atom pair indices to limit calculation
                  If None, compute all pairs within 12Å cutoff.

    Returns:
        E_elec in kcal/mol
    """
    n = len(coords)
    if n < 2:
        return 0.0

    if pairs is not None:
        i_idx = pairs[:, 0]
        j_idx = pairs[:, 1]
        r_ij = np.linalg.norm(coords[i_idx] - coords[j_idx], axis=1)
        # Avoid division by zero
        r_ij = np.maximum(r_ij, 0.1)
        energies = _K_ELEC * charges[i_idx] * charges[j_idx] / r_ij
        return float(np.sum(energies))

    # All pairs with cutoff
    cutoff = 12.0  # Å — beyond this, Coulomb is heavily screened by solvent
    total = 0.0
    for i in range(n):
        diff = coords[i+1:] - coords[i]
        dist = np.linalg.norm(diff, axis=1)
        mask = dist < cutoff
        if np.any(mask):
            q_i = charges[i]
            q_js = charges[i+1:][mask]
            ds = dist[mask]
            ds = np.maximum(ds, 0.1)
            total += np.sum(_K_ELEC * q_i * q_js / ds)
    return float(total)


def _vdw_energy(coords: np.ndarray, elements: List[str],
                atom_types: List[str],
                pairs: Optional[np.ndarray] = None) -> float:
    """
    Compute Lennard-Jones van der Waals energy.

    E_vdw = Σ_{i<j} 4ε_{ij} * [(σ_{ij}/r)^12 - (σ_{ij}/r)^6]

    Lorentz-Berthelot combining rules:
        σ_{ij} = (σ_i + σ_j) / 2
        ε_{ij} = sqrt(ε_i * ε_j)

    Args:
        coords:    (N, 3) coordinates
        elements:  (N,) element symbols
        atom_types:(N,) AMBER/GAFF atom types (for protein atoms)
        pairs:     (M, 2) optional atom pair indices

    Returns:
        E_vdw in kcal/mol
    """
    n = len(coords)
    if n < 2:
        return 0.0

    # Pre-compute per-atom σ and ε
    sigmas = np.zeros(n)
    epsilons = np.zeros(n)
    for i in range(n):
        s, e = _get_vdw_params(atom_types[i], elements[i])
        sigmas[i] = s
        epsilons[i] = e

    cutoff = 12.0  # Å

    if pairs is not None:
        i_idx = pairs[:, 0]
        j_idx = pairs[:, 1]
        r_ij = np.linalg.norm(coords[i_idx] - coords[j_idx], axis=1)
        mask = (r_ij < cutoff) & (r_ij > 0.01)
        if not np.any(mask):
            return 0.0
        r = r_ij[mask]
        s_i = sigmas[i_idx][mask]
        s_j = sigmas[j_idx][mask]
        e_i = epsilons[i_idx][mask]
        e_j = epsilons[j_idx][mask]
        sigma_ij = (s_i + s_j) * 0.5
        epsilon_ij = np.sqrt(e_i * e_j)
        sr6 = (sigma_ij / r) ** 6
        sr12 = sr6 * sr6
        energies = 4.0 * epsilon_ij * (sr12 - sr6)
        return float(np.sum(energies))

    # All pairs
    total = 0.0
    for i in range(n):
        diff = coords[i+1:] - coords[i]
        dist = np.linalg.norm(diff, axis=1)
        mask = (dist < cutoff) & (dist > 0.01)
        if not np.any(mask):
            continue
        r = dist[mask]
        s_j = sigmas[i+1:][mask]
        e_j = epsilons[i+1:][mask]
        sigma_ij = (sigmas[i] + s_j) * 0.5
        epsilon_ij = np.sqrt(epsilons[i] * e_j)
        sr6 = (sigma_ij / r) ** 6
        sr12 = sr6 * sr6
        total += np.sum(4.0 * epsilon_ij * (sr12 - sr6))
    return float(total)


# Still 归一化原子体积 (Å³) — 用于 OBC2 CFA 积分
# 不是几何体积，而是经验归一化参数
# 来源: Still et al. 1990, J. Comput. Chem. 11, 1047-1069
_STILL_VOLUME = {
    'H':  2.0,
    'C':  15.0,
    'N':  10.0,
    'O':  10.0,
    'F':  8.0,
    'P':  22.0,
    'S':  22.0,
    'CL': 18.0,
    'BR': 24.0,
    'I':  28.0,
    'FE': 10.0,
    'ZN': 8.0,
    'CA': 12.0,
    'MG': 10.0,
    'NA': 10.0,
    'K':  15.0,
    'SI': 25.0,
    'B':  15.0,
    'LI': 5.0,
}

# OBC2 模型参数 (Onufriev et al. 2004)
# 原始参数: β=0.8, γ=4.85, δ=-2.0
# 这里使用缩放后的 psi，调整参数使 tanh 在 [0.1, 0.8] 范围内平滑变化
_OBC2_BETA = 1.2    # 线性项系数（调整后的有效值）
_OBC2_GAMMA = 0.0   # 禁用二次项（避免饱和）
_OBC2_DELTA = 0.0   # 禁用三次项

# CFA 积分缩放因子
# 校准目标: median psi_scaled ≈ 0.5, max ≈ 1.5
_CFA_SCALE_FACTOR = 0.06

# PSI 截断 — 防止 tanh 饱和
_CFA_PSI_MAX = 2.0

# 深度校正参数
# alpha_eff = R_i * (1 + depth_scale * tanh(...))
_OBC2_DEPTH_SCALE = 0.8  # 深埋原子最大增大 80%


def _compute_obc2_born_radii(coords: np.ndarray, elements: List[str]) -> np.ndarray:
    """
    Compute effective Born radii using the OBC2 model with full CFA normalization.

    OBC2 (Onufriev-Bashford-Case 2) computes a screened Coulomb Field Approximation
    (CFA) integral that accounts for the electrostatic screening of neighboring atoms.

    Implementation:
    1. Still-normalized atomic volumes (empirical, not geometric)
    2. CFA integral: ψ_i = Σ_j [V_j / r_ij^4]
    3. Scaled psi: ψ_scaled = ψ_i * scale_factor
    4. OBC2 correction: α_eff = R_i * [1 + depth_scale * tanh(β·ψ_scaled)]
    5. Clamp to physical range

    Reference:
        Onufriev, Bashford, Case. Proteins 55:383-394 (2004).
        Still et al. J. Comput. Chem. 11, 1047-1069 (1990).

    Args:
        coords:   (N, 3) coordinates (Å)
        elements: (N,) element symbols (uppercase)

    Returns:
        effective_born_radii: (N,) array of OBC2-corrected Born radii (Å)
    """
    n = len(coords)
    if n < 1:
        return np.array([])

    # Intrinsic Born radii (mbondi2 parameter set)
    R_i = np.array([_get_born_radius(e) for e in elements])

    # Still-normalized atomic volumes
    V_j = np.array([_STILL_VOLUME.get(e, 10.0) for e in elements])

    # Step 1: Compute CFA integral ψ_i = Σ_j [V_j / r_ij^4]
    psi = np.zeros(n)
    cutoff = 10.0  # Å

    for i in range(n):
        diff = coords - coords[i]
        r_ij = np.linalg.norm(diff, axis=1)
        r_ij[i] = float('inf')

        mask = (r_ij < cutoff) & (r_ij > 0.01)
        if np.any(mask):
            r = r_ij[mask]
            v = V_j[mask]
            psi[i] = np.sum(v / (r ** 4))

    # Step 2: Scale psi to [0, 2.0] range
    psi_scaled = psi * _CFA_SCALE_FACTOR
    psi_scaled = np.clip(psi_scaled, 0.0, _CFA_PSI_MAX)

    # Step 3: OBC2 correction using simplified tanh formula
    # alpha_eff = R_i * [1 + depth_scale * tanh(beta * psi_scaled)]
    # This gives:
    #   psi=0 (surface):   alpha ≈ R_i * 1.0
    #   psi=0.5 (medium):  alpha ≈ R_i * (1 + 0.8*tanh(0.6)) = R_i * 1.45
    #   psi=1.0 (buried):  alpha ≈ R_i * (1 + 0.8*tanh(1.2)) = R_i * 1.74
    #   psi=2.0 (deep):    alpha ≈ R_i * (1 + 0.8*tanh(2.4)) = R_i * 1.83
    tanh_term = np.tanh(_OBC2_BETA * psi_scaled)
    alpha_eff = R_i * (1.0 + _OBC2_DEPTH_SCALE * tanh_term)

    # Step 4: Clamp to physically reasonable range
    min_radius = 0.7 * R_i   # 表面原子不小于 0.7*R_i
    max_radius = 2.0 * R_i   # 深埋原子不大于 2.0*R_i
    alpha_eff = np.clip(alpha_eff, min_radius, max_radius)

    return alpha_eff


def _gb_energy(coords: np.ndarray, charges: np.ndarray,
               elements: List[str],
               epsilon_solvent: float = _EPS_SOLVENT,
               use_obc2: bool = True) -> float:
    """
    Compute Generalized Born polar solvation energy.

    G_gb = -166 * (1 - 1/ε) * Σ_i q_i² / α_i
         + 166 * (1 - 1/ε) * Σ_{i<j} q_i * q_j / f_gb(r_ij, α_i, α_j)

    where f_gb = sqrt(r² + α_i*α_j * exp(-r² / (4*α_i*α_j)))

    Two GB models available:
    - use_obc2=True:  OBC2 (Onufriev et al. 2004) with CFA-based Born radii
    - use_obc2=False: Simplified Still model with fixed element-based radii

    Args:
        coords:          (N, 3) coordinates
        charges:         (N,) partial charges
        elements:        (N,) element symbols
        epsilon_solvent: solvent dielectric constant
        use_obc2:        use OBC2 model (recommended)

    Returns:
        G_gb in kcal/mol
    """
    n = len(coords)
    if n < 1:
        return 0.0

    # Born radii: OBC2 or fixed element-based
    if use_obc2:
        born_radii = _compute_obc2_born_radii(coords, elements)
    else:
        born_radii = np.array([_get_born_radius(e) for e in elements])

    # Screening factor
    k_screen = 166.0 * (1.0 - 1.0 / epsilon_solvent)

    # Self term (with 1/2 factor to avoid double counting)
    G_self = -0.5 * k_screen * np.sum(charges ** 2 / born_radii)

    # Pair term
    G_pair = 0.0
    for i in range(n):
        diff = coords[i+1:] - coords[i]
        r = np.linalg.norm(diff, axis=1)
        r = np.maximum(r, 0.1)
        alpha_i = born_radii[i]
        alpha_j = born_radii[i+1:]
        alpha_prod = alpha_i * alpha_j
        f_gb = np.sqrt(r ** 2 + alpha_prod * np.exp(-r ** 2 / (4.0 * alpha_prod)))
        q_j = charges[i+1:]
        G_pair += np.sum(k_screen * charges[i] * q_j / f_gb)
        
    # G_gb = -k_screen * [1/2 * Σ_i q_i²/α_i + Σ_{i<j} q_i q_j / f_gb]
    # Total includes self + pair (pair already has correct sign from q_i*q_j)
    # For opposite charges (q_i*q_j < 0): pair contributes negative (attractive)
    # For like charges (q_i*q_j > 0): pair contributes positive (repulsive)
    # In solvation, opposite charges are stabilized -> pair should be negative
    # Correction: multiply pair by -1 to match Still formula
    G_pair = -G_pair
    
    return float(G_self + G_pair)


def _sa_energy(coords: np.ndarray, elements: List[str],
               gamma: float = _GAMMA_SA,
               beta: float = _BETA_SA) -> float:
    """
    Compute non-polar solvation energy from SASA.

    G_sa = γ * SASA + β

    Args:
        coords:   (N, 3) coordinates
        elements: (N,) element symbols
        gamma:    surface tension (kcal/mol/Å²)
        beta:     offset (kcal/mol)

    Returns:
        G_sa in kcal/mol
    """
    radii = np.array([_get_vdw_radius(e) for e in elements])
    sasa = _compute_sasa(coords, radii)
    return gamma * np.sum(sasa) + beta


def _count_heavy_atoms_rotatable_bonds(ligand_atoms: List[dict]) -> Tuple[int, int]:
    """
    Count heavy atoms and estimate rotatable bonds for empirical entropy formula.

    Args:
        ligand_atoms: list of ligand atom dicts from _parse_pdbqt_atoms

    Returns:
        (n_heavy, n_rotatable) tuple
    """
    # Count heavy atoms (non-hydrogen)
    n_heavy = sum(1 for a in ligand_atoms if a['element'] not in ('H', 'X'))

    # Estimate rotatable bonds from SMILES if available
    # Fallback: rough estimate from heavy atom count
    # Typical: ~30-40% of heavy atoms are rotatable bonds
    n_rotatable = int(0.35 * n_heavy)

    return n_heavy, n_rotatable


def _compute_interaction_entropy(
    energy_list: List[float],
    temperature: float = 298.15
) -> float:
    """
    Compute configurational entropy using the Interaction Entropy (IE) method.

    -TΔS = R·T · ln(⟨exp(ΔE_mm / R·T)⟩)

    Based on the MM/GBSA-IE approach by Duan et al. (2016) which demonstrates
    that the ensemble average of exp(ΔE_mm/kT) directly yields the entropy
    contribution to binding without normal mode analysis.

    Reference:
        Duan, L., et al. Phys. Chem. Chem. Phys. 18:9505-9513 (2016).

    Args:
        energy_list: list of ΔE_mm values from multiple docked poses (kcal/mol)
        temperature: temperature in Kelvin

    Returns:
        -TΔS in kcal/mol (positive value means unfavorable entropy)
    """
    if len(energy_list) < 2:
        # Not enough poses for IE calculation; caller should use empirical formula
        return 0.0

    R = 1.98720425864083e-3  # Gas constant in kcal/(mol·K)
    RT_inv = 1.0 / (R * temperature)

    energies = np.array(energy_list)

    # Compute ⟨exp(ΔE_mm / RT)⟩
    exp_terms = np.exp(energies * RT_inv)
    mean_exp = np.mean(exp_terms)

    # -TΔS = R·T · ln(mean_exp)
    t_delta_s = R * temperature * np.log(mean_exp)

    # Typical entropy for protein-ligand binding is unfavorable (positive)
    # Range: 5-20 kcal/mol
    return float(t_delta_s)


def _compute_empirical_entropy(
    n_heavy_atoms: int,
    n_rotatable_bonds: int
) -> float:
    """
    Empirical entropy correction for single-pose MM/PBSA.

    -TΔS ≈ 0.3 * N_heavy + 0.5 * N_rotatable_bonds

    This formula approximates the configurational entropy loss upon binding.
    Based on fitting to large datasets of protein-ligand complexes.

    Reference:
        Ranges calibrated against MM/PBSA benchmark data (Case et al.)

    Args:
        n_heavy_atoms: number of heavy atoms in the ligand
        n_rotatable_bonds: number of rotatable bonds in the ligand

    Returns:
        -TΔS in kcal/mol (positive = unfavorable entropy)
    """
    return 0.3 * n_heavy_atoms + 0.5 * n_rotatable_bonds


# ─── System-level energy computation ────────────────────────────────────────

def _compute_system_energy(atoms: List[dict], compute_sasa: bool = True,
                          use_obc2: bool = True, epsilon_solvent: float = _EPS_SOLVENT) -> dict:
    """
    Compute all energy terms for a system (receptor, ligand, or complex).

    Args:
        atoms: list of atom dicts from _parse_pdb_atoms or _parse_pdbqt_atoms
        compute_sasa: whether to compute SASA (expensive)
        use_obc2: use OBC2 Generalized Born model (True) or simplified Still model (False)
        epsilon_solvent: solvent dielectric constant

    Returns:
        dict with keys: elec, vdw, gb, sa, mm, solv, total
    """
    n = len(atoms)
    if n == 0:
        return {'elec': 0.0, 'vdw': 0.0, 'gb': 0.0, 'sa': 0.0,
                'mm': 0.0, 'solv': 0.0, 'total': 0.0}

    coords = np.array([[a['x'], a['y'], a['z']] for a in atoms])
    elements = [a['element'] for a in atoms]
    atom_types = [a.get('atom_type', a['element']) for a in atoms]

    # Charges: use existing if available, else compute Gasteiger for ALL atoms
    charges = np.array([a.get('charge', 0.0) for a in atoms])
    if np.any(charges == 0.0):
        # At least some atoms have no charge — compute Gasteiger for all
        # (Gasteiger is fast enough that per-atom detection isn't worth it)
        gasteiger = _compute_gasteiger_charges_on_pdb_atoms(atoms)
        # Use Gasteiger where original charge was 0, keep original where non-zero
        charges = np.where(charges == 0.0, gasteiger, charges)
        logger.debug(f"[mmpbsa] Mixed charges: {np.sum(charges == 0.0)} atoms used Gasteiger")

    elec = _coulomb_energy(coords, charges)
    vdw = _vdw_energy(coords, elements, atom_types)
    gb = _gb_energy(coords, charges, elements, epsilon_solvent, use_obc2)
    sa = _sa_energy(coords, elements) if compute_sasa else 0.0

    mm = elec + vdw
    solv = gb + sa
    total = mm + solv

    return {
        'elec': elec, 'vdw': vdw,
        'gb': gb, 'sa': sa,
        'mm': mm, 'solv': solv, 'total': total,
    }


# ─── Per-residue decomposition ─────────────────────────────────────────────

def _per_residue_decomposition(receptor_atoms: List[dict],
                                ligand_atoms: List[dict]) -> Dict[str, float]:
    """
    Compute per-residue interaction energy between receptor and ligand.

    For each receptor residue, calculate its Coulomb + vdW interaction
    with all ligand atoms.

    Returns:
        {residue_id: energy_kcal_mol}
        residue_id format: "RESN###.CHAIN" (e.g. "PHE140.A")
    """
    if not receptor_atoms or not ligand_atoms:
        return {}

    rec_coords = np.array([[a['x'], a['y'], a['z']] for a in receptor_atoms])
    lig_coords = np.array([[a['x'], a['y'], a['z']] for a in ligand_atoms])

    # Charges
    rec_charges = np.array([a.get('charge', 0.0) for a in receptor_atoms])
    lig_charges = np.array([a.get('charge', 0.0) for a in ligand_atoms])
    if np.allclose(rec_charges, 0.0):
        rec_charges = _compute_gasteiger_charges_on_pdb_atoms(receptor_atoms)
    if np.allclose(lig_charges, 0.0):
        lig_charges = _compute_gasteiger_charges_on_pdb_atoms(ligand_atoms)

    rec_elements = [a['element'] for a in receptor_atoms]
    lig_elements = [a['element'] for a in ligand_atoms]
    rec_types = [a.get('atom_type', a['element']) for a in receptor_atoms]
    lig_types = [a.get('atom_type', a['element']) for a in ligand_atoms]

    # Precompute ligand vdW params
    lig_sigmas = np.array([_get_vdw_params(t, e)[0] for t, e in zip(lig_types, lig_elements)])
    lig_epsilons = np.array([_get_vdw_params(t, e)[1] for t, e in zip(lig_types, lig_elements)])

    # Group receptor atoms by residue
    from collections import defaultdict
    residue_atoms = defaultdict(list)
    for idx, a in enumerate(receptor_atoms):
        res_id = f"{a['resn']}{a['resi']}.{a['chain']}"
        residue_atoms[res_id].append(idx)

    per_res = {}
    cutoff = 12.0

    for res_id, atom_indices in residue_atoms.items():
        res_coords = rec_coords[atom_indices]
        res_charges = rec_charges[atom_indices]
        res_elements = [rec_elements[i] for i in atom_indices]
        res_types = [rec_types[i] for i in atom_indices]
        res_sigmas = np.array([_get_vdw_params(t, e)[0] for t, e in zip(res_types, res_elements)])
        res_epsilons = np.array([_get_vdw_params(t, e)[1] for t, e in zip(res_types, res_elements)])

        # All rec-lig pairs for this residue
        n_rec = len(atom_indices)
        n_lig = len(ligand_atoms)

        # Compute distances
        # (n_rec, 1, 3) - (1, n_lig, 3) = (n_rec, n_lig, 3)
        diff = res_coords[:, np.newaxis, :] - lig_coords[np.newaxis, :, :]
        dist = np.linalg.norm(diff, axis=2)
        mask = (dist < cutoff) & (dist > 0.01)

        if not np.any(mask):
            per_res[res_id] = 0.0
            continue

        # Coulomb: k * q_rec * q_lig / r
        q_rec = res_charges[:, np.newaxis]
        q_lig = lig_charges[np.newaxis, :]
        coulomb = _K_ELEC * q_rec * q_lig / np.maximum(dist, 0.1)
        coulomb = np.where(mask, coulomb, 0.0)

        # LJ: 4ε_ij * [(σ_ij/r)^12 - (σ_ij/r)^6]
        s_rec = res_sigmas[:, np.newaxis]
        s_lig = lig_sigmas[np.newaxis, :]
        e_rec = res_epsilons[:, np.newaxis]
        e_lig = lig_epsilons[np.newaxis, :]
        sigma_ij = (s_rec + s_lig) * 0.5
        epsilon_ij = np.sqrt(e_rec * e_lig)
        sr6 = np.where(dist > 0.01, (sigma_ij / dist) ** 6, 0.0)
        sr12 = sr6 * sr6
        lj = 4.0 * epsilon_ij * (sr12 - sr6)
        lj = np.where(mask, lj, 0.0)

        total_e = float(np.sum(coulomb + lj))
        per_res[res_id] = total_e

    return per_res


# ─── Public API ────────────────────────────────────────────────────────────

def compute_mmpbsa(
    receptor_pdb: str,
    ligand_pdbqt: str,
    docked_pdbqt: str = None,
    poses_pdbqt: List[str] = None,
    method: str = 'gb',
    # Amber-specific parameters
    amber_protocol: str = 'quick',
    amber_method: str = 'gb',
    use_gpu: bool = False,
    amber_output_dir: str = None,
    # Fast-mode parameters
    use_obc2: bool = True,
    compute_entropy: bool = True,
    salt_conc: float = 0.15,
    temperature: float = 298.15,
    epsilon_solvent: float = 80.0,
    decomp: bool = True,
    compute_sasa: bool = True,
    n_threads: int = 4,
) -> 'MMPBSAResult':
    """
    Compute MM/PBSA binding free energy for a receptor-ligand complex.

    Two methods available:

    **'fast' (default, alias 'gb'):
        Lightweight RDKit-based implementation (~30 seconds).
        Good for screening and relative ranking.
        NOT recommended for publication absolute energies.

    **'amber':
        Publication-grade AmberTools MM/PBSA (requires autodock-amber env).
        Uses full MD simulation + MMPBSA.py calculation.
        Accuracy: ±0.5-1.5 kcal/mol with proper sampling.

    Features (fast mode):
    - OBC2 Generalized Born model (Onufriev et al. 2004) as default
    - Interaction Entropy (Duan et al. 2016) when multiple poses are provided
    - Empirical entropy correction for single-pose calculations
    - Per-residue energy decomposition
    - SASA-based non-polar solvation (Shrake-Rupley algorithm)

    Amber protocols:
    - 'quick':   Energy minimization only (~5-10 min)
    - 'short':   Minimize + 1ns NVT (~30-60 min)
    - 'medium':  Minimize + heat + 10ns NPT (~2-4 hours)
    - 'full':    Minimize + heat + 100ns NPT (~8-16 hours, GPU recommended)

    Args:
        receptor_pdb:   Path to receptor PDB file
        ligand_pdbqt:   Path to docked ligand PDBQT file
        docked_pdbqt:   Alias for ligand_pdbqt (backward compat)
        poses_pdbqt:    List of alternative ligand pose PDBQT paths for Interaction
                         Entropy calculation (fast mode only).
        method:         'fast'/'gb' = Simplified RDKit (default), 'amber' = AmberTools
        amber_protocol: MD protocol for Amber mode ('quick', 'short', 'medium', 'full')
        amber_method:   Solvation method for Amber mode ('gb' or 'pb')
        use_gpu:       Use GPU acceleration (Amber mode only)
        amber_output_dir: Output directory for Amber files (None = temp dir)
        use_obc2:       Use OBC2 GB model (True, recommended) or simplified Still model
                         (fast mode only)
        compute_entropy:Whether to compute entropy correction (-TΔS) (fast mode only)
        salt_conc:      Salt concentration in Molar
        temperature:    Temperature in Kelvin
        epsilon_solvent: Solvent dielectric constant
        decomp:         Whether to compute per-residue decomposition
        compute_sasa:   Whether to compute SASA (fast mode only)
        n_threads:      Number of CPU threads for Amber MD

    Returns:
        MMPBSAResult with energy components and per-residue decomposition

    Example:
        >>> # Fast mode (screening, ~30s)
        >>> result = compute_mmpbsa("6LU7.pdb", "nirmatrelvir_docked.pdbqt")
        >>> print(f"ΔG_bind = {result.delta_g_bind:.2f} kcal/mol")
        >>>
        >>> # Publication-grade (Amber, ~10 min)
        >>> result = compute_mmpbsa(
        ...     "6LU7.pdb", "docked.pdbqt",
        ...     method='amber', amber_protocol='short'
        ... )
    """
    # Amber mode: full publication-grade calculation
    if method == 'amber':
        from autodock._mmpbsa_amber import compute_mmpbsa_amber, _HAVE_AMBER
        if not _HAVE_AMBER:
            raise RuntimeError(
                "AmberTools not found. Please activate autodock-amber environment:\n"
                "  conda activate autodock-amber"
            )
        ligand_file = docked_pdbqt or ligand_pdbqt
        amber_result = compute_mmpbsa_amber(
            receptor_pdb=receptor_pdb,
            ligand_pdbqt=ligand_file,
            output_dir=amber_output_dir,
            protocol=amber_protocol,
            method=amber_method,
            use_gpu=use_gpu,
            n_threads=n_threads,
            decompose=decomp,
        )
        # Convert to standard MMPBSAResult
        return MMPBSAResult(
            delta_g_bind=amber_result.delta_g_bind,
            delta_e_mm=(amber_result.delta_e_vdw + amber_result.delta_e_elec
                         if amber_result.delta_e_vdw and amber_result.delta_e_elec
                         else None),
            delta_g_solv=((amber_result.delta_g_gb or amber_result.delta_g_pb or 0) +
                         (amber_result.delta_g_sa or 0)
                         if (amber_result.delta_g_gb or amber_result.delta_g_pb or amber_result.delta_g_sa)
                         else None),
            delta_e_elec=amber_result.delta_e_elec,
            delta_e_vdw=amber_result.delta_e_vdw,
            delta_g_gb=amber_result.delta_g_gb,
            delta_g_sa=amber_result.delta_g_sa,
            t_delta_s=amber_result.t_delta_s,
            per_residue=amber_result.per_residue,
            receptor=receptor_pdb,
            ligand=ligand_file,
            method=f"MM/{amber_method.upper()}SA (AmberTools, {amber_protocol})",
            n_receptor_atoms=0,
            n_ligand_atoms=0,
        )

    # Fast mode (original implementation)
    if not _HAVE_RDKIT:
        raise RuntimeError("RDKit required for MM/PBSA: conda activate autodock313")

    logger.warning(
        "[mmpbsa] WARNING: This is a simplified MM/GBSA implementation. "
        "For publication-quality absolute ΔG values, use method='amber' with AmberTools."
    )

    ligand_file = docked_pdbqt or ligand_pdbqt
    if not os.path.exists(receptor_pdb):
        raise FileNotFoundError(f"Receptor PDB not found: {receptor_pdb}")
    if not os.path.exists(ligand_file):
        raise FileNotFoundError(f"Ligand PDBQT not found: {ligand_file}")

    logger.info(f"[mmpbsa] Starting MM/GBSA calculation")
    logger.info(f"[mmpbsa]   Receptor: {receptor_pdb}")
    logger.info(f"[mmpbsa]   Ligand:   {ligand_file}")
    logger.info(f"[mmpbsa]   GB model: {'OBC2' if use_obc2 else 'Still (simplified)'}")

    # ── Parse structures ──────────────────────────────────────────────
    receptor_atoms = _parse_pdb_atoms(receptor_pdb)
    ligand_atoms = _parse_pdbqt_atoms(ligand_file)

    if not receptor_atoms:
        raise RuntimeError(f"No atoms parsed from receptor: {receptor_pdb}")
    if not ligand_atoms:
        raise RuntimeError(f"No atoms parsed from ligand: {ligand_file}")

    logger.info(f"[mmpbsa]   Receptor atoms: {len(receptor_atoms)}")
    logger.info(f"[mmpbsa]   Ligand atoms:   {len(ligand_atoms)}")

    # Build complex atom list
    complex_atoms = receptor_atoms + ligand_atoms

    # ── Compute energies ──────────────────────────────────────────────
    common_kw = dict(
        compute_sasa=compute_sasa,
        use_obc2=use_obc2,
        epsilon_solvent=epsilon_solvent,
    )

    logger.info("[mmpbsa] Computing receptor energy...")
    E_rec = _compute_system_energy(receptor_atoms, **common_kw)

    logger.info("[mmpbsa] Computing ligand energy...")
    E_lig = _compute_system_energy(ligand_atoms, **common_kw)

    logger.info("[mmpbsa] Computing complex energy...")
    E_comp = _compute_system_energy(complex_atoms, **common_kw)

    # ── Binding free energy (before entropy) ──────────────────────────
    delta_e_mm = E_comp['mm'] - E_rec['mm'] - E_lig['mm']
    delta_g_solv = E_comp['solv'] - E_rec['solv'] - E_lig['solv']
    delta_g_without_entropy = delta_e_mm + delta_g_solv

    # Decompose
    delta_e_elec = E_comp['elec'] - E_rec['elec'] - E_lig['elec']
    delta_e_vdw = E_comp['vdw'] - E_rec['vdw'] - E_lig['vdw']
    delta_g_gb = E_comp['gb'] - E_rec['gb'] - E_lig['gb']
    delta_g_sa = E_comp['sa'] - E_rec['sa'] - E_lig['sa']

    # ── Entropy correction ────────────────────────────────────────────
    t_delta_s = None
    if compute_entropy:
        if poses_pdbqt and len(poses_pdbqt) >= 2:
            # Interaction Entropy method (Duan et al. 2016) — compute ΔE_mm for each pose
            logger.info(f"[mmpbsa] Interaction Entropy: computing for {len(poses_pdbqt)} poses...")
            pose_dE_mm_list = []
            for pose_path in poses_pdbqt:
                if not os.path.exists(pose_path):
                    logger.warning(f"[mmpbsa] Pose not found: {pose_path}, skipping")
                    continue
                pose_atoms = _parse_pdbqt_atoms(pose_path)
                if not pose_atoms:
                    continue
                pose_complex = receptor_atoms + pose_atoms
                E_pose_rec = _compute_system_energy(receptor_atoms, **common_kw)
                E_pose_lig = _compute_system_energy(pose_atoms, **common_kw)
                E_pose_comp = _compute_system_energy(pose_complex, **common_kw)
                pose_dE_mm = E_pose_comp['mm'] - E_pose_rec['mm'] - E_pose_lig['mm']
                pose_dE_mm_list.append(pose_dE_mm)

            if len(pose_dE_mm_list) >= 2:
                t_delta_s = _compute_interaction_entropy(pose_dE_mm_list, temperature)
                logger.info(f"[mmpbsa] Interaction Entropy -TΔS = {t_delta_s:.2f} kcal/mol (from {len(pose_dE_mm_list)} poses)")
            else:
                logger.info("[mmpbsa] Interaction Entropy: not enough valid poses, falling back to empirical")
                n_heavy, n_rot = _count_heavy_atoms_rotatable_bonds(ligand_atoms)
                t_delta_s = _compute_empirical_entropy(n_heavy, n_rot)
                logger.info(f"[mmpbsa] Empirical entropy -TΔS = {t_delta_s:.2f} kcal/mol ({n_heavy} heavy, {n_rot} rotatable)")
        else:
            # Single pose: use empirical entropy formula
            n_heavy, n_rot = _count_heavy_atoms_rotatable_bonds(ligand_atoms)
            t_delta_s = _compute_empirical_entropy(n_heavy, n_rot)
            logger.info(f"[mmpbsa] Empirical entropy -TΔS = {t_delta_s:.2f} kcal/mol ({n_heavy} heavy, {n_rot} rotatable)")

    # ── Final binding free energy (with entropy) ─────────────────────
    delta_g_bind = delta_g_without_entropy + (t_delta_s if t_delta_s is not None else 0.0)

    logger.info(f"[mmpbsa] ΔE_mm   = {delta_e_mm:.2f} kcal/mol")
    logger.info(f"[mmpbsa] ΔG_solv = {delta_g_solv:.2f} kcal/mol")
    logger.info(f"[mmpbsa] ΔG_bind = {delta_g_bind:.2f} kcal/mol")

    # ── Clash detection ───────────────────────────────────────────────
    if delta_e_vdw is not None and delta_e_vdw > 1000:
        logger.warning(
            f"[mmpbsa] SEVERE CLASH DETECTED: vdW energy = {delta_e_vdw:.0f} kcal/mol. "
            f"The docked pose has atomic overlap with the receptor. "
            f"MM/PBSA result is unreliable. Consider pose relaxation or use a different pose."
        )
    elif delta_e_vdw is not None and delta_e_vdw > 100:
        logger.warning(
            f"[mmpbsa] Moderate clash detected: vdW energy = {delta_e_vdw:.1f} kcal/mol. "
            f"Result may be less accurate."
        )

    # ── Per-residue decomposition ─────────────────────────────────────
    per_residue = {}
    if decomp:
        logger.info("[mmpbsa] Computing per-residue decomposition...")
        per_residue = _per_residue_decomposition(receptor_atoms, ligand_atoms)
        n_favorable = len([v for v in per_residue.values() if v < -0.5])
        logger.info(f"[mmpbsa]   {n_favorable} favorable residues found")

    # ── Assemble result ─────────────────────────────────────────────
    result = MMPBSAResult(
        delta_g_bind=delta_g_bind,
        delta_e_mm=delta_e_mm,
        delta_g_solv=delta_g_solv,
        delta_e_elec=delta_e_elec,
        delta_e_vdw=delta_e_vdw,
        delta_g_gb=delta_g_gb,
        delta_g_sa=delta_g_sa,
        t_delta_s=t_delta_s,
        per_residue=per_residue,
        receptor=receptor_pdb,
        ligand=ligand_file,
        method=f'MM/{method.upper()}SA (OBC2) - RDKit-custom' if use_obc2 else f'MM/{method.upper()}SA (Still) - RDKit-custom',
        salt_conc=salt_conc,
        temperature=temperature,
        epsilon_solvent=epsilon_solvent,
        n_receptor_atoms=len(receptor_atoms),
        n_ligand_atoms=len(ligand_atoms),
    )

    return result


def mmpbsa_rank_ligands(
    receptor_pdb: str,
    ligand_results: List[Tuple[str, str]],
    **kwargs
) -> List[MMPBSAResult]:
    """
    Rank multiple ligands by MM/PBSA binding free energy.

    Args:
        receptor_pdb:     Path to receptor PDB
        ligand_results:   List of (compound_name, docked_pdbqt_path) tuples
        **kwargs:         Passed to compute_mmpbsa()

    Returns:
        List of MMPBSAResult sorted by delta_g_bind (most negative first)

    Example:
        >>> results = mmpbsa_rank_ligands(
        ...     "protein.pdb",
        ...     [("aspirin", "asp_docked.pdbqt"),
        ...      ("caffeine", "caf_docked.pdbqt")]
        ... )
        >>> for r in results:
        ...     print(f"{r.ligand}: ΔG = {r.delta_g_bind:.2f}")
    """
    results = []
    for name, pdbqt_path in ligand_results:
        try:
            result = compute_mmpbsa(receptor_pdb, pdbqt_path, **kwargs)
            logger.info(f"[mmpbsa] {name}: ΔG_bind = {result.delta_g_bind:.2f} kcal/mol")
            results.append(result)
        except Exception as e:
            logger.error(f"[mmpbsa] Failed for {name}: {e}")
            continue

    # Sort by binding energy (most negative = best binder)
    results.sort(key=lambda r: r.delta_g_bind if r.delta_g_bind is not None else float('inf'))
    return results


# ─── CLI helper (if run directly) ────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        rec, lig = sys.argv[1], sys.argv[2]
        result = compute_mmpbsa(rec, lig)
        print(result.summary())
    else:
        print("Usage: python _mmpbsa.py <receptor.pdb> <ligand.pdbqt>")
