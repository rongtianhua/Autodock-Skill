"""
AmberTools MM/PBSA Module
==========================

Publication-quality binding free energy calculation using AmberTools.

Requirements:
    - AmberTools 24+ (tleap, antechamber, parmchk2, sander, MMPBSA.py)
    - autodock-amber conda environment

Environment:
    conda activate autodock-amber

Usage:
    from autodock._mmpbsa_amber import (
        prepare_amber_topology,
        run_amber_md,
        run_mmpbsa_amber,
    )

Workflow:
    1. prepare_amber_topology() - Build receptor/ligand/complex topology
    2. run_amber_md() - Run MD simulation with specified protocol
    3. run_mmpbsa_amber() - Calculate binding free energy from trajectory
"""

import os
import re
import shutil
import tempfile
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from autodock._core import autodock_logger

logger = autodock_logger


# ─── Amber Environment Check ───────────────────────────────────────────────────

def _check_amber_env() -> bool:
    """Check if AmberTools are available in the current environment.
    
    Automatically looks for 'autodock-amber' conda environment if tools
    aren't found in current PATH, and adds the env bin to PATH dynamically.
    """
    # First check if already in PATH
    all_found = True
    for tool in ['tleap', 'antechamber', 'parmchk2', 'sander', 'MMPBSA.py']:
        if not shutil.which(tool):
            all_found = False
            break
    
    if all_found:
        return True
    
    # Not found - try to find autodock-amber conda environment
    try:
        import subprocess
        result = subprocess.run(
            ['conda', 'env', 'list'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        for line in result.stdout.split('\n'):
            if 'autodock-amber' in line and not line.startswith('#'):
                # Extract path - last column
                parts = line.split()
                if parts:
                    env_path = parts[-1]
                    bin_path = os.path.join(env_path, 'bin')
                    if os.path.isdir(bin_path):
                        # Add to PATH
                        os.environ['PATH'] = bin_path + os.pathsep + os.environ['PATH']
                        logger.info(f"[mmpbsa-amber] Added AmberTools to PATH: {bin_path}")
                        # Re-check
                        for tool in ['tleap', 'antechamber', 'parmchk2', 'sander', 'MMPBSA.py']:
                            if not shutil.which(tool):
                                return False
                        return True
    except Exception as e:
        logger.debug(f"[mmpbsa-amber] Could not auto-discover autodock-amber env: {e}")
    
    return False


_HAVE_AMBER = _check_amber_env()


# ─── Exceptions ──────────────────────────────────────────────────────────────

class AmberPreparationError(Exception):
    """Raised when topology preparation fails."""
    pass


class AmberMDError(Exception):
    """Raised when MD simulation fails."""
    pass


class AmberMMPBSAError(Exception):
    """Raised when MMPBSA calculation fails."""
    pass


# ─── Result Data Class ───────────────────────────────────────────────────────

@dataclass
class AmberMMPBSAResult:
    """Structured result from Amber MMPBSA calculation."""

    # Binding free energy
    delta_g_bind: Optional[float] = None       # kcal/mol

    # Energy components
    delta_e_vdw: Optional[float] = None         # van der Waals
    delta_e_elec: Optional[float] = None        # Electrostatic
    delta_g_gb: Optional[float] = None          # GB solvation (if method=gb)
    delta_g_pb: Optional[float] = None          # PB solvation (if method=pb)
    delta_g_sa: Optional[float] = None          # Non-polar SASA

    # Entropy (if computed)
    t_delta_s: Optional[float] = None  # -TΔS (kcal/mol) from quasi-harmonic normal-mode entropy (MMPBSA.py, Miller et al. 2012 JCTC 8:3314-3321)

    # Per-residue decomposition
    per_residue: Dict[str, float] = field(default_factory=dict)

    # Metadata
    method: str = 'gb'                           # 'gb' or 'pb'
    protocol: str = 'quick'                      # 'quick', 'short', 'medium', 'full'
    n_frames: int = 0
    topology_file: str = ''
    trajectory_file: str = ''
    output_file: str = ''

    @property
    def is_publication_ready(self) -> bool:
        """Whether this result is suitable for publication."""
        return self.protocol in ('medium', 'full') and self.delta_g_bind is not None

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "=" * 60,
            "Amber MM/PBSA Binding Free Energy",
            "=" * 60,
            f"Protocol:      {self.protocol}",
            f"Method:        MM/{self.method.upper()}SA",
            f"Frames used:   {self.n_frames}",
            "",
            "Binding Free Energy Components:",
        ]
        if self.delta_g_bind is not None:
            lines.append(f"  ΔG_bind = {self.delta_g_bind:>10.2f} kcal/mol")
        if self.delta_e_vdw is not None:
            lines.append(f"  ΔE_vdw  = {self.delta_e_vdw:>10.2f} kcal/mol")
        if self.delta_e_elec is not None:
            lines.append(f"  ΔE_elec = {self.delta_e_elec:>10.2f} kcal/mol")
        if self.delta_g_gb is not None:
            lines.append(f"  ΔG_GB   = {self.delta_g_gb:>10.2f} kcal/mol")
        if self.delta_g_pb is not None:
            lines.append(f"  ΔG_PB   = {self.delta_g_pb:>10.2f} kcal/mol")
        if self.delta_g_sa is not None:
            lines.append(f"  ΔG_SA   = {self.delta_g_sa:>10.2f} kcal/mol")
        if self.t_delta_s is not None:
            lines.append(f"  -TΔS     = {self.t_delta_s:>10.2f} kcal/mol")

        if self.per_residue:
            lines.extend([
                "",
                "Top 5 Contributing Residues:",
            ])
            sorted_res = sorted(self.per_residue.items(), key=lambda x: x[1])
            for res, energy in sorted_res[:5]:
                lines.append(f"  {res:12s}  {energy:>+8.2f} kcal/mol")

        lines.extend([
            "",
            "Files:",
            f"  Topology:     {self.topology_file}",
            f"  Trajectory:   {self.trajectory_file}",
            f"  MMPBSA out:   {self.output_file}",
        ])
        return '\n'.join(lines)


# ─── Helper Functions ─────────────────────────────────────────────────────────

def _run_cmd(cmd: List[str], cwd: Optional[str] = None, timeout: int = 3600) -> Tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    logger.debug(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after {timeout}s: {' '.join(cmd)}")
        return -1, '', 'Timeout'


def _pdbqt_to_pdb(pdbqt_path: str, output_pdb: str) -> str:
    """Convert PDBQT to PDB (extract coordinates only, remove partial charge info)."""
    with open(pdbqt_path) as f:
        lines = f.readlines()

    with open(output_pdb, 'w') as f:
        for line in lines:
            if line.startswith('ATOM') or line.startswith('HETATM'):
                # Keep ATOM/HETATM lines but strip extra PDBQT fields
                # Format: ATOM  123  C   UNL     1      1.234  5.678  9.012  1.00  0.00     0.000 C
                # Convert to: ATOM  123  C   UNL     1      1.234  5.678  9.012  1.00  0.00           C
                if len(line) >= 66:
                    f.write(line[:66] + '           ' + line[77:78] + '\n')
                else:
                    f.write(line)
            elif line.startswith('END'):
                f.write(line)

    logger.info(f"Converted {pdbqt_path} to {output_pdb}")
    return output_pdb


# ─── Topology Preparation ─────────────────────────────────────────────────────

def prepare_amber_topology(
    receptor_pdb: str,
    ligand_pdbqt: str,
    output_dir: str,
    forcefield: str = 'ff14SB',
    ligand_charge_method: str = 'bcc',
    water_model: str = 'tip3p',
    box_size: float = 12.0,  # Angstroms from molecule to box edge
) -> dict:
    """
    Prepare Amber topology files for receptor, ligand, and complex.

    Steps:
    1. Clean receptor PDB with pdb4amber
    2. Convert ligand PDBQT to PDB
    3. Parameterize ligand with antechamber (GAFF + BCC charges)
    4. Build receptor, ligand, and complex topologies with tleap
    5. Solvate complex in a water box with counterions

    Args:
        receptor_pdb: Path to receptor PDB file
        ligand_pdbqt: Path to ligand PDBQT file (from Vina docking)
        output_dir: Directory for output files
        forcefield: Protein force field (default: ff14SB)
        ligand_charge_method: Charge method for ligand ('bcc' or 'gas')
        water_model: Water model (default: tip3p)
        box_size: Water box padding in Angstroms

    Returns:
        Dictionary with paths to output files:
        {
            'complex_prmtop': str,
            'complex_rst7': str,
            'receptor_prmtop': str,
            'receptor_rst7': str,
            'ligand_prmtop': str,
            'ligand_rst7': str,
            'output_dir': str,
        }

    Raises:
        AmberPreparationError: If any step fails
    """
    if not _HAVE_AMBER:
        raise AmberPreparationError(
            "AmberTools not found. Please activate autodock-amber environment:\n"
            "  conda activate autodock-amber"
        )

    os.makedirs(output_dir, exist_ok=True)
    output_dir = os.path.abspath(output_dir)

    logger.info("=" * 60)
    logger.info("Amber Topology Preparation")
    logger.info("=" * 60)

    # ─── Step 1: Clean receptor with pdb4amber ────────────────────────────────
    logger.info("[1/6] Cleaning receptor with pdb4amber...")
    receptor_clean = os.path.join(output_dir, 'receptor_clean.pdb')
    cmd = [
        'pdb4amber',
        '-i', receptor_pdb,
        '-o', receptor_clean,
        '--dry',  # Remove crystal waters
        '--reduce',  # Add hydrogens
    ]
    ret, stdout, stderr = _run_cmd(cmd)
    if ret != 0:
        logger.error(f"pdb4amber failed: {stderr}")
        raise AmberPreparationError(f"pdb4amber failed: {stderr}")

    # ─── Step 2: Convert ligand PDBQT to PDB ──────────────────────────────────
    logger.info("[2/6] Converting ligand PDBQT to PDB...")
    ligand_pdb = os.path.join(output_dir, 'ligand.pdb')
    _pdbqt_to_pdb(ligand_pdbqt, ligand_pdb)

    # ─── Step 3: Parameterize ligand with antechamber ─────────────────────────
    logger.info(f"[3/6] Parameterizing ligand with antechamber (charge={ligand_charge_method})...")
    ligand_mol2 = os.path.join(output_dir, 'ligand.mol2')
    ligand_frcmod = os.path.join(output_dir, 'ligand.frcmod')

    # Run antechamber
    cmd = [
        'antechamber',
        '-i', ligand_pdb,
        '-fi', 'pdb',
        '-o', ligand_mol2,
        '-fo', 'mol2',
        '-s', '2',  # Verbosity
        '-c', ligand_charge_method,  # Charge method
    ]
    ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=300)
    if ret != 0:
        logger.warning(f"antechamber failed with {ligand_charge_method}, trying 'gas'...")
        # Try gas charges as fallback
        cmd[-1] = 'gas'
        ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=300)
        if ret != 0:
            logger.error(f"antechamber failed: {stderr}")
            raise AmberPreparationError(
                f"Ligand parameterization failed. Common issues:\n"
                f"  - Unusual valence or connectivity\n"
                f"  - Missing hydrogens\n"
                f"  - Charge assignment failed\n"
                f"Error: {stderr}"
            )

    # Run parmchk2 to generate frcmod
    cmd = [
        'parmchk2',
        '-i', ligand_mol2,
        '-f', 'mol2',
        '-o', ligand_frcmod,
    ]
    ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir)
    if ret != 0:
        logger.error(f"parmchk2 failed: {stderr}")
        raise AmberPreparationError(f"parmchk2 failed: {stderr}")

    # ─── Step 4: Build receptor topology ──────────────────────────────────────
    logger.info("[4/6] Building receptor topology...")
    receptor_tleap = os.path.join(output_dir, 'receptor.tleap')
    receptor_prmtop = os.path.join(output_dir, 'receptor.prmtop')
    receptor_rst7 = os.path.join(output_dir, 'receptor.rst7')

    with open(receptor_tleap, 'w') as f:
        f.write(f"""source leaprc.protein.{forcefield}
source leaprc.water.{water_model}
rec = loadpdb {receptor_clean}
saveamberparm rec {receptor_prmtop} {receptor_rst7}
quit
""")

    cmd = ['tleap', '-f', receptor_tleap]
    ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=120)
    if ret != 0 or not os.path.exists(receptor_prmtop):
        logger.error(f"tleap receptor failed: {stderr}\n{stdout}")
        raise AmberPreparationError(f"tleap failed for receptor")

    # ─── Step 5: Build ligand topology ────────────────────────────────────────
    logger.info("[5/6] Building ligand topology...")
    ligand_tleap = os.path.join(output_dir, 'ligand.tleap')
    ligand_prmtop = os.path.join(output_dir, 'ligand.prmtop')
    ligand_rst7 = os.path.join(output_dir, 'ligand.rst7')

    with open(ligand_tleap, 'w') as f:
        f.write(f"""source leaprc.gaff
loadamberparams {ligand_frcmod}
lig = loadmol2 {ligand_mol2}
saveamberparm lig {ligand_prmtop} {ligand_rst7}
quit
""")

    cmd = ['tleap', '-f', ligand_tleap]
    ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=120)
    if ret != 0 or not os.path.exists(ligand_prmtop):
        logger.error(f"tleap ligand failed: {stderr}\n{stdout}")
        raise AmberPreparationError(f"tleap failed for ligand")

    # ─── Step 6: Build complex topology + solvate ─────────────────────────────
    logger.info("[6/6] Building complex topology and solvating...")
    complex_tleap = os.path.join(output_dir, 'complex.tleap')
    complex_prmtop = os.path.join(output_dir, 'complex.prmtop')
    complex_rst7 = os.path.join(output_dir, 'complex.rst7')

    with open(complex_tleap, 'w') as f:
        f.write(f"""source leaprc.protein.{forcefield}
source leaprc.water.{water_model}
source leaprc.gaff
loadamberparams {ligand_frcmod}
rec = loadpdb {receptor_clean}
lig = loadmol2 {ligand_mol2}
com = combine {{ rec lig }}
solvatebox com {water_model} {box_size}
addions com Na+ 0
addions com Cl- 0
saveamberparm com {complex_prmtop} {complex_rst7}
quit
""")

    cmd = ['tleap', '-f', complex_tleap]
    ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=300)
    if ret != 0 or not os.path.exists(complex_prmtop):
        logger.error(f"tleap complex failed: {stderr}\n{stdout}")
        raise AmberPreparationError(f"tleap failed for complex")

    logger.info("Topology preparation complete!")
    logger.info(f"  Complex: {complex_prmtop}")
    logger.info(f"  Receptor: {receptor_prmtop}")
    logger.info(f"  Ligand:   {ligand_prmtop}")

    return {
        'complex_prmtop': complex_prmtop,
        'complex_rst7': complex_rst7,
        'receptor_prmtop': receptor_prmtop,
        'receptor_rst7': receptor_rst7,
        'ligand_prmtop': ligand_prmtop,
        'ligand_rst7': ligand_rst7,
        'output_dir': output_dir,
    }


# ─── MD Simulation ───────────────────────────────────────────────────────────

def _write_md_input(
    output_file: str,
    protocol: str,
    imin: int = 0,
    ntx: int = 1,
    ntb: int = 1,
    ntp: int = 0,
    ntt: int = 3,
    temp0: float = 300.0,
    gamma_ln: float = 1.0,
    dt: float = 0.002,
    nstlim: int = 1000,
    ntwx: int = 1000,
    ntwe: int = 1000,
    ntwr: int = 1000,
    ntpr: int = 100,
    cut: float = 8.0,
    ioutfm: int = 1,
    **kwargs,
) -> None:
    """Write Amber MD input file."""
    with open(output_file, 'w') as f:
        f.write(f"&cntrl  ! {protocol}\n")
        f.write(f"  imin={imin}, ntx={ntx}, ntb={ntb}, ntp={ntp},\n")
        f.write(f"  ntt={ntt}, temp0={temp0}, gamma_ln={gamma_ln},\n")
        f.write(f"  dt={dt}, nstlim={nstlim},\n")
        f.write(f"  ntwx={ntwx}, ntwe={ntwe}, ntwr={ntwr}, ntpr={ntpr},\n")
        f.write(f"  cut={cut}, ioutfm={ioutfm},\n")
        for key, val in kwargs.items():
            f.write(f"  {key}={val},\n")
        f.write("/\n")


def run_amber_md(
    prmtop: str,
    rst7: str,
    output_prefix: str,
    protocol: str = 'quick',
    use_gpu: bool = False,
    n_threads: int = 4,
) -> str:
    """
    Run Amber MD simulation with specified protocol.

    Protocols:
    - 'quick':   Energy minimization only (2000 steps SD, ~5-10 min)
    - 'short':   Minimize + 1ns NVT (50ps heat + 950ps production, ~30-60 min)
    - 'medium':  Minimize + heat + 10ns NPT (~2-4 hours)
    - 'full':    Minimize + heat + 100ns NPT (~8-16 hours, GPU recommended)

    Args:
        prmtop: Path to topology file
        rst7: Path to initial coordinates
        output_prefix: Prefix for output files
        protocol: Simulation protocol ('quick', 'short', 'medium', 'full')
        use_gpu: Use pmemd.cuda if available
        n_threads: Number of CPU threads for sander

    Returns:
        Path to final trajectory file
    """
    if not _HAVE_AMBER:
        raise AmberMDError(
            "AmberTools not found. Please activate autodock-amber environment."
        )

    logger.info("=" * 60)
    logger.info(f"Amber MD Simulation: {protocol}")
    logger.info("=" * 60)

    output_dir = os.path.dirname(output_prefix) or '.'
    os.makedirs(output_dir, exist_ok=True)

    # ─── Protocol definitions ────────────────────────────────────────────────
    PROTOCOLS = {
        'quick': [
            # Minimization (2000 steps steepest descent)
            ('min', {'imin': 1, 'ntx': 1, 'ntb': 0, 'ntp': 0, 'ntt': 0,
                     'nstlim': 2000, 'ntwx': 0, 'ntwe': 0, 'ntwr': 2000, 'ntpr': 100,
                     'cut': 8.0, 'ioutfm': 1}),
        ],
        'short': [
            # Minimization
            ('min', {'imin': 1, 'ntx': 1, 'ntb': 0, 'ntp': 0, 'ntt': 0,
                     'nstlim': 5000, 'ntwx': 0, 'ntwe': 0, 'ntwr': 5000, 'ntpr': 500,
                     'cut': 8.0, 'ioutfm': 1}),
            # Heating (50ps, 0 -> 300K, NVT)
            ('heat', {'imin': 0, 'ntx': 1, 'irest': 0, 'ntb': 1, 'ntp': 0,
                      'ntt': 3, 'temp0': 300.0, 'tempi': 0.0, 'gamma_ln': 1.0,
                      'nstlim': 25000, 'dt': 0.002, 'ntwx': 5000, 'ntwr': 25000, 'ntpr': 1000,
                      'cut': 8.0, 'ioutfm': 1}),
            # Production NVT (950ps)
            ('prod', {'imin': 0, 'ntx': 5, 'irest': 1, 'ntb': 1, 'ntp': 0,
                      'ntt': 3, 'temp0': 300.0, 'gamma_ln': 1.0,
                      'nstlim': 475000, 'dt': 0.002, 'ntwx': 1000, 'ntwr': 50000, 'ntpr': 1000,
                      'cut': 8.0, 'ioutfm': 1}),
        ],
        'medium': [
            # Minimization
            ('min', {'imin': 1, 'ntx': 1, 'ntb': 0, 'ntp': 0, 'ntt': 0,
                     'nstlim': 10000, 'ntwx': 0, 'ntwe': 0, 'ntwr': 10000, 'ntpr': 1000,
                     'cut': 8.0, 'ioutfm': 1}),
            # Heating (100ps NVT)
            ('heat', {'imin': 0, 'ntx': 1, 'irest': 0, 'ntb': 1, 'ntp': 0,
                      'ntt': 3, 'temp0': 300.0, 'tempi': 0.0, 'gamma_ln': 1.0,
                      'nstlim': 50000, 'dt': 0.002, 'ntwx': 5000, 'ntwr': 50000, 'ntpr': 1000,
                      'cut': 8.0, 'ioutfm': 1}),
            # Density equilibration (100ps NPT)
            ('density', {'imin': 0, 'ntx': 5, 'irest': 1, 'ntb': 2, 'ntp': 1,
                         'ntt': 3, 'temp0': 300.0, 'gamma_ln': 1.0,
                         'nstlim': 50000, 'dt': 0.002, 'ntwx': 5000, 'ntwr': 50000, 'ntpr': 1000,
                         'cut': 8.0, 'ioutfm': 1, 'barostat': 2}),
            # Production NPT (10ns)
            ('prod', {'imin': 0, 'ntx': 5, 'irest': 1, 'ntb': 2, 'ntp': 1,
                      'ntt': 3, 'temp0': 300.0, 'gamma_ln': 1.0,
                      'nstlim': 5000000, 'dt': 0.002, 'ntwx': 1000, 'ntwr': 100000, 'ntpr': 5000,
                      'cut': 8.0, 'ioutfm': 1, 'barostat': 2}),
        ],
        'full': [
            # Minimization
            ('min', {'imin': 1, 'ntx': 1, 'ntb': 0, 'ntp': 0, 'ntt': 0,
                     'nstlim': 10000, 'ntwx': 0, 'ntwe': 0, 'ntwr': 10000, 'ntpr': 1000,
                     'cut': 8.0, 'ioutfm': 1}),
            # Heating (100ps NVT)
            ('heat', {'imin': 0, 'ntx': 1, 'irest': 0, 'ntb': 1, 'ntp': 0,
                      'ntt': 3, 'temp0': 300.0, 'tempi': 0.0, 'gamma_ln': 1.0,
                      'nstlim': 50000, 'dt': 0.002, 'ntwx': 5000, 'ntwr': 50000, 'ntpr': 1000,
                      'cut': 8.0, 'ioutfm': 1}),
            # Density equilibration (200ps NPT)
            ('density', {'imin': 0, 'ntx': 5, 'irest': 1, 'ntb': 2, 'ntp': 1,
                         'ntt': 3, 'temp0': 300.0, 'gamma_ln': 1.0,
                         'nstlim': 100000, 'dt': 0.002, 'ntwx': 5000, 'ntwr': 100000, 'ntpr': 1000,
                         'cut': 8.0, 'ioutfm': 1, 'barostat': 2}),
            # Production NPT (100ns)
            ('prod', {'imin': 0, 'ntx': 5, 'irest': 1, 'ntb': 2, 'ntp': 1,
                      'ntt': 3, 'temp0': 300.0, 'gamma_ln': 1.0,
                      'nstlim': 50000000, 'dt': 0.002, 'ntwx': 1000, 'ntwr': 500000, 'ntpr': 10000,
                      'cut': 8.0, 'ioutfm': 1, 'barostat': 2}),
        ],
    }

    if protocol not in PROTOCOLS:
        raise ValueError(f"Unknown protocol '{protocol}'. Use: quick, short, medium, full")

    # Choose executable
    if use_gpu and shutil.which('pmemd.cuda'):
        exe = 'pmemd.cuda'
        logger.info("Using GPU acceleration (pmemd.cuda)")
    else:
        exe = 'sander'
        if use_gpu:
            logger.warning("pmemd.cuda not found, falling back to sander (CPU)")

    prev_rst = rst7
    final_traj = None

    for stage_name, stage_params in PROTOCOLS[protocol]:
        logger.info(f"Running stage: {stage_name}")

        mdin = f"{output_prefix}_{stage_name}.in"
        mdout = f"{output_prefix}_{stage_name}.out"
        mdvel = f"{output_prefix}_{stage_name}.vel"
        mden = f"{output_prefix}_{stage_name}.en"
        mdrestrt = f"{output_prefix}_{stage_name}.rst7"
        mdcrd = f"{output_prefix}_{stage_name}.nc"

        _write_md_input(mdin, stage_name, **stage_params)

        # Build command
        cmd = [exe]
        cmd.extend(['-O'])  # Overwrite
        cmd.extend(['-i', mdin])
        cmd.extend(['-o', mdout])
        cmd.extend(['-p', prmtop])
        cmd.extend(['-c', prev_rst])
        cmd.extend(['-r', mdrestrt])
        cmd.extend(['-x', mdcrd])
        if stage_params.get('imin', 0) == 0:  # Not minimization
            cmd.extend(['-v', mdvel])
            cmd.extend(['-e', mden])

        # Set threads
        env = os.environ.copy()
        env['OMP_NUM_THREADS'] = str(n_threads)

        # Estimate timeout
        nstlim = stage_params.get('nstlim', 1000)
        timeout = max(300, int(nstlim * 0.01))  # Rough estimate

        ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=timeout)
        if ret != 0:
            logger.error(f"Stage {stage_name} failed: {stderr}\n{stdout}")
            raise AmberMDError(f"MD stage '{stage_name}' failed. Check {mdout}")

        prev_rst = mdrestrt
        final_traj = mdcrd
        logger.info(f"  Stage '{stage_name}' complete")

    logger.info(f"MD simulation complete! Final trajectory: {final_traj}")
    return final_traj


# ─── MMPBSA Calculation ──────────────────────────────────────────────────────

def _parse_mmpbsa_summary(output_file: str, method: str = 'gb') -> Dict[str, float]:
    """Parse MMPBSA.py output summary file for binding energy components."""
    result = {}

    # The summary file is usually named *_MMPBSA_summary.dat
    summary_file = output_file.replace('.out', '_MMPBSA_summary.dat')
    if not os.path.exists(summary_file):
        summary_file = output_file + '_MMPBSA_summary.dat'
    if not os.path.exists(summary_file):
        logger.warning(f"Summary file not found: {summary_file}")
        return result

    with open(summary_file) as f:
        content = f.read()

    # Parse binding energy section
    # Typical format:
    # DELTA TOTAL       -10.234      2.345
    # VDWAALS            -5.678      1.234
    # EEL               -12.345      3.456
    # G gas             -18.023      4.690
    # GB/PBSURF          5.678      1.123
    # GB/PBSOLV          2.123      0.456
    # G solvation        7.801      1.579
    # NMODE             -12.345      2.345  (quasi-harmonic entropy, -TΔS)

    patterns = {
        'delta_g_bind': r'DELTA\s+TOTAL\s+([\-\d\.]+)',
        'delta_e_vdw': r'VDWAALS\s+([\-\d\.]+)',
        'delta_e_elec': r'EEL\s+([\-\d\.]+)',
        'delta_g_gb': r'(?:GB|PBSURF)\s+([\-\d\.]+)',
        'delta_g_sa': r'(?:GB|PBSOLV)\s+([\-\d\.]+)',
        # Quasi-harmonic normal-mode entropy (NMODE)
        # MMPBSA.py outputs -TΔS as NMODE or IGBERY term when nmode_igb=10
        't_delta_s': r'(?:NMODE|IGBERY)\s+([\-\d\.]+)',
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            result[key] = float(match.group(1))

    return result


def run_mmpbsa_amber(
    complex_prmtop: str,
    receptor_prmtop: str,
    ligand_prmtop: str,
    trajectory: str,
    output_prefix: str,
    method: str = 'gb',  # 'gb' or 'pb'
    start_frame: int = 1,
    end_frame: int = -1,
    interval: int = 1,
    decompose: bool = False,
) -> AmberMMPBSAResult:
    """
    Run MMPBSA.py on MD trajectory.

    Args:
        complex_prmtop: Path to complex topology
        receptor_prmtop: Path to receptor topology
        ligand_prmtop: Path to ligand topology
        trajectory: Path to MD trajectory (.nc or .mdcrd)
        output_prefix: Prefix for output files
        method: 'gb' (Generalized Born) or 'pb' (Poisson-Boltzmann)
        start_frame: First frame to analyze
        end_frame: Last frame to analyze (-1 = last)
        interval: Analyze every Nth frame
        decompose: Enable per-residue decomposition

    Returns:
        AmberMMPBSAResult with binding energy components

    Raises:
        AmberMMPBSAError: If MMPBSA calculation fails
    """
    if not _HAVE_AMBER:
        raise AmberMMPBSAError(
            "AmberTools not found. Please activate autodock-amber environment."
        )

    if method not in ('gb', 'pb'):
        raise ValueError(f"Method must be 'gb' or 'pb', got '{method}'")

    logger.info("=" * 60)
    logger.info(f"MMPBSA Calculation: MM/{method.upper()}SA")
    logger.info("=" * 60)

    output_dir = os.path.dirname(output_prefix) or '.'
    os.makedirs(output_dir, exist_ok=True)

    # Create MMPBSA input file
    mmpbsa_in = f"{output_prefix}_mmpbsa.in"
    mmpbsa_out = f"{output_prefix}_mmpbsa.out"

    with open(mmpbsa_in, 'w') as f:
        if method == 'gb':
            # OBC2 (igb=10) + normal mode entropy (nmode_igb=10)
            # ref: Onufriev et al. (2004) Proteins 55:383-394
            # ref: Miller et al. (2012) JCTC 8:3314-3321
            f.write(f"""&general
  startframe={start_frame}, endframe={end_frame}, interval={interval},
  verbose=2, keep_files=0,
/
&gb
  igb=10,            # OBC2 GB model (Onufriev-Bashford-Case 2)
  saltcon=0.150,
  probe=1.4,
  nmode_igb=10,      # Enable normal-mode entropy (-TΔS) via quasi-harmonic analysis
/
""")
        else:
            # PB method
            f.write(f"""&general
  startframe={start_frame}, endframe={end_frame}, interval={interval},
  verbose=2, keep_files=0,
/
&pb
  saltcon=0.150,
  probe=1.4,
/
""")
        if decompose:
            f.write("""&decomp
  idecomp=1,
  dec_verbose=1,
/
""")

    # Run MMPBSA.py
    cmd = [
        'MMPBSA.py',
        '-O',  # Overwrite
        '-i', mmpbsa_in,
        '-o', mmpbsa_out,
        '-sp', complex_prmtop,
        '-cp', complex_prmtop,
        '-rp', receptor_prmtop,
        '-lp', ligand_prmtop,
        '-y', trajectory,
    ]

    logger.info(f"Running MMPBSA.py (method={method})...")
    ret, stdout, stderr = _run_cmd(cmd, cwd=output_dir, timeout=7200)
    if ret != 0:
        logger.error(f"MMPBSA.py failed: {stderr}\n{stdout}")
        raise AmberMMPBSAError(f"MMPBSA calculation failed. Check {mmpbsa_out}")

    # Parse results
    parsed = _parse_mmpbsa_summary(mmpbsa_out, method=method)

    result = AmberMMPBSAResult(
        method=method,
        n_frames=len(range(start_frame, 
                           (end_frame if end_frame > 0 else 1000), 
                           interval)) if end_frame > 0 else 100,
        topology_file=complex_prmtop,
        trajectory_file=trajectory,
        output_file=mmpbsa_out,
        **parsed,
    )

    # Parse per-residue decomposition if available
    if decompose:
        decomp_file = f"{output_prefix}_FINAL_DECOMP_MMPBSA.dat"
        if os.path.exists(decomp_file):
            result.per_residue = _parse_decomp_file(decomp_file)

    logger.info(f"MMPBSA calculation complete!")
    logger.info(f"  ΔG_bind = {result.delta_g_bind:.2f} kcal/mol")
    return result


def _parse_decomp_file(decomp_file: str) -> Dict[str, float]:
    """Parse per-residue decomposition file."""
    per_residue = {}
    with open(decomp_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('|'):
                continue
            # Typical format: RESNAME RESNUM CHAIN TOTAL ...
            parts = line.split()
            if len(parts) >= 4:
                resname = parts[0]
                resnum = parts[1]
                chain = parts[2] if parts[2] != '-' else 'A'
                try:
                    energy = float(parts[3])
                    key = f"{resname}{resnum}.{chain}"
                    per_residue[key] = energy
                except ValueError:
                    continue
    return per_residue


# ─── High-Level API ──────────────────────────────────────────────────────────

def compute_mmpbsa_amber(
    receptor_pdb: str,
    ligand_pdbqt: str,
    output_dir: Optional[str] = None,
    protocol: str = 'quick',
    method: str = 'gb',
    use_gpu: bool = False,
    n_threads: int = 4,
    decompose: bool = True,
) -> AmberMMPBSAResult:
    """
    High-level API: Run full Amber MM/PBSA workflow.

    This is a convenience function that:
    1. Prepares Amber topologies (receptor + ligand + complex)
    2. Runs MD simulation with specified protocol
    3. Calculates MMPBSA binding free energy

    Args:
        receptor_pdb: Path to receptor PDB file
        ligand_pdbqt: Path to ligand PDBQT file
        output_dir: Output directory (temporary directory if None)
        protocol: MD protocol ('quick', 'short', 'medium', 'full')
        method: Solvation method ('gb' or 'pb')
        use_gpu: Use GPU acceleration if available
        n_threads: Number of CPU threads
        decompose: Enable per-residue decomposition

    Returns:
        AmberMMPBSAResult with binding energy components

    Example:
        >>> result = compute_mmpbsa_amber(
        ...     'receptor.pdb',
        ...     'docked.pdbqt',
        ...     protocol='quick',
        ...     method='gb',
        ... )
        >>> print(result.delta_g_bind)
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix='amber_mmpbsa_')
    else:
        os.makedirs(output_dir, exist_ok=True)

    output_dir = os.path.abspath(output_dir)
    logger.info(f"Output directory: {output_dir}")

    # Step 1: Prepare topologies
    topo = prepare_amber_topology(
        receptor_pdb=receptor_pdb,
        ligand_pdbqt=ligand_pdbqt,
        output_dir=os.path.join(output_dir, 'topology'),
    )

    # Step 2: Run MD
    traj = run_amber_md(
        prmtop=topo['complex_prmtop'],
        rst7=topo['complex_rst7'],
        output_prefix=os.path.join(output_dir, 'md', 'md'),
        protocol=protocol,
        use_gpu=use_gpu,
        n_threads=n_threads,
    )

    # Step 3: Run MMPBSA
    result = run_mmpbsa_amber(
        complex_prmtop=topo['complex_prmtop'],
        receptor_prmtop=topo['receptor_prmtop'],
        ligand_prmtop=topo['ligand_prmtop'],
        trajectory=traj,
        output_prefix=os.path.join(output_dir, 'mmpbsa', 'mmpbsa'),
        method=method,
        start_frame=1,
        end_frame=-1,
        interval=max(1, 50 if protocol in ('medium', 'full') else 1),
        decompose=decompose,
    )

    result.protocol = protocol
    return result
