"""
Autodock Core Module
====================
Shared infrastructure: logging, feature flags, DockingResult dataclass, constants.
"""
import os
import tempfile
import warnings
import logging
from typing import Optional, Callable
import signal
from dataclasses import dataclass, field, asdict
from datetime import datetime

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
# File logging is enabled automatically if ~/.openclaw/logs/ exists.
autodock_logger = logging.getLogger("autodock")
autodock_logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setLevel(logging.DEBUG)
_handler.setFormatter(logging.Formatter("[autodock] %(message)s"))
autodock_logger.addHandler(_handler)

# Optional file logging
_log_dir = os.path.expanduser("~/.openclaw/logs")
if os.path.isdir(_log_dir):
    _file_handler = logging.FileHandler(
        os.path.join(_log_dir, "autodock.log"),
        mode='a'  # append
    )
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    autodock_logger.addHandler(_file_handler)

# Backward compat: module-level logger for SKILL.md usage
logger = autodock_logger

# Convenience log levels
def _log_info(msg): autodock_logger.info(msg)
def _log_warning(msg): autodock_logger.warning(msg)
def _log_error(msg): autodock_logger.error(msg)
def _log_debug(msg): autodock_logger.debug(msg)

# ─── Seed management for reproducible docking ───────────────────────────
import random

_REPRODUCIBLE_SEED = 42  # default for backwards compatibility when seed is not set

def _get_vina_seed(seed: int | None = None) -> int:
    """
    Return a valid Vina seed integer.

    - If seed is given (int), use it directly (deterministic/reproducible).
    - If seed is None, draw a random integer in [1, 2^31-1] to avoid
      correlated sampling across multiple runs or multiple conformers.

    Vina seeds must be positive integers.  The range [1, 2^31-1] is safe
    for Vina's internal Mersenne Twister.
    """
    if seed is not None:
        return int(seed)
    # Random seed: ensures independent sampling between runs and conformers
    return random.randint(1, 2_147_483_647)


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
    clash_acceptable: bool | None = None  # True if clash_score <= 1.2 (explicit-H threshold)

    # ── Binding pocket ───────────────────────────────────────────────────
    binding_pocket: dict | None = None  # {pocket_num, center, box_size, druggability, p2rank_prob}

    # ── Output files ────────────────────────────────────────────────────
    best_pose_pdbqt: str | None = None
    all_poses_pdbqt: list = field(default_factory=list)
    png_2d: str | None = None       # 2D interaction diagram path (dock_single)
    png_3d: str | None = None       # 3D PyMOL scene path (dock_single)
    output_dir: str | None = None    # Working directory (dock_single)

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
        # π-π + π-cation are aggregated together (PLIP TYPE MAP: 11 keys → 8 display categories)
        self._n_pi_stacking = sum(
            1 for i in self.interactions
            if i.get('type') in ('π-π', 'π-cation')
        )
        self._n_hydrophobic = sum(1 for i in self.interactions if i.get('type') == 'Hydrophobic')
        self._interactions_computed = True

    @property
    def interaction_summary(self) -> dict:
        """Human-readable interaction profile."""
        return {
            'H-bond': self.n_hbonds,
            'π-π/π-cation': self.n_pi_stacking,
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
    seed: int | None = None,
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
    from meeko.polymer import PolymerCreationError
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

