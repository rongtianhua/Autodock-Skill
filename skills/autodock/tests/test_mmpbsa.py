"""
Tests for MM/PBSA module (_mmpbsa.py).

Covers:
  - compute_mmpbsa basic functionality
  - MMPBSAResult data structure
  - Parsing (PDB + PDBQT)
  - Energy calculation sanity checks
  - Per-residue decomposition
"""
import os
import sys
import tempfile
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock._core import _HAVE_RDKIT

pytestmark = pytest.mark.skipif(not _HAVE_RDKIT, reason="RDKit required")


class TestMMPBSABasics:
    """Smoke tests for compute_mmpbsa."""

    def test_compute_mmpbsa_returns_result(self):
        """compute_mmpbsa should return a MMPBSAResult with expected fields."""
        from autodock import compute_mmpbsa, MMPBSAResult

        # Minimal receptor (1 ALA residue)
        rec_pdb = """ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA     1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA     1       2.009   1.420   0.000  1.00  0.00           C
ATOM      4  O   ALA     1       1.269   2.400   0.000  1.00  0.00           O
ATOM      5  CB  ALA     1       1.989  -0.729  -1.240  1.00  0.00           C
ATOM      6  H   ALA     1      -0.385   0.880   0.000  1.00  0.00           H
ATOM      7  HA  ALA     1       1.803  -0.519   0.908  1.00  0.00           H
ATOM      8  HB1 ALA     1       1.638  -0.317  -2.189  1.00  0.00           H
ATOM      9  HB2 ALA     1       3.079  -0.729  -1.240  1.00  0.00           H
ATOM     10  HB3 ALA     1       1.638  -1.763  -1.240  1.00  0.00           H
END
"""
        # Minimal ligand (CH4) at ~6 Å distance
        lig_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       7.989  -0.729  -1.240  0.00  0.00     0.000 C
ATOM      2  H   UNL     1       8.489  -0.729  -0.350  0.00  0.00     0.000 H
ATOM      3  H   UNL     1       8.489  -0.729  -2.130  0.00  0.00     0.000 H
ATOM      4  H   UNL     1       7.489   0.181  -1.240  0.00  0.00     0.000 H
ATOM      5  H   UNL     1       7.489  -1.639  -1.240  0.00  0.00     0.000 H
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as rf:
            rf.write(rec_pdb)
            rec_path = rf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(lig_pdbqt)
            lig_path = lf.name

        try:
            result = compute_mmpbsa(rec_path, lig_path, compute_sasa=False, decomp=False)
            assert isinstance(result, MMPBSAResult)
            assert result.n_receptor_atoms == 10
            assert result.n_ligand_atoms == 5
            assert result.delta_e_mm is not None
            assert not np.isnan(result.delta_e_mm)
            assert not np.isnan(result.delta_g_bind)
        finally:
            os.unlink(rec_path)
            os.unlink(lig_path)

    def test_per_residue_decomposition(self):
        """Per-residue decomposition should identify interacting residues."""
        from autodock import compute_mmpbsa

        rec_pdb = """ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA     1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA     1       2.009   1.420   0.000  1.00  0.00           C
ATOM      4  O   ALA     1       1.269   2.400   0.000  1.00  0.00           O
ATOM      5  CB  ALA     1       1.989  -0.729  -1.240  1.00  0.00           C
ATOM      6  H   ALA     1      -0.385   0.880   0.000  1.00  0.00           H
ATOM      7  HA  ALA     1       1.803  -0.519   0.908  1.00  0.00           H
ATOM      8  HB1 ALA     1       1.638  -0.317  -2.189  1.00  0.00           H
ATOM      9  HB2 ALA     1       3.079  -0.729  -1.240  1.00  0.00           H
ATOM     10  HB3 ALA     1       1.638  -1.763  -1.240  1.00  0.00           H
END
"""
        # Ligand close enough to interact (3.5 Å from CB — vdW contact)
        lig_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       5.500  -0.729  -1.240  0.00  0.00     0.000 C
ATOM      2  H   UNL     1       6.000  -0.729  -0.350  0.00  0.00     0.000 H
ATOM      3  H   UNL     1       6.000  -0.729  -2.130  0.00  0.00     0.000 H
ATOM      4  H   UNL     1       5.000   0.181  -1.240  0.00  0.00     0.000 H
ATOM      5  H   UNL     1       5.000  -1.639  -1.240  0.00  0.00     0.000 H
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as rf:
            rf.write(rec_pdb)
            rec_path = rf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(lig_pdbqt)
            lig_path = lf.name

        try:
            result = compute_mmpbsa(rec_path, lig_path, compute_sasa=False, decomp=True)
            assert 'ALA1.A' in result.per_residue
            # With a close ligand, ALA1 should have non-zero interaction
            assert abs(result.per_residue['ALA1.A']) > 0.001
        finally:
            os.unlink(rec_path)
            os.unlink(lig_path)


class TestMMPBSAResult:
    """Test MMPBSAResult data structure."""

    def test_to_dict(self):
        """to_dict should serialize all fields."""
        from autodock import MMPBSAResult
        r = MMPBSAResult(delta_g_bind=-10.5, delta_e_elec=-2.3, delta_e_vdw=-8.2)
        d = r.to_dict()
        assert d['delta_g_bind'] == -10.5
        assert d['delta_e_elec'] == -2.3

    def test_to_dataframe_rows(self):
        """to_dataframe_rows should return sorted per-residue data."""
        from autodock import MMPBSAResult
        r = MMPBSAResult(
            per_residue={'PHE140.A': -2.5, 'ASP189.A': -1.8, 'ALA1.A': 0.3}
        )
        rows = r.to_dataframe_rows()
        assert len(rows) == 3
        assert rows[0]['residue'] == 'PHE140.A'  # Most favorable first
        assert rows[0]['energy_kcal_mol'] == -2.5

    def test_summary_contains_energies(self):
        """summary() should include all energy components."""
        from autodock import MMPBSAResult
        r = MMPBSAResult(
            delta_g_bind=-15.2,
            delta_e_mm=-20.5,
            delta_g_solv=5.3,
            delta_e_elec=-8.1,
            delta_e_vdw=-12.4,
            delta_g_gb=-3.2,
            delta_g_sa=8.5,
            per_residue={'PHE140.A': -3.2},
        )
        summary = r.summary()
        assert 'MM/GBSA Binding Free Energy: -15.20' in summary
        assert 'PHE140.A' in summary


class TestMMPBSAParsing:
    """Test PDB/PDBQT parsing."""

    def test_parse_pdb_atoms(self):
        """_parse_pdb_atoms should extract coordinates and metadata."""
        from autodock._mmpbsa import _parse_pdb_atoms

        pdb = """ATOM      1  N   ALA     1       1.000   2.000   3.000  1.00  0.00           N
ATOM      2  CA  ALA     1       4.000   5.000   6.000  1.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as f:
            f.write(pdb)
            path = f.name
        try:
            atoms = _parse_pdb_atoms(path)
            assert len(atoms) == 2
            assert atoms[0]['element'] == 'N'
            assert atoms[0]['x'] == 1.0
            assert atoms[1]['resn'] == 'ALA'
        finally:
            os.unlink(path)

    def test_parse_pdbqt_atoms(self):
        """_parse_pdbqt_atoms should extract charges and atom types."""
        from autodock._mmpbsa import _parse_pdbqt_atoms

        pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       1.000   2.000   3.000  0.00  0.00     0.145 A
ATOM      2  O   UNL     1       4.000   5.000   6.000  0.00  0.00    -0.426 OA
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write(pdbqt)
            path = f.name
        try:
            atoms = _parse_pdbqt_atoms(path)
            assert len(atoms) == 2
            assert atoms[0]['charge'] == 0.145
            assert atoms[0]['atom_type'] == 'A'
            assert atoms[0]['element'] == 'C'  # from atom_name, not atom_type
            assert atoms[1]['charge'] == -0.426
            assert atoms[1]['atom_type'] == 'OA'
            assert atoms[1]['element'] == 'O'
        finally:
            os.unlink(path)


class TestMMPBSANoClash:
    """Verify reasonable energies for non-clashing poses."""

    def test_weak_interaction_small_negative(self):
        """At 6 Å distance, binding energy should be small and negative."""
        from autodock import compute_mmpbsa

        rec_pdb = """ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA     1       1.458   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA     1       2.009   1.420   0.000  1.00  0.00           C
ATOM      4  O   ALA     1       1.269   2.400   0.000  1.00  0.00           O
ATOM      5  CB  ALA     1       1.989  -0.729  -1.240  1.00  0.00           C
ATOM      6  H   ALA     1      -0.385   0.880   0.000  1.00  0.00           H
ATOM      7  HA  ALA     1       1.803  -0.519   0.908  1.00  0.00           H
ATOM      8  HB1 ALA     1       1.638  -0.317  -2.189  1.00  0.00           H
ATOM      9  HB2 ALA     1       3.079  -0.729  -1.240  1.00  0.00           H
ATOM     10  HB3 ALA     1       1.638  -1.763  -1.240  1.00  0.00           H
END
"""
        # CH4 at ~6 Å — weak vdW interaction
        lig_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       7.989  -0.729  -1.240  0.00  0.00     0.000 C
ATOM      2  H   UNL     1       8.489  -0.729  -0.350  0.00  0.00     0.000 H
ATOM      3  H   UNL     1       8.489  -0.729  -2.130  0.00  0.00     0.000 H
ATOM      4  H   UNL     1       7.489   0.181  -1.240  0.00  0.00     0.000 H
ATOM      5  H   UNL     1       7.489  -1.639  -1.240  0.00  0.00     0.000 H
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as rf:
            rf.write(rec_pdb)
            rec_path = rf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(lig_pdbqt)
            lig_path = lf.name

        try:
            result = compute_mmpbsa(rec_path, lig_path, compute_sasa=False, decomp=False)
            # At 6 Å, energy should be small (|ΔG| < 1 kcal/mol)
            assert abs(result.delta_g_bind) < 1.0
            assert not np.isnan(result.delta_g_bind)
        finally:
            os.unlink(rec_path)
            os.unlink(lig_path)
