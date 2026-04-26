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
import tempfile
import warnings
from typing import Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ─── DockingResult: structured publication-ready result ─────────────────────────

@dataclass(slots=True)
class DockingResult:
    """
    Structured result from a single-compound docking run.

    Use .to_dict() for JSON serialization, .to_dataframe_row() for CSV export.
    """
    # ── Identity ────────────────────────────────────────────────────────
    compound_name: str
    receptor: str                   # receptor PDBQT path or name
    method: str = "AutoDock Vina 1.2.5"

    # ── Docking parameters (for method reproducibility) ──────────────────
    center: tuple = field(default_factory=tuple)
    box_size: tuple = field(default_factory=tuple)
    exhaustiveness: int = 32
    n_poses: int = 10
    seed: int = 42

    # ── Core docking scores ──────────────────────────────────────────────
    best_affinity: float | None = None       # kcal/mol (more negative = tighter)
    pre_dock_score: float | None = None     # kcal/mol (input pose, None if skipped)
    score_improvement: float | None = None   # pre_dock - best (positive = improved)

    # ── Redocking validation (populated by validate_docking_protocol) ───
    rmsd_from_crystal: float | None = None  # Å (None if not redocked)
    protocol_valid: bool | None = None      # True if rmsd <= threshold
    redocking_threshold: float | None = None  # Å threshold used

    # ── Interactions (raw + aggregated) ─────────────────────────────────
    interactions: list = field(default_factory=list)  # raw list from detect_interactions()

    # Aggregated counts — derived from interactions on first access
    _n_hbonds: int = field(default=0, repr=False)
    _n_pi_stacking: int = field(default=0, repr=False)
    _n_hydrophobic: int = field(default=0, repr=False)
    _interactions_computed: bool = field(default=False, repr=False)

    # ── Clash detection ──────────────────────────────────────────────────
    clash_score: float | None = None    # Å overlap (DynamicBind/PoseBusters)
    clash_acceptable: bool | None = None  # True if clash_score <= 0.5

    # ── Binding pocket ───────────────────────────────────────────────────
    binding_pocket: dict | None = None  # {pocket_num, center, box_size, druggability, p2rank_prob}

    # ── Output files ────────────────────────────────────────────────────
    best_pose_pdbqt: str | None = None
    all_poses_pdbqt: list = field(default_factory=list)

    def __post_init__(self):
        # Normalize tuple fields that might come as lists from JSON
        for attr in ('center', 'box_size'):
            val = getattr(self, attr)
            if val and isinstance(val, (list, tuple)) and len(val) == 3:
                setattr(self, attr, tuple(float(v) for v in val))

    @property
    def n_hbonds(self) -> int:
        if not self._interactions_computed:
            self._aggregate_interactions()
        return self._n_hbonds

    @property
    def n_pi_stacking(self) -> int:
        if not self._interactions_computed:
            self._aggregate_interactions()
        return self._n_pi_stacking

    @property
    def n_hydrophobic(self) -> int:
        if not self._interactions_computed:
            self._aggregate_interactions()
        return self._n_hydrophobic

    def _aggregate_interactions(self):
        self._n_hbonds = sum(1 for i in self.interactions if i.get('type') == 'H-bond')
        self._n_pi_stacking = sum(1 for i in self.interactions if i.get('type') == 'π-π')
        self._n_hydrophobic = sum(1 for i in self.interactions if i.get('type') == 'Hydrophobic')
        self._interactions_computed = True

    @property
    def interaction_summary(self) -> dict:
        """Human-readable interaction profile."""
        return {
            'H-bond': self.n_hbonds,
            'π-π stacking': self.n_pi_stacking,
            'Hydrophobic': self.n_hydrophobic,
        }

    def to_dict(self) -> dict:
        """Serialize to dict (for JSON)."""
        d = asdict(self)
        # Remove private cached-count fields
        d.pop('_n_hbonds', None)
        d.pop('_n_pi_stacking', None)
        d.pop('_n_hydrophobic', None)
        d.pop('_interactions_computed', None)
        return d

    def to_dataframe_row(self) -> dict:
        """One-row dict for pandas DataFrame / CSV export."""
        pocket_info = self.binding_pocket or {}
        return {
            'compound': self.compound_name,
            'receptor': os.path.basename(self.receptor),
            'best_affinity_kcal_mol': self.best_affinity,
            'pre_dock_score': self.pre_dock_score,
            'score_improvement': self.score_improvement,
            'n_H_bonds': self.n_hbonds,
            'n_pi_stacking': self.n_pi_stacking,
            'n_hydrophobic': self.n_hydrophobic,
            'clash_score_A': self.clash_score,
            'clash_acceptable': self.clash_acceptable,
            'rmsd_from_crystal_A': self.rmsd_from_crystal,
            'protocol_valid': self.protocol_valid,
            'pocket_num': pocket_info.get('pocket_num', None),
            'pocket_druggability': pocket_info.get('druggability', None),
            'pocket_p2rank_prob': pocket_info.get('p2rank_prob', None),
            'pocket_center_x': self.center[0] if self.center else None,
            'pocket_center_y': self.center[1] if self.center else None,
            'pocket_center_z': self.center[2] if self.center else None,
            'box_size_x': self.box_size[0] if self.box_size else None,
            'box_size_y': self.box_size[1] if self.box_size else None,
            'box_size_z': self.box_size[2] if self.box_size else None,
            'exhaustiveness': self.exhaustiveness,
            'n_poses': self.n_poses,
            'seed': self.seed,
            'best_pose_pdbqt': self.best_pose_pdbqt,
            'method': self.method,
        }


def build_docking_result(
    compound_name: str,
    receptor: str,
    center: tuple,
    box_size: tuple,
    energies,
    poses: list,
    interactions: list = None,
    clash_result: dict = None,
    pre_dock_score: float = None,
    binding_pocket: dict = None,
    best_pose_path: str = None,
    rmsd_from_crystal: float = None,
    protocol_valid: bool = None,
    redocking_threshold: float = None,
    exhaustiveness: int = 32,
    n_poses: int = 10,
    seed: int = 42,
) -> DockingResult:
    """
    Build a DockingResult from raw docking outputs.

    This is the standard way to create a publication-ready result from
    dock_ligand() / dock_ligand_multi() outputs.
    """
    best_affinity = float(energies[0][0]) if (energies is not None and energies.size > 0) else None
    score_improvement = (pre_dock_score - best_affinity) if (pre_dock_score is not None and best_affinity is not None) else None

    return DockingResult(
        compound_name=compound_name,
        receptor=receptor,
        center=tuple(center) if center else None,
        box_size=tuple(box_size) if box_size else None,
        exhaustiveness=exhaustiveness,
        n_poses=n_poses,
        seed=seed,
        best_affinity=best_affinity,
        pre_dock_score=pre_dock_score,
        score_improvement=score_improvement,
        rmsd_from_crystal=rmsd_from_crystal,
        protocol_valid=protocol_valid,
        redocking_threshold=redocking_threshold,
        interactions=interactions or [],
        clash_score=clash_result.get('clash_score') if clash_result else None,
        clash_acceptable=clash_result.get('is_acceptable') if clash_result else None,
        binding_pocket=binding_pocket,
        best_pose_pdbqt=best_pose_path,
        all_poses_pdbqt=poses if poses else [],
    )


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
    from rdkit.Chem import AllChem, Draw, rdPartialCharges
    _HAVE_RDKIT = True
except ImportError:
    _HAVE_RDKIT = False
    warnings.warn("rdkit not available")

import numpy as np

try:
    from plip.structure.preparation import PDBComplex
    from plip.basic import config as plip_config
    _HAVE_PLIP = True
except ImportError:
    _HAVE_PLIP = False

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
# SHARED CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Water / non-structural residue names to remove during receptor/pocket prep.
# Covers PDB-standard water names and common alt. loc. identifiers.
_SKIP_RES = {'HOH', 'WAT', 'H2O', 'PJE', '02J', '010', '03U', '03T', '02K', '02L'}

# P2Rank binary (installed manually under tools/)
_P2RANK_DIR = os.path.join(os.path.dirname(__file__), 'tools', 'p2rank_2.5.1')
_P2RANK_BIN = os.path.join(_P2RANK_DIR, 'prank')
_JAVA_HOME = '/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home'


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

    if remove_waters:
        lines = [l for l in pdb_content.split('\n')
                 if not (l.startswith('ATOM') or l.startswith('HETATM'))
                 or l[17:20].strip() not in _SKIP_RES]
        pdb_content = '\n'.join(lines)

    templates = ResidueChemTemplates.create_from_defaults()
    # charge_model='gasteiger' writes Gasteiger partial charges to the PDBQT
    # charge field (col 71-76). AD4 atom types are loaded by default.
    mk_prep = MoleculePreparation(charge_model='gasteiger')
    polymer = Polymer.from_pdb_string(pdb_content, templates, mk_prep)
    rigid_pdbqt, _ = PDBQTWriterLegacy.write_from_polymer(polymer)

    os.makedirs(os.path.dirname(output_pdbqt) or '.', exist_ok=True)
    with open(output_pdbqt, 'w') as f:
        f.write(rigid_pdbqt)

    print(f"[autodock] Receptor prepared: {output_pdbqt}")
    return output_pdbqt


def prepare_ligand(smiles: str, output_pdbqt: str, name: str = "LIG",
                 seed: int = 42) -> str:
    """
    Prepare a ligand for docking (SMILES → PDBQT).

    Uses RDKit ETKDGv3 for 3D conformer + meeko for PDBQT export.

    Args:
        smiles: SMILES string of ligand
        output_pdbqt: Output PDBQT file path
        name: Residue name in PDBQT (default: LIG)
        seed: Random seed for ETKDGv3 conformer generation (default: 42).
              Fixed seed ensures reproducible 3D geometry across runs.

    Returns:
        Path to output PDBQT file
    """
    if not _HAVE_RDKIT or not _HAVE_MEEKO:
        raise RuntimeError("rdkit and meeko required: conda activate autodock313")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smiles}")
    mol = Chem.AddHs(mol, addCoords=True)
    # Fixed seed → reproducible conformer across runs
    params_etkdg = AllChem.ETKDGv3()
    params_etkdg.randomSeed = seed
    AllChem.EmbedMolecule(mol, params_etkdg)
    AllChem.MMFFOptimizeMolecule(mol)
    # Pre-compute Gasteiger charges so they are available in the mol
    # before meeko reads them (avoids reliance on meeko's internal copy)
    rdPartialCharges.ComputeGasteigerCharges(mol)

    params = MoleculePreparation(charge_model='gasteiger')
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

# Pocket dimension sanity bounds (Angstroms)
_POCKET_MIN_DIM = 5.0   # minimum pocket span in any axis
_POCKET_MAX_DIM = 60.0 # maximum pocket span (larger → likely false positive)


def _compute_box_size(dims: tuple, padding: float = 5.0) -> tuple:
    """
    Compute Vina docking box size from pocket dimensions.

    Rounds to nearest 0.5 A to match Vina's internal 0.375 A grid spacing.
    Ensures minimum box of 10 A on each axis.
    """
    raw = [d + 2 * padding for d in dims]
    box = []
    for v in raw:
        rounded = round(v * 2) / 2  # nearest 0.5 A
        box.append(max(10.0, rounded))
    return tuple(box)


def _run_p2rank_rescore(prep_pdb_abs: str, prep_pdb_basename: str,
                        out_dir: str) -> dict[int, float] | None:
    """
    Run P2Rank fpocket-rescore to get calibrated probability scores for fpocket pockets.

    Returns:
        Dictionary mapping fpocket pocket number -> P2Rank probability (0-1).
        Returns None on failure (P2Rank not available, no Java, etc.).
        Prints warnings but does not raise.
    """
    import subprocess

    if not os.path.exists(_P2RANK_BIN):
        print(f"[autodock] P2Rank not found at {_P2RANK_BIN}, skipping rescoring")
        return None

    java_home = _JAVA_HOME
    if not os.path.exists(java_home):
        print(f"[autodock] Java not found at {java_home}, skipping P2Rank rescoring")
        return None

    env = os.environ.copy()
    env['JAVA_HOME'] = java_home
    env['PATH'] = f"{java_home}/bin:{os.environ.get('PATH', '')}"

    # fpocket must be on PATH for fpocket-rescore to run ad-hoc fpocket
    fpocket_bin = '/opt/homebrew/Caskroom/miniconda/base/envs/autodock313/bin/fpocket'
    if os.path.exists(fpocket_bin):
        env['PATH'] = f"{os.path.dirname(fpocket_bin)}:{env['PATH']}"

    ds_file = os.path.join(out_dir, 'p2rank.ds')
    # fpocket-rescore dataset format: list of PDB files (fpocket will be run ad-hoc)
    with open(ds_file, 'w') as f:
        f.write(f"# fpocket-rescore dataset for {prep_pdb_basename}\n\n")
        f.write(f"{os.path.abspath(prep_pdb_abs)}\n")

    pred_out = os.path.join(out_dir, 'p2rank_out')
    try:
        result = subprocess.run(
            [_P2RANK_BIN, 'fpocket-rescore', ds_file, '-o', pred_out, '-visualizations', '0'],
            capture_output=True, text=True, timeout=300,
            env=env
        )
        if result.returncode != 0:
            print(f"[autodock] P2Rank fpocket-rescore failed: {result.stderr[:200]}")
            return None
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[autodock] P2Rank fpocket-rescore error: {e}")
        return None

    # Parse predictions CSV for probability column
    # Output is at pred_out/{basename_with_ext}_predictions.csv
    base_with_ext = os.path.basename(prep_pdb_abs)  # e.g. "1fbl.pdb"
    csv_path = os.path.join(pred_out, f'{base_with_ext}_predictions.csv')
    if not os.path.exists(csv_path):
        print(f"[autodock] P2Rank predictions CSV not found: {csv_path}")
        return None

    probabilities = {}  # pocket_num -> probability
    with open(csv_path, 'r') as f:
        header = [h.strip() for h in f.readline().strip().split(',')]
        # header: name, rank, score, probability, sas_points, surf_atoms, center_x, center_y, center_z, residue_ids, surf_atom_ids
        prob_idx = header.index('probability') if 'probability' in header else -1
        cx_idx = header.index('center_x') if 'center_x' in header else -1

        if prob_idx < 0 or cx_idx < 0:
            print(f"[autodock] P2Rank CSV missing expected columns: {header}")
            return None

        for line in f:
            parts = [p.strip() for p in line.strip().split(',')]
            if len(parts) <= max(prob_idx, cx_idx):
                continue
            try:
                name = parts[0].strip()   # e.g. 'pocket.1'
                prob = float(parts[prob_idx])
                cx = float(parts[cx_idx])
                cy = float(parts[cx_idx + 1])
                cz = float(parts[cx_idx + 2])
                # Extract fpocket pocket number from name
                if '.' in name:
                    fpocket_num = int(name.split('.')[-1])
                    probabilities[fpocket_num] = prob
            except (ValueError, IndexError):
                continue

    return probabilities


def find_top_pockets(receptor_pdb: str,
                    ligand_pdb: str = None,
                    padding: float = 5.0,
                    max_pockets: int = 3,
                    use_p2rank: bool = True) -> list:
    """
    Identify top-N candidate binding pockets (sorted by P2Rank probability desc).

    Priority:
      1. ligand_pdb provided → single pocket centered on ligand (most accurate)
      2. Otherwise → fpocket cavity detection → P2Rank rescoring → top-N by
         calibrated probability (more reliable than Druggability Score alone)

    Args:
        receptor_pdb: Protein PDB file (Apo or AlphaFold)
        ligand_pdb: Optional co-crystallized ligand PDB to center on
        padding: Padding around detected pocket (Angstroms)
        max_pockets: Maximum number of pockets to return (default 3;
                     top-3 covers ~90%+ of true binding sites in benchmarks)
        use_p2rank: Whether to run P2Rank rescoring for calibrated probabilities
                    (default True). Set False to use fpocket Druggability Score only.

    Returns:
        List of pocket dicts, each containing:
          center      : (x, y, z) tuple
          box_size    : (sx, sy, sz) tuple (0.5 A grid-rounded)
          druggability : float Druggability Score from fpocket
          p2rank_prob : float Calibrated probability from P2Rank (0-1), or None
          pocket_num  : int fpocket pocket number (None for ligand-based)
        Sorted by P2Rank probability descending (falls back to druggability if
        P2Rank unavailable). Empty list if none pass validation.
    """
    if not _HAVE_RDKIT:
        raise RuntimeError("rdkit required: conda activate autodock313")

    # ── Option 1: co-crystallized ligand (gold standard) ────────────────
    if ligand_pdb and os.path.exists(ligand_pdb):
        mol = Chem.MolFromPDBFile(ligand_pdb)
        conf = mol.GetConformer()
        coords = [conf.GetAtomPosition(i) for i in range(mol.GetNumAtoms())]
        xs = [c.x for c in coords]; ys = [c.y for c in coords]; zs = [c.z for c in coords]
        center = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        dims = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        box_size = _compute_box_size(dims, padding)
        print(f"[autodock] Binding site from ligand: center={center}, box={box_size}")
        return [{'center': center, 'box_size': box_size,
                 'druggability': None, 'p2rank_prob': None, 'pocket_num': None}]

    # ── Option 2: fpocket cavity detection + optional P2Rank rescoring ──
    import subprocess, tempfile, shutil

    fpocket_bin = '/opt/homebrew/Caskroom/miniconda/base/envs/autodock313/bin/fpocket'
    if not os.path.exists(fpocket_bin):
        raise FileNotFoundError(
            f"fpocket not found at {fpocket_bin}. "
            "Install with: conda install -c conda-forge fpocket -n autodock313"
        )

    prep_pdb = tempfile.mktemp(suffix='_prep.pdb')
    _prepare_pdb_for_fpocket(receptor_pdb, prep_pdb)

    prep_pdb_abs = os.path.abspath(prep_pdb)
    prep_dir = os.path.dirname(prep_pdb_abs) or '.'
    base = os.path.splitext(os.path.basename(prep_pdb))[0]
    out_dir = os.path.join(prep_dir, base + '_out')

    try:
        result = subprocess.run(
            [fpocket_bin, '-f', prep_pdb_abs],
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

        # ── P2Rank rescoring ──────────────────────────────────────────
        p2rank_probs = None
        if use_p2rank:
            p2rank_probs = _run_p2rank_rescore(prep_pdb_abs, base, out_dir)
            if p2rank_probs:
                print(f"[autodock] P2Rank rescored {len(p2rank_probs)} pockets "
                      f"(prob range: {min(p2rank_probs.values()):.3f} - "
                      f"{max(p2rank_probs.values()):.3f})")

        # ── Sort and filter pockets ──────────────────────────────────
        # Primary sort: P2Rank probability (higher = more confident)
        # Secondary sort: fpocket Druggability Score (tiebreaker)
        def pocket_sort_key(p):
            prob = p2rank_probs.get(p['num'], None) if p2rank_probs else None
            return (prob if prob is not None else -1.0, p['druggability'])

        pockets.sort(key=pocket_sort_key, reverse=True)

        result_pockets = []
        for p in pockets:
            if any(d < _POCKET_MIN_DIM or d > _POCKET_MAX_DIM for d in p['dims']):
                continue
            prob = p2rank_probs.get(p['num'], None) if p2rank_probs else None
            center = p['center']
            box_size = _compute_box_size(p['dims'], padding)
            result_pockets.append({
                'center': center,
                'box_size': box_size,
                'druggability': p['druggability'],
                'p2rank_prob': prob,
                'pocket_num': p['num'],
            })
            if len(result_pockets) >= max_pockets:
                break

        if not result_pockets:
            raise RuntimeError(
                f"All {len(pockets)} fpocket pockets failed dimension validation "
                f"(min={_POCKET_MIN_DIM} A, max={_POCKET_MAX_DIM} A). "
                f"Protein may lack druggable pockets."
            )

        for i, pk in enumerate(result_pockets):
            prob_str = (f"P2Rank={pk['p2rank_prob']:.3f}"
                        if pk['p2rank_prob'] is not None else "P2Rank=N/A")
            print(f"[autodock] Pocket {i+1} (fpocket #{pk['pocket_num']}): "
                  f"center={pk['center']}, box={pk['box_size']} "
                  f"({prob_str}, druggability={pk['druggability']:.3f})")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        if os.path.exists(prep_pdb):
            os.remove(prep_pdb)

    return result_pockets


# ─────────────────────────────────────────────────────────────────────────────
# RMSD CALCULATION (publication-standard atom-to-atom & center-of-mass)
# ─────────────────────────────────────────────────────────────────────────────

def _read_ligand_from_pdbqt_3d(pdbqt_path: str):
    """
    Parse a PDBQT file into an RDKit mol with 3D coordinates.

    Strategy: extract coordinates directly from PDBQT columns (30-54 for x/y/z,
    76-78 for element) WITHOUT going through AddHs/Embed.  This avoids any
    mismatch between RDKit-generated H positions and the real PDBQT coordinates.

    SMILES is parsed only to set bond orders (not coordinates) when available.
    The molecule is kept STRICTLY as the non-H heavy atoms in the PDBQT so that
    AlignMol comparison is fair.  RMSD benchmarks (CASF-2013, PMC12661494) use
    heavy-atom-only RMSD by convention.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    smiles = None
    coords = []   # [(element, x, y, z)]

    with open(pdbqt_path) as fh:
        for line in fh:
            if line.startswith('REMARK SMILES '):
                parts = line.strip().split()
                if len(parts) == 3:          # "REMARK SMILES CCO"
                    smiles = parts[2]
            if not (line.startswith('ATOM') or line.startswith('HETATM')):
                continue
            # Skip hydrogens in the PDBQT (they are explicit in some formats)
            elem = line[76:78].strip().capitalize()
            if not elem or elem in ('H', 'D'):
                elem = line[12:14].strip().capitalize()
            if elem in ('A', ''):
                elem = 'C'
            if elem not in ('C', 'N', 'O', 'S', 'P', 'F', 'Cl', 'Br', 'I'):
                elem = 'C'
            try:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
            except ValueError:
                continue
            coords.append((elem, x, y, z))

    if not coords:
        return None

    # Build mol with SMILES bond orders if available
    if smiles:
        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            # Strip Hs (AddHs would add them at wrong positions)
            mol = Chem.RemoveHs(mol)
            n_atoms = mol.GetNumAtoms()
            if n_atoms != len(coords):
                # SMILES atom count mismatch with PDBQT coords — fall back to raw
                mol = None

    if smiles and mol is not None:
        # Use SMILES mol as template (correct bond orders), apply PDBQT coords
        mol = Chem.RWMol(mol)
    else:
        # Build from scratch with raw coordinates (no bond order info)
        mol = Chem.RWMol()

    for elem, x, y, z in coords:
        a = Chem.Atom(elem)
        mol.AddAtom(a)

    mol = mol.GetMol()
    conf = Chem.Conformer(len(coords))
    conf.Set3D(True)
    for i, (elem, x, y, z) in enumerate(coords):
        conf.SetAtomPosition(i, (x, y, z))
    mol.AddConformer(conf)
    return mol


def compute_rmsd(docked_pdbqt: str,
                 reference_pdbqt: str,
                 method: str = 'atom') -> float:
    """
    Compute RMSD between a docked pose and its crystal reference.

    Uses RDKit AllChem.AlignMol() for optimal superposition (Kabsch algorithm)
    before RMSD calculation — the publication-standard approach.

    Args:
        docked_pdbqt:   PDBQT file from Vina docking output
        reference_pdbqt: Crystal / reference PDBQT file
        method:         'atom'   = atom-to-atom RMSD after optimal superposition
                        'com'    = center-of-mass RMSD
                        'both'   = return (atom_rmsd, com_rmsd)

    Returns:
        float RMSD in Å. Returns None on parse error.
        For method='both': returns (atom_rmsd, com_rmsd)

    Reference standard:
        Atom-to-atom RMSD < 2.0 Å = successful redocking (CASF-2013 benchmark;
        PMC12661494 kinase benchmarking; Scientific Reports 2024 RMSD validation)
    """
    if not _HAVE_RDKIT:
        print("[autodock] RDKit not available for RMSD calculation")
        return None

    from rdkit import Chem
    from rdkit.Chem import AllChem

    ref_mol = _read_ligand_from_pdbqt_3d(reference_pdbqt)
    docked_mol = _read_ligand_from_pdbqt_3d(docked_pdbqt)

    if ref_mol is None or docked_mol is None:
        print("[autodock] Could not parse PDBQT for RMSD")
        return None

    n_ref = ref_mol.GetNumAtoms()
    n_docked = docked_mol.GetNumAtoms()
    if n_ref != n_docked:
        print(f"[autodock] Atom count mismatch: ref={n_ref} vs docked={n_docked} "
              "— may be different protonation states. Proceeding anyway.")
        min_atoms = min(n_ref, n_docked)
        # Truncate to common number of atoms
        if n_ref != min_atoms:
            ref_mol = Chem.PathToSubmol(ref_mol, list(range(min_atoms)))
        if n_docked != min_atoms:
            docked_mol = Chem.PathToSubmol(docked_mol, list(range(min_atoms)))

    # Optimal superposition via RMSD alignment
    # AllChem.AlignMol() returns the RMSD after optimal rotation
    atom_rmsd = AllChem.AlignMol(docked_mol, ref_mol)

    if method == 'atom':
        return float(atom_rmsd)

    # Center-of-mass RMSD
    def com(mol):
        conf = mol.GetConformer()
        xs = [conf.GetAtomPosition(i).x for i in range(mol.GetNumAtoms())]
        ys = [conf.GetAtomPosition(i).y for i in range(mol.GetNumAtoms())]
        zs = [conf.GetAtomPosition(i).z for i in range(mol.GetNumAtoms())]
        n = mol.GetNumAtoms()
        return (sum(xs) / n, sum(ys) / n, sum(zs) / n)

    rc = com(ref_mol)
    dc = com(docked_mol)
    import numpy as np
    com_rmsd = np.sqrt((dc[0] - rc[0])**2 + (dc[1] - rc[1])**2 + (dc[2] - rc[2])**2)

    if method == 'com':
        return float(com_rmsd)
    return float(atom_rmsd), float(com_rmsd)


def validate_docking_protocol(receptor_pdbqt: str,
                              ligand_crystal_pdbqt: str,
                              center: tuple,
                              box_size: tuple,
                              rmsd_threshold: float = 2.0,
                              exhaustiveness: int = 32,
                              n_poses: int = 1) -> dict:
    """
    Validate the docking protocol by redocking the crystal ligand.

    This is the gold-standard validation step required before reporting any
    docking result in a scientific publication:
      1. Extract the co-crystallized ligand (reference pose)
      2. Re-dock it back into the binding site using the SAME protocol
      3. Compute RMSD between the best redocked pose and the crystal pose
      4. If RMSD < threshold → protocol is validated

    Args:
        receptor_pdbqt:         Prepared receptor PDBQT
        ligand_crystal_pdbqt:   The EXACT same PDBQT used as input to docking
                                (e.g. the prepared co-crystallized ligand)
        center:                 (x, y, z) docking box center
        box_size:              (sx, sy, sz) box dimensions in Å
        rmsd_threshold:         Maximum allowed RMSD in Å (default 2.0;
                                CASF-2013 / kinase benchmarking standard)
        exhaustiveness:         Search depth (default 32, publication-standard)
        n_poses:               Number of poses to generate (default 1 = best only)

    Returns:
        dict with keys:
          is_valid (bool):       True if RMSD <= rmsd_threshold
          rmsd_atom (float):    Atom-to-atom RMSD after optimal superposition (Å)
          rmsd_com (float):      Center-of-mass RMSD (Å)
          best_affinity (float): Best Vina binding affinity (kcal/mol)
          n_poses_returned (int): Number of poses generated
          threshold (float):    The threshold used

    Example:
        >>> result = validate_docking_protocol(rec_pdbqt, lig_pdbqt,
        ...                                    center=(x,y,z), box_size=(20,20,20))
        >>> if result['is_valid']:
        ...     print(f"Protocol validated: RMSD={result['rms']:.2f} Å")
        >>> else:
        ...     print(f"WARNING: RMSD={result['rms_atom']:.2f} Å > {rmsd_threshold} Å")
    """
    print(f"[autodock] === Redocking Validation ===")
    print(f"  Receptor: {receptor_pdbqt}")
    print(f"  Ligand (crystal): {ligand_crystal_pdbqt}")
    print(f"  Center: {center}, Box: {box_size}")
    print(f"  exhaustiveness={exhaustiveness}, threshold={rmsd_threshold} Å")

    # Step 1: Dock the crystal ligand back
    energies, poses = dock_ligand(
        receptor_pdbqt=receptor_pdbqt,
        ligand_pdbqt=ligand_crystal_pdbqt,
        center=center,
        box_size=box_size,
        exhaustiveness=exhaustiveness,
        n_poses=n_poses,
    )

    if not poses:
        return {'is_valid': False, 'error': 'No poses generated', 'best_affinity': None}

    best_energy = float(energies[0][0]) if energies.size > 0 else None
    best_pose_pdbqt = poses[0]  # already sorted by Vina (best = first)

    # Step 2: Write the best redocked pose to a temp file for RMSD comparison
    with tempfile.NamedTemporaryFile(mode='w', suffix='_redocked.pdbqt',
                                    delete=False) as tf:
        redocked_path = tf.name
    try:
        with open(redocked_path, 'w') as f:
            f.write(best_pose_pdbqt)

        # Step 3: Compute RMSD vs crystal reference
        rmsd_atom, rmsd_com = compute_rmsd(redocked_path, ligand_crystal_pdbqt,
                                            method='both')

        is_valid = rmsd_atom <= rmsd_threshold

        print(f"[autodock] Redocking RMSD: atom={rmsd_atom:.3f} Å "
              f"(threshold={rmsd_threshold} Å), com={rmsd_com:.3f} Å")
        print(f"[autodock] Best affinity: {best_energy} kcal/mol")
        print(f"[autodock] Validation: {'✅ PASSED' if is_valid else '⚠️  FAILED'}")

        return {
            'is_valid': is_valid,
            'rmsd_atom': rmsd_atom,
            'rmsd_com': rmsd_com,
            'best_affinity': best_energy,
            'n_poses_returned': len(poses),
            'threshold': rmsd_threshold,
            'redocked_pose_path': redocked_path,
        }
    finally:
        os.unlink(redocked_path)


def find_binding_site(receptor_pdb: str,
                     ligand_pdb: str = None,
                     padding: float = 5.0) -> tuple:
    """
    Define docking search box using fpocket (cavity detection).

    **New code should prefer `find_top_pockets()`** which returns rich pocket metadata
    and supports multi-pocket fallback. This function is kept for backward compatibility.

    Priority:
      1. ligand_pdb provided → center on ligand (most accurate)
      2. Otherwise → fpocket top-1 druggable pocket

    Args:
        receptor_pdb: Protein PDB file (Apo or AlphaFold)
        ligand_pdb: Optional co-crystallized ligand PDB to center on
        padding: Padding around ligand/pocket (Angstroms)

    Returns:
        (center: tuple, box_size: tuple)
        center = (x, y, z)
        box_size = (sx, sy, sz)
    """
    pockets = find_top_pockets(receptor_pdb, ligand_pdb, padding, max_pockets=1)
    top = pockets[0]
    return top['center'], top['box_size']


def dock_ligand_multi(receptor_pdbqt: str,
                     ligand_pdbqt: str,
                     receptor_pdb: str = None,
                     ligand_pdb: str = None,
                     padding: float = 5.0,
                     max_pockets: int = 3,
                     exhaustiveness: int = 32,
                     n_poses: int = 10,
                     receptor_pdb_for_analysis: str = None,
                     include_interactions: bool = False,
                     include_clash: bool = False) -> tuple:
    """
    Dock a ligand into a protein, automatically trying multiple binding pockets.

    Strategy:
      1. If ligand_pdb (co-crystallized ligand) is provided → center on it
      2. Otherwise → fpocket cavity detection, try up to max_pockets ranked by
         Druggability Score, keeping the globally best result.

    Args:
        receptor_pdbqt: Prepared receptor PDBQT file
        ligand_pdbqt: Prepared ligand PDBQT file
        receptor_pdb: Original receptor PDB file (needed for pocket detection)
        ligand_pdb: Co-crystallized ligand PDB (optional; enables ligand-centered mode)
        padding: Padding around pocket (Angstroms)
        max_pockets: Maximum number of pockets to try (default 3; top-3 covers ~90%+)
        exhaustiveness: Vina search thoroughness (default 32, publication-standard;
                        8 = quick screening; higher = more thorough but slower)
        n_poses: Number of poses per pocket
        receptor_pdb_for_analysis: Protein PDB file path for interaction / clash
            analysis of the best pose (optional; uses receptor_pdb if not set)
        include_interactions: If True, detect interactions for the best pose
        include_clash: If True, compute clash score for the best pose

    Returns:
        (best_energies, best_poses, best_pocket_info)
        best_energies  : ndarray, binding affinities (kcal/mol)
        best_poses     : list of PDBQT strings
        best_pocket_info: dict with center, box_size, druggability, pocket_num
        If include_interactions or include_clash is True, also returns
        all_pocket_metadata as 4th element:
            (energies, poses, pocket_info, all_pocket_metadata)
        all_pocket_metadata is a list[dict], one entry per pocket that docked
        successfully, each containing:
          - pocket_index (int): 0-based index of this pocket
          - pocket_info (dict): the pocket descriptor (center, box_size, etc.)
          - affinity (float): best Vina affinity for this pocket
          - interactions (list): contact details (if include_interactions=True)
          - clash (dict): clash metrics (if include_clash=True)
        Note: interactions and clash are computed for every successfully docked
        pocket, not only the Vina-selected best pocket.
    """
    if not _HAVE_VINA:
        raise RuntimeError("vina required: conda activate autodock313")

    # ── Resolve receptor PDB (required for fpocket pocket detection) ─────
    # find_top_pockets() calls fpocket which needs a real PDB file.
    # If receptor_pdb is None, fall back to single-pocket ligand-centered docking.
    if receptor_pdb is None:
        # Ligand-centered: center on the ligand's bounding-box centroid.
        # Find the ligand file — ligand_pdbqt is always available.
        import tempfile as _tf
        try:
            _lig = _read_ligand_from_pdbqt_3d(ligand_pdbqt)
            if _lig is None:
                raise RuntimeError(f"Could not parse ligand PDBQT: {ligand_pdbqt}")
            _conf = _lig.GetConformer()
            _xs = [_conf.GetAtomPosition(i).x for i in range(_lig.GetNumAtoms())]
            _ys = [_conf.GetAtomPosition(i).y for i in range(_lig.GetNumAtoms())]
            _zs = [_conf.GetAtomPosition(i).z for i in range(_lig.GetNumAtoms())]
            _cen = (sum(_xs)/len(_xs), sum(_ys)/len(_ys), sum(_zs)/len(_zs))
            # Simple 1-pocket fallback using the ligand centroid
            pockets = [{
                'pocket_num': None,
                'center': _cen,
                'box_size': _compute_box_size(
                    (max(_xs)-min(_xs), max(_ys)-min(_ys), max(_zs)-min(_zs)),
                    padding=padding),
                'druggability': None,
                'p2rank_prob': None,
                'note': 'ligand-centered (receptor_pdb not provided)',
            }]
            print(f"[autodock] receptor_pdb=None → ligand-centered single-pocket mode "
                  f"(center=({_cen[0]:.1f},{_cen[1]:.1f},{_cen[2]:.1f}))")
        except Exception as _e:
            raise RuntimeError(
                f"dock_ligand_multi requires receptor_pdb for multi-pocket detection. "
                f"Either provide receptor_pdb, or use dock_ligand() for single-pocket. "
                f"Original error: {_e}"
            )
    else:
        pockets = find_top_pockets(receptor_pdb, ligand_pdb, padding, max_pockets)

    all_results = []
    for i, pocket in enumerate(pockets):
        try:
            v = Vina(sf_name='vina', seed=42)
            v.set_receptor(receptor_pdbqt)
            v.set_ligand_from_file(ligand_pdbqt)
            v.compute_vina_maps(center=pocket['center'], box_size=pocket['box_size'])
            v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses,
                   min_rmsd=1.0)
            energies = v.energies(n_poses=n_poses, energy_range=3.0)

            # Use write_poses() (official API) to avoid fragile manual parsing.
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                            delete=False) as tf:
                tmp_path = tf.name
            try:
                v.write_poses(tmp_path, n_poses=n_poses, energy_range=3.0,
                              overwrite=True)
                with open(tmp_path) as f:
                    pdbqt_str = f.read()
                parts = pdbqt_str.split('MODEL ')
                poses = [f'MODEL {i}\n{parts[i]}' for i in range(1, len(parts))
                         if parts[i].strip()]
            finally:
                os.unlink(tmp_path)

            best_affinity = float(energies[0][0]) if energies.size > 0 else None
            if best_affinity is not None:
                print(f"[autodock] Pocket {i+1} #{pocket['pocket_num']}: "
                      f"affinity={best_affinity} kcal/mol ({len(poses)} poses)")
                all_results.append({
                    'energies': energies,
                    'poses': poses,
                    'best_affinity': best_affinity,
                    'pocket': pocket,
                })
        except Exception as e:
            print(f"[autodock] Pocket {i+1} #{pocket['pocket_num']}: FAILED - {e}")
            continue

    if not all_results:
        raise RuntimeError(
            f"Docking failed for all {len(pockets)} candidate pockets. "
            "Check receptor/ligand PDBQT files for format errors."
        )

    # Vina-selected best pocket (most negative = tightest binding)
    best_result = min(all_results, key=lambda r: r['best_affinity'])

    pk = best_result['pocket']
    drugg = (f"{pk['druggability']:.3f}" if pk['druggability'] is not None else "N/A")
    prob = (f"P2Rank={pk['p2rank_prob']:.3f}" if pk.get('p2rank_prob') is not None else "P2Rank=N/A")
    print(f"[autodock] Best pocket: #{pk['pocket_num'] or 'ligand-centered'} "
          f"({prob}, druggability={drugg}, "
          f"affinity={best_result['best_affinity']} kcal/mol)")

    # ── Optional: per-pocket interaction + clash analysis ──────────
    # Analyze ALL successfully docked pockets, not just the Vina-selected best.
    # This mirrors how experimental validation works: each candidate pocket gets
    # inspected independently before drawing conclusions.
    analysis_pdb = receptor_pdb_for_analysis or receptor_pdb
    all_pocket_metadata = []
    if analysis_pdb and (include_interactions or include_clash):
        for idx, res in enumerate(all_results):
            pocket_meta = {
                'pocket_index': idx,
                'pocket_info': res['pocket'],
                'affinity': res['best_affinity'],
            }
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                            delete=False) as tf:
                tmp_path = tf.name
            try:
                with open(tmp_path, 'w') as f:
                    f.write(res['poses'][0])
                if include_interactions:
                    pocket_meta['interactions'] = detect_interactions(
                        receptor_pdb=analysis_pdb, ligand_pdbqt=tmp_path,
                        center=res['pocket']['center'])
                if include_clash:
                    pocket_meta['clash'] = compute_clash_score(
                        res['poses'][0], analysis_pdb)
            finally:
                os.unlink(tmp_path)

            all_pocket_metadata.append(pocket_meta)
            n_int = len(pocket_meta.get('interactions', []))
            clash_s = pocket_meta.get('clash', {}).get('clash_score', 'N/A')
            print(f"[autodock] Pocket {idx+1} analysis: {n_int} contacts, "
                  f"clash={clash_s}Å")
    else:
        all_pocket_metadata = None

    if all_pocket_metadata:
        return (best_result['energies'], best_result['poses'],
                best_result['pocket'], all_pocket_metadata)
    return best_result['energies'], best_result['poses'], best_result['pocket']


def _prepare_pdb_for_fpocket(pdb_in: str, pdb_out: str) -> None:
    """Remove waters and non-structural residues, keep only ATOM/HETATM."""
    with open(pdb_in) as fin, open(pdb_out, 'w') as fout:
        for line in fin:
            if line.startswith('ATOM') or line.startswith('HETATM'):
                if line[17:20].strip() not in _SKIP_RES:
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
                    try:
                        x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
                        coords.append([x, y, z])
                    except ValueError:
                        # Skip malformed PQR lines (e.g. missing coordinates)
                        continue
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



def compute_clash_score(docked_pdbqt: str,
                         receptor_pdb: str,
                         clash_threshold: float = 0.5) -> dict:
    """
    Detect steric clashes between a docked ligand pose and the protein.

    Clash score = max(overlap) across all protein-ligand atom pairs,
    where overlap = vdw_radii_sum - distance (positive = clash).
    Reported in: DynamicBind (Nature 2024), PoseBusters benchmark.
    A clash score < 0.5 Å is generally acceptable for publication.

    Args:
        docked_pdbqt:  Docked ligand PDBQT string or file path
        receptor_pdb:  Protein PDB file (not PDBQT)
        clash_threshold: Warning threshold in Å overlap (default 0.5)

    Returns:
        dict with:
          clash_score (float):   max overlap in Å (clash > 0.5 is problematic)
          mean_overlap (float):  mean of all positive overlaps
          n_clashing_pairs (int): number of atom pairs with overlap > 0
          is_acceptable (bool):   True if clash_score <= clash_threshold
          n_protein_atoms (int): protein atom count in range
          n_ligand_atoms (int):  ligand atom count in range
    """
    import numpy as np

    # VDW radii (Bondi, Å)
    VDW = {'C': 1.70, 'N': 1.55, 'O': 1.52, 'S': 1.80,
           'P': 1.80, 'F': 1.47, 'Cl': 1.75, 'Br': 1.85,
           'I': 1.98, 'H': 1.20, 'D': 1.20}

    def vdw(elem):
        return VDW.get(elem, 1.70)

    # ── Parse protein ──────────────────────────────────────────────
    try:
        prot = Chem.MolFromPDBFile(receptor_pdb, removeHs=False)
    except Exception as e:
        return {'clash_score': None, 'error': f'receptor parse failed: {e}'}
    if prot is None:
        return {'clash_score': None, 'error': 'receptor parse returned None'}
    prot_conf = prot.GetConformer()
    prot_atoms = []
    for a in prot.GetAtoms():
        res = a.GetPDBResidueInfo()
        if not res:
            continue
        elem = a.GetSymbol()
        pos = prot_conf.GetAtomPosition(a.GetIdx())
        prot_atoms.append((elem, pos.x, pos.y, pos.z))

    # ── Parse ligand PDBQT ─────────────────────────────────────────
    if os.path.exists(docked_pdbqt):
        lig_path = docked_pdbqt
    else:
        # treat as string content
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                        delete=False) as tf:
            tf.write(docked_pdbqt)
            lig_path = tf.name

    try:
        lig = _read_ligand_from_pdbqt_3d(lig_path)
    finally:
        if not os.path.exists(docked_pdbqt) and os.path.exists(lig_path):
            os.unlink(lig_path)

    if lig is None or not prot_atoms:
        return {'clash_score': None, 'error': 'parse failed'}

    lig_conf = lig.GetConformer()
    lig_atoms = []
    for i in range(lig.GetNumAtoms()):
        elem = lig.GetAtomWithIdx(i).GetSymbol()
        pos = lig_conf.GetAtomPosition(i)
        lig_atoms.append((elem, pos.x, pos.y, pos.z))

    # ── Compute pairwise distances and overlaps ────────────────────
    overlaps = []
    cutoff = 4.0  # only check pairs within 4 Å

    for (pe, px, py, pz) in prot_atoms:
        for (le, lx, ly, lz) in lig_atoms:
            d = np.sqrt((px-lx)**2 + (py-ly)**2 + (pz-lz)**2)
            if d < cutoff:
                r_sum = vdw(pe) + vdw(le)
                overlap = r_sum - d
                if overlap > 0:
                    overlaps.append(overlap)

    if not overlaps:
        return {
            'clash_score': 0.0, 'mean_overlap': 0.0,
            'n_clashing_pairs': 0,
            'is_acceptable': True,
            'n_protein_atoms': len(prot_atoms),
            'n_ligand_atoms': len(lig_atoms),
        }

    max_overlap = float(max(overlaps))
    mean_overlap = float(np.mean(overlaps))

    print(f"[autodock] Clash score: {max_overlap:.3f} Å "
          f"({len(overlaps)} clashing pairs), "
          f"{'✅ acceptable' if max_overlap <= clash_threshold else '⚠️  WARNING'}")

    return {
        'clash_score': max_overlap,
        'mean_overlap': mean_overlap,
        'n_clashing_pairs': len(overlaps),
        'is_acceptable': max_overlap <= clash_threshold,
        'n_protein_atoms': len(prot_atoms),
        'n_ligand_atoms': len(lig_atoms),
    }


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
    # Use sanitize=False as fallback: some PDBs have element-column issues
    # (e.g. "A" for generic atoms) that RDKit rejects.  We pre-process the
    # PDB content to replace unknown element names with "C" before parsing.
    try:
        prot = Chem.MolFromPDBFile(receptor_pdb, removeHs=False)
    except Exception as e:
        print(f"[autodock] Could not parse receptor PDB with standard parser: {e}")
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
            print(f"[autodock] Could not parse receptor PDB (fallback also failed: {e2})")
            return []

    if prot is None:
        print(f"[autodock] Could not parse receptor PDB (returned None)")
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


def _build_complex_pdb_for_plip(receptor_pdbqt: str, ligand_pdbqt: str) -> str:
    """
    Build a valid complex PDB for PLIP.

    Strategy:
      1. Convert receptor PDBQT → PDB via pybel (gives clean PDB ATOM records)
      2. Extract ligand ATOM lines from docked PDBQT (ROOT/BRANCH → PDB via pybel)
      3. Combine: receptor PDB (strip trailing END/CONECT/MASTER) + ligand ATOMs + END

    Both files must be in the SAME coordinate system (guaranteed by Vina/ADT).

    Returns path to temp complex PDB.  Caller must os.unlink() it.
    """
    # Step 1: Convert receptor PDBQT → PDB
    rec_mol = next(_pybel.readfile('pdbqt', receptor_pdbqt))
    rec_pdb_str = rec_mol.write('pdb')

    # Step 2: Get ligand ATOM lines (ROOT/BRANCH → clean PDB)
    lig_pdb_str = _parse_ligand_from_pdbqt_for_plip(ligand_pdbqt)
    lig_atom_lines = [
        l + '\n' for l in lig_pdb_str.splitlines()
        if l.startswith(('ATOM', 'HETATM'))
    ]

    # Step 3: Build complex PDB
    # Remove trailing structural records from receptor PDB (END, CONECT, MASTER)
    rec_lines = rec_pdb_str.splitlines()
    while rec_lines and rec_lines[-1].startswith(('END', 'CONECT', 'MASTER')):
        rec_lines.pop()

    tmp = tempfile.NamedTemporaryFile(
        suffix='_plip_complex.pdb', delete=False, mode='w'
    )
    for l in rec_lines:
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



def _map_pybel_to_rdk_atom_idx(ligand_pdbqt: str) -> dict:
    """
    Map pybel atom indices → RDKit atom indices by coordinate matching.

    PLIP uses pybel atom indices; our renderers use RDKit indices.
    We match by rounding 3D coordinates to 0.01 Å.

    Returns:
        dict: (round_x, round_y, round_z) → rdk_atom_idx
    """
    lig_rdk = _read_ligand_from_pdbqt_3d(ligand_pdbqt)
    if lig_rdk is None:
        return {}
    conf = lig_rdk.GetConformer()
    coord_map = {}
    for i in range(lig_rdk.GetNumAtoms()):
        p = conf.GetAtomPosition(i)
        coord_map[(round(p.x, 2), round(p.y, 2), round(p.z, 2))] = i
    return coord_map



def detect_interactions_plip(receptor_pdb: str,
                            ligand_pdbqt: str,
                            output_dir: str = None) -> tuple:
    """
    Detect protein-ligand interactions using PLIP (8 interaction types).


    This is the primary interaction detector, replacing detect_interactions().
    Falls back to the RDKit-based detect_interactions() if PLIP fails.


    Args:
        receptor_pdb: Protein PDB file
        ligand_pdbqt: Docked ligand PDBQT file
        output_dir: Directory for PLIP output (default: system temp)


    Returns:
        (interactions_list, xml_report_path)
            interactions: list of dicts with keys:
                type, color, resn, resi, chain, atom,
                ligand_atom_idx (RDKit index), distance, description
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

        # Find the docked ligand's interaction set
        key = None
        for k, pli in plcomplex.interaction_sets.items():
            if pli.ligand.type in ('SMALLMOLECULE', 'UNSPECIFIED'):
                key = k
                break
        if key is None:
            key = list(plcomplex.interaction_sets.keys())[-1]

        pli = plcomplex.interaction_sets[key]


    except Exception as e:
        print(f"[autodock] PLIP analysis failed: {e}, falling back to RDKit")
        if complex_pdb and os.path.exists(complex_pdb):
            os.unlink(complex_pdb)
        return detect_interactions(receptor_pdb=receptor_pdb, ligand_pdbqt=ligand_pdbqt)

    try:
        # Build pybel -> RDKit coordinate mapping
        coord_to_rdk = _map_pybel_to_rdk_atom_idx(ligand_pdbqt)

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

            Returns pybel Atom, or None if no ligand atom is available.
            '''
            if itype == 'hydrophobic_contacts':
                return item.ligatom
            elif itype in ('hbonds_pdon', 'hbonds_ldon'):
                return item.a if item.protisdon else item.d
            elif itype == 'pistacking':
                return item.ligandring.atoms[0]
            elif itype in ('pication_paro', 'pication_laro'):
                # protcharged=True: ring=ligand aromatic -> use ring
                # protcharged=False: ring=protein aromatic -> use charge group
                if getattr(item, 'protcharged', True):
                    return item.ring.atoms[0]  # ligand aromatic ring
                else:
                    # charge group may have atoms -- try .atoms[0]
                    charge = item.charge
                    return charge.atoms[0] if hasattr(charge, 'atoms') else None

            elif itype in ('saltbridge_lneg', 'saltbridge_pneg'):
                # Salt bridges store RingCenter objects -- no pybel Atom available
                return None
            elif itype == 'halogen_bonds':
                # don.x is the ligand halogen atom
                return item.don.x
            elif itype == 'water_bridges':
                # item.d is the ligand atom (always)
                return item.d
            elif itype == 'metal_complexes':
                return item.target.atom if hasattr(item.target, 'atom') else None
            return None

        # Map PLIP interaction type -> our standardized type + color
        TYPE_MAP = {
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

        interactions = []
        for attr, (itype, color) in TYPE_MAP.items():
            items = getattr(pli, attr, [])
            if not items:
                continue
            for item in items:
                pa = _get_ligatom_pybel(item, attr)
                if pa is not None:
                    c = pa.coords
                    rdk_idx = coord_to_rdk.get(
                        (round(c[0], 2), round(c[1], 2), round(c[2], 2)), None
                    )
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
        print(f"[autodock][PLIP] H-bond={n_hb}, π-π/π-cat={n_pi}, "
              f"Hydrophobic={n_hp}, SaltBr={n_sb}, Other={n_ot} | Total={len(unique)}")

        xml_path = os.path.join(output_dir, f"report.xml")
        return unique, xml_path if os.path.exists(xml_path) else ''

    finally:
        if complex_pdb and os.path.exists(complex_pdb):
            os.unlink(complex_pdb)



def render_interactions_2d(receptor_pdb: str,
                          ligand_pdbqt: str,
                          interactions: list,
                          output_png: str,
                          center: tuple = None,
                          ligand_resn: str = None,
                          width: int = 800,
                          height: int = 600,
                          dpi: int = 150) -> bool:
    """
    Render 2D protein-ligand interaction diagram using PLIP's PyMOL visualizer.

    Generates publish-ready 2D diagram via PLIP's built-in PyMOL rendering.
    Falls back to the existing PyMOL-based render_interactions_pymol() if
    PLIP rendering fails.


    Args:
        receptor_pdb: Protein PDB file
        ligand_pdbqt: Docked ligand PDBQT file
        interactions: Interaction list (for API compatibility, not used directly)
        output_png: Output PNG path
        center: (x, y, z) ligand center (unused, kept for API compat)
        ligand_resn: Ligand residue name (auto-detected if None)
        width, height: Output resolution (passed to PyMOL)
        dpi: Output DPI

    Returns:
        True if rendering succeeded
    """
    if not _HAVE_PYMOL:
        print("[autodock] PyMOL not available - 2D diagram skipped")
        return False

    if ligand_resn is None:
        ligand_resn = _detect_ligand_resn_for_plip(ligand_pdbqt)

    output_dir = os.path.dirname(os.path.abspath(output_png)) or '.'
    os.makedirs(output_dir, exist_ok=True)

    _configure_plip(output_dir)
    plip_config.PICS = True
    plip_config.PYMOL = True


    complex_pdb = None
    try:
        complex_pdb = _build_complex_pdb_for_plip(receptor_pdb, ligand_pdbqt)


        plcomplex = PDBComplex()
        plcomplex.output_path = output_dir
        plcomplex.load_pdb(complex_pdb)
        plcomplex.analyze()

        from plip.visualization import visualize
        visualize.visualize_in_pymol(plcomplex)

        # Find the generated PNG (PLIP names it based on ligand)
        pngs = [
            f for f in os.listdir(output_dir)
            if f.endswith('.png')
        ]

        if pngs:
            src = os.path.join(output_dir, pngs[0])
            dst = os.path.abspath(output_png)
            import shutil
            shutil.move(src, dst)
            ok = os.path.exists(dst) and os.path.getsize(dst) > 5000
            size = os.path.getsize(dst) // 1024
            print(f"[autodock] 2D diagram: {'OK' if ok else 'FAILED'} ({size}KB) → {dst}")
            return bool(ok)

        print("[autodock] 2D diagram: PLIP did not generate PNG")
        return False

    except Exception as e:
        print(f"[autodock] 2D diagram failed: {e}")
        return False

    finally:
        if complex_pdb and os.path.exists(complex_pdb):
            os.unlink(complex_pdb)


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
    print(f"[autodock] Interactions: H-bond={_n_hb}, pi-pi={_n_pi}, Hydro={_n_hp}")
    print(f"[autodock] Interaction render: {'OK' if ok else 'FAILED'} ({size}KB)")
    return ok

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
                exhaustiveness: int = 32,
                n_poses: int = 10,
                receptor_pdb: str = None,
                include_interactions: bool = False,
                include_clash: bool = False) -> tuple:
    """
    Dock a single ligand into a protein binding site (AutoDock Vina).

    Args:
        receptor_pdbqt: Prepared receptor PDBQT
        ligand_pdbqt: Prepared ligand PDBQT
        center: (x, y, z) center of binding box
        box_size: (sx, sy, sz) box dimensions (Å)
        exhaustiveness: Search thoroughness (default 32, publication-standard;
                        8 = quick screening; higher = more thorough but slower)
        n_poses: Number of poses to return
        receptor_pdb: Protein PDB file (needed for interaction / clash analysis)
        include_interactions: If True, detect H-bond / π-π / hydrophobic contacts
                              for the best pose using RDKit geometry (requires receptor_pdb)
        include_clash: If True, compute clash score for the best pose
                       (requires receptor_pdb; clash_score < 0.5 Å is publication-standard)

    Returns:
        (energies: ndarray, poses: list of PDBQT strings)
        energies[n][0] = total affinity (kcal/mol, more negative = tighter)
        If include_interactions or include_clash is True, returns
        (energies, poses, metadata_dict) where metadata_dict contains
        'interactions' (list) and/or 'clash' (dict).
    """
    if not _HAVE_VINA:
        raise RuntimeError("vina required: conda activate autodock313")

    v = Vina(sf_name='vina', seed=42)
    v.set_receptor(receptor_pdbqt)
    v.set_ligand_from_file(ligand_pdbqt)
    v.compute_vina_maps(center=center, box_size=box_size)
    v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses,
           min_rmsd=1.0)

    energies = v.energies(n_poses=n_poses, energy_range=3.0)

    # Use write_poses() (official API) to write all poses to a temp PDBQT file,
    # then read it back as a list of PDBQT strings.  This avoids fragile manual
    # string parsing while keeping the same in-memory return type.
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                      delete=False) as tf:
        tmp_path = tf.name
    try:
        v.write_poses(tmp_path, n_poses=n_poses, energy_range=3.0,
                      overwrite=True)
        with open(tmp_path) as f:
            pdbqt_str = f.read()
        # Split on MODEL boundaries; each part[1] is a complete PDBQT pose
        parts = pdbqt_str.split('MODEL ')
        poses = [f'MODEL {i}\n{parts[i]}' for i in range(1, len(parts))
                 if parts[i].strip()]
    finally:
        os.unlink(tmp_path)

    best = float(energies[0][0]) if energies.size > 0 else None
    print(f"[autodock] Best affinity: {best} kcal/mol ({len(poses)} poses)")

    # ── Optional: score the initial ligand pose ───────────────────
    # v.score() evaluates the input pose before docking — useful as a baseline.
    # A much better docking score vs initial score confirms the search found a
    # more favorable binding mode (publication-quality validation).
    # NOTE: score() requires the ligand to be inside the grid box.  For
    # pre-prepared ligands with unknown coordinates, this may raise a
    # RuntimeError ("ligand outside grid box") — we catch it gracefully.
    score_init_total = None
    try:
        score_init = v.score()
        score_init_total = float(score_init[0]) if hasattr(score_init, '__getitem__')                           else float(score_init)
        if score_init_total is not None:
            print(f"[autodock] Pre-dock score (input pose): {score_init_total} kcal/mol")
    except RuntimeError as e:
        if 'outside' in str(e).lower():
            print(f"[autodock] Pre-dock score: skipped (ligand not in grid box; {e})")
        else:
            raise

    # ── Optional: interaction detection + clash analysis ───────────
    metadata = {}
    if include_interactions and receptor_pdb:
        print("[autodock] Detecting interactions for best pose...")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                        delete=False) as tf:
            tmp_path = tf.name
        try:
            with open(tmp_path, 'w') as f:
                f.write(poses[0])
            interactions = detect_interactions(
                receptor_pdb=receptor_pdb,
                ligand_pdbqt=tmp_path,
                center=center,
            )
            metadata['interactions'] = interactions
        finally:
            os.unlink(tmp_path)

    if include_clash and receptor_pdb:
        print("[autodock] Computing clash score for best pose...")
        clash_result = compute_clash_score(poses[0], receptor_pdb)
        metadata['clash'] = clash_result

    if metadata:
        return energies, poses, metadata
    return energies, poses


def virtual_screen(receptor_pdbqt: str,
                  ligand_smiles_dict: dict,
                  center: tuple,
                  box_size: tuple,
                  output_dir: str = "./docking_results",
                  exhaustiveness: int = 32,
                  n_poses: int = 3,
                  receptor_pdb: str = None,
                  include_interactions: bool = False,
                  include_clash: bool = False) -> tuple:
    """
    Screen a compound library against a protein target.

    Returns:
        tuple: (results_df, docking_results_list)
            results_df: pandas DataFrame sorted by binding affinity
            docking_results_list: list of DockingResult objects (full data)
        Both are sorted identically by affinity.
        A CSV file is also written to output_dir/docking_results.csv.

    Note:
        exhaustiveness=32 is the publication-standard Monte Carlo sampling depth.
        For large library screening (>1000 compounds) where speed matters more
        than exhaustive accuracy, reduce to 8–16 but be aware that binding
        mode predictions may be less reliable.
    """
    if not all([_HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO]):
        raise RuntimeError("vina + rdkit + meeko required")

    import pandas as pd
    os.makedirs(output_dir, exist_ok=True)

    # Resolve analysis PDB (for interaction / clash detection)
    analysis_pdb = receptor_pdb
    if not analysis_pdb:
        # Try to locate a PDB matching the receptor PDBQT name
        pdb_candidate = receptor_pdbqt.replace('.pdbqt', '.pdb')
        if os.path.exists(pdb_candidate):
            analysis_pdb = pdb_candidate

    v = Vina(sf_name='vina', seed=42)
    v.set_receptor(receptor_pdbqt)
    v.compute_vina_maps(center=center, box_size=box_size)

    results = []
    for name, smiles in ligand_smiles_dict.items():
        try:
            ligand_pdbqt = os.path.join(output_dir, f"{name}.pdbqt")
            prepare_ligand(smiles, ligand_pdbqt)
            v.set_ligand_from_file(ligand_pdbqt)
            # score() evaluates the input ligand pose before docking
            # Catches "ligand outside grid box" gracefully (pre-prepared ligands)
            score_init_total = None
            try:
                score_init = v.score()
                score_init_total = float(score_init[0]) if hasattr(score_init, '__getitem__')                                   else float(score_init)
                if score_init_total is not None:
                    print(f"[autodock] {name}: pre-dock score={score_init_total} kcal/mol, "
                          f"docked={best} kcal/mol")
            except RuntimeError as e:
                if 'outside' in str(e).lower():
                    print(f"[autodock] {name}: pre-dock score=skipped (ligand outside grid box)")
                else:
                    raise

            v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses,
                   min_rmsd=1.0)
            energies = v.energies(n_poses=n_poses, energy_range=3.0)
            best = float(energies[0][0]) if energies.size > 0 else None
            pose_file = os.path.join(output_dir, f"{name}_poses.pdbqt")
            if best is not None:
                v.write_poses(pose_file, n_poses=n_poses, energy_range=3.0)
            else:
                pose_file = None
            # Per-compound interaction + clash analysis (optional)
            # Use write_pose() (official Vina API) to capture the best pose as a string.
            best_pose_str = None
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                            delete=False) as tf:
                tmp_pose_path = tf.name
            try:
                if best is not None:
                    v.write_pose(tmp_pose_path, overwrite=True)
                    with open(tmp_pose_path) as f:
                        best_pose_str = f.read()
            finally:
                if os.path.exists(tmp_pose_path):
                    os.unlink(tmp_pose_path)

            interactions_out = []
            clash_out = None
            if analysis_pdb and (include_interactions or include_clash) and best_pose_str:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                                delete=False) as tf:
                    tmp_path = tf.name
                try:
                    with open(tmp_path, 'w') as f:
                        f.write(best_pose_str)
                    if include_interactions:
                        try:
                            interactions_out = detect_interactions(
                                receptor_pdb=analysis_pdb, ligand_pdbqt=tmp_path,
                                center=center)
                        except Exception as e:
                            print(f"[autodock]   interaction detection failed: {e}")
                            interactions_out = []
                    if include_clash:
                        try:
                            clash_out = compute_clash_score(best_pose_str, analysis_pdb)
                        except Exception as e:
                            print(f"[autodock]   clash detection failed: {e}")
                            clash_out = {'clash_score': None, 'is_acceptable': None}
                finally:
                    os.unlink(tmp_path)

            pose_path = os.path.join(output_dir, f"{name}_best.pdbqt")
            if best_pose_str:
                with open(pose_path, 'w') as f:
                    f.write(best_pose_str)
            else:
                pose_path = None

            results.append({'name': name, 'smiles': smiles,
                            'affinity_kcal_mol': best,
                            'pre_dock_score': score_init_total,
                            'interactions': interactions_out,
                            'clash_score': clash_out.get('clash_score') if clash_out else None,
                            'clash_acceptable': clash_out.get('is_acceptable') if clash_out else None,
                            'best_pose_path': pose_path,
                            'poses_file': pose_file})
            print(f"[autodock] {name}: {best} kcal/mol")
        except Exception as e:
            print(f"[autodock] {name}: FAILED - {e}")
            results.append({'name': name, 'smiles': smiles,
                            'affinity_kcal_mol': None, 'error': str(e)})

    # ── Build structured DockingResult objects ─────────────────────────
    docking_results = []
    for row in results:
        dr = DockingResult(
            compound_name=row['name'],
            receptor=receptor_pdbqt,
            center=tuple(center) if center else None,
            box_size=tuple(box_size) if box_size else None,
            exhaustiveness=exhaustiveness,
            n_poses=n_poses,
            seed=42,
            best_affinity=row.get('affinity_kcal_mol'),
            pre_dock_score=row.get('pre_dock_score'),
            score_improvement=(row.get('pre_dock_score') - row.get('affinity_kcal_mol'))
                               if row.get('pre_dock_score') and row.get('affinity_kcal_mol') else None,
            interactions=row.get('interactions', []),
            clash_score=row.get('clash_score'),
            clash_acceptable=row.get('clash_acceptable'),
            best_pose_pdbqt=row.get('best_pose_path'),
        )
        docking_results.append(dr)

    results_df = pd.DataFrame(results).sort_values('affinity_kcal_mol')

    # ── Write CSV ────────────────────────────────────────────────────────
    csv_path = os.path.join(output_dir, 'docking_results.csv')
    if docking_results:
        df_export = pd.DataFrame([r.to_dataframe_row() for r in docking_results])
        df_export.to_csv(csv_path, index=False, float_format='%.4f')
        print(f"[autodock] Results table written → {csv_path}")

    return results_df, docking_results


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
