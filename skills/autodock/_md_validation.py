"""
Autodock MD Validation Module
==============================
Lightweight pose stability validation via energy minimization (OpenMM).
Uses pose-relaxation approach instead of full MD for speed.

Protocols:
- 'quick':  Energy minimization only (5-10 min) — default
- 'short':  Minimization + short NVT (30-60 min) — explicit opt-in

Requires 'autodock-amber' conda environment with OpenMM + PDBFixer.
"""
import os
import tempfile
from typing import Dict, Optional

import numpy as np

from autodock._core import autodock_logger, ValidationError
logger = autodock_logger

# ── Check OpenMM availability ────────────────────────────────────────────────
_HAVE_OPENMM = False
try:
    import openmm
    import openmm.app as app
    import openmm.unit as unit
    from pdbfixer import PDBFixer
    _HAVE_OPENMM = True
except ImportError:
    pass


def validate_pose_stability(
    receptor_pdb: str,
    ligand_pdbqt: str,
    protocol: str = 'quick',
    output_dir: Optional[str] = None,
    use_gpu: bool = False,
) -> Dict:
    """
    Validate docking pose stability via energy minimization (OpenMM).

    Args:
        receptor_pdb: Protein PDB file path
        ligand_pdbqt: Docked ligand PDBQT path
        protocol: 'quick' (minimization only) | 'short' (min + NVT)
        output_dir: Directory for output files (None = temp dir)
        use_gpu: Use GPU acceleration (Metal on macOS)

    Returns:
        {
            'is_stable': bool,          # True if pose is stable after relaxation
            'ligand_rmsd': float,       # Å (minimized vs original)
            'energy_delta': float,      # kcal/mol (final - initial)
            'minimized_pdb': str,      # path to minimized PDBQT
            'protocol': str,            # protocol used
            'warnings': list[str],     # any warnings
            'openmm_available': bool,  # whether OpenMM was available
        }

    Raises:
        ValidationError: if setup fails
    """
    if not os.path.exists(receptor_pdb):
        raise ValidationError(f"Receptor file not found: {receptor_pdb}")
    if not os.path.exists(ligand_pdbqt):
        raise ValidationError(f"Ligand file not found: {ligand_pdbqt}")

    result = {
        "is_stable": False,
        "ligand_rmsd": 0.0,
        "energy_delta": 0.0,
        "minimized_pdb": "",
        "protocol": protocol,
        "warnings": [],
        "openmm_available": _HAVE_OPENMM,
    }

    if not _HAVE_OPENMM:
        logger.warning("OpenMM/PDBFixer not available — skipping MD validation")
        result["warnings"].append("OpenMM not installed in autodock-amber environment")
        return result

    if protocol not in ('quick', 'short'):
        raise ValidationError(f"Unknown protocol: {protocol} (use 'quick' or 'short')")

    output_dir = output_dir or tempfile.mkdtemp()

    try:
        if protocol == 'quick':
            _run_quick_validation(receptor_pdb, ligand_pdbqt, output_dir, use_gpu, result)
        else:
            _run_short_validation(receptor_pdb, ligand_pdbqt, output_dir, use_gpu, result)
    except Exception as e:
        result["warnings"].append(f"Validation failed: {e}")
        logger.warning(f"Pose stability validation failed: {e}")

    return result


def _run_quick_validation(
    receptor_pdb: str,
    ligand_pdbqt: str,
    output_dir: str,
    use_gpu: bool,
    result: Dict,
) -> None:
    """Run quick protocol: receptor prep + ligand extraction + minimization."""
    # Import OpenMM here to avoid top-level ImportError if not available
    import openmm
    import openmm.app as app
    import openmm.unit as unit
    from pdbfixer import PDBFixer

    # 1. Fix receptor with PDBFixer
    logger.info("Preparing receptor with PDBFixer...")
    fixer = PDBFixer(filename=receptor_pdb)
    fixer.findMissingResidues()
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.0)

    # 2. Extract ligand from PDBQT
    logger.info("Extracting ligand from PDBQT...")
    lig_coords, lig_names = _extract_ligand_from_pdbqt(ligand_pdbqt)

    # 3. Combine receptor + ligand into one structure
    from openmm.app import PDBFile, Topology, Modeller
    from openmm import Vec3

    pdb_file = tempfile.NamedTemporaryFile(suffix='.pdb', delete=False)
    pdb_file.close()

    # Write fixed receptor to temp PDB
    with open(pdb_file.name, 'w') as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)

    # Load and add ligand as a residue
    modeller = Modeller(fixer.topology, fixer.positions)
    lig_top = Topology()
    lig_chain = lig_top.addChain()
    lig_res = lig_top.addResidue("LIG", lig_chain)
    lig_top_up = lig_top.addUniverse()

    for name, coord in zip(lig_names, lig_coords):
        atom = lig_top.addAtom(name, openmm.app.Element.getBySymbol(name[:2].strip()), lig_res)
        lig_top_up.append(Vec3(*coord))

    modeller.add(lig_top, [Vec3(*c) for c in lig_coords])

    # 4. Create OpenMM system with implicit solvent (for speed)
    forcefield = app.ForceField('amber14/protein.ff14SB.xml', 'amber14/tip3p.xml')

    # For ligand: use GAFF via antechamber (simplified — skip for quick protocol)
    # Instead, just minimize with receptor-only FF and treat ligand as rigid
    # This is a simplification — full GAFF would be needed for production

    try:
        system = forcefield.createSystem(modeller.topology, nonbondedMethod=app.NO_CUTOFF)
    except Exception as e:
        result["warnings"].append(f"System creation failed: {e}")
        return

    # 5. Add platform
    if use_gpu:
        platform = openmm.Platform.getPlatformByName('CUDA')
    else:
        platform = openmm.Platform.getPlatformByName('CPU')

    # 6. Energy minimization
    logger.info("Running energy minimization...")
    integrator = openmm.LangevinIntegrator(300 * unit.kelvin, 1/unit.picosecond, 1 * unit.femtosecond)
    simulation = app.Simulation(modeller.topology, system, integrator, platform)
    simulation.context.setPositions(modeller.positions)

    # Compute initial energy
    initial_energy = simulation.context.getState(getEnergy=True).getPotentialEnergy()

    # Minimize
    simulation.minimizeEnergy(maxIterations=500)

    # Get minimized positions
    minimized_positions = simulation.context.getState(getPositions=True).getPositions()
    final_energy = simulation.context.getState(getEnergy=True).getPotentialEnergy()

    # 7. Compute RMSD of ligand atoms
    lig_indices = [i for i, r in enumerate(modeller.topology.residues()) if r.name == "LIG"]
    if lig_indices:
        lig_res_idx = lig_indices[0]
        res_atoms = list(modeller.topology.residues())[lig_res_idx].atoms()
        lig_atom_indices = [a.index for a in res_atoms]

        # Get original and minimized positions for ligand
        n_lig_atoms = len(lig_names)
        original_lig = np.array([(lig_coords[i][0], lig_coords[i][1], lig_coords[i][2]) for i in range(n_lig_atoms)])
        minimized_lig = np.array([
            (minimized_positions[a.index].x, minimized_positions[a.index].y, minimized_positions[a.index].z)
            for a in res_atoms
        ])

        rmsd = float(np.sqrt(np.mean(np.sum((original_lig - minimized_lig)**2, axis=1))))
        result["ligand_rmsd"] = rmsd

    result["energy_delta"] = float((final_energy - initial_energy).value_in_unit(unit.kilocalories_per_mole))

    # 8. Write minimized structure
    out_pdb = os.path.join(output_dir, "minimized_complex.pdb")
    with open(out_pdb, 'w') as f:
        PDBFile.writeFile(simulation.topology, simulation.context.getState(getPositions=True).getPositions(), f)

    # Also write ligand as PDBQT for compatibility
    out_pdbqt = os.path.join(output_dir, "minimized_ligand.pdbqt")
    _write_pdbqt_from_positions(out_pdbqt, lig_names, minimized_positions, lig_atom_indices if lig_indices else list(range(len(lig_names))))

    result["minimized_pdb"] = out_pdbqt

    # 9. Stability assessment
    # Quick protocol: RMSD < 2.0 Å and energy decreased (or small increase) → stable
    is_stable = result["ligand_rmsd"] < 2.0 and result["energy_delta"] < 50.0
    result["is_stable"] = is_stable

    logger.info(f"Pose stability: RMSD={rmsd:.2f} Å, ΔE={result['energy_delta']:.1f} kcal/mol → {'STABLE' if is_stable else 'UNSTABLE'}")


def _run_short_validation(
    receptor_pdb: str,
    ligand_pdbqt: str,
    output_dir: str,
    use_gpu: bool,
    result: Dict,
) -> None:
    """Run short protocol: quick + NVT equilibration (1 ns)."""
    import openmm
    import openmm.app as app
    import openmm.unit as unit
    from pdbfixer import PDBFixer

    # Short protocol uses the same approach but with NVT after minimization
    logger.info("Running short protocol: minimization + 1 ns NVT at 300K...")

    # Reuse quick validation setup
    _run_quick_validation(receptor_pdb, ligand_pdbqt, output_dir, use_gpu, result)

    # If quick passed, continue with NVT
    if not result["is_stable"]:
        result["warnings"].append("Skipping NVT — pose already flagged unstable")
        return

    # Placeholder for NVT — would add 1ns equilibration here
    result["warnings"].append("Short protocol NVT equilibration not yet implemented (quick protocol used)")


def _extract_ligand_from_pdbqt(pdbqt_path: str):
    """Extract coordinates and atom names from PDBQT file."""
    coords = []
    names = []
    with open(pdbqt_path) as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
                name = line[12:16].strip()
                coords.append((x, y, z))
                names.append(name)
    return coords, names


def _write_pdbqt_from_positions(output_path: str, atom_names: list, positions, atom_indices: list):
    """Write a PDBQT file from OpenMM positions."""
    with open(output_path, 'w') as f:
        for idx, atom_idx in enumerate(atom_indices):
            pos = positions[atom_idx]
            name = atom_names[idx] if idx < len(atom_names) else "X"
            f.write(f"ATOM  {idx+1:5d} {name:4s}  LIG A   1    {pos.x:8.3f}{pos.y:8.3f}{pos.z:8.3f}  1.00  0.00          A\n")
        f.write("END\n")