# AmberTools MM/PBSA Workflow Reference

## Overview

This document describes the complete AmberTools-based MM/PBSA workflow for
publication-quality binding free energy calculations integrated into the
autodock skill.

**Accuracy**: ±0.5–1.5 kcal/mol with proper MD sampling
**Runtime**: 5 minutes (quick) → 16+ hours (full production)

---

## Environment Setup

### Create autodock-amber Environment

```bash
conda create -n autodock-amber -c conda-forge ambertools openmm pdbfixer -y
conda activate autodock-amber
```

### Verify Installation

```bash
# Check AmberTools are available
which tleap antechamber parmchk2 sander MMPBSA.py

# Verify Python bindings
python -c "import parmed; print('ParmEd OK')"
```

---

## Complete End-to-End Workflow

### Step 1: Prepare Input Files

**Receptor PDB**: Clean, hydrogenated, no ligands or cofactors
```bash
# Use pdb4amber for initial cleaning (auto-run by prepare_amber_topology)
pdb4amber -i receptor.pdb -o receptor_clean.pdb --dry --reduce
```

**Ligand PDBQT**: Docked pose from Vina with partial charges
```python
# From autodock skill - already has Gasteiger charges
from autodock import prepare_ligand
prepare_ligand("aspirin.smi", "ligand.pdbqt")
```

---

### Step 2: Build Topology Files

```python
from autodock import prepare_amber_topology

topology = prepare_amber_topology(
    receptor_pdb="receptor.pdb",
    ligand_pdbqt="ligand.pdbqt",
    output_dir="amber_topology",
    forcefield="ff14SB",           # Protein force field
    ligand_charge_method="bcc",    # AM1-BCC charges (fast, recommended)
    water_model="tip3p",           # Water model
    box_size=12.0,                 # Å from molecule to box edge
)

print("Complex topology:", topology['complex_prmtop'])
print("Receptor topology:", topology['receptor_prmtop'])
print("Ligand topology:", topology['ligand_prmtop'])
```

**What this does internally**:
1. `pdb4amber` - Clean receptor PDB, add hydrogens, remove crystal waters
2. `antechamber` - Parameterize ligand with GAFF, assign AM1-BCC charges
3. `parmchk2` - Generate missing ligand force field parameters
4. `tleap` - Build receptor, ligand, and solvated complex topologies

**Output files in amber_topology/**:
- `complex.prmtop`, `complex.rst7` - Solvated complex (protein + ligand + water + ions)
- `receptor.prmtop`, `receptor.rst7` - Dry receptor
- `ligand.prmtop`, `ligand.rst7` - Ligand in vacuum
- `ligand.mol2`, `ligand.frcmod` - Ligand GAFF parameters

---

### Step 3: Run MD Simulation

```python
from autodock import run_amber_md

trajectory = run_amber_md(
    prmtop=topology['complex_prmtop'],
    rst7=topology['complex_rst7'],
    output_prefix="amber_md/md",
    protocol="short",              # 'quick' | 'short' | 'medium' | 'full'
    use_gpu=False,                 # Set to True if GPU available
    n_threads=4,                   # CPU threads
)

print("Final trajectory:", trajectory)
```

#### Protocol Reference

| Protocol | MD Stages | Runtime | Accuracy | Use Case |
|----------|-----------|---------|----------|----------|
| `quick` | Minimization only (2000 steps) | 5-10 min | Low | Fast screening, topology validation |
| `short` | Min → Heat (50ps) → 1ns NVT | 30-60 min | Medium | Method validation, pose ranking |
| `medium` | Min → Heat → Density → 10ns NPT | 2-4 hrs | Good | Publication preliminary results |
| `full` | Min → Heat → Density → 100ns NPT | 8-16 hrs | Excellent | Final publication figures |

**MD Details**:
- Thermostat: Langevin (300K)
- Barostat: Monte Carlo (1 atm, constant pressure)
- Timestep: 2 fs
- Cutoff: 8 Å
- Trajectory saved every 1 ps

---

### Step 4: Run MMPBSA Calculation

```python
from autodock import run_mmpbsa_amber

result = run_mmpbsa_amber(
    complex_prmtop=topology['complex_prmtop'],
    receptor_prmtop=topology['receptor_prmtop'],
    ligand_prmtop=topology['ligand_prmtop'],
    trajectory=trajectory,
    output_prefix="amber_mmpbsa/mmpbsa",
    method="gb",                    # 'gb' (faster) | 'pb' (more accurate)
    start_frame=1,
    end_frame=-1,                   # -1 = last frame
    interval=1,                     # Analyze every Nth frame
    decompose=True,                 # Per-residue decomposition
)

print(result.summary())
print(f"ΔG_bind = {result.delta_g_bind:.2f} kcal/mol")
```

#### GB vs PB Methods

| Method | Speed | Accuracy | Description |
|--------|-------|----------|-------------|
| `gb` | Fast | Good | Generalized Born (Onufriev OBC2) |
| `pb` | Slow | Excellent | Poisson-Boltzmann (APBS solver) |

**Energy Components**:
- ΔG_bind = ΔE_MM + ΔG_solvation - TΔS
- ΔE_MM = ΔE_vdw (van der Waals) + ΔE_elec (Coulomb)
- ΔG_solvation = ΔG_polar (GB/PB) + ΔG_nonpolar (SASA)

---

### Step 5: High-Level API (One-Call)

```python
from autodock import compute_mmpbsa

# Publication-grade Amber calculation
result = compute_mmpbsa(
    receptor_pdb="receptor.pdb",
    ligand_pdbqt="ligand.pdbqt",
    method="amber",                 # Critical - enables Amber mode!
    amber_protocol="short",         # 'quick' | 'short' | 'medium' | 'full'
    amber_method="gb",              # 'gb' | 'pb'
    use_gpu=False,
    decomp=True,
)

print(result.summary())
print(f"Is publication grade? {result.is_publication_grade}")
```

---

## Results Interpretation

### Typical Energy Range

| Component | Typical Value | Notes |
|-----------|---------------|-------|
| ΔE_vdw | -15 to -60 kcal/mol | Favorable vdW contacts |
| ΔE_elec | -10 to -100 kcal/mol | Hydrogen bonds, salt bridges |
| ΔG_GB/PB | +20 to +80 kcal/mol | Unfavorable desolvation penalty |
| ΔG_SA | +2 to +8 kcal/mol | Nonpolar burial penalty |
| ΔG_bind | -5 to -20 kcal/mol | **Net binding free energy** |

### Binding Affinity Conversion

```
ΔG_bind (kcal/mol) → Kd (μM) at 298K:
-5 kcal/mol → ~200 μM (weak)
-8 kcal/mol → ~1.5 μM (fragment hit)
-10 kcal/mol → ~50 nM (good lead)
-12 kcal/mol → ~1.5 nM (drug-like)
-15 kcal/mol → ~8 pM (tight binder)
```

### Per-Residue Decomposition

```python
# Print hot-spot residues
for res, energy in sorted(result.per_residue.items(), key=lambda x: x[1])[:10]:
    if energy < -1.0:  # Significant contribution
        print(f"{res:12s} {energy:+.2f} kcal/mol")
```

**Hot-spot thresholds**:
- < -2.0 kcal/mol: Critical hot spot
- -1.0 to -2.0: Significant contribution
- > +0.5: Unfavorable interaction

---

## Troubleshooting

### Topology Preparation Failures

**"antechamber: cannot assign charge"**
- Try `ligand_charge_method="gas"` (Gasteiger fallback)
- Check for unusual valences or uncommon elements
- Use parameterized ligand from RCSB Ligand Expo if available

**"tleap: fatal error"**
- Check PDB file for missing atoms, alternate conformations, or invalid residues
- Use `pdbfixer` to repair PDB first

### MD Simulation Crashes

**"LINCS warning" / "SHAKE error"**
- Initial structure has clashes → increase minimization steps
- Try `protocol="medium"` which includes more extensive minimization

**NaN energies after heating**
- Bad initial geometry → check PDB carefully
- Try slower heating ramp

### MMPBSA Failures

**"MMPBSA.py: trajectory mismatch"**
- Receptor/ligand topologies must be from the same tleap session as complex
- Don't modify topology files after creation

**"All NaN results"**
- Check MD simulation completed successfully
- Look at the .out file for errors

---

## Performance Tips

### GPU Acceleration

```python
# Requires AmberTools compiled with CUDA
# and pmemd.cuda in PATH
result = compute_mmpbsa(
    ...,
    use_gpu=True,  # 5-10x speedup!
)
```

### Frame Sampling

For long trajectories, use `interval` to reduce calculation time:
```python
# Analyze every 10th frame (10x faster)
result = run_mmpbsa_amber(..., interval=10)
```

### Parallelization

```python
# Use more CPU threads for sander
result = compute_mmpbsa(..., n_threads=8)
```

---

## Publication Checklist

Before using these results in a publication:

1. **Use at least `protocol="medium"` (10ns)**
   - `quick` and `short` are for screening only

2. **Run 3+ independent replicas**
   - Report mean ± standard error
   - Check convergence across replicates

3. **Use PB method for final results**
   - GB is acceptable for screening
   - PB is more physically accurate

4. **Compute entropy (quasi-harmonic)**
   - TΔS contribution is essential for absolute values

5. **Report all components**
   - ΔE_vdw, ΔE_elec, ΔG_polar, ΔG_nonpolar, TΔS
   - Don't just report ΔG_bind!

---

## Command-Line Reference

### Direct AmberTools Commands (if needed)

```bash
# Prepare ligand parameters
antechamber -i ligand.pdb -o ligand.mol2 -fi pdb -fo mol2 -c bcc -s 2
parmchk2 -i ligand.mol2 -f mol2 -o ligand.frcmod

# Build topology with tleap (interactive)
tleap -f leaprc.protein.ff14SB

# Run minimization
sander -O -i min.in -o min.out -p complex.prmtop -c complex.rst7 -r min.rst7

# Run MMPBSA
MMPBSA.py -O -i mmpbsa.in -o FINAL_RESULTS.dat -sp complex.prmtop \
    -cp complex.prmtop -rp receptor.prmtop -lp ligand.prmtop -y md.nc
```

---

## References

1. **AmberTools**: https://ambermd.org/AmberTools.php
2. **MMPBSA.py**: Miller et al. (2012) JCTC 8:3314-3321
3. **Generalized Born**: Onufriev et al. (2004) Proteins 55:383-394
4. **AM1-BCC charges**: Jakalian et al. (2000) JCC 21:132-146
5. **GAFF force field**: Wang et al. (2004) JCC 25:1157-1174
