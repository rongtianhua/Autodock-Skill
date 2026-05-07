"""
Autodock Validation Module
===========================
RMSD calculation, clash scoring, and redocking protocol validation.
"""
import os
import tempfile
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

from autodock._preparation import _read_ligand_from_pdbqt_3d
from autodock._core import autodock_logger, _HAVE_RDKIT

# Backward-compat logger alias
logger = autodock_logger

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
                              n_poses: int = 1,
                              seed: int | None = None) -> dict:
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
        seed=seed,
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




def compute_clash_score(docked_pdbqt: str,
                         receptor_pdb: str,
                         clash_threshold: float = 1.2) -> dict:
    """
    Detect steric clashes between a docked ligand pose and the protein.

    Clash score = max(overlap) across all protein-ligand atom pairs,
    where overlap = vdw_radii_sum - distance (positive = clash).
    Reported in: DynamicBind (Nature 2024), PoseBusters benchmark.

    Important threshold distinction:
      - explicit-H systems (this skill, removeHs=False): threshold = 1.2 Å
        H atoms participate in VDW calculations; H-H contacts naturally
        yield larger overlaps. A clash score < 1.2 Å is acceptable.
      - heavy-atom-only systems (PoseBusters default): threshold = 0.5 Å
        No H atoms; stricter geometric constraints apply.

    Args:
        docked_pdbqt:  Docked ligand PDBQT string or file path
        receptor_pdb:  Protein PDB file (not PDBQT)
        clash_threshold: Warning threshold in Å overlap (default 1.2 for
                         explicit-H systems; use 0.5 for heavy-atom-only)

    Returns:
        dict with:
          clash_score (float):   max overlap in Å
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


