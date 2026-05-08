"""
Autodock Preparation Module
==============================
Receptor/ligand preparation and binding site detection (fpocket + P2Rank).
"""
import os
import shutil
import subprocess
import tempfile
import re
import json
import csv
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, rdPartialCharges

from meeko import MoleculePreparation, RDKitMolCreate, PDBQTWriterLegacy, Polymer
from meeko.polymer import PolymerCreationError

from autodock._core import autodock_logger, _HAVE_RDKIT, _HAVE_MEEKO, _SKIP_RES, _SKIP_WATER, PreparationError

# Backward-compat logger alias
logger = autodock_logger
from autodock._core import _P2RANK_DIR, _P2RANK_PRANK, _P2RANK_JAR, _JAVA_HOME
from autodock._core import _detect_receptor_source, _RECEPTOR_SOURCE_LABELS, _safe_color

def prepare_receptor(pdb_file: str, output_pdbqt: str,
                    remove_waters: bool = True,
                    input_format: str = 'auto') -> str:
    """
    Prepare protein structure for docking (PDB/mmCIF → PDBQT).

    Uses meeko (Polymer + PDBQTWriterLegacy) instead of openbabel.
    Supports .pdb, .cif, and .pdbx input formats via ProDy auto-conversion.

    Args:
        pdb_file: Input structure file path (.pdb, .cif, or .pdbx)
        output_pdbqt: Output PDBQT file path
        remove_waters: Remove HOH / WAT residues
        input_format: 'auto' | 'pdb' | 'cif' | 'pdbx'
                      'auto' (default): detect from file extension
                      'pdb': force PDB text parsing
                      'cif'/'pdbx': parse via ProDy then convert to PDB

    Returns:
        Path to output PDBQT file

    Raises:
        FileNotFoundError: If input file does not exist
        TypeError: If arguments are not of expected types
        RuntimeError: If ProDy required for .cif but not available
    """
    if not isinstance(pdb_file, str):
        raise TypeError(f"pdb_file must be str, got {type(pdb_file).__name__}")
    if not isinstance(output_pdbqt, str):
        raise TypeError(f"output_pdbqt must be str, got {type(output_pdbqt).__name__}")
    if not os.path.exists(pdb_file):
        raise FileNotFoundError(f"Structure file not found: {pdb_file}")

    from meeko import ResidueChemTemplates

    if not _HAVE_MEEKO or not _HAVE_RDKIT:
        raise PreparationError("meeko and rdkit required: conda activate autodock313")

    # ── Format detection ──────────────────────────────────────────────
    ext = os.path.splitext(pdb_file)[1].lower()
    if input_format == 'auto':
        if ext in ('.cif', '.pdbx'):
            input_format = 'cif'
        else:
            input_format = 'pdb'
    elif input_format not in ('pdb', 'cif', 'pdbx'):
        raise ValueError(f"input_format must be 'auto'|'pdb'|'cif'|'pdbx', got: {input_format}")

    # ── Read/convert input ────────────────────────────────────────────
    if input_format in ('cif', 'pdbx'):
        # ProDy mmCIF → PDB text conversion
        try:
            import prody
        except ImportError:
            raise RuntimeError(
                "ProDy required for .cif/.pdbx parsing. "
                "Install: conda install -c conda-forge prody"
            )
        structure = prody.parseMMCIF(pdb_file)
        # Write to PDB string in memory
        import io
        pdb_stream = io.StringIO()
        prody.writePDBStream(pdb_stream, structure)
        pdb_content = pdb_stream.getvalue()
        logger.info(f"[autodock] Converted {ext} → PDB via ProDy ({structure.numAtoms()} atoms)")
    else:
        # Direct PDB text read
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
    try:
        polymer = Polymer.from_pdb_string(pdb_content, templates, mk_prep)
    except PolymerCreationError:
        # Non-standard residues (e.g. NFH/NFN) fail template matching by default.
        # Retry with allow_bad_res=True: meeko removes the offending residues and
        # produces a valid PDBQT for the remaining well-resolved protein.
        logger.warning(
            f"[autodock] Some residues in {os.path.basename(pdb_file)}"
            f" failed template matching — retrying with allow_bad_res=True"
        )
        polymer = Polymer.from_pdb_string(
            pdb_content, templates, mk_prep, allow_bad_res=True)
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
        raise PreparationError("rdkit and meeko required: conda activate autodock313")
    if not isinstance(smiles, str):
        raise TypeError(f"smiles must be str, got {type(smiles).__name__}")
    if not isinstance(output_pdbqt, str):
        raise TypeError(f"output_pdbqt must be str, got {type(output_pdbqt).__name__}")

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise PreparationError(f"Could not parse SMILES: {smiles}")
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
        raise PreparationError(f"Meeko ligand prep failed: {err}")
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
        raise PreparationError("rdkit and meeko required: conda activate autodock313")
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
            raise PreparationError(f"Could not parse SMILES: {smiles}")
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
            raise PreparationError(f"Meeko conformer {i} failed: {err}")
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
_POCKET_MAX_DIM = 40.0  # maximum pocket span (40 Å is more than enough for drug-sized molecules)

# Volume-based false positive filtering
# Pockets > 2000 A³ are typically solvent-exposed grooves or PPI interfaces
_POCKET_MAX_VOLUME = 2000.0   # Å³
_POCKET_MIN_DEPTH = 3.0       # Å — very shallow pockets are often false positives

# Confidence thresholds (soft warnings, not hard filters)
_P2RANK_PROB_THRESHOLD = 0.15      # P2Rank confidence threshold
_DRUGGABILITY_THRESHOLD = 0.15     # fpocket druggability threshold


def _compute_box_size(dims: tuple, padding: float = 5.0,
                     ligand_pdbqt: str | None = None) -> tuple:
    """
    Compute Vina docking box size from pocket dimensions.

    Rounds to nearest 0.5 A to match Vina's internal 0.375 A grid spacing.
    Ensures minimum box of 10 A on each axis.

    If ligand_pdbqt provided, ensures box is large enough for the ligand
    plus additional padding (box must fit ligand + 2*padding on each side).
    """
    raw = [d + 2 * padding for d in dims]

    if ligand_pdbqt and os.path.exists(ligand_pdbqt):
        lig_dims = _estimate_ligand_dimensions(ligand_pdbqt)
        if lig_dims:
            # Box must fit ligand + 2*padding on each side
            raw = [max(r, ld + 4 * padding) for r, ld in zip(raw, lig_dims)]

    box = []
    for v in raw:
        rounded = round(v * 2) / 2  # nearest 0.5 A
        box.append(max(10.0, rounded))
    return tuple(box)


def _estimate_ligand_dimensions(pdbqt_path: str) -> tuple | None:
    """Estimate ligand bounding box from PDBQT coordinates."""
    try:
        coords = []
        with open(pdbqt_path) as f:
            for line in f:
                if line.startswith(('ATOM', 'HETATM')):
                    try:
                        x = float(line[30:38])
                        y = float(line[38:46])
                        z = float(line[46:54])
                        coords.append((x, y, z))
                    except ValueError:
                        continue
        if coords:
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            zs = [c[2] for c in coords]
            return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    except Exception:
        pass
    return None


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
                    use_p2rank: bool = True,
                    fpocket_min_alpha: float = 3.4,
                    fpocket_max_alpha: float = 6.2,
                    ligand_pdbqt: str = None) -> list:
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
        raise PreparationError("rdkit required: conda activate autodock313")

    # ── Option 1: co-crystallized ligand (gold standard) ────────────────
    if ligand_pdb and os.path.exists(ligand_pdb):
        mol = Chem.MolFromPDBFile(ligand_pdb)
        conf = mol.GetConformer()
        coords = [conf.GetAtomPosition(i) for i in range(mol.GetNumAtoms())]
        xs = [c.x for c in coords]; ys = [c.y for c in coords]; zs = [c.z for c in coords]
        center = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        dims = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        box_size = _compute_box_size(dims, padding, ligand_pdbqt)
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
            [fpocket_bin, '-f', prep_pdb_abs,
             '-m', str(fpocket_min_alpha),
             '-M', str(fpocket_max_alpha)],
            capture_output=True, text=True, timeout=120, cwd=prep_dir
        )
        if result.returncode != 0:
            raise PreparationError(f"fpocket failed: {result.stderr}")

        info_file = os.path.join(out_dir, base + '_info.txt')
        if not os.path.exists(info_file):
            raise PreparationError(f"fpocket did not produce info file: {info_file}")

        pockets = _parse_fpocket_info(info_file)
        if not pockets:
            raise PreparationError(f"No pockets found by fpocket in {receptor_pdb}")

        # ── P2Rank rescoring ──────────────────────────────────────────
        p2rank_probs = None
        if use_p2rank:
            p2rank_probs = _run_p2rank_rescore(prep_pdb_abs, base, out_dir)
            if p2rank_probs:
                logger.info(f"[autodock] P2Rank rescored {len(p2rank_probs)} pockets "
                      f"(prob range: {min(p2rank_probs.values()):.3f} - "
                      f"{max(p2rank_probs.values()):.3f})")

        # Validate P2Rank pocket count matches fpocket
        if p2rank_probs and len(p2rank_probs) != len(pockets):
            logger.warning(
                f"[autodock] P2Rank returned {len(p2rank_probs)} pockets, "
                f"but fpocket found {len(pockets)}. Number mapping may be unreliable."
            )

        # ── Sort and filter pockets ──────────────────────────────────
        # Primary sort: P2Rank probability (higher = more confident)
        # Secondary sort: Druggability Score minus opening penalty
        # Prefer closed pockets (0-1 openings) over open pockets (2+ openings)
        def pocket_sort_key(p):
            prob = p2rank_probs.get(p['num'], None) if p2rank_probs else None
            drugg = p['druggability']
            # Closed pockets are more likely to be true binding sites
            opening_penalty = 0.0
            if p.get('openings') is not None:
                opening_penalty = p['openings'] * 0.05  # -0.05 per opening
            return (prob if prob is not None else -1.0,
                    drugg - opening_penalty)

        pockets.sort(key=pocket_sort_key, reverse=True)

        result_pockets = []
        for p in pockets:
            # Dimension check
            if any(d < _POCKET_MIN_DIM or d > _POCKET_MAX_DIM for d in p['dims']):
                continue
            # Volume check — oversized pockets are typically false positives
            if p.get('volume') is not None and p['volume'] > _POCKET_MAX_VOLUME:
                logger.warning(f"[autodock] Pocket #{p['num']} oversized ({p['volume']:.0f} Å³ > {_POCKET_MAX_VOLUME}), skipping")
                continue
            # Depth check — soft warning for shallow pockets
            if p.get('depth') is not None and p['depth'] < _POCKET_MIN_DEPTH:
                logger.info(f"[autodock] Pocket #{p['num']} shallow (depth={p['depth']:.1f}Å), may be false positive")
            prob = p2rank_probs.get(p['num'], None) if p2rank_probs else None
            center = p['center']
            box_size = _compute_box_size(p['dims'], padding, ligand_pdbqt)
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
            prob = pk['p2rank_prob']
            prob_str = f"P2Rank={prob:.3f}" if prob is not None else "P2Rank=N/A"
            # Low confidence warnings
            if prob is not None and prob < _P2RANK_PROB_THRESHOLD:
                logger.warning(f"[autodock] Pocket {i+1} (fpocket #{pk['pocket_num']}): "
                               f"LOW P2Rank confidence ({prob:.3f} < {_P2RANK_PROB_THRESHOLD})")
            if pk['druggability'] < _DRUGGABILITY_THRESHOLD:
                logger.warning(f"[autodock] Pocket {i+1} (fpocket #{pk['pocket_num']}): "
                               f"LOW druggability ({pk['druggability']:.3f} < {_DRUGGABILITY_THRESHOLD})")
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

def _prepare_pdb_for_fpocket(pdb_in: str, pdb_out: str) -> None:
    """Remove waters, keep ATOM/HETATM. Only skip generic water names."""
    with open(pdb_in) as fin, open(pdb_out, 'w') as fout:
        for line in fin:
            if line.startswith('ATOM') or line.startswith('HETATM'):
                if line[17:20].strip() not in _SKIP_WATER:
                    fout.write(line)


def _parse_fpocket_info(info_path: str) -> list:
    """Parse fpocket *_info.txt to extract pocket centroids, dims, and descriptors."""
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

        # Parse additional fpocket descriptors
        vm = re.search(r'Volume\s+:\s+([\d.]+)', block)
        volume = float(vm.group(1)) if vm else None

        depm = re.search(r'Depth\s+:\s+([\d.]+)', block)
        depth = float(depm.group(1)) if depm else None

        om = re.search(r'Number of mouth openings\s+:\s+(\d+)', block)
        openings = int(om.group(1)) if om else None

        apm = re.search(r'Number of apolar alpha sphere\s+:\s+(\d+)', block)
        n_apolar = int(apm.group(1)) if apm else None

        ppm = re.search(r'Number of polar alpha sphere\s+:\s+(\d+)', block)
        n_polar = int(ppm.group(1)) if ppm else None

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
                'volume': volume,
                'depth': depth,
                'openings': openings,
                'n_apolar': n_apolar,
                'n_polar': n_polar,
                'center': center,
                'dims': dims if dims else (20.0, 20.0, 20.0),
            })
    return pockets


# ─────────────────────────────────────────────────────────────────────────────
# INTERACTION DETECTION (RDKit geometry)
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


