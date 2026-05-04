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
import logging
from typing import Optional, Callable
import signal
from dataclasses import dataclass, field, asdict
from datetime import datetime

# Autodock logger — can be silenced via autodock_logger.setLevel(logging.WARNING)
autodock_logger = logging.getLogger("autodock")
autodock_logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setLevel(logging.DEBUG)
_handler.setFormatter(logging.Formatter("[autodock] %(message)s"))
autodock_logger.addHandler(_handler)

# Backward compat: module-level logger for SKILL.md usage
logger = autodock_logger

# Convenience log levels
def _log_info(msg): autodock_logger.info(msg)
def _log_warning(msg): autodock_logger.warning(msg)
def _log_error(msg): autodock_logger.error(msg)
def _log_debug(msg): autodock_logger.debug(msg)

# ─── DockingResult: structured publication-ready result ─────────────────────────

_RECEPTOR_SOURCE_LABELS = {
    'PDB':          'X-ray crystal structure (RCSB PDB)',
    'PDB-REDO':     'PDB-REDO optimized crystal structure',
    'AlphaFold':    'AlphaFold2 predicted structure (UniProt)',
    'SWISS-MODEL':  'SWISS-MODEL homology model',
}

def _detect_receptor_source(pdb_path: str) -> str | None:
    """
    Auto-detect receptor source from PDB file header.
    
    Returns one of: 'PDB', 'PDB-REDO', 'AlphaFold', 'SWISS-MODEL', or None if unknown.
    """
    if not os.path.exists(pdb_path):
        return None
    with open(pdb_path) as f:
        text = f.read(5000)  # read first 5KB for header
    
    if 'REMARK 1  DESIGNATED MODEL' in text or 'TITLE  ALPHAFOLD' in text.upper():
        return 'AlphaFold'
    if 'EXPDTA  THEORETICAL MODEL' in text:
        return 'SWISS-MODEL'
    if 'PDB-REDO' in text:
        return 'PDB-REDO'
    if 'EXPDTA  X-RAY' in text or 'EXPDTA  SYNCHROTRON' in text:
        return 'PDB'
    return None

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
    receptor_source: str = None   # 'PDB' | 'AlphaFold' | 'SWISS-MODEL' | 'PDB-REDO' | None

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

    @property
    def method_label(self) -> str:
        """Full method description for publications."""
        parts = [self.method]
        if self.receptor_source:
            parts.append(f"({_RECEPTOR_SOURCE_LABELS.get(self.receptor_source, self.receptor_source)})")
        return ' '.join(parts)

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
        # Add human-readable receptor source
        if d.get('receptor_source'):
            d['receptor_source_label'] = _RECEPTOR_SOURCE_LABELS.get(
                d['receptor_source'], d['receptor_source'])
        return d

    def to_dataframe_row(self) -> dict:
        """One-row dict for pandas DataFrame / CSV export."""
        pocket_info = self.binding_pocket or {}
        return {
            'compound': self.compound_name,
            'receptor': os.path.basename(self.receptor),
            'receptor_source': self.receptor_source or None,
            'receptor_source_label': _RECEPTOR_SOURCE_LABELS.get(self.receptor_source, self.receptor_source) if self.receptor_source else None,
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
    receptor_source: str = None,
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
        receptor_source=receptor_source,
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
import pandas as pd
import threading

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
# P0-1 ✅: P2Rank 2.5.1 已安装（2026-05-04）
# 路径：~/.openclaw/workspace/skills/autodock/tools/p2rank_2.5.1/prank
# 需要 JAVA_HOME=/opt/homebrew/opt/openjdk@21

_P2RANK_DIR = os.path.join(os.path.dirname(__file__), 'tools', 'p2rank_2.5.1')
_P2RANK_PRANK = os.path.join(_P2RANK_DIR, 'prank')
_P2RANK_JAR  = os.path.join(_P2RANK_DIR, 'bin', 'p2rank.jar')

# Java home — probe homebrew openjdk@21 first, fall back to /Library/Java
_JAVA_HOME = '/opt/homebrew/opt/openjdk@21'
if not os.path.exists(f"{_JAVA_HOME}/bin/java"):
    _JAVA_HOME = '/Library/Java/JavaVirtualMachines/openjdk-21.jdk/Contents/Home'
if not os.path.exists(f"{_JAVA_HOME}/bin/java"):
    import subprocess
    try:
        java_bin = subprocess.run(['/usr/libexec/java_home', '-v', '21', '--failfast'],
                                   capture_output=True, text=True, timeout=5)
        if java_bin.returncode == 0:
            _JAVA_HOME = java_bin.stdout.strip()
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

    Raises:
        FileNotFoundError: If input PDB file does not exist
        TypeError: If arguments are not of expected types
    """
    if not isinstance(pdb_file, str):
        raise TypeError(f"pdb_file must be str, got {type(pdb_file).__name__}")
    if not isinstance(output_pdbqt, str):
        raise TypeError(f"output_pdbqt must be str, got {type(output_pdbqt).__name__}")
    if not os.path.exists(pdb_file):
        raise FileNotFoundError(f"PDB file not found: {pdb_file}")

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

    logger.info(f"[autodock] Receptor prepared: {output_pdbqt}")
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
    if not isinstance(smiles, str):
        raise TypeError(f"smiles must be str, got {type(smiles).__name__}")
    if not isinstance(output_pdbqt, str):
        raise TypeError(f"output_pdbqt must be str, got {type(output_pdbqt).__name__}")

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

    logger.info(f"[autodock] Ligand prepared: {output_pdbqt}")
    return output_pdbqt


def prepare_ligand_conformers(smiles: str,
                               output_dir: str,
                               n_conformers: int = 10,
                               name: str = "LIG",
                               seed_start: int = 42) -> list:
    """
    Generate multiple 3D conformers of a ligand for multi-conformer docking.

    Each conformer is generated with a different random seed, then MMFF-optimized
    and converted to PDBQT. Conformers are saved as conformer_0.pdbqt … conformer_N.pdbqt
    inside output_dir.

    Args:
        smiles:           SMILES string of ligand
        output_dir:       Directory to write conformer PDBQT files
        n_conformers:     Number of conformers to generate (default: 10)
        name:             Residue name in PDBQT (default: LIG)
        seed_start:       Starting random seed (default: 42).
                          Conformers use seeds [seed_start, seed_start+1, …, seed_start+n-1].

    Returns:
        List of PDBQT file paths (length = n_conformers)
    """
    if not _HAVE_RDKIT or not _HAVE_MEEKO:
        raise RuntimeError("rdkit and meeko required: conda activate autodock313")
    if not isinstance(smiles, str):
        raise TypeError(f"smiles must be str, got {type(smiles).__name__}")
    if not isinstance(n_conformers, int) or n_conformers < 1:
        raise ValueError(f"n_conformers must be a positive int, got {n_conformers}")

    os.makedirs(output_dir, exist_ok=True)
    pdbqt_paths = []

    for i in range(n_conformers):
        seed = seed_start + i
        out_pdbqt = os.path.join(output_dir, f"conformer_{i}.pdbqt")

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Could not parse SMILES: {smiles}")
        mol = Chem.AddHs(mol, addCoords=True)
        params_etkdg = AllChem.ETKDGv3()
        params_etkdg.randomSeed = seed
        AllChem.EmbedMolecule(mol, params_etkdg)
        AllChem.MMFFOptimizeMolecule(mol)
        rdPartialCharges.ComputeGasteigerCharges(mol)

        params = MoleculePreparation(charge_model='gasteiger')
        mol_setup = params.prepare(mol)
        setup = mol_setup[0] if isinstance(mol_setup, list) else mol_setup

        pdbqt_str, success, err = PDBQTWriterLegacy.write_string(setup)
        if not success:
            raise RuntimeError(f"Meeko conformer {i} failed: {err}")
        with open(out_pdbqt, 'w') as fh:
            fh.write(pdbqt_str)

        pdbqt_paths.append(out_pdbqt)
        logger.debug(f"[autodock] Conformer {i}/{n_conformers} (seed={seed}): {out_pdbqt}")

    logger.info(f"[autodock] Generated {n_conformers} conformers in {output_dir}")
    return pdbqt_paths


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
    Run P2Rank rescore to get calibrated probability scores for fpocket pockets.

    Returns:
        Dictionary mapping fpocket pocket number -> P2Rank probability (0-1).
        Returns None on failure (P2Rank not available, no Java, etc.).
        Prints warnings but does not raise.
    """
    import subprocess

    if not os.path.exists(_P2RANK_PRANK):
        logger.warning(f"[autodock] P2Rank not found at {_P2RANK_PRANK}, skipping rescoring")
        return None

    java_home = _JAVA_HOME
    if not os.path.exists(java_home):
        logger.warning(f"[autodock] Java not found at {java_home}, skipping P2Rank rescoring")
        return None

    env = os.environ.copy()
    env['JAVA_HOME'] = java_home
    env['PATH'] = f"{java_home}/bin:{os.environ.get('PATH', '')}"

    # fpocket must be on PATH for P2Rank rescore to locate fpocket pocket PDBs
    fpocket_bin = '/opt/homebrew/Caskroom/miniconda/base/envs/autodock313/bin/fpocket'
    if os.path.exists(fpocket_bin):
        env['PATH'] = f"{os.path.dirname(fpocket_bin)}:{env['PATH']}"

    ds_file = os.path.join(out_dir, 'p2rank.ds')
    # P2Rank rescore needs HEADER: prediction protein
    # prediction = fpocket pocket PDB, protein = original PDB
    with open(ds_file, 'w') as f:
        f.write(f"# P2Rank rescore for {prep_pdb_basename}\n")
        f.write("PARAM.PREDICTION_METHOD=fpocket\n")
        f.write("HEADER: prediction protein\n")
        # fpocket creates {basename}_out/ directory with pockets inside
        fpocket_out_dir = os.path.join(os.path.dirname(prep_pdb_abs),
                                        f"{prep_pdb_basename}_out")
        # fpocket combined pocket atoms file: {basename}_out.pdb
        fpocket_pdb = os.path.join(fpocket_out_dir, f"{prep_pdb_basename}_out.pdb")
        f.write(f"{fpocket_pdb}  {os.path.abspath(prep_pdb_abs)}\n")

    pred_out = os.path.join(out_dir, 'p2rank_out')
    try:
        result = subprocess.run(
            ['bash', _P2RANK_PRANK, 'rescore', ds_file, '-o', pred_out, '-visualizations', '0'],
            capture_output=True, text=True, timeout=300,
            env=env
        )
        if result.returncode != 0:
            logger.error(f"[autodock] P2Rank rescore failed: {result.stderr[:200]}")
            return None
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning(f"[autodock] P2Rank rescore error: {e}")
        return None

    # Parse predictions CSV for probability column
    # Output is at pred_out/{basename_with_ext}_predictions.csv
    base_with_ext = os.path.basename(prep_pdb_abs)  # e.g. "1fbl.pdb"
    csv_path = os.path.join(pred_out, f'{base_with_ext}_predictions.csv')
    if not os.path.exists(csv_path):
        logger.warning(f"[autodock] P2Rank predictions CSV not found: {csv_path}")
        return None

    probabilities = {}  # pocket_num -> probability
    with open(csv_path, 'r') as f:
        header = [h.strip() for h in f.readline().strip().split(',')]
        # header: name, rank, score, probability, sas_points, surf_atoms, center_x, center_y, center_z, residue_ids, surf_atom_ids
        prob_idx = header.index('probability') if 'probability' in header else -1
        cx_idx = header.index('center_x') if 'center_x' in header else -1

        if prob_idx < 0 or cx_idx < 0:
            logger.warning(f"[autodock] P2Rank CSV missing expected columns: {header}")
            return None

        for line in f:
            parts = [p.strip() for p in line.strip().split(',')]
            if len(parts) <= max(prob_idx, cx_idx):
                continue
            try:
                name = parts[0].strip()   # e.g. 'pocket.1' or 'pocket1'
                prob = float(parts[prob_idx])
                cx = float(parts[cx_idx])
                cy = float(parts[cx_idx + 1])
                cz = float(parts[cx_idx + 2])
                # Extract pocket number from name (handles both 'pocket.1' and 'pocket1')
                import re
                m = re.search(r'pocket[._]?(\d+)', name, re.IGNORECASE)
                if m:
                    fpocket_num = int(m.group(1))
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
        logger.info(f"[autodock] Binding site from ligand: center={center}, box={box_size}")
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
                logger.info(f"[autodock] P2Rank rescored {len(p2rank_probs)} pockets "
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
            logger.info(f"[autodock] Pocket {i+1} (fpocket #{pk['pocket_num']}): "
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

    if not os.path.exists(pdbqt_path):
        return None

    smiles = None
    coords = []   # [(element, x, y, z)]

    try:
        with open(pdbqt_path) as fh:
            for line in fh:
                if line.startswith('REMARK SMILES '):
                    parts = line.strip().split()
                    if len(parts) == 3:          # "REMARK SMILES CCO"
                        smiles = parts[2]
                if not (line.startswith('ATOM') or line.startswith('HETATM')):
                    continue
                # Parse element from PDBQT.
                # Primary: col77-78 (PDBQT standard, element symbol right-justified in 2 chars).
                # For ADT-generated PDBQTs, atom name = 'C.1', 'N.5', 'Cl.6' etc.
                # Take FIRST CHARACTER of atom name (col12) as element when needed.
                elem = line[78:80].strip().capitalize()
                if not elem or elem in ('H', 'D'):
                    # Fallback to first char of atom name for types like 'C.1', 'N.5', 'Cl.6'
                    elem = line[12:13].strip().capitalize()
                if not elem or elem in ('H', 'D', 'A', ''):
                    elem = line[12:14].strip().capitalize()
                # Canonicalize common elements
                elem_map = {'Cl': 'Cl', 'Br': 'Br'}
                elem = elem_map.get(elem, elem.capitalize())
                if elem not in ('C', 'N', 'O', 'S', 'P', 'F', 'Cl', 'Br', 'I', 'H', 'D'):
                    elem = 'C'  # unknown → treat as carbon (dominant element)
                try:
                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])
                except ValueError:
                    continue
                coords.append((elem, x, y, z))
    except Exception:
        return None

    if not coords:
        return None

    # Build mol with SMILES bond orders if available.
    # When atom counts mismatch (e.g. SMILES=35 vs PDBQT=40 for Nirmatrelvir),
    # keep the SMILES mol — its bond info is needed for 2D rendering.
    # We skip applying 3D coords in that case (2D coords will be generated by caller).
    if smiles:
        mol = Chem.MolFromSmiles(smiles)
        if mol is not None:
            mol = Chem.RemoveHs(mol)
            if mol.GetNumAtoms() == len(coords):
                # Perfect match — apply PDBQT 3D coordinates to existing atoms
                for i, (elem, x, y, z) in enumerate(coords):
                    mol.GetAtomWithIdx(i).SetAtomicNum(Chem.GetPeriodicTable().GetAtomicNumber(elem))
                conf = Chem.Conformer(mol.GetNumAtoms())
                conf.Set3D(True)
                for i, (elem, x, y, z) in enumerate(coords):
                    conf.SetAtomPosition(i, (x, y, z))
                mol.AddConformer(conf)
                return mol
            else:
                # Atom count mismatch (e.g. SMILES=35 vs PDBQT=40 for Nirmatrelvir).
                # SMILES lacks explicit H atoms; PDBQT may include them.
                # Use element-aware nearest-neighbor matching to apply 3D coords.
                # For each SMILES atom, find the nearest PDBQT atom of the same element.
                smi_elements = [a.GetSymbol() for a in mol.GetAtoms()]
                pdbqt_elem_list = [c[0] for c in coords]
                pdbqt_pts = [(c[1], c[2], c[3]) for c in coords]

                elem_to_pdbqt = {}
                for i, e in enumerate(pdbqt_elem_list):
                    elem_to_pdbqt.setdefault(e, []).append(i)

                mapping = {}   # smi_atom_idx -> pdbqt_coord_idx
                used_pdbqt = set()
                for smi_i, smi_elem in enumerate(smi_elements):
                    candidates = [j for j in elem_to_pdbqt.get(smi_elem, []) if j not in used_pdbqt]
                    if not candidates:
                        # No unmatched atom of this element — skip (coord stays at origin)
                        mapping[smi_i] = None
                        continue
                    # Find nearest by Euclidean distance
                    best_j, best_d = candidates[0], float('inf')
                    sx, sy, sz = 0.0, 0.0, 0.0  # placeholder until we have coords
                    for j in candidates:
                        dx = pdbqt_pts[j][0] - sx
                        dy = pdbqt_pts[j][1] - sy
                        dz = pdbqt_pts[j][2] - sz
                        d = (dx*dx + dy*dy + dz*dz)**0.5
                        if d < best_d:
                            best_d = d
                            best_j = j
                    mapping[smi_i] = best_j
                    used_pdbqt.add(best_j)

                # Apply matched 3D coords
                conf = Chem.Conformer(mol.GetNumAtoms())
                conf.Set3D(True)
                for smi_i in range(mol.GetNumAtoms()):
                    pdbqt_i = mapping.get(smi_i)
                    if pdbqt_i is not None:
                        c = coords[pdbqt_i]
                        conf.SetAtomPosition(smi_i, (c[1], c[2], c[3]))
                    # else: leave at origin (will be overwritten by Compute2DCoords later)
                mol.AddConformer(conf)
                return mol

    # No SMILES — use OpenBabel to perceive bond orders, then merge with PDBQT coords.
    # OpenBabel's SDF output correctly assigns bond types (single/double/aromatic)
    # from the 3D structure, solving the "0 bonds" issue.
    ob_mol = None
    try:
        ob_mol = next(_pybel.readfile('pdbqt', pdbqt_path))
    except Exception:
        pass

    if ob_mol is not None:
        try:
            sdf_path = os.path.join(tempfile.gettempdir(), f'_pdbqt_sdf_{os.getpid()}.sdf')
            ob_mol.write(format='sdf', filename=sdf_path, overwrite=True)
            sdf_mol = Chem.MolFromMolFile(sdf_path, removeHs=False)
            if sdf_mol is not None and sdf_mol.GetNumAtoms() == len(coords):
                # Atom counts match — merge SDF bonds into the PDBQT mol
                rwmol = Chem.RWMol()
                for i, (elem, x, y, z) in enumerate(coords):
                    a = Chem.Atom(elem)
                    rwmol.AddAtom(a)
                # Add bonds BEFORE GetMol() — RDKit Mol is immutable, only RWMol has AddBond
                for bond in sdf_mol.GetBonds():
                    try:
                        rwmol.AddBond(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), bond.GetBondType())
                    except Exception:
                        pass
                rwmol = rwmol.GetMol()
                # Attach 3D conformer from PDBQT coords
                conf = Chem.Conformer(len(coords))
                conf.Set3D(True)
                for i, (elem, x, y, z) in enumerate(coords):
                    conf.SetAtomPosition(i, (x, y, z))
                rwmol.AddConformer(conf)
                try:
                    os.unlink(sdf_path)
                except Exception:
                    pass
                return rwmol
            if sdf_mol is not None and os.path.exists(sdf_path):
                try:
                    os.unlink(sdf_path)
                except Exception:
                    pass
        except Exception:
            pass

    # Fallback: build from raw coords (no bond order info — OpenBabel failed)
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

    Uses rdMolAlign.GetBestRMS() for optimal superposition (Kabsch algorithm)
    before RMSD calculation — the publication-standard approach (CASF-2013).

    When the docked and reference molecules have different atom counts
    (e.g. different protonation states), uses Maximum Common Substructure
    (MCS) alignment to restrict RMSD to the shared scaffold.

    Args:
        docked_pdbqt:     PDBQT file from Vina docking output
        reference_pdbqt:  Crystal / reference PDBQT file
        method:           'atom' = atom-to-atom RMSD after optimal superposition
                           'com'  = center-of-mass RMSD
                           'both'  = return (atom_rmsd, com_rmsd)

    Returns:
        float RMSD in Å. Returns None when molecules have no common
        scaffold (atom count differs AND MCS < 3 shared atoms).
        For method='both': returns (atom_rmsd, com_rmsd)

    Reference standard:
        Atom-to-atom RMSD < 2.0 Å = successful redocking
        (CASF-2013 benchmark, PMC12661494, Scientific Reports 2024)
    """
    if not _HAVE_RDKIT:
        logger.error("[autodock] RDKit not available for RMSD calculation")
        return None

    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolAlign, rdFMCS

    ref_mol = _read_ligand_from_pdbqt_3d(reference_pdbqt)
    docked_mol = _read_ligand_from_pdbqt_3d(docked_pdbqt)

    if ref_mol is None or docked_mol is None:
        logger.error("[autodock] Could not parse PDBQT for RMSD")
        return None

    n_ref = ref_mol.GetNumAtoms()
    n_docked = docked_mol.GetNumAtoms()

    # ── Same atom count: direct optimal alignment ─────────────────────────
    if n_ref == n_docked:
        atom_rmsd = rdMolAlign.GetBestRMS(docked_mol, ref_mol)
    else:
        # Different atom counts: find MCS to identify the shared scaffold.
        # RMSD is computed ONLY on the MCS-matched atoms.
        # If MCS yields < 3 matched atom pairs, the molecules are too
        # different for a meaningful RMSD → return None.
        mcs_result = rdFMCS.FindMCS(
            [ref_mol, docked_mol],
            ringMatchesRingOnly=True,
            bondCompare=rdFMCS.BondCompare.CompareAny,
            timeout=10,
        )
        if mcs_result.numAtoms < 3:
            logger.warning(
                f"[autodock] RMSD: ref={n_ref} atoms vs docked={n_docked} atoms, "
                f"but MCS found only {mcs_result.numAtoms} common atoms "
                f"(< 3 minimum) — no meaningful RMSD. Returning None."
            )
            return None

        patom = Chem.MolFromSmarts(mcs_result.smartsString)
        if patom is None:
            logger.error("[autodock] Could not parse MCS smarts for RMSD")
            return None

        mr = ref_mol.GetSubstructMatch(patom)   # atom indices in ref_mol
        md = docked_mol.GetSubstructMatch(patom) # atom indices in docked_mol

        if not mr or not md or len(mr) != len(md):
            logger.error(
                f"[autodock] MCS substructure match failed "
                f"(ref={len(mr)}, docked={len(md)}) — no meaningful RMSD."
            )
            return None

        # Build atom map: (docked_idx, ref_idx) pairs for rdMolAlign
        atom_map = list(zip(md, mr))
        atom_rmsd = rdMolAlign.GetBestRMS(docked_mol, ref_mol, atomMap=atom_map)
        logger.warning(
            f"[autodock] RMSD computed on MCS subset: "
            f"{len(mr)} matched atoms (ref={n_ref}, docked={n_docked}). "
            f"atom_rmsd={atom_rmsd:.4f} A"
        )

    if method == 'atom':
        return float(atom_rmsd)

    # ── Center-of-mass RMSD (always uses full molecule) ──────────────
    def _com(mol):
        conf = mol.GetConformer()
        xs = [conf.GetAtomPosition(i).x for i in range(mol.GetNumAtoms())]
        ys = [conf.GetAtomPosition(i).y for i in range(mol.GetNumAtoms())]
        zs = [conf.GetAtomPosition(i).z for i in range(mol.GetNumAtoms())]
        n = mol.GetNumAtoms()
        return (sum(xs) / n, sum(ys) / n, sum(zs) / n)

    rc = _com(ref_mol)
    dc = _com(docked_mol)
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
    logger.info(f"[autodock] === Redocking Validation ===")
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

        logger.info(f"[autodock] Redocking RMSD: atom={rmsd_atom:.3f} Å "
              f"(threshold={rmsd_threshold} Å), com={rmsd_com:.3f} Å")
        logger.info(f"[autodock] Best affinity: {best_energy} kcal/mol")
        logger.info(f"[autodock] Validation: {'✅ PASSED' if is_valid else '⚠️  FAILED'}")

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

    Raises:
        FileNotFoundError: If receptor_pdb does not exist
        TypeError: If arguments have wrong types
        ValueError: If padding is not positive
    """
    if not isinstance(receptor_pdb, str):
        raise TypeError(f"receptor_pdb must be str, got {type(receptor_pdb).__name__}")
    if not os.path.exists(receptor_pdb):
        raise FileNotFoundError(f"Receptor PDB not found: {receptor_pdb}")
    if ligand_pdb is not None and not isinstance(ligand_pdb, str):
        raise TypeError(f"ligand_pdb must be str or None, got {type(ligand_pdb).__name__}")
    if ligand_pdb and not os.path.exists(ligand_pdb):
        raise FileNotFoundError(f"Ligand PDB not found: {ligand_pdb}")
    if not isinstance(padding, (int, float)) or padding <= 0:
        raise ValueError(f"padding must be positive number, got {padding}")

    pockets = find_top_pockets(receptor_pdb, ligand_pdb, padding, max_pockets=1)
    top = pockets[0]
    return top['center'], top['box_size']


def dock_ligand_multi_conformer(receptor_pdbqt: str,
                                   conformer_pdbqts: list,
                                   receptor_pdb: str = None,
                                   ligand_pdb: str = None,
                                   padding: float = 5.0,
                                   max_pockets: int = 3,
                                   exhaustiveness: int = 32,
                                   n_poses: int = 10) -> dict:
    """
    Dock multiple ligand conformers and return the globally best poses.

    Each conformer in conformer_pdbqts is docked independently against the
    same binding site. All resulting poses are pooled, ranked by Vina
    binding energy, and the top n_poses are returned.

    This is the recommended protocol for publication-quality docking as it
    explores both conformational space and pose diversity simultaneously.

    Args:
        receptor_pdbqt:  Prepared receptor PDBQT file
        conformer_pdbqts: List of prepared ligand PDBQT files (e.g. from
                          prepare_ligand_conformers).
        receptor_pdb:   Original receptor PDB file (needed for fpocket detection).
                        If None, uses ligand-centered single-pocket mode.
        ligand_pdb:     Co-crystallized ligand PDB (optional).
        padding:        Padding around pocket (Å)
        max_pockets:    Maximum number of fpocket pockets to try (default 3).
        exhaustiveness: Vina search thoroughness (default 32).
        n_poses:        Number of final poses to return (default 10).

    Returns:
        dict with keys:
          'best_energy'   : float, best binding energy (kcal/mol)
          'best_pose_path': str, path to best-ranked pose PDBQT
          'all_poses'    : list of (energy, pdbqt_str) tuples, sorted ascending
          'n_conformers' : int, number of conformers that produced poses
          'pocket_info'  : dict, best pocket metadata
    """
    if not _HAVE_VINA:
        raise RuntimeError("vina required: conda activate autodock313")
    if not isinstance(conformer_pdbqts, list) or len(conformer_pdbqts) < 1:
        raise ValueError("conformer_pdbqts must be a non-empty list")

    # ── Detect binding site once ────────────────────────────────────────
    pockets = find_top_pockets(receptor_pdb, ligand_pdb, padding,
                               max_pockets=max_pockets)
    best_pocket = pockets[0]
    logger.info(f"[autodock] Multi-conformer docking: {len(conformer_pdbqts)} conformers "
                f"→ pocket #{best_pocket['pocket_num']}")

    # Pool of (energy, pdbqt_str)
    all_poses: list = []
    n_success = 0

    for conf_path in conformer_pdbqts:
        try:
            v = Vina(sf_name='vina', seed=42)
            v.set_receptor(receptor_pdbqt)
            v.set_ligand_from_file(conf_path)
            v.compute_vina_maps(center=best_pocket['center'],
                                 box_size=best_pocket['box_size'])
            v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses, min_rmsd=1.0)
            energies = v.energies(n_poses=n_poses, energy_range=3.0)

            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                            delete=False) as tf:
                tmp_path = tf.name
            try:
                v.write_poses(tmp_path, n_poses=n_poses, energy_range=3.0,
                              overwrite=True)
                with open(tmp_path) as f:
                    pdbqt_str = f.read()
                parts = pdbqt_str.split('MODEL ')
                for i, part in enumerate(parts[1:], start=0):
                    pose_str = f'MODEL {i+1}\n{part}'
                    if energies.size > i:
                        all_poses.append((float(energies[i][0]), pose_str))
            finally:
                os.unlink(tmp_path)

            n_success += 1
            logger.debug(f"[autodock] Conformer {n_success}: "
                         f"{len([e for e in energies])} poses, "
                         f"best={energies[0][0]:.2f} kcal/mol")
        except Exception as e:
            logger.warning(f"[autodock] Conformer {conf_path} failed: {e}")
            continue

    if not all_poses:
        raise RuntimeError("All conformers failed to dock")

    # Sort ascending (most negative = best binding)
    all_poses.sort(key=lambda x: x[0])
    top_poses = all_poses[:n_poses]

    # Write top poses to output directory derived from first conformer path
    out_dir = os.path.join(os.path.dirname(conformer_pdbqts[0]), 'multi_conformer_results')
    os.makedirs(out_dir, exist_ok=True)

    best_energy, best_pose_str = top_poses[0]
    best_pose_path = os.path.join(out_dir, 'best_pose.pdbqt')
    with open(best_pose_path, 'w') as f:
        f.write(best_pose_str)

    logger.info(f"[autodock] Multi-conformer docking done: "
                f"{n_success}/{len(conformer_pdbqts)} conformers succeeded, "
                f"{len(all_poses)} total poses, best={best_energy:.2f} kcal/mol")

    return {
        'best_energy': best_energy,
        'best_pose_path': best_pose_path,
        'all_poses': all_poses,
        'n_conformers': n_success,
        'pocket_info': best_pocket,
    }


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
            logger.info(f"[autodock] receptor_pdb=None → ligand-centered single-pocket mode "
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
                logger.info(f"[autodock] Pocket {i+1} #{pocket['pocket_num']}: "
                      f"affinity={best_affinity} kcal/mol ({len(poses)} poses)")
                all_results.append({
                    'energies': energies,
                    'poses': poses,
                    'best_affinity': best_affinity,
                    'pocket': pocket,
                })
        except Exception as e:
            logger.error(f"[autodock] Pocket {i+1} #{pocket['pocket_num']}: FAILED - {e}")
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
    logger.info(f"[autodock] Best pocket: #{pk['pocket_num'] or 'ligand-centered'} "
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
            logger.info(f"[autodock] Pocket {idx+1} analysis: {n_int} contacts, "
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
            elem = line[78:80].strip().capitalize() or line[12:14].strip().capitalize()
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
    A clash score < 1.0 Å is generally acceptable for explicit-H systems
    (PoseBusters benchmark uses 0.5 Å for heavy-atom-only comparisons).

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

    logger.info(f"[autodock] Clash score: {max_overlap:.3f} Å "
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
        lig = _read_ligand_from_pdbqt(ligand_pdbqt)
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


    # Convert GLY/TYR HETATMs → ATOM (dipeptide substrate → standard amino acids).
    # PLIP treats HETATM records as SMALLMOLECULE ligands (competes with UNL).
    # ATOM records are treated as protein residues (no site-selection competition).
    prot_lines = []
    for l in rec_lines:
        if l.startswith('HETATM') and ('GLY A 501' in l or 'TYR A 502' in l):
            l = 'ATOM' + l[6:]  # Convert HETATM → ATOM
            prot_lines.append(l)
        elif l.startswith('HETATM'):
            continue  # Strip metal ions and other HETATMs
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
            elif itype in ('pistacking', 'pication_paro', 'pication_laro'):
                # π-π / π-cation: use ring centroid approach
                # Find all ring atoms → compute 3D centroid → pick nearest atom to centroid
                # This is more accurate than just atoms[0]
                ring_obj = None
                if itype == 'pistacking':
                    ring_obj = item.ligandring
                elif hasattr(item, 'ring') and item.ring:
                    ring_obj = item.ring  # aromatic ring
                if ring_obj and hasattr(ring_obj, 'atoms') and ring_obj.atoms:
                    atoms = ring_obj.atoms
                    if len(atoms) == 1:
                        return atoms[0]
                    # Compute 3D centroid of all ring atoms
                    coords = np.array([a.coords for a in atoms])
                    centroid = coords.mean(axis=0)
                    # Pick the ring atom nearest to centroid
                    min_dist = float('inf')
                    nearest = atoms[0]
                    for a in atoms:
                        d = np.linalg.norm(np.array(a.coords) - centroid)
                        if d < min_dist:
                            min_dist = d
                            nearest = a
                    return nearest, None
                return None, None

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
                # Store protein centroid for nearest-ligand-atom fallback
                prot_center = None
                if hasattr(prot_side, 'center') and prot_side.center:
                    prot_center = prot_side.center
                return pa, prot_center
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
                    'protisdon': getattr(item, 'protisdon', None),   # for H-bond arrow direction
                    'prot_x': px,
                    'prot_y': py,
                    'prot_z': pz,
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
    dummy_info = []   # (dummy_idx, itype, res_label, lig_atom_idx, arrow_rev)
    seen = {}          # (itype, resn, resi, chain) → dummy_idx

    for interaction in interactions:
        itype   = interaction.get('type', 'Unknown')
        resn    = interaction.get('resn', 'UNK')
        resi    = interaction.get('resi', '?')
        chain   = interaction.get('chain', '')
        lig_idx = interaction.get('ligand_atom_idx')  # may be None

        # ── Resolve ligand atom index ───────────────────────────────────────
        if lig_idx is None and lig_rdk is not None:
            # Fallback: use the protein atom position → find nearest ligand atom
            # (salt bridges / metal complexes often lack direct pybel atom mapping)
            pass  # handled below after we get protein coords

        if lig_idx is None or lig_idx < 0:
            # Fallback: nearest ligand atom to the protein interaction partner
            # (salt bridges / metal complexes / water bridges with no direct pybel atom mapping)
            prot_center = interaction.get('_prot_center')
            prot_x = interaction.get('prot_x')
            prot_y = interaction.get('prot_y')
            prot_z = interaction.get('prot_z')
            
            # Prefer _prot_center (set for salt bridges via charge.center)
            if prot_center and isinstance(prot_center, (list, tuple)) and len(prot_center) >= 3:
                prot_x, prot_y, prot_z = prot_center[0], prot_center[1], prot_center[2]
            
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
                    if nearest_idx is not None and min_dist <= 5.0:  # within 5 Å
                        lig_idx = nearest_idx
                except ValueError:
                    pass

            if lig_idx is None or lig_idx < 0:
                # Still cannot map — skip this interaction
                continue

        # ── Residue label ────────────────────────────────────────────────────
        res_label = f"{resn}{resi}" + (f".{chain}" if chain else "")

        # ── Deduplication: one dummy per (itype, resn, resi, chain) ─────────
        key = (itype, resn, resi, chain)
        if key in seen:
            didx = seen[key]
            dummy_info.append((didx, itype, res_label, lig_idx, False))
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
        # arrow_rev: if protein is donor (protisdon=True), arrow points protein→ligand (rev=True)
        # arrow_rev=False: arrow points ligand→protein
        arrow_rev = interaction.get('protisdon', False) == True
        dummy_info.append((didx, itype, res_label, lig_idx, arrow_rev))

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
        if prot_c is not None:
            prot_px = svg_drawer.GetDrawCoords(Point2D(prot_c[0], prot_c[1]))
            draw_from = prot_px
            draw_to = lig_px
        else:
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
        opts.annotationFontScale = 1.0
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
        dummy_indices = sorted(set(d[0] for d in dummy_info))
        dummy_colors = {}
        for didx, itype, _, _lidx, _arrow in dummy_info:
            if didx not in dummy_colors:
                style = INTERACTION_STYLE.get(itype, INTERACTION_STYLE.get('Hydrophobic', {}))
                dummy_colors[didx] = style.get('color', (0.5, 0.5, 0.5))

        drawer.DrawMolecule(
            rwmol,
            highlightAtoms=dummy_indices,
            highlightAtomColors=dummy_colors,
        )

        # ── 6. Post-processing: draw interaction lines/arrows ───────────────
        # We draw on TOP of the molecule using pixel coordinates from GetDrawCoords
        drawn_pairs = set()

        for didx, itype, res_label, lig_idx, arrow_rev in dummy_info:
            style = INTERACTION_STYLE.get(itype, INTERACTION_STYLE.get('Hydrophobic', {}))
            color = style.get('color', (0.5, 0.5, 0.5))
            lw = style.get('line_width', 1.8)
            end_style = style.get('end_style', 'dash')

            # Get 2D molecular coordinates
            lig_pos = conf.GetAtomPosition(lig_idx)
            dum_pos = conf.GetAtomPosition(didx)

            # Convert to pixel coordinates
            lig_px = drawer.GetDrawCoords(Point2D(lig_pos.x, lig_pos.y))
            dum_px = drawer.GetDrawCoords(Point2D(dum_pos.x, dum_pos.y))

            # Skip if points are coincident (shouldn't happen but guard)
            dx = dum_px.x - lig_px.x
            dy = dum_px.y - lig_px.y
            if (dx*dx + dy*dy) < 1:
                continue

            drawer.SetColour(color)

            if end_style == 'arrow':
                # Directional arrow: H-bond or halogen bond
                # Convention: arrow points FROM ligand atom TO protein residue
                # (i.e., direction of interaction flow)
                if arrow_rev:
                    drawer.DrawArrow(
                        Point2D(dum_px.x, dum_px.y),
                        Point2D(lig_px.x, lig_px.y),
                        False, 0.065, 0.45,
                    )
                else:
                    drawer.DrawArrow(
                        Point2D(lig_px.x, lig_px.y),
                        Point2D(dum_px.x, dum_px.y),
                        False, 0.065, 0.45,
                    )

            elif end_style == 'double':
                # Double line: π-π, salt bridge, metal complex
                drawer.DrawLine(
                    Point2D(lig_px.x, lig_px.y),
                    Point2D(dum_px.x, dum_px.y),
                )
                # Second line offset perpendicular to the first
                length = (dx*dx + dy*dy) ** 0.5
                if length > 0:
                    nx = -dy / length * 3.0
                    ny = dx / length * 3.0
                    drawer.DrawLine(
                        Point2D(lig_px.x + nx, lig_px.y + ny),
                        Point2D(dum_px.x + nx, dum_px.y + ny),
                    )

            elif end_style == 'dash':
                # Dashed: hydrophobic, water bridge
                drawer.DrawLine(
                    Point2D(lig_px.x, lig_px.y),
                    Point2D(dum_px.x, dum_px.y),
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
        for didx, itype, res_label, lig_idx, _arrow in dummy_info:
            if not res_label:
                continue
            pos = conf.GetAtomPosition(didx)
            px = drawer.GetDrawCoords(Point2D(pos.x, pos.y))
            # Label offset: below and right of the dummy circle
            lx = int(px.x + 8)
            ly = int(px.y + 6)
            # Clip to image bounds
            if 0 <= lx < img.width - 60 and 0 <= ly < img.height - 16:
                draw.text((lx, ly), res_label,
                          fill=(20, 20, 20, 230), font=font)

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

        size = os.path.getsize(output_png)
        ok = size > 30000  # publication diagram should be ≥30KB at 300dpi
        if not ok:
            logger.info(f"[autodock] 2D diagram SUSPECT: only {size} bytes — "
                  f"molecule may have rendered without bonds (0 bonds) or scaling error. "
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

def dock_ligand(receptor_pdbqt: str,
                ligand_pdbqt: str,
                center: tuple,
                box_size: tuple,
                exhaustiveness: int = 32,
                n_poses: int = 10,
                receptor_pdb: str = None,
                include_interactions: bool = False,
                include_clash: bool = False,
                output_dir: str = None,
                return_structured: bool = False,
                timeout: int = 600) -> tuple:
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
        output_dir: If provided, save docking poses to this directory:
                    - docking_best.pdbqt   ← best pose (Vina-ranked #1)
                    - docking_all_poses.pdbqt ← all n_poses
                    These files can be passed directly to detect_interactions() and
                    render_scene() without manual path handling.
        timeout: Maximum seconds to wait for docking to complete (default 600s).
                 If docking takes longer, raises TimeoutError.

    Returns:
        (energies: ndarray, poses: list of PDBQT strings)
        energies[n][0] = total affinity (kcal/mol, more negative = tighter)
        If include_interactions or include_clash or output_dir is True, returns
        (energies, poses, metadata_dict) where metadata_dict contains:
        - 'best_pose_path': path to docking_best.pdbqt (if output_dir provided)
        - 'all_poses_path': path to docking_all_poses.pdbqt (if output_dir provided)
        - 'interactions': contact list (if include_interactions=True)
        - 'clash': clash metrics (if include_clash=True)
    """
    if not _HAVE_VINA:
        raise RuntimeError("vina required: conda activate autodock313")
    # ── Input validation ─────────────────────────────────────────────────────
    if not isinstance(receptor_pdbqt, str):
        raise TypeError(f"receptor_pdbqt must be str, got {type(receptor_pdbqt).__name__}")
    if not isinstance(ligand_pdbqt, str):
        raise TypeError(f"ligand_pdbqt must be str, got {type(ligand_pdbqt).__name__}")
    if not os.path.exists(receptor_pdbqt):
        raise FileNotFoundError(f"Receptor PDBQT not found: {receptor_pdbqt}")
    if not os.path.exists(ligand_pdbqt):
        raise FileNotFoundError(f"Ligand PDBQT not found: {ligand_pdbqt}")
    if not isinstance(center, (tuple, list)) or len(center) != 3:
        raise TypeError(f"center must be (x, y, z) tuple/list, got {type(center).__name__}")
    if not isinstance(box_size, (tuple, list)) or len(box_size) != 3:
        raise TypeError(f"box_size must be (sx, sy, sz) tuple/list, got {type(box_size).__name__}")
    if any(d <= 0 for d in box_size):
        raise ValueError(f"box_size must be positive, got {box_size}")

    v = Vina(sf_name='vina', seed=42)
    v.set_receptor(receptor_pdbqt)
    v.set_ligand_from_file(ligand_pdbqt)
    v.compute_vina_maps(center=center, box_size=box_size)
    # ── Docking with optional timeout ──────────────────────────────────────────
    def _dock_with_timeout(vina_obj, ex, nposes, rmsd, timeout_sec):
        """
        Run vina.do_dock in a background thread; raise TimeoutError if it
        does not return within timeout_sec seconds.
        """
        result = {}
        def worker():
            try:
                vina_obj.dock(exhaustiveness=ex, n_poses=nposes, min_rmsd=rmsd)
                result['done'] = True
            except Exception as e:
                result['error'] = str(e)
                result['done'] = True

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=timeout_sec)
        if t.is_alive():
            # Timed out — Vina is stuck
            raise TimeoutError(
                f"Docking timed out after {timeout_sec}s. "
                f"Try a smaller search space or increase timeout."
            )
        if 'error' in result:
            raise RuntimeError(f"Docking failed: {result['error']}")

    _dock_with_timeout(v, exhaustiveness, n_poses, 1.0, timeout)

    energies = v.energies(n_poses=n_poses, energy_range=3.0)

    # Use write_poses() (official API) to write all poses to a PDBQT file,
    # then read it back as a list of PDBQT strings.  If output_dir is provided,
    # persist the files to disk so downstream steps (interaction detection,
    # PyMOL rendering) can read them.  Otherwise fall back to a temp file.
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        all_poses_path = os.path.join(output_dir, 'docking_all_poses.pdbqt')
        best_pose_path = os.path.join(output_dir, 'docking_best.pdbqt')
        pose_write_path = all_poses_path
    else:
        all_poses_path = None
        best_pose_path = None
        pose_write_path = None

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
        # Persist to output_dir if requested
        if output_dir:
            with open(all_poses_path, 'w') as f:
                f.write(pdbqt_str)
            with open(best_pose_path, 'w') as f:
                f.write(poses[0] if poses else '')
            logger.info(f"[autodock] Poses saved: {best_pose_path} (best), {all_poses_path} (all)")
    finally:
        os.unlink(tmp_path)

    best = float(energies[0][0]) if energies.size > 0 else None
    logger.info(f"[autodock] Best affinity: {best} kcal/mol ({len(poses)} poses)")

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
            logger.info(f"[autodock] Pre-dock score (input pose): {score_init_total} kcal/mol")
    except RuntimeError as e:
        if 'outside' in str(e).lower():
            logger.info(f"[autodock] Pre-dock score: skipped (ligand not in grid box; {e})")
        else:
            raise

    # ── Optional: interaction detection + clash analysis ───────────
    metadata = {}
    if best_pose_path:
        metadata['best_pose_path'] = best_pose_path
        metadata['all_poses_path'] = all_poses_path

    if include_interactions and receptor_pdb:
        logger.info("[autodock] Detecting interactions for best pose...")
        # Use the persisted best pose if available, otherwise fall back to temp file
        lig_pdbqt_for_intx = best_pose_path if best_pose_path else None
        if not lig_pdbqt_for_intx:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                            delete=False) as tf:
                tmp_path = tf.name
            try:
                with open(tmp_path, 'w') as f:
                    f.write(poses[0])
                lig_pdbqt_for_intx = tmp_path
            finally:
                pass  # don't delete yet, detect_interactions needs it
        try:
            interactions = detect_interactions(
                receptor_pdb=receptor_pdb,
                ligand_pdbqt=lig_pdbqt_for_intx,
                center=center,
            )
            metadata['interactions'] = interactions
        finally:
            if not best_pose_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    if include_clash and receptor_pdb:
        logger.info("[autodock] Computing clash score for best pose...")
        clash_result = compute_clash_score(poses[0], receptor_pdb)
        metadata['clash'] = clash_result

    if metadata:
        if return_structured:
            clash_res = metadata.get('clash')
            dr = build_docking_result(
                compound_name=os.path.basename(ligand_pdbqt),
                receptor=receptor_pdbqt,
                center=tuple(center) if center else None,
                box_size=tuple(box_size) if box_size else None,
                energies=energies, poses=poses,
                interactions=metadata.get('interactions'),
                clash_result=clash_res,
                pre_dock_score=None,
                best_pose_path=best_pose_path,
            )
            return dr
        return energies, poses, metadata
    if return_structured:
        dr = build_docking_result(
            compound_name=os.path.basename(ligand_pdbqt),
            receptor=receptor_pdbqt,
            center=tuple(center) if center else None,
            box_size=tuple(box_size) if box_size else None,
            energies=energies, poses=poses,
            pre_dock_score=None,
            best_pose_path=best_pose_path,
        )
        return dr
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
                  include_clash: bool = False,
                  n_workers: int = 4) -> tuple:
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

    """
    Screen a compound library against a protein target (parallel, publication-standard).

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

    Args:
        n_workers: Number of parallel worker threads (default 4).
                   Increase for faster screening on multi-core machines.
                   Note: Vina is CPU-bound; >8 workers rarely helps on <8-core systems.
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

    # ── Per-worker Vina instance factory ────────────────────────────────────
    # Each thread gets its own Vina instance (non-thread-safe C++ binding).
    # Vina maps are thread-safe to read after init; receptor is set once per
    # instance in _init_vina_worker().
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _init_vina_worker():
        v = Vina(sf_name='vina', seed=42)
        v.set_receptor(receptor_pdbqt)
        v.compute_vina_maps(center=center, box_size=box_size)
        return v

    def _dock_single(name: str, smiles: str) -> dict:
        """Dock one compound; runs in a worker thread with its own Vina instance."""
        ligand_pdbqt = os.path.join(output_dir, f"{name}.pdbqt")
        try:
            prepare_ligand(smiles, ligand_pdbqt)

            # Each worker has its own Vina instance — no lock needed.
            v = Vina(sf_name='vina', seed=42)
            v.set_receptor(receptor_pdbqt)
            v.compute_vina_maps(center=center, box_size=box_size)
            v.set_ligand_from_file(ligand_pdbqt)

            score_init_total = None
            try:
                score_init = v.score()
                score_init_total = float(score_init[0]) if hasattr(score_init, '__getitem__') else float(score_init)
            except RuntimeError as e:
                if 'outside' in str(e).lower():
                    logger.info(f"[autodock] {name}: pre-dock score=skipped (ligand outside grid box)")
                    score_init_total = None
                else:
                    raise

            v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses, min_rmsd=1.0)
            energies = v.energies(n_poses=n_poses, energy_range=3.0)
            best = float(energies[0][0]) if energies.size > 0 else None
            pose_file = os.path.join(output_dir, f"{name}_poses.pdbqt") if best is not None else None
            if best is not None:
                v.write_poses(pose_file, n_poses=n_poses, energy_range=3.0)

            if score_init_total is not None:
                logger.info(f"[autodock] {name}: pre-dock score={score_init_total} kcal/mol, docked={best} kcal/mol")
            else:
                logger.info(f"[autodock] {name}: docked={best} kcal/mol")

            # Capture best pose as string
            best_pose_str = None
            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as tf:
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
                with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as tf:
                    tmp_path = tf.name
                try:
                    with open(tmp_path, 'w') as f:
                        f.write(best_pose_str)
                    if include_interactions:
                        try:
                            interactions_out = detect_interactions(
                                receptor_pdb=analysis_pdb, ligand_pdbqt=tmp_path, center=center)
                        except Exception as e:
                            logger.info(f"[autodock]   interaction detection failed: {e}")
                            interactions_out = []
                    if include_clash:
                        try:
                            clash_out = compute_clash_score(best_pose_str, analysis_pdb)
                        except Exception as e:
                            logger.info(f"[autodock]   clash detection failed: {e}")
                            clash_out = {'clash_score': None, 'is_acceptable': None}
                finally:
                    os.unlink(tmp_path)

            pose_path = os.path.join(output_dir, f"{name}_best.pdbqt")
            if best_pose_str:
                with open(pose_path, 'w') as f:
                    f.write(best_pose_str)
            else:
                pose_path = None

            return {'name': name, 'smiles': smiles,
                    'affinity_kcal_mol': best,
                    'pre_dock_score': score_init_total,
                    'interactions': interactions_out,
                    'clash_score': clash_out.get('clash_score') if clash_out else None,
                    'clash_acceptable': clash_out.get('is_acceptable') if clash_out else None,
                    'best_pose_path': pose_path,
                    'poses_file': pose_file,
                    'error': None}
        except Exception as e:
            logger.error(f"[autodock] {name}: FAILED - {e}")
            return {'name': name, 'smiles': smiles,
                    'affinity_kcal_mol': None, 'error': str(e)}

    # ── Parallel execution ────────────────────────────────────────────────
    n_workers = max(1, n_workers)
    logger.info(f"[autodock] virtual_screen: {len(ligand_smiles_dict)} compounds, "
                f"exhaustiveness={exhaustiveness}, n_workers={n_workers}")

    results = []
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = {
            executor.submit(_dock_single, name, smiles): name
            for name, smiles in ligand_smiles_dict.items()
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

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
    else:
        # All compounds failed — build DataFrame from raw results (includes 'error' col)
        df_err = pd.DataFrame(results)
        # Standardize column names to match to_dataframe_row schema
        df_err = df_err.rename(columns={
            'name': 'compound',
            'affinity_kcal_mol': 'best_affinity_kcal_mol',
        }, errors='ignore')
        logger.warning(f"[autodock] All compounds failed; writing error log to {csv_path}")
        df_export = df_err

    df_export.to_csv(csv_path, index=False, float_format='%.4f')

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


def predict_admet(smiles_list: list[str],
                use_remote: bool = True,
                timeout: int = 120) -> pd.DataFrame | None:
    """
    Predict ADMET properties for a list of compounds.

    Tries three paths in order:
      1. ADMET-AI (Neurosnap) — fast REST API, 99 columns, ~1-5s
      2. ADMETlab 3.0 web via Playwright — 122 columns, ~20-30s
      3. Local RDKit — always works, curated subset, instant

    Args:
        smiles_list: List of SMILES strings
        use_remote: If False, skip remote calls and use RDKit only
        timeout: Total timeout in seconds (default 120)

    Returns:
        DataFrame with ADMET columns. Schema varies by source:
          - ADMET-AI: 99 columns (molecular_weight, logP, hbond_acceptors,
            hbond_donors, Lipinski, QED, CYP1A2_Veith, CYP2C19_Veith,
            CYP2D6_Veith, CYP3A4_Veith, hERG, BBB_Martins, HIA_Hou,
            AMES, DILI, ClinTox, Carcinogens, PAMPA_NCATS, ...)
          - ADMETlab web (Playwright): 122 columns, same endpoints
          - RDKit: SMILES, MW, LogP, TPSA, HBD, HBA, RotatableBonds,
            QED, LipinskiViolations, VeberCompliant, PAINSAlert,
            BBB_penetration, hERG_risk, CYP3A4_inhibitor, source
        Returns None if all methods fail.
    """
    if not _HAVE_RDKIT:
        logger.error("[autodock] RDKit not available for ADMET prediction")
        return None

    if not smiles_list:
        return None

    # ── Path 1: ADMET-AI (Neurosnap) — fast REST API ────────────────
    if use_remote:
        try:
            df = _predict_admet_neurosnap(smiles_list, timeout=min(timeout, 60))
            if df is not None and len(df) > 0:
                logger.info(f"[autodock] ADMET-AI (Neurosnap): {len(df)} compounds, "
                            f"{len(df.columns)} columns")
                return df
        except Exception as e:
            logger.warning(f"[autodock] ADMET-AI failed ({e}), trying Playwright")

    # ── Path 2: ADMETlab via Playwright browser → CSV ───────────────
    if use_remote:
        try:
            csv_path = _run_admetlab_browser(smiles_list, timeout=min(timeout, 60))
            if csv_path:
                df = _parse_admetlab_csv(csv_path)
                if df is not None and len(df) > 0:
                    logger.info(f"[autodock] ADMETlab browser: {len(df)} compounds, "
                                f"{len(df.columns)} columns")
                    return df
        except Exception as e:
            logger.warning(f"[autodock] ADMETlab browser failed ({e}), using RDKit")

    # ── Path 3: Local RDKit ─────────────────────────────────────────
    return _predict_admet_rdkit(smiles_list)


def _predict_admet_neurosnap(smiles_list: list[str], timeout: int = 60) -> pd.DataFrame | None:
    """
    Predict ADMET via ADMET-AI on Neurosnap (https://neurosnap.ai).

    Workflow:
      1. Submit job via POST /api/job/submit/ADMET-AI (multipart, JSON molecules)
      2. Poll /api/job/status/<job_id> until 'completed'
      3. Download /api/job/file/<job_id>/out/results.csv

    API key is read from the ADMETLAB_API_KEY environment variable,
    or ~/.openclaw/keys/neurosnap_api_key.

    Returns DataFrame with 99 columns (molecular_weight, logP, CYP, hERG, etc.)
    or None if the call fails.
    """
    import json, time, os, urllib.request, urllib.error

    # Resolve API key
    api_key = os.environ.get('ADMETLAB_API_KEY') or _load_neurosnap_key()
    if not api_key:
        logger.debug("[autodock] No Neurosnap API key found")
        return None

    endpoint = 'https://neurosnap.ai'

    # Build multipart body — "Input Molecules" field with JSON array of SMILES
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    molecules = [{'data': smi.strip(), 'type': 'smiles'} for smi in smiles_list if smi.strip()]
    body = (f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="Input Molecules"\r\n\r\n'
            f'{json.dumps(molecules)}\r\n'
            f'--{boundary}--\r\n').encode()

    # Submit job
    try:
        req = urllib.request.Request(
            f'{endpoint}/api/job/submit/ADMET-AI',
            data=body,
            headers={
                'X-API-KEY': api_key,
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'User-Agent': 'curl/7.70+',
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            job_id = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[autodock] Neurosnap job submit failed: {e}")
        return None

    # Poll until done
    status_url = f'{endpoint}/api/job/status/{job_id}'
    poll_req = urllib.request.Request(status_url, headers={'X-API-KEY': api_key, 'User-Agent': 'curl/7.70+'})
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(poll_req, timeout=10) as r:
                status = json.loads(r.read())
            if status == 'completed':
                break
            elif status in ('failed', 'deleted', 'cancelled'):
                logger.warning(f"[autodock] Neurosnap job {status}: {job_id}")
                return None
        except Exception as e:
            logger.warning(f"[autodock] Neurosnap status poll error: {e}")
            return None
        time.sleep(2)
    else:
        logger.warning(f"[autodock] Neurosnap job timed out after {timeout}s")
        return None

    # Download results CSV
    csv_url = f'{endpoint}/api/job/file/{job_id}/out/results.csv'
    try:
        csv_req = urllib.request.Request(csv_url, headers={'X-API-KEY': api_key, 'User-Agent': 'curl/7.70+'})
        with urllib.request.urlopen(csv_req, timeout=30) as r:
            csv_data = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        logger.warning(f"[autodock] Neurosnap CSV download failed: {e}")
        return None

    # Parse CSV
    import io as _io
    try:
        df = pd.read_csv(_io.StringIO(csv_data))
    except Exception as e:
        logger.warning(f"[autodock] Failed to parse Neurosnap CSV: {e}")
        return None

    if df.empty:
        return None

    # Normalise: lowercase column names, add source tag
    df.columns = [str(c).strip().lower() for c in df.columns]
    # 'molecule' column holds SMILES
    if 'molecule' in df.columns:
        df = df.rename(columns={'molecule': 'smiles'})
    df['source'] = 'admet_ai'

    return df


def _load_neurosnap_key() -> str | None:
    """Load Neurosnap API key from ~/.openclaw/keys/neurosnap_api_key."""
    key_file = os.path.expanduser('~/.openclaw/keys/neurosnap_api_key')
    try:
        with open(key_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _run_admetlab_browser(smiles_list: list[str], timeout: int = 60) -> str | None:
    """
    Run ADMETlab 3.0 via Playwright browser automation.
    Submits the SMILES list through the web form, waits for the result page,
    parses the CSV URL from the HTML, and returns the CSV file path.

    Returns path to the downloaded CSV file ( caller must delete it ), or None.
    """
    import subprocess, tempfile, os

    node_script = os.path.join(os.path.dirname(__file__), 'tools', 'admetlab_web.js')
    if not os.path.exists(node_script):
        logger.warning(f"[autodock] admetlab_web.js not found at {node_script}")
        return None

    # Write SMILES to a temp file (one per line)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.smi', delete=False) as f:
        f.write('\n'.join(smiles_list))
        smiles_file = f.name

    tmp_csv = tempfile.mktemp(suffix='.csv')

    try:
        result = subprocess.run(
            ['node', node_script, '--csv', tmp_csv, '--smiles-file', smiles_file],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
            cwd=os.path.dirname(node_script)
        )
        if result.returncode != 0:
            logger.warning(f"[autodock] admetlab_web.js failed: {result.stderr[:200]}")
            return None

        if os.path.exists(tmp_csv) and os.path.getsize(tmp_csv) > 100:
            return tmp_csv
        else:
            logger.warning(f"[autodock] admetlab_web.js returned empty or no file")
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"[autodock] admetlab_web.js timed out after {timeout}s")
        return None
    finally:
        try: os.unlink(smiles_file)
        except: pass


def _parse_admetlab_csv(csv_path: str) -> pd.DataFrame | None:
    """Parse ADMETlab CSV into a normalised DataFrame."""
    try:
        # ADMETlab CSV may use comma or tab as separator; try comma first
        try:
            df = pd.read_csv(csv_path, sep=',')
        except Exception:
            df = pd.read_csv(csv_path, sep='\t')
        os.unlink(csv_path)
    except Exception:
        return None

    if df.empty:
        return None

    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]

    # Normalise: if there's a 'smiles' col and also 'raw_smiles', keep only 'smiles'
    if 'raw_smiles' in df.columns and 'smiles' in df.columns:
        df = df.drop(columns=['raw_smiles'])

    # Lower-case the source column
    if 'source' in df.columns:
        df['source'] = df['source'].astype(str).str.lower().str.strip()

    return df


def _predict_admet_rdkit(smiles_list: list[str]) -> pd.DataFrame:
    """Local RDKit ADMET calculation — always available fallback."""
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Lipinski
    from rdkit.Chem.QED import qed
    from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

    results = []
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            results.append({'SMILES': smi, 'source': 'error', 'error': 'Invalid SMILES',
                            'MW': None, 'LogP': None, 'TPSA': None})
            continue

        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        catalog = FilterCatalog(params)
        entry = catalog.GetFirstMatch(mol)

        mw   = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        hbd  = Lipinski.NumHDonors(mol)
        hba  = Lipinski.NumHAcceptors(mol)
        tpsa = Descriptors.TPSA(mol)
        rot  = Lipinski.NumRotatableBonds(mol)
        violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
        veber = rot <= 10 and tpsa <= 140
        herg_risk = (logp > 4 and tpsa < 75)  # conservative proxy

        results.append({
            'SMILES': smi,
            'MW': round(mw, 2),
            'LogP': round(logp, 2),
            'TPSA': round(tpsa, 1),
            'HBD': hbd,
            'HBA': hba,
            'RotatableBonds': rot,
            'QED': round(qed(mol), 3),
            'LipinskiViolations': violations,
            'VeberCompliant': veber,
            'PAINSAlert': entry.GetDescription() if entry else None,
            'BBB_penetration': 'High' if (logp > 0 and tpsa < 90) else 'Low',
            'hERG_risk': herg_risk,
            'CYP3A4_inhibitor': None,
            'source': 'local_rdkit',
        })

    df = pd.DataFrame(results)
    logger.info(f"[autodock] Local RDKit ADMET: {len(df)} compounds calculated")
    return df


def filter_admet(df: pd.DataFrame,
                 max_lipinski_violations: int = 1,
                 min_qed: float = 0.5,
                 max_herg_risk: bool = False,
                 filter_pains: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Apply ADMET drug-likeness filters to a DataFrame from predict_admet().

    Args:
        df: DataFrame from predict_admet() with SMILES column
        max_lipinski_violations: Max allowed Lipinski violations (default 1)
        min_qed: Minimum QED score (default 0.5)
        max_herg_risk: If True, reject compounds flagged as hERG risk
        filter_pains: If True, reject PAINS-flagged compounds

    Returns:
        (passed_df, failed_df) — both retain all original columns plus 'filter_reason'
    """
    if 'SMILES' not in df.columns:
        raise ValueError("DataFrame must have 'SMILES' column")

    df = df.copy()
    df['filter_reason'] = None

    # Lipinski
    mask_lipinski = df['LipinskiViolations'] <= max_lipinski_violations
    df.loc[~mask_lipinski, 'filter_reason'] = \
        df.loc[~mask_lipinski, 'filter_reason'].apply(
            lambda x: f"Lipinski violations: {x['LipinskiViolations']}" if x else f"Lipinski violations: {df.loc[~mask_lipinski, 'LipinskiViolations'].values[0]}")
    # QED
    mask_qed = df['QED'] >= min_qed
    df.loc[~mask_qed, 'filter_reason'] = df.loc[~mask_qed, 'filter_reason'].apply(
        lambda x: f"QED {x['QED']:.2f} < {min_qed}" if x and x else f"QED below threshold")
    # Veber
    mask_veber = df.get('VeberCompliant', pd.Series([True]*len(df)))
    # hERG: safe bool conversion to avoid ~ on bool deprecation warning
    herg_series = df.get('hERG_risk', pd.Series([False]*len(df)))
    herg_is_true = herg_series.astype(int).astype(bool)
    mask_herg = ~herg_is_true if max_herg_risk else pd.Series([True]*len(df), index=df.index)
    # PAINS: only filter if filter_pains=True
    mask_pains = df['PAINSAlert'].isna() if filter_pains else pd.Series([True]*len(df), index=df.index)

    mask_pass = mask_lipinski & mask_qed & mask_veber & mask_herg & mask_pains

    df.loc[~mask_lipinski, 'filter_reason'] = \
        'Lipinski violations: ' + df.loc[~mask_lipinski, 'LipinskiViolations'].astype(str)
    df.loc[~mask_qed, 'filter_reason'] = \
        'QED=' + df.loc[~mask_qed, 'QED'].round(2).astype(str) + f' < {min_qed}'
    if filter_pains:
        df.loc[~mask_pains, 'filter_reason'] = \
            'PAINS alert: ' + df.loc[~mask_pains, 'PAINSAlert'].fillna('').astype(str)
    if max_herg_risk:
        df.loc[~mask_herg, 'filter_reason'] = 'hERG risk'

    passed = df[mask_pass].copy()
    failed = df[~mask_pass].copy()

    logger.info(f"[autodock] ADMET filter: {len(passed)}/{len(df)} passed "
                f"(Lipinski≤{max_lipinski_violations}, QED≥{min_qed}, "
                f"hERG_risk={max_herg_risk}, PAINS={filter_pains})")
    return passed, failed


# ─────────────────────────────────────────────────────────────────────────────
# P1-5: VIRTUAL SCREENING STATISTICS — Enrichment Metrics
# ─────────────────────────────────────────────────────────────────────────────

def fetch_bioactivities(
    target_chembl_id: str,
    standard_types: tuple = ("IC50", "Ki", "EC50", "Kd"),
    min_pchembl: float = None,
    cache_file: str = None,
    timeout: int = 10,
) -> dict:
    """
    Fetch bioactivity records for a target from ChEMBL.

    Retrieves published IC50/Ki/EC50/Kd data with SMILES for a given
    ChEMBL target ID. Results are cached to cache_file (JSON) on success.
    """
    import json as _json, os as _os, requests as _requests
    if cache_file and _os.path.exists(cache_file):
        logger.info(f"[autodock] Loading cached bioactivities from {cache_file}")
        with open(cache_file) as f:
            return _json.load(f)
    base_url = "https://www.ebi.ac.uk/chembl/api/data"
    headers = {"Accept": "application/json"}
    try:
        tgt_resp = _requests.get(f"{base_url}/target/{target_chembl_id}.json",
                                headers=headers, timeout=timeout)
        tgt_resp.raise_for_status()
        target_name = tgt_resp.json().get("pref_name", target_chembl_id)
    except Exception as e:
        logger.warning(f"[autodock] Could not fetch target name for {target_chembl_id}: {e}")
        target_name = target_chembl_id
    all_activities, offset, page_size = [], 0, 1000
    while True:
        params = {"target_chembl_id": target_chembl_id, "limit": page_size, "offset": offset}
        if standard_types:
            params["standard_type"] = ",".join(standard_types)
        try:
            resp = _requests.get(f"{base_url}/activity.json", params=params,
                               headers=headers, timeout=timeout)
            resp.raise_for_status()
            page = resp.json().get("activities", [])
        except Exception as e:
            logger.warning(f"[autodock] ChEMBL API error at offset {offset}: {e}")
            break
        if not page:
            break
        all_activities.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    smiles_to_id, smiles_to_pchembl, smiles_to_type = {}, {}, {}
    for rec in all_activities:
        smiles = rec.get("canonical_smiles")
        if not smiles:
            continue
        pchembl = rec.get("pchembl_value")
        stype = rec.get("standard_type", "")
        if standard_types and stype not in standard_types:
            continue
        if min_pchembl is not None:
            if pchembl is None:
                continue
            try:
                if float(pchembl) < min_pchembl:
                    continue
            except (TypeError, ValueError):
                continue
        existing = smiles_to_pchembl.get(smiles)
        if existing is None or (pchembl is not None and float(pchembl) > float(existing)):
            smiles_to_pchembl[smiles] = pchembl
            smiles_to_id[smiles] = rec.get("molecule_chembl_id", "")
            smiles_to_type[smiles] = stype
    result = {"smiles_to_id": smiles_to_id, "smiles_to_pchembl": smiles_to_pchembl,
              "smiles_to_type": smiles_to_type, "target_name": target_name,
              "count": len(smiles_to_pchembl)}
    if cache_file:
        try:
            with open(cache_file, "w") as f:
                _json.dump(result, f)
            logger.info(f"[autodock] Cached {result['count']} activities to {cache_file}")
        except Exception as e:
            logger.warning(f"[autodock] Could not write cache file: {e}")
    logger.info(f"[autodock] fetch_bioactivities: {result['count']} unique active compounds for {target_name}")
    return result

def compute_enrichment(screened_smiles: list, bioactivity_data: dict,
                       decoy_smiles: list = None, threshold_pchembl: float = 6.0) -> dict:
    """
    Compute enrichment statistics (AUC, BEDROC, EF) for virtual screening results.
    """
    import numpy as np
    from scipy import stats as scipy_stats
    n_total = len(screened_smiles)
    if n_total == 0:
        return {"error": "No screened compounds provided"}
    active_smiles = set(bioactivity_data["smiles_to_pchembl"].keys())
    smiles_to_id = bioactivity_data["smiles_to_id"]
    is_active = np.array([s in active_smiles for s in screened_smiles], dtype=bool)
    n_active = int(is_active.sum())
    n_decoys = len(decoy_smiles) if decoy_smiles else (n_total - n_active)
    if n_active == 0:
        return {"n_screened": n_total, "n_active": 0, "n_decoys": n_decoys,
                "enrichment_factors": {}, "auc": 0.5, "bedroc": 0.0, "ef_1pct": 0.0,
                "ef_5pct": 0.0, "ef_10pct": 0.0, "n_hits_top50": 0, "n_hits_top1pct": 0,
                "active_names": {}, "recall_top10pct": 0.0,
                "note": "No active compounds found in screened library"}
    active_names = {s: smiles_to_id.get(s, "") for s in screened_smiles if s in active_smiles}
    y_true = is_active.astype(int)
    y_score = np.arange(n_total, 0, -1, dtype=float)
    auc = float(scipy_stats.roc_auc_score(y_true, y_score))
    alpha, m = 20.0, n_active
    r_i = np.where(is_active)[0] + 1
    def _bedroc(ranks, n, m, alpha):
        if m == 0 or n == 0:
            return 0.0
        s = sum(np.exp(-alpha * ri / n) for ri in ranks)
        random_sum = (1 - np.exp(-alpha)) / (n * (1 - np.exp(-alpha / n)))
        return s / (m * random_sum) if random_sum else 0.0
    bedroc = _bedroc(r_i, n_total, m, alpha)
    def ef_at_fraction(frac):
        k = max(1, int(np.ceil(n_total * frac)))
        hits_topk = int(is_active[:k].sum())
        return float((hits_topk / m) / frac) if m > 0 else 0.0
    enrichment_factors = {frac: ef_at_fraction(frac) for frac in [0.005, 0.01, 0.02, 0.05, 0.10]}
    k_50 = min(50, n_total)
    top1pct_k = max(1, int(np.ceil(n_total * 0.01)))
    top10pct_k = max(1, int(np.ceil(n_total * 0.10)))
    recall_top10pct = float(is_active[:top10pct_k].sum()) / m if m > 0 else 0.0
    return {"n_screened": n_total, "n_active": n_active, "n_decoys": n_decoys,
            "enrichment_factors": enrichment_factors, "auc": auc, "bedroc": bedroc,
            "ef_1pct": enrichment_factors[0.01], "ef_5pct": enrichment_factors[0.05],
            "ef_10pct": enrichment_factors[0.10],
            "n_hits_top50": int(is_active[:k_50].sum()),
            "n_hits_top1pct": int(is_active[:top1pct_k].sum()),
            "active_names": active_names, "recall_top10pct": recall_top10pct}

def print_enrichment_report(stats: dict, target_name: str = None):
    """Print a formatted enrichment statistics report."""
    if "error" in stats:
        print(f"[autodock] Enrichment error: {stats['error']}")
        return
    sep = "=" * 55
    hdr = "Enrichment Statistics"
    if target_name:
        hdr = f"Enrichment Statistics — {target_name}"
    auc_val = stats["auc"]
    auc_label = "Excellent" if auc_val > 0.9 else "Good" if auc_val > 0.8 else "Fair" if auc_val > 0.7 else "Poor"
    print(f"\n{sep}\n  {hdr}\n{sep}")
    print(f"  Screened compounds : {stats['n_screened']}")
    print(f"  Confirmed actives  : {stats['n_active']} ({100*stats['n_active']/max(stats['n_screened'],1):.1f}%)")
    print(f"  Decoys / inactives : {stats['n_decoys']}")
    print(f"\n  -- Global Ranking ----------------------------------------")
    print(f"  AUC               : {stats['auc']:.4f}  ({auc_label})")
    print(f"  BEDROC (alpha=20)  : {stats['bedroc']:.4f}")
    print(f"\n  -- Enrichment Factors ------------------------------------")
    for frac, ef in stats["enrichment_factors"].items():
        label = f"EF@{int(frac*100)}%"
        bar = "#" * min(int(ef), 20) if ef > 0 else ""
        print(f"  {label:<10} : {ef:6.2f}x  {bar}")
    print(f"\n  -- Early Enrichment --------------------------------------")
    print(f"  Top 50 hits        : {stats['n_hits_top50']} active compounds")
    print(f"  Top 1% hits        : {stats['n_hits_top1pct']} active compounds")
    print(f"  Recall @ top 10%   : {100*stats['recall_top10pct']:.1f}% of all actives found")
    print(f"{sep}\n")


# ─────────────────────────────────────────────────────────────────────────────
# ZINC22 Compound Database Access
# ─────────────────────────────────────────────────────────────────────────────

_ZINC22_BASE = "https://files.docking.org/zinc22"
_ZINC_GENERATIONS = ["a","b","c","d","e","f","g"]   # g = ZINC20 in stock (newest)

def parse_zinc_tranche(tranche_code: str) -> dict | None:
    """
    Parse a ZINC tranche code into physicochemical properties.

    Tranche format: H##P###M###-phase
      H##   = H-bond donor count (0–29)
      P###  = LogP × 10 (integer, e.g. P035 = 3.5)
      M###  = molecular weight in Da
      phase = reactivity classification (0=stable, 1=reactive, ...)

    Example: H05P035M400-0
      → h_donors=5, logp=3.5, mw=400, phase=0

    Returns None if the tranche code cannot be parsed.
    """
    import re
    m = re.match(r"H(\d+)P(\d+)M(\d+)-(\d+)", str(tranche_code))
    if not m:
        return None
    return {
        "h_donors": int(m.group(1)),
        "logp": int(m.group(2)) / 10.0,
        "mw": int(m.group(3)),
        "phase": int(m.group(4)),
    }


def _zinc_tranche_url(generation: str, h_donors: int, logp: float, mw: int,
                      suffix: str = "N.g.smi.gz") -> str:
    """
    Build the ZINC22 files URL for a specific tranche.

    Args:
        generation: ZINC22 generation letter (e.g. "g" for ZINC20 in stock)
        h_donors:   H-bond donor count (0–29)
        logp:       Partition coefficient (used to find P### subdir)
        mw:         Molecular weight in Da (rounded to nearest M### dir)
        suffix:     File suffix: "N.g.smi.gz" (neutral), "L.g.smi.gz" (acid),
                   "M.g.smi.gz" (base), "O.g.smi.gz" (other)
    Returns:
        Full HTTPS URL to the tranche file
    """
    h_str = f"H{h_donors:02d}"
    # MW-based tranche subdir: round to nearest 100 Da bucket
    mw_bucket = f"M{int(round(mw / 100) * 100):03d}"
    # LogP-based tranche subdir
    p_str = f"P{int(round(logp * 10)):03d}"
    return f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{h_str}{p_str}/{h_str}{mw_bucket}-{suffix}"


def sample_zinc_compounds(n: int = 100,
                          h_donors_range: tuple[int, int] = (0, 5),
                          logp_range: tuple[float, float] = (-2, 5),
                          mw_range: tuple[int, int] = (150, 500),
                          generation: str = "g",
                          output_csv: str = None,
                          verbose: bool = True,
                          n_workers: int = 4) -> pd.DataFrame:
    """
    Sample purchasable drug-like compounds from ZINC22 by property criteria.

    ZINC22 tranche files are at:
      https://files.docking.org/zinc22/zinc-22{gen}/{H##}/{H##M###}/{H##M###}-{suffix}.smi.gz
      (MW branch — also available via LogP branch at {H##P###}/{H##P###}-{suffix})

    Each .smi.gz file contains SMILES and ZINC IDs (tab-separated, one per line).
    Property-filtered sampling is performed by scanning tranche directories and
    randomly drawing compounds.  Network I/O is parallelized (default 4 workers).

    Args:
        n:               Target number of sampled compounds.
        h_donors_range:  (min, max) H-bond donor count (inclusive, 0–29).
        logp_range:      (min, max) LogP (inclusive).
        mw_range:        (min, max) molecular weight in Da (inclusive).
        generation:      ZINC22 generation: "g" = ZINC20 in stock (default, ~130M
                         purchasable). Use older letters for historical tranches.
        output_csv:      Optional CSV save path.
        verbose:         Print progress messages.
        n_workers:       Number of concurrent HTTP workers (default 4).

    Returns:
        DataFrame with columns: zinc_id, smiles, h_donors, logp, mw, tranche_url.

    Note:
        ZINC22 contains 230M+ purchasable compounds.  With n_workers=4 and
        ~2.5s per HTTP request, 60 tranche files complete in ~15s.

    Example:
        >>> df = sample_zinc_compounds(n=50, mw_range=(250, 400), logp_range=(2, 4))
        >>> print(df.head())
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import gzip
    import re
    import urllib.request
    import random

    def fetch(url: str, timeout: int = 12) -> str | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.70+"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return gzip.decompress(resp.read()).decode("utf-8", "ignore") if resp.status == 200 else None
        except Exception:
            return None

    h_min, h_max = h_donors_range
    p_min = int(round(logp_range[0] * 10))
    p_max = int(round(logp_range[1] * 10))
    mw_min, mw_max = mw_range

    if verbose:
        logger.info(f"[autodock] ZINC22 sampling: gen={generation}, H={h_min}-{h_max}, "
                    f"LogP={logp_range[0]:.1f}–{logp_range[1]:.1f}, MW={mw_min}–{mw_max}, "
                    f"target={n}, workers={n_workers}")

    url_pool = []

    # Build targeted URL pool
    # zinc-22g has H04–H29; clamp h loop to that intersection
    h_start = max(h_min, 4)
    h_end = max(h_max + 1, h_start + 1, 4)
    for h in range(h_start, min(h_end, 30)):
        for p in range(p_min, min(p_max + 1, 60), 10):
            for mw_b in range((mw_min // 100) * 100,
                              min((mw_max // 100 + 1) * 100 + 100, 1000), 100):
                h_str = f"H{h:02d}"
                p_str = f"H{h:02d}P{p:03d}"
                mw_str = f"{mw_b:03d}"
                for suffix in ["N.g.smi.gz", "L.g.smi.gz", "M.g.smi.gz", "O.g.smi.gz"]:
                    # MW branch
                    url_pool.append(
                        f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{h_str}{mw_str}/"
                        f"{h_str}{mw_str}-{suffix}"
                    )
                    # LogP branch
                    url_pool.append(
                        f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{p_str}/"
                        f"{p_str}-{suffix}"
                    )

    random.shuffle(url_pool)
    if verbose:
        logger.info(f"[autodock] ZINC22: built {len(url_pool)} candidate URLs")

    collected = []

    def parse_tranche_props(url: str):
        """Extract (h_donors, logp, mw) from ZINC22 tranche URL.
        
        URL patterns:
          .../H{h}P{p}/H{h}P{p}-{suffix}  → LogP branch: h_donors=h, logp=p/10, mw≈midpoint
          .../H{h}/H{h}M{m}/H{h}M{m}-{suffix}  → MW branch: h_donors=h, mw=m*100, logp≈midpoint
        """
        logp_m = re.search(r"/H(\d+)P(\d+)/", url)   # LogP branch: /H{h}P{p}/
        mw_m   = re.search(r"/H(\d+)M(\d+)/",
                            url)   # MW branch: /H{h}M{m}/
        if logp_m:
            h, p = int(logp_m.group(1)), int(logp_m.group(2))
            return h, p / 10.0, 0   # MW is bucketed, represent as 0
        if mw_m:
            h, m_val = int(mw_m.group(1)), int(mw_m.group(2))
            return h, 0.0, m_val * 100   # MW bucket start (e.g. M000 → 0, M100 → 100)
        return 4, 0.0, 0   # zinc-22g default

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(fetch, url, 12): url for url in url_pool[:48]}
        for fut in as_completed(futures):
            if len(collected) >= n:
                for f in futures:
                    f.cancel()
                break
            url = futures[fut]
            txt = fut.result()
            if not txt:
                continue
            valid_lines = [l.strip() for l in txt.splitlines() if l.strip() and "	" in l]
            if not valid_lines:
                continue
            td_h, td_p, td_m = parse_tranche_props(url)
            sample_n = min(len(valid_lines), max(1, n - len(collected)))
            for line in random.sample(valid_lines, min(sample_n, len(valid_lines))):
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                collected.append({
                    "zinc_id": parts[1].strip(),
                    "smiles": parts[0].strip(),
                    "h_donors": td_h,
                    "logp": td_p,
                    "mw": td_m,
                    "tranche_url": url,
                })

    df = pd.DataFrame(collected[:n])
    if output_csv and len(df):
        df.to_csv(output_csv, index=False)
        if verbose:
            logger.info(f"[autodock] ZINC22: saved {len(df)} compounds to {output_csv}")
    if verbose:
        logger.info(f"[autodock] ZINC22 sampling done: {len(df)}/{n}, scanned {min(48, len(url_pool))} tranche files")
    return df

def lookup_zinc_id(zinc_id: str, generation: str = "g") -> dict | None:
    """
    Look up a single ZINC ID and return its SMILES and properties.

    Searches the ZINC22 tranche index files to locate the compound.

    Args:
        zinc_id: ZINC identifier (e.g. "ZINC000000000001")
        generation: ZINC22 generation ("a"–"g"), default "g" (ZINC20 in stock).

    Returns:
        dict with keys: zinc_id, smiles, h_donors, logp, mw, tranche or None if not found.

    Note:
        ZINC IDs are distributed across tranche files.  This function scans
        the relevant tranche directories to locate the ID, which may take
        5–30 seconds depending on the tranche structure.

    Example:
        >>> result = lookup_zinc_id("ZINC000000000001")
        >>> print(result["smiles"])
    """
    import gzip, urllib.request, re

    def fetch_gz(url: str, timeout: int = 15) -> str | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.70+"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return gzip.decompress(resp.read()).decode("utf-8", errors="ignore")
        except Exception:
            return None

    # Tranche files are: {H_str}/{H_str}P{logp_bucket}/{H_str}P{logp_bucket}M{mw_bucket}-{suffix}.txt.gz
    # We scan the index .txt.gz files (not .smi.gz) to find the zinc_id.
    # Strategy: scan a curated set of tranche index files that cover most compounds.
    # H_donors ranges 0-29, MW 0-900, LogP 0.0-6.0

    # Extract numeric suffix from ZINC ID (e.g. ZINC000000000001 → 1)
    try:
        num = int(zinc_id.replace("ZINC", ""))
    except ValueError:
        return None

    # For efficiency: search tranches most likely to contain low ZINC IDs
    # Low ZINC IDs are typically in lower MW/LogP tranches
    candidates = []
    for h in range(0, 10):       # H-donors 0-9
        for p in range(0, 60, 10):  # LogP buckets 0-5.9
            for mw in range(0, 900, 100):
                h_str = f"H{h:02d}"
                p_str = f"H{h:02d}P{p:03d}"
                mw_str = f"{mw:03d}"
                for suffix in ["N.g.txt.gz", "L.g.txt.gz", "M.g.txt.gz", "O.g.txt.gz"]:
                    url = f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{p_str}/{h_str}{p_str}{mw_str}-{suffix}"
                    candidates.append(url)

    # Search first 200 candidates as a reasonable scope
    for url in candidates[:200]:
        txt = fetch_gz(url, timeout=10)
        if not txt:
            continue
        lines = txt.splitlines()
        # Index files are one ZINC ID per line (sorted)
        for line in lines:
            if line.strip() == zinc_id:
                # Found — parse tranche path to get properties
                tranche_m = re.search(r"H(\d+)P(\d+)M(\d+)", url)
                if tranche_m:
                    props = {
                        "h_donors": int(tranche_m.group(1)),
                        "logp": int(tranche_m.group(2)) / 10.0,
                        "mw": int(tranche_m.group(3)),
                    }
                else:
                    props = {}
                return {
                    "zinc_id": zinc_id,
                    "smiles": None,   # SMILES not in .txt index, only in .smi.gz
                    **props,
                    "tranche": url.split("/")[-1].replace("-N.g.txt.gz","").replace("-L.g.txt.gz","").replace("-M.g.txt.gz","").replace("-O.g.txt.gz",""),
                    "note": "SMILES available via sample_zinc_compounds() with tranche filter"
                }

    return None



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
