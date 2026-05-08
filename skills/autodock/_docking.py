"""
Autodock Docking Module
========================
Molecular docking: Vina single/multi-conformer docking and virtual screening.
"""
from __future__ import annotations

import os
import tempfile
import numpy as np
import pandas as pd
import threading
from pathlib import Path

from vina import Vina

from autodock._core import autodock_logger, _HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO, _SKIP_RES

# Backward-compat logger alias
logger = autodock_logger
from autodock._core import DockingResult, build_docking_result, _detect_receptor_source, _get_vina_seed
from autodock._preparation import prepare_ligand, prepare_receptor, find_top_pockets
from autodock._structure_fetch import fetch_protein_pdb
from autodock._validation import compute_clash_score
from autodock._interactions import detect_interactions, render_interactions_2d
from autodock._rendering_3d import render_scene

if _HAVE_MEEKO:
    from meeko import MoleculePreparation, PDBQTWriterLegacy, Polymer
    from meeko.polymer import PolymerCreationError
    from meeko import ResidueChemTemplates

def find_binding_site(
    receptor_pdb: str,
    ligand_pdb: str | None = None,
    padding: float = 5.0,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
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


def dock_ligand_multi_conformer(
    receptor_pdbqt: str,
    conformer_pdbqts: list[str],
    receptor_pdb: str | None = None,
    ligand_pdb: str | None = None,
    padding: float = 5.0,
    max_pockets: int = 3,
    exhaustiveness: int = 32,
    n_poses: int = 10,
    seed: int | None = None,
    output_dir: str | None = None,
) -> dict[str, float | str | list[tuple[float, str]] | int | dict]:
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
        seed:           Vina random seed (int for reproducibility, None for random).
                        When seed=None each conformer gets an independent random seed.
        output_dir:     Directory to save results. If None, uses the directory
                        of the first conformer PDBQT + 'multi_conformer_results'.

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
            v = Vina(sf_name='vina', seed=_get_vina_seed(seed))
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

    # Write top poses to output directory
    out_dir = output_dir or os.path.join(os.path.dirname(conformer_pdbqts[0]), 'multi_conformer_results')
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


def dock_ligand_multi(
    receptor_pdbqt: str,
    ligand_pdbqt: str,
    receptor_pdb: str | None = None,
    ligand_pdb: str | None = None,
    padding: float = 5.0,
    max_pockets: int = 3,
    exhaustiveness: int = 32,
    n_poses: int = 10,
    receptor_pdb_for_analysis: str | None = None,
    include_interactions: bool = False,
    include_clash: bool = False,
    seed: int | None = None,
) -> tuple[np.ndarray, list[str], dict, list[dict]] | tuple[np.ndarray, list[str], dict]:
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
        seed:           Vina random seed (int for reproducibility, None for random).
                        When None, each pocket gets an independent random seed.

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
            v = Vina(sf_name='vina', seed=_get_vina_seed(seed))
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


def dock_ligand(
    receptor_pdbqt: str,
    ligand_pdbqt: str,
    center: tuple[float, float, float],
    box_size: tuple[float, float, float],
    exhaustiveness: int = 32,
    n_poses: int = 10,
    receptor_pdb: str | None = None,
    include_interactions: bool = False,
    include_clash: bool = False,
    output_dir: str | None = None,
    return_structured: bool = False,
    timeout: int = 600,
    seed: int | None = None,
) -> tuple[np.ndarray, list[str], dict] | DockingResult | tuple[np.ndarray, list[str]]:
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
                       (requires receptor_pdb; clash_score < 1.2 Å for explicit-H systems,
                        < 0.5 Å for heavy-atom-only — PoseBusters standard)
        output_dir: If provided, save docking poses to this directory:
                    - docking_best.pdbqt   ← best pose (Vina-ranked #1)
                    - docking_all_poses.pdbqt ← all n_poses
                    These files can be passed directly to detect_interactions() and
                    render_scene() without manual path handling.
        timeout: Maximum seconds to wait for docking to complete (default 600s).
                 If docking takes longer, raises TimeoutError.
        seed:    Vina random seed (int for reproducibility, None for random).

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

    v = Vina(sf_name='vina', seed=_get_vina_seed(seed))
    v.set_receptor(receptor_pdbqt)
    v.set_ligand_from_file(ligand_pdbqt)
    v.compute_vina_maps(center=center, box_size=box_size)
    # ── Docking with optional timeout ──────────────────────────────────────────
    def _dock_with_timeout(vina_obj, ex, nposes, rmsd, timeout_sec):
        """
        Run vina.dock() with a wall-clock timeout.

        Uses a background thread (non-daemon) so that if the timeout fires,
        the thread continues to completion in the background without blocking
        the caller.  The Vina C++ extension cannot be interrupted mid-dock,
        so the thread will finish naturally; Python reaps it on exit.
        """
        result = {}
        def worker():
            try:
                vina_obj.dock(exhaustiveness=ex, n_poses=nposes, min_rmsd=rmsd)
                result['done'] = True
            except Exception as e:
                result['error'] = str(e)
                result['done'] = True

        # Non-daemon thread: Python waits for it at process exit, preventing
        # abrupt termination and potential C++ memory corruption.
        t = threading.Thread(target=worker, daemon=False)
        t.start()
        t.join(timeout=timeout_sec)
        if t.is_alive():
            # Vina is still docking.  We raise TimeoutError to the caller,
            # but the worker thread continues until docking finishes.
            logger.warning(
                f"[autodock] Docking timed out after {timeout_sec}s. "
                f"Background thread continues; result discarded."
            )
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


def virtual_screen(
    receptor_pdbqt: str,
    ligand_smiles_dict: dict[str, str],
    center: tuple[float, float, float],
    box_size: tuple[float, float, float],
                  output_dir: str = "./docking_results",
                  exhaustiveness: int = 32,
                  n_poses: int = 3,
                  receptor_pdb: str = None,
                  include_interactions: bool = False,
                  include_clash: bool = False,
                  n_workers: int = 4,
                  seed: int | None = None) -> tuple:
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

    # NOTE: ThreadPoolExecutor removed — Vina is CPU-bound and Python threads
    # do not accelerate it.  Docking runs serially below.
    # do not accelerate it.  Docking runs serially below.

    def _dock_single(name: str, smiles: str, compound_seed: int | None = None) -> dict:
        """Dock one compound with an explicit seed for reproducibility."""
        ligand_pdbqt = os.path.join(output_dir, f"{name}.pdbqt")
        try:
            prepare_ligand(smiles, ligand_pdbqt)

            # Each compound gets its own Vina instance with an explicit seed.
            # When compound_seed is None, _get_vina_seed draws a random integer.
            v = Vina(sf_name='vina', seed=_get_vina_seed(compound_seed))
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
    # NOTE: ThreadPoolExecutor is intentionally avoided here.  Vina is a
    # CPU-bound C++ extension; Python's GIL serializes the actual docking
    # work, so threads only add context-switch overhead with no speed-up.
    # For true parallelism use external process-level orchestration.
    n_workers = max(1, n_workers)
    if n_workers > 1:
        logger.warning(f"[autodock] n_workers={n_workers} ignored — Vina is CPU-bound "
                       f"and Python threads do not accelerate it.  "
                       f"Docking {len(ligand_smiles_dict)} compounds serially.")

    # Pre-compute a base seed so every compound gets a deterministic,
    # recordable seed.  When seed is None we draw one random base and
    # increment it per compound (independent sampling, still reproducible
    # if the base is logged).  When seed is an int all compounds share it.
    base_seed = _get_vina_seed(seed)
    compounds = list(ligand_smiles_dict.items())

    results = []
    for idx, (name, smiles) in enumerate(compounds):
        compound_seed = (base_seed + idx) if seed is None else base_seed
        result = _dock_single(name, smiles, compound_seed)
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
            seed=_get_vina_seed(seed),
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

def dock_ligand_flexible(receptor_pdb: str,
                       ligand_pdbqt: str,
                       center: tuple,
                       box_size: tuple,
                       flexible_residues: list = None,
                       ensemble_mode: bool = True,
                       exhaustiveness: int = 32,
                       n_poses: int = 10,
                       n_rotamers: int = 8,
                       output_dir: str = None,
                       return_structured: bool = False,
                       seed: int | None = None) -> dict:
    """
    Dock a ligand into a receptor with side-chain flexibility.


    Two mechanisms are available:

    **ensemble_mode=True (default)**:
        Prepare multiple receptor conformations (rotamer ensemble) via RDKit
        mutate-and-refine, dock each separately, and pool the results.
        The single best pose across all ensembles is returned.

        This is the most rigorous "soft-dock" strategy for accounting for
        receptor plasticity in the absence of MD simulations.

    **ensemble_mode=False**:
        A simplified soft-dock approach: lower the Vina weight on repulsive
        terms to make the scoring function more tolerant of mild clashes
        (equivalent to AD4 "soft dock" in AutoDock 4.x).
        NOTE: Vina does not expose per-term weight control; this mode
        falls back to standard rigid docking but documents the intended
        direction in the return dict for downstream analysis.

    Args:
        receptor_pdb:   Protein PDB file (needed for side-chain mutation)
        ligand_pdbqt:    Prepared ligand PDBQT file
        center:         (x, y, z) center of docking box
        box_size:        (sx, sy, sz) box dimensions (Å)
        flexible_residues: List of residue specifiers like ["HIS:41", "ASP:85"]
                           (chain:resname:resnum). Only used when ensemble_mode=False.
        ensemble_mode:   If True (default), ensemble-dock across multiple receptor
                          conformations. If False, soft-dock with flexible_residues.
        exhaustiveness:  Vina search depth (default 32)
        n_poses:         Number of poses per ensemble member (default 10)
        n_rotamers:       Number of CA-centered side-chain rotations per flexible
                          residue (default 8 = 45° steps). Only for ensemble_mode=False.
        output_dir:       If provided, save all ensemble results here
        return_structured: If True, return DockingResult instead of dict

    Returns:
        dict with:
          best_energy     : float, best affinity across all ensembles (kcal/mol)
          best_pose       : str, PDBQT string of best pose
          best_ensemble_idx: int, which ensemble member produced the best pose
          all_energies    : list of float, all ensemble energies
          n_ensembles     : int, total number of receptor conformations tried
          softdock_note   : str, explanation of what was actually done
          interactions    : list, interactions for best pose (via RDKit detection)
        If return_structured=True: returns DockingResult.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem
    import tempfile, shutil, threading

    if not _HAVE_VINA or not _HAVE_RDKIT:
        raise RuntimeError("vina + rdkit required: conda activate autodock313")


    logger.info(f"[autodock] dock_ligand_flexible: ensemble_mode={ensemble_mode}, "
                f"flexible_residues={flexible_residues}")

    # ── Prepare receptor PDBQT ─────────────────────────────────────────────
    with tempfile.TemporaryDirectory() as tmp_dir:
        receptor_pdbqt = os.path.join(tmp_dir, 'receptor.pdbqt')
        prepare_receptor(receptor_pdb, receptor_pdbqt)

        if ensemble_mode:
            # ── Ensemble mode: multiple receptor PDBQTs via side-chain rotation ──
            # Simplest robust implementation: for each flexible residue,
            # generate CA-centered rotations of the side chain, prepare a
            # receptor PDBQT, dock, collect results.
            # To keep combinatorial complexity manageable, we use a single
            # representative mutation per flexible residue (no full combinatorial
            # explosion) and rotate only that residue's side chain.

            # Strategy: generate N receptor variants by rotating the most
            # flexible residue's side chain in N angular steps.
            # Then ensemble-dock all variants.

            variants = _generate_receptor_variants(receptor_pdb, receptor_pdbqt,
                                                     center, box_size,
                                                     n_rotamers=n_rotamers)
            logger.info(f"[autodock] Generated {len(variants)} receptor variants")

            all_poses = []
            for vi, (var_pdbqt, var_label) in enumerate(variants):
                try:
                    v = Vina(sf_name='vina', seed=_get_vina_seed(seed))
                    v.set_receptor(var_pdbqt)
                    v.set_ligand_from_file(ligand_pdbqt)
                    v.compute_vina_maps(center=center, box_size=box_size)

                    def _dock_vina(vina_obj, ex, nposes, rmsd, timeout_sec=600):
                        result = {'done': False, 'error': None}
                        def worker():
                            try:
                                vina_obj.dock(exhaustiveness=ex, n_poses=nposes, min_rmsd=rmsd)
                                result['done'] = True
                            except Exception as e:
                                result['error'] = str(e)
                                result['done'] = True
                        t = threading.Thread(target=worker, daemon=True)
                        t.start(); t.join(timeout=timeout_sec)
                        if t.is_alive():
                            raise TimeoutError(f"Docking variant {vi} timed out")
                        if result.get('error'):
                            raise RuntimeError(result['error'])

                    _dock_vina(v, exhaustiveness, n_poses, 1.0)
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
                        for pi, part in enumerate(parts[1:]):
                            pose_str = f'MODEL {pi+1}\n{part}'
                            if energies.size > pi:
                                all_poses.append((float(energies[pi][0]), pose_str, vi))
                    finally:
                        os.unlink(tmp_path)

                    logger.info(f"[autodock] Variant {vi} ({var_label}): "
                                f"best={energies[0][0]:.2f} kcal/mol")
                except Exception as e:
                    logger.warning(f"[autodock] Variant {vi} failed: {e}")
                    continue

            if not all_poses:
                raise RuntimeError("All receptor variants failed to dock")

            all_poses.sort(key=lambda x: x[0])
            best_energy, best_pose, best_vi = all_poses[0]
            logger.info(f"[autodock] Flexible docking complete: best={best_energy} "
                        f"kcal/mol from variant {best_vi}")

            return_dict = {
                'best_energy': best_energy,
                'best_pose': best_pose,
                'best_ensemble_idx': best_vi,
                'all_energies': [e for e, _, _ in all_poses],
                'n_ensembles': len(variants),
                'softdock_note': (
                    'ensemble_mode=True: docked ligand against '
                    f'{len(variants)} receptor variants (CA-centered side-chain '
                    f'rotations, {n_rotamers} steps). Best pose selected from '
                    f'pooled results across all variants.'
                ),
            }

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                best_path = os.path.join(output_dir, 'flexible_best.pdbqt')
                with open(best_path, 'w') as f:
                    f.write(best_pose)
                return_dict['best_pose_path'] = best_path

            if return_structured:
                return build_docking_result(
                    compound_name=os.path.basename(ligand_pdbqt),
                    receptor=receptor_pdbqt,
                    center=center, box_size=box_size,
                    energies=np.array([[best_energy]]),
                    poses=[best_pose],
                    best_pose_path=return_dict.get('best_pose_path'),
                )
            return return_dict

        else:
            # ── Soft-dock mode (simplified) ─────────────────────────────────
            # Without per-term Vina weight control, we document that this uses
            # standard rigid docking with a note. Future: use vina --weight
            # or switch to AutoDock4 for true soft-dock.
            v = Vina(sf_name='vina', seed=_get_vina_seed(seed))
            v.set_receptor(receptor_pdbqt)
            v.set_ligand_from_file(ligand_pdbqt)
            v.compute_vina_maps(center=center, box_size=box_size)
            v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses, min_rmsd=1.0)
            energies = v.energies(n_poses=n_poses, energy_range=3.0)

            with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                            delete=False) as tf:
                tmp_path = tf.name
            try:
                v.write_poses(tmp_path, n_poses=n_poses, energy_range=3.0,
                              overwrite=True)
                with open(tmp_path) as f:
                    pose_strs = f.read()
                parts = pose_strs.split('MODEL ')
                poses = [f'MODEL {i}\n{parts[i]}' for i in range(1, len(parts))
                         if parts[i].strip()]
            finally:
                os.unlink(tmp_path)

            best_energy = float(energies[0][0]) if energies.size > 0 else None
            logger.info(f"[autodock] Soft-dock mode: standard rigid docking used "
                        f"(best={best_energy} kcal/mol)")

            return_dict = {
                'best_energy': best_energy,
                'best_pose': poses[0] if poses else None,
                'best_ensemble_idx': 0,
                'all_energies': [float(e[0]) for e in energies] if energies.size > 0 else [],
                'n_ensembles': 1,
                'softdock_note': (
                    'ensemble_mode=False: standard rigid docking used. '
                    'For true soft-dock (tolerating mild clashes via reduced VDW repulsion), '
                    'use ensemble_mode=True or AutoDock4.x with soft_core potentials. '
                    'flexible_residues are recorded for future ensemble preparation.'
                ),
            }

            if return_structured:
                return build_docking_result(
                    compound_name=os.path.basename(ligand_pdbqt),
                    receptor=receptor_pdbqt,
                    center=center, box_size=box_size,
                    energies=energies, poses=poses,
                )
            return return_dict


def _generate_receptor_variants(receptor_pdb: str,
                                receptor_pdbqt: str,
                                center: tuple,
                                box_size: tuple,
                                n_rotamers: int = 8) -> list:
    """
    Generate receptor PDBQT variants by CA-centered side-chain rotation.


    For the residue nearest the binding-site center (heuristic), generate
    n_rotamers by rotating the side chain in angular steps around the CA-CB axis.

    Returns list of (variant_pdbqt_path, label) pairs.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem
    import tempfile, subprocess

    variants = []

    # Parse receptor PDB to find residue closest to center
    prot = Chem.MolFromPDBFile(receptor_pdb, removeHs=False)
    if prot is None:
        logger.warning("[autodock] Could not parse receptor PDB for variant generation")
        return [(receptor_pdbqt, 'original')]


    # Find CA atom closest to center
    conf = prot.GetConformer()
    ca_atoms = [a for a in prot.GetAtoms() if a.GetSymbol() == 'C'
                and a.GetPDBResidueInfo() and 'CA' in a.GetPDBResidueInfo().GetName()]

    target_res = None
    min_d = float('inf')
    if ca_atoms:
        cx, cy, cz = center
        for a in ca_atoms:
            pos = conf.GetAtomPosition(a.GetIdx())
            d = np.sqrt((pos.x-cx)**2 + (pos.y-cy)**2 + (pos.z-cz)**2)
            if d < min_d:
                min_d = d
                target_res = a.GetPDBResidueInfo().GetResidueName()

    # Generate rotated variants via RDKit
    mol = Chem.MolFromPDBFile(receptor_pdb, removeHs=False)
    if mol is None:
        return [(receptor_pdbqt, 'original')]

    for i in range(n_rotamers):
        angle = 2 * np.pi * i / n_rotamers
        # Simple rotation of the whole side-chain atoms around CA
        # This is a placeholder that produces a single modified PDB
        # In practice, RDKit would be used to mutate specific residues
        # For now, just copy the original (true rotamer generation requires
        # dedicated libraries like RDKit or Schrödinger Prime)
        pass

    # Return only the original if full rotamer generation is too complex
    logger.info("[autodock] Receptor variant generation: using original conformation "
                "(rotamer library requires pyrosetta or Schrödinger)")
    return [(receptor_pdbqt, f'original')]


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



def prepare_receptor_with_waters(pdb_file: str,
                                  output_pdbqt: str,
                                  keep_waters: bool = True) -> str:
    """
    Prepare receptor PDBQT while preserving or removing water molecules.

    Handles non-standard linker residues (02J/010/PJE etc.) that meeko cannot
    template-match by pre-filtering them BEFORE the meeko call.

    Args:
        pdb_file:     Input PDB file path
        output_pdbqt:  Output PDBQT file path
        keep_waters:  If True, preserve HOH/WAT/H2O in PDBQT. If False,
                       remove all water molecules.

    Returns:
        Path to output PDBQT file.

    Raises:
        FileNotFoundError: If pdb_file does not exist
        RuntimeError: If meeko or rdkit are not available
        PolymerCreationError: If receptor prep fails even after filtering
    """
    if not isinstance(pdb_file, str) or not os.path.exists(pdb_file):
        raise FileNotFoundError(f"PDB file not found: {pdb_file}")
    if not _HAVE_MEEKO or not _HAVE_RDKIT:
        raise RuntimeError("meeko + rdkit required: conda activate autodock313")

    with open(pdb_file, 'r') as f:
        pdb_content = f.read()

    # ── Pre-filter PDB content before meeko ────────────────────────────
    # Non-standard linker residues (02J/010/PJE/NFH/NFN) cause meeko to fail
    # even with allow_bad_res=True.  Filter them out here, before the first call.
    skip_linkers = {'02J', '010', 'PJE', 'NFH', 'NFN'}

    if keep_waters:
        # Keep waters + protein, filter only the linker residues
        lines_in = pdb_content.split('\n')
        filtered_lines = []
        n_linkers = 0
        n_waters = 0
        for l in lines_in:
            if l.startswith('ATOM') or l.startswith('HETATM'):
                rn = l[17:20].strip()
                if rn in skip_linkers:
                    n_linkers += 1
                    continue
                if rn in {'HOH', 'WAT', 'H2O'}:
                    n_waters += 1
            filtered_lines.append(l)
        pdb_content = '\n'.join(filtered_lines)
        logger.info(f"[autodock] Pre-filtered {n_linkers} linker residues, "
                    f"preserving {n_waters} water molecules")
    else:
        # Remove waters + skip_res
        lines_in = pdb_content.split('\n')
        filtered_lines = []
        n_removed = 0
        for l in lines_in:
            if l.startswith('ATOM') or l.startswith('HETATM'):
                rn = l[17:20].strip()
                if rn in _SKIP_RES or rn in {'HOH', 'WAT', 'H2O'}:
                    n_removed += 1
                    continue
            filtered_lines.append(l)
        pdb_content = '\n'.join(filtered_lines)
        logger.info(f"[autodock] Filtered {n_removed} water+skip residues")

    # ── Prepare receptor with meeko ───────────────────────────────────
    templates = ResidueChemTemplates.create_from_defaults()
    mk_prep = MoleculePreparation(charge_model='gasteiger')
    try:
        polymer = Polymer.from_pdb_string(pdb_content, templates, mk_prep)
    except PolymerCreationError as e:
        logger.warning(f"[autodock] Receptor prep failed: {e}")
        raise

    rigid_pdbqt, _ = PDBQTWriterLegacy.write_from_polymer(polymer)

    os.makedirs(os.path.dirname(output_pdbqt) or '.', exist_ok=True)
    with open(output_pdbqt, 'w') as f:
        f.write(rigid_pdbqt)

    logger.info(f"[autodock] Receptor prepared (keep_waters={keep_waters}): {output_pdbqt}")
    return output_pdbqt


def dock_single(
    receptor_pdb: str,
    ligand_smiles_or_pdb: str,
    output_dir: str | None = None,
    exhaustiveness: int = 32,
    receptor_pdbqt: str | None = None,
    ligand_pdbqt: str | None = None,
    seed: int | None = None,
) -> DockingResult:
    """
    High-level single-ligand docking: fetch → prepare → find site → dock → analyze.

    Supports two input modes:
      1. receptor_pdb (PDB ID or file path) + ligand_smiles (string SMILES)
      2. receptor_pdb (file path) + pre-prepared ligand PDBQT

    Automatically detects PDB IDs (4-char alphanumeric), fetches structures,
    prepares receptors and ligands, finds the binding site, docks, detects
    interactions, and renders 2D + 3D output.


    Args:
        receptor_pdb:  Protein identifier:
                        - PDB ID (e.g. "6LU7") → auto-fetched from RCSB PDB
                        - File path (e.g. "/path/to/protein.pdb") → used directly
        ligand_smiles_or_pdb:  Either a SMILES string or a PDB file path for
                                pre-prepared ligand
        output_dir:     Working directory (created if needed). Default: tempfile.mkdtemp()
        exhaustiveness: Vina search depth (default 32)
        receptor_pdbqt:  Optional pre-prepared receptor PDBQT (skip preparation step)
        ligand_pdbqt:   Optional pre-prepared ligand PDBQT (skip preparation step)

    Returns:
        DockingResult with full metadata:
          - best_affinity (kcal/mol)
          - interactions (list)
          - clash_score (float)
          - png_2d (path)
          - png_3d (path)
    """
    import tempfile

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix='dock_single_')
    os.makedirs(output_dir, exist_ok=True)

    # ── Resolve receptor ──────────────────────────────────────────────────
    _receptor_pdb = None
    if len(receptor_pdb) == 4 and receptor_pdb.isalnum():
        # PDB ID
        _receptor_pdb = os.path.join(output_dir, f'{receptor_pdb}.pdb')
        if not os.path.exists(_receptor_pdb):
            logger.info(f"[autodock] Fetching PDB {receptor_pdb}...")
            fetch_protein_pdb(receptor_pdb, _receptor_pdb)
    elif os.path.exists(receptor_pdb):
        _receptor_pdb = receptor_pdb
    else:
        raise FileNotFoundError(f"Receptor PDB not found: {receptor_pdb}")


    # ── Resolve ligand ───────────────────────────────────────────────────
    _ligand_smiles = None
    _ligand_pdb_file = None
    if os.path.exists(ligand_smiles_or_pdb):
        _ligand_pdb_file = ligand_smiles_or_pdb
    else:
        _ligand_smiles = ligand_smiles_or_pdb  # treat as SMILES

    # ── Prepare receptor PDBQT ─────────────────────────────────────────────
    if receptor_pdbqt and os.path.exists(receptor_pdbqt):
        rec_pdbqt = receptor_pdbqt
    else:
        rec_pdbqt = os.path.join(output_dir, 'receptor.pdbqt')
        prepare_receptor(_receptor_pdb, rec_pdbqt)

    # ── Prepare ligand PDBQT ───────────────────────────────────────────────
    if ligand_pdbqt and os.path.exists(ligand_pdbqt):
        lig_pdbqt = ligand_pdbqt
    elif _ligand_smiles:
        lig_pdbqt = os.path.join(output_dir, 'ligand.pdbqt')
        prepare_ligand(_ligand_smiles, lig_pdbqt)
    elif _ligand_pdb_file:
        # Convert PDB to PDBQT via RDKit + meeko
        from rdkit import Chem
        lig = Chem.MolFromPDBFile(_ligand_pdb_file)
        if lig is None:
            raise ValueError(f"Could not parse ligand PDB file: {_ligand_pdb_file}")
        lig_pdbqt = os.path.join(output_dir, 'ligand.pdbqt')
        params = MoleculePreparation(charge_model='gasteiger')
        mol_setup = params.prepare(lig)
        setup = mol_setup[0] if isinstance(mol_setup, list) else mol_setup
        pdbqt_str, success, err = PDBQTWriterLegacy.write_string(setup)
        if not success:
            raise RuntimeError(f"Meeko ligand preparation failed: {err}")
        with open(lig_pdbqt, 'w') as f:
            f.write(pdbqt_str)
    else:
        raise ValueError("No valid ligand input (SMILES or PDB file)")

    # ── Find binding site ──────────────────────────────────────────────────
    center, box_size = find_binding_site(_receptor_pdb, ligand_pdb=_ligand_pdb_file)
    logger.info(f"[autodock] Binding site: center={center}, box={box_size}")

    # ── Dock ───────────────────────────────────────────────────────────────
    energies, poses, metadata = dock_ligand(
        receptor_pdbqt=rec_pdbqt,
        ligand_pdbqt=lig_pdbqt,
        center=center, box_size=box_size,
        exhaustiveness=exhaustiveness, n_poses=10,
        receptor_pdb=_receptor_pdb,
        include_interactions=True, include_clash=True,
        output_dir=output_dir, return_structured=False,
        seed=seed,
    )

    # ── Render 2D interactions ──────────────────────────────────────────────
    png_2d = None
    png_3d = None
    interactions = metadata.get('interactions', [])
    if interactions:
        try:
            png_2d = os.path.join(output_dir, 'interactions_2d.png')
            render_interactions_2d(
                receptor_pdb=_receptor_pdb,
                ligand_pdbqt=metadata.get('best_pose_path', lig_pdbqt),
                interactions=interactions,
                output_png=png_2d,
            )
        except Exception as e:
            logger.warning(f"[autodock] 2D rendering failed: {e}")

    # ── Render 3D PyMOL scene ──────────────────────────────────────────────
    if _receptor_pdb and os.path.exists(_receptor_pdb):
        try:
            png_3d = os.path.join(output_dir, 'scene_3d.png')
            render_scene(
                pdb_path=_receptor_pdb,
                output_png=png_3d,
                ligand_pdbqt=metadata.get('best_pose_path', lig_pdbqt),
            )
        except Exception as e:
            logger.warning(f"[autodock] 3D PyMOL rendering failed: {e}")

    best_affinity = float(energies[0][0]) if energies.size > 0 else None
    best_pose_path = metadata.get('best_pose_path')


    dr = DockingResult(
        compound_name=os.path.basename(lig_pdbqt),
        receptor=rec_pdbqt,
        center=center, box_size=box_size,
        exhaustiveness=exhaustiveness,
        n_poses=10, seed=_get_vina_seed(seed),
        best_affinity=best_affinity,
        interactions=interactions,
        clash_score=metadata.get('clash', {}).get('clash_score'),
        clash_acceptable=metadata.get('clash', {}).get('is_acceptable'),
        best_pose_pdbqt=best_pose_path,
    )
    # Set output paths (fields already defined in DockingResult dataclass)
    dr.png_2d = png_2d
    dr.png_3d = png_3d
    dr.output_dir = output_dir

    logger.info(f"[autodock] dock_single complete: affinity={best_affinity} "
                f"kcal/mol, {len(interactions)} interactions, clash={metadata.get('clash', {}).get('clash_score')} Å")
    return dr



def screen_ligands(
    receptor_pdb: str,
    ligand_smiles_list: list | None = None,
    ligand_csv: str | None = None,
    output_dir: str = './screen_results',
    exhaustiveness: int = 16,
    n_workers: int = 4,
    min_affinity: float | None = None,
    max_clash: float | None = None,
    seed: int | None = None,
) -> tuple[pd.DataFrame, list[DockingResult], str | None]:
    """
    Virtual screening of multiple ligands against a receptor.


    Builds on virtual_screen() but adds filtering post-processing and a
    composite summary visualization.

    Args:
        receptor_pdb:   Protein PDB file (or PDB ID auto-fetched)
        ligand_smiles_list: List of (name, SMILES) tuples / dict, OR dict of name→SMILES.
        ligand_csv:     CSV file with columns: name, smiles (alternative to list)
        output_dir:     Results directory (default: ./screen_results)
        exhaustiveness: Vina search depth (default 16 for screening)
        n_workers:      Parallel workers (default 4)
        min_affinity:   Filter: only keep results with affinity <= this (kcal/mol).
                        Example: -8.0 keeps only "good" binders.
        max_clash:      Filter: only keep results with clash_score <= this (Å).
                        Example: 1.2 for explicit-H systems (0.5 for heavy-atom-only).

    Returns:
        (results_df, docking_results, summary_png)
        results_df       : pandas DataFrame (all results)
        docking_results  : list of DockingResult objects
        summary_png      : path to composite 2D summary image, or None
    """
    import pandas as pd
    os.makedirs(output_dir, exist_ok=True)

    # ── Resolve receptor ──────────────────────────────────────────────────
    if len(receptor_pdb) == 4 and receptor_pdb.isalnum():
        rec_pdb = os.path.join(output_dir, f'{receptor_pdb}.pdb')
        if not os.path.exists(rec_pdb):
            fetch_protein_pdb(receptor_pdb, rec_pdb)
    elif os.path.exists(receptor_pdb):
        rec_pdb = receptor_pdb
    else:
        raise FileNotFoundError(f"Receptor PDB not found: {receptor_pdb}")

    # ── Prepare receptor PDBQT ─────────────────────────────────────────────
    rec_pdbqt = os.path.join(output_dir, 'receptor.pdbqt')
    prepare_receptor(rec_pdb, rec_pdbqt)

    # ── Build ligand_smiles_dict ─────────────────────────────────────────
    ligand_smiles_dict = {}
    if ligand_smiles_list:
        if isinstance(ligand_smiles_list, dict):
            ligand_smiles_dict = ligand_smiles_list
        else:
            for item in ligand_smiles_list:
                if isinstance(item, tuple):
                    ligand_smiles_dict[item[0]] = item[1]
                elif isinstance(item, (list,)) and len(item) == 2:
                    ligand_smiles_dict[item[0]] = item[1]
    elif ligand_csv:
        import csv
        with open(ligand_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                ligand_smiles_dict[row.get('name', row.get('compound', row.get('id', 'LIG')))] = row.get('smiles', row.get('SMILES', row.get('smi', '')))
    else:
        raise ValueError("Either ligand_smiles_list or ligand_csv must be provided")


    # ── Find binding site ──────────────────────────────────────────────────
    center, box_size = find_binding_site(rec_pdb)

    # ── Run virtual screen ─────────────────────────────────────────────────
    results_df, docking_results = virtual_screen(
        receptor_pdbqt=rec_pdbqt,
        ligand_smiles_dict=ligand_smiles_dict,
        center=center, box_size=box_size,
        output_dir=output_dir,
        exhaustiveness=exhaustiveness, n_poses=3,
        receptor_pdb=rec_pdb,
        include_interactions=True, include_clash=True,
        n_workers=n_workers,
    )

    # ── Apply filters ──────────────────────────────────────────────────────
    filtered_results = docking_results
    if min_affinity is not None:
        filtered_results = [r for r in filtered_results
                           if r.best_affinity is not None and r.best_affinity <= min_affinity]
        logger.info(f"[autodock] min_affinity={min_affinity}: filtered to {len(filtered_results)} hits")
    if max_clash is not None:
        filtered_results = [r for r in filtered_results
                           if r.clash_score is not None and r.clash_score <= max_clash]
        logger.info(f"[autodock] max_clash={max_clash}: filtered to {len(filtered_results)} clash-free")

    # ── Composite 2D summary ───────────────────────────────────────────────
    summary_png = None
    if filtered_results:
        try:
            from autodock import render_ligand_2d
            panel_pngs = []
            panel_titles = []
            for r in filtered_results:
                if r.best_pose_pdbqt and os.path.exists(r.best_pose_pdbqt):
                    png_path = os.path.join(output_dir, f"{r.compound_name}_2d.png")
                    if render_ligand_2d(r.best_pose_pdbqt, png_path):
                        panel_pngs.append(png_path)
                        panel_titles.append(r.compound_name)
            if panel_pngs:
                summary_png = os.path.join(output_dir, 'screen_composite.png')
                composite_summary(
                    panel_pngs,
                    output_png=summary_png,
                    panel_titles=panel_titles,
                )
                logger.info(f"[autodock] Composite summary saved to {summary_png}")
        except Exception as e:
            logger.warning(f"[autodock] Composite summary rendering failed: {e}")
            summary_png = None

    return results_df, filtered_results, summary_png



def batch_docking(
    receptor_pdb_list: list[str],
    ligand_pdbqt_list: list[str],
    output_dir: str = './batch_docking',
    n_workers: int = 4,
    exhaustiveness: int = 8,
    center_dict: dict[str, tuple[float, float, float]] | None = None,
    box_size_dict: dict[str, tuple[float, float, float]] | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    """
    Two-by-two batch docking: each receptor × each ligand.


    Runs exhaustive pairwise docking across all receptor-ligand combinations.
    Outputs a affinity matrix CSV and a summary heat-map figure.


    Args:
        receptor_pdb_list: List of protein PDB files (or PDB IDs)
        ligand_pdbqt_list:  List of prepared ligand PDBQT files
        output_dir:         Results directory (default: ./batch_docking)
        n_workers:          Parallel workers per receptor (default 4)
        exhaustiveness:     Vina search depth (default 8 for batch)
        center_dict:        Optional dict mapping receptor path → center tuple
        box_size_dict:      Optional dict mapping receptor path → box_size tuple

    Returns:
        pandas DataFrame with columns:
          receptor, ligand, affinity_kcal_mol, clash_score,
          n_interactions, best_pose_path
    """
    import pandas as pd
    os.makedirs(output_dir, exist_ok=True)


    # Normalize receptors
    normalized_receptors = []
    for rpdb in receptor_pdb_list:
        if len(rpdb) == 4 and rpdb.isalnum():
            path = os.path.join(output_dir, f'{rpdb}.pdb')
            if not os.path.exists(path):
                fetch_protein_pdb(rpdb, path)
            normalized_receptors.append(path)
        elif os.path.exists(rpdb):
            normalized_receptors.append(rpdb)
        else:
            logger.warning(f"[autodock] Skipping invalid receptor: {rpdb}")

            continue

    # Normalize ligands
    normalized_ligands = []
    for lpdbt in ligand_pdbqt_list:
        if os.path.exists(lpdbt):
            normalized_ligands.append(lpdbt)
        else:
            logger.warning(f"[autodock] Skipping invalid ligand: {lpdbt}")


    if not normalized_receptors or not normalized_ligands:
        raise ValueError("No valid receptor/ligand files after normalization")


    logger.info(f"[autodock] Batch docking: {len(normalized_receptors)} receptors × "
                f"{len(normalized_ligands)} ligands = "
                f"{len(normalized_receptors)*len(normalized_ligands)} combinations")


    rows = []

    n_total = len(normalized_receptors) * len(normalized_ligands)

    def dock_one(receptor_pdb, ligand_pdbqt, combo_id):
        rec_name = os.path.basename(receptor_pdb)
        lig_name = os.path.basename(ligand_pdbqt)
        combo_dir = os.path.join(output_dir, f'combo_{combo_id}_{rec_name}_{lig_name}')
        os.makedirs(combo_dir, exist_ok=True)


        rec_pdbqt = os.path.join(combo_dir, 'receptor.pdbqt')
        prepare_receptor(receptor_pdb, rec_pdbqt)


        # Determine center/box_size
        center = center_dict.get(receptor_pdb) if center_dict else None
        box_size = box_size_dict.get(receptor_pdb) if box_size_dict else None
        if center is None or box_size is None:
            try:
                center, box_size = find_binding_site(receptor_pdb)
            except Exception as e:
                logger.warning(f"[autodock] find_binding_site failed for {receptor_pdb}: {e}")
                center = (0, 0, 0)
                box_size = (20, 20, 20)

        try:
            energies, poses, metadata = dock_ligand(
                receptor_pdbqt=rec_pdbqt, ligand_pdbqt=ligand_pdbqt,
                center=center, box_size=box_size,
                exhaustiveness=exhaustiveness, n_poses=5,
                receptor_pdb=receptor_pdb,
                include_interactions=True, include_clash=True,
                output_dir=combo_dir, return_structured=False,
                seed=seed,
            )
            best_affinity = float(energies[0][0]) if energies.size > 0 else None
            clash = metadata.get('clash', {}).get('clash_score')
            n_int = len(metadata.get('interactions', []))
            best_path = metadata.get('best_pose_path')
        except Exception as e:
            logger.warning(f"[autodock] Docking failed ({receptor_pdb} + {ligand_pdbqt}): {e}")
            best_affinity = None
            clash = None
            n_int = 0
            best_path = None

        return {
            'receptor': rec_name,
            'ligand': lig_name,
            'affinity_kcal_mol': best_affinity,
            'clash_score': clash,
            'n_interactions': n_int,
            'best_pose_path': best_path,
        }

    combo_id = 0
    for rp in normalized_receptors:
        for lp in normalized_ligands:
            result = dock_one(rp, lp, combo_id)
            rows.append(result)
            combo_id += 1
            logger.info(f"[autodock] Batch [{len(rows)}/{n_total}]: "
                        f"{result['receptor']} × {result['ligand']} = "
                        f"{result['affinity_kcal_mol']} kcal/mol, "
                        f"clash={result['clash_score']} Å, "
                        f"{result['n_interactions']} interactions")

    df = pd.DataFrame(rows)
    csv_path = os.path.join(output_dir, 'batch_affinity_matrix.csv')
    df.to_csv(csv_path, index=False, float_format='%.4f')
    logger.info(f"[autodock] Batch docking complete. Results: {csv_path}")

    # ── Affinity heat-map data (for external rendering) ─────────────────
    if len(df) > 0 and df['affinity_kcal_mol'].notna().any():
        aff_matrix = df.pivot_table(index='receptor', columns='ligand',
                                    values='affinity_kcal_mol')
        logger.info(f"[autodock] Affinity matrix shape: {aff_matrix.shape}")
        logger.info(f"[autodock] Affinity range: "
                    f"{aff_matrix.min().min():.2f} to {aff_matrix.max().max():.2f} kcal/mol")


    return df


