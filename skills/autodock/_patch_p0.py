with open('_autodock.py', 'r') as f:
    content = f.read()

old = '''def compute_rmsd(docked_pdbqt: str,
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
        logger.error("[autodock] RDKit not available for RMSD calculation")
        return None

    from rdkit import Chem
    from rdkit.Chem import AllChem

    ref_mol = _read_ligand_from_pdbqt_3d(reference_pdbqt)
    docked_mol = _read_ligand_from_pdbqt_3d(docked_pdbqt)

    if ref_mol is None or docked_mol is None:
        logger.error("[autodock] Could not parse PDBQT for RMSD")
        return None

    n_ref = ref_mol.GetNumAtoms()
    n_docked = docked_mol.GetNumAtoms()
    if n_ref != n_docked:
        logger.warning(f"[autodock] Atom count mismatch: ref={n_ref} vs docked={n_docked} "
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
    return float(atom_rmsd), float(com_rmsd)'''

new = '''def compute_rmsd(docked_pdbqt: str,
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
    return float(atom_rmsd), float(com_rmsd)'''

if old in content:
    content = content.replace(old, new)
    print("P0-1: compute_rmsd replaced with MCS version ✓")
else:
    print("P0-1: exact match not found, searching...")
    idx = content.find('def compute_rmsd(docked_pdbqt: str,')
    if idx >= 0:
        print(f"Found at {idx}")
        print(repr(content[idx:idx+250]))

with open('_autodock.py', 'w') as f:
    f.write(content)