"""
Autodock Pose Clustering Module
================================
RMSD-based pose clustering for post-docking analysis.
"""
import os
import tempfile
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign
from rdkit import RDLogger

from autodock._core import autodock_logger, _HAVE_RDKIT
from autodock._validation import _read_ligand_from_pdbqt_3d

# Backward-compat logger alias
logger = autodock_logger


def cluster_poses(poses_pdbqt: str,
                  n_clusters: int = 5,
                  rmsd_cutoff: float = 2.0,
                  output_dir: str = None) -> list:
    """
    Cluster multiple docking poses by RMSD and return cluster representatives.

    Uses RMSD matrix + Ward's hierarchical clustering to group poses by structural
    similarity.  Returns one representative per cluster (lowest Vina energy),
    plus cluster statistics.

    Args:
        poses_pdbqt:  PDBQT file containing multiple MODEL blocks (from Vina
                     write_poses), OR a list of PDBQT strings.
        n_clusters:   Target number of clusters (default 5).  The actual number
                      may be smaller if fewer poses are available.
        rmsd_cutoff:  RMSD threshold (Å) below which two poses are considered
                      structurally similar (used for auto-detecting n_clusters
                      if n_clusters=None).  Not used when n_clusters is specified.
        output_dir:   If provided, write cluster representative PDBQTs here:
                      cluster_0_representative.pdbqt …

    Returns:
        List of dicts (one per cluster), sorted by ascending cluster energy:
          - cluster_id      : int  (0 = best-energy cluster)
          - n_poses         : int  (number of poses in this cluster)
          - representative  : str  (PDBQT string of lowest-energy pose)
          - mean_rmsd       : float (mean pairwise RMSD within cluster)
          - centroid_energy  : float (Vina energy of representative pose)
          - member_energies  : list of float (all Vina energies in cluster)
          - member_pose_strs: list of str (all PDBQT strings in cluster)
    """
    if not _HAVE_RDKIT:
        raise RuntimeError("rdkit required: conda activate autodock313")

    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist, squareform

    # ── Parse poses ─────────────────────────────────────────────────────────
    if isinstance(poses_pdbqt, str):
        if not os.path.exists(poses_pdbqt):
            raise FileNotFoundError(f"PDBQT file not found: {poses_pdbqt}")
        with open(poses_pdbqt) as f:
            pdbqt_str = f.read()
        parts = pdbqt_str.split('MODEL ')
        pose_strs = [f'MODEL {i}\n{parts[i]}'
                     for i in range(1, len(parts)) if parts[i].strip()]
    else:
        pose_strs = list(poses_pdbqt)

    n_poses = len(pose_strs)
    if n_poses < 2:
        raise ValueError(
            f"Need at least 2 poses for clustering, got {n_poses}. "
            "Use n_poses >= 2 when docking."
        )

    logger.info(f"[autodock] Clustering {n_poses} poses into {n_clusters} clusters "
                f"(RMSD cutoff={rmsd_cutoff} Å)")

    # ── Parse molecules ────────────────────────────────────────────────────
    mols = []
    for i, pstr in enumerate(pose_strs):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt',
                                         delete=False) as tf:
            tf.write(pstr)
            tmp = tf.name
        try:
            mol = _read_ligand_from_pdbqt_3d(tmp)
        finally:
            os.unlink(tmp)
        if mol is None:
            logger.warning(f"[autodock] Could not parse pose {i+1}, skipping")
            continue
        mol.SetProp('_pose_idx', str(i))
        mols.append(mol)

    if len(mols) < 2:
        raise RuntimeError(f"Fewer than 2 poses could be parsed ({len(mols)})")

    # ── Compute RMSD matrix ─────────────────────────────────────────────────
    n_mols = len(mols)
    rmsd_mat = np.zeros((n_mols, n_mols))
    for i in range(n_mols):
        for j in range(i + 1, n_mols):
            try:
                r = rdMolAlign.GetBestRMS(mols[i], mols[j])
            except Exception:
                r = 999.0
            rmsd_mat[i, j] = r
            rmsd_mat[j, i] = r

    # ── Hierarchical clustering ────────────────────────────────────────────
    # Ward's method minimizes within-cluster variance
    dist_vec = squareform(rmsd_mat)
    Z = linkage(dist_vec, method='ward')

    # Auto-detect n_clusters from rmsd_cutoff if not specified
    actual_n_clusters = n_clusters
    if actual_n_clusters is None:
        actual_n_clusters = max(1, sum(f < rmsd_cutoff for f in Z[:, 2]))

    labels = fcluster(Z, t=actual_n_clusters, criterion='maxclust')
    labels = labels - 1  # 0-indexed

    # ── Group poses by cluster ─────────────────────────────────────────────
    clusters = {}
    for i, label in enumerate(labels):
        clusters.setdefault(label, []).append(i)

    # ── Build result per cluster ───────────────────────────────────────────
    results = []
    for cid in sorted(clusters.keys()):
        idxs = clusters[cid]
        n_members = len(idxs)

        # Representative = lowest Vina energy (best binding mode)
        member_energies = []
        for idx in idxs:
            try:
                parts = pose_strs[idx].split('MODEL ')[1].split('\n')
                for line in parts:
                    if line.startswith('TORSDOF'):
                        import re
                        m = re.search(r'TORSDA\s+([\-\d.]+)', pose_strs[idx])
                        if m:
                            pass  # we don't have energy here
                        break
                # Check for REMARK VINA RESULT header
                for line in pose_strs[idx].split('\n'):
                    if 'VINA RESULT' in line:
                        import re
                        rm = re.search(r'VINA RESULT:\s+([\-\d.]+)\s+([\-\d.]+)\s+([\-\d.]+)',
                                       line)
                        if rm:
                            member_energies.append((idx, float(rm.group(1))))
                            break
            except Exception:
                pass

        rep_idx = idxs[0]
        if member_energies:
            rep_idx = min(member_energies, key=lambda x: x[1])[0]
        rep_pose = pose_strs[rep_idx]

        # Mean pairwise RMSD within cluster
        if n_members > 1:
            sub = rmsd_mat[np.ix_(idxs, idxs)]
            np.fill_diagonal(sub, 0)
            mean_rmsd = float(sub.sum() / (n_members * (n_members - 1)))
        else:
            mean_rmsd = 0.0

        results.append({
            'cluster_id': len(results),
            'n_poses': n_members,
            'representative': rep_pose,
            'mean_rmsd': mean_rmsd,
            'centroid_energy': None,  # energy unknown without Vina result header
            'member_energies': [e for _, e in member_energies],
            'member_pose_strs': [pose_strs[i] for i in idxs],
        })

    # Sort by energy (best = most negative) if energies are available
    results.sort(key=lambda c: (min(c['member_energies']) if c['member_energies']
                                 else float('inf')))

    # Re-number cluster IDs after sorting
    for i, r in enumerate(results):
        r['cluster_id'] = i

    # ── Write cluster representatives ──────────────────────────────────────
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        for r in results:
            cid = r['cluster_id']
            path = os.path.join(output_dir, f'cluster_{cid}_representative.pdbqt')
            with open(path, 'w') as f:
                f.write(r['representative'])
            logger.debug(f"[autodock] Cluster {cid}: wrote {path}")

    logger.info(f"[autodock] Clustering done: {len(results)} clusters, "
                f"sizes={[r['n_poses'] for r in results]}")

    return results
