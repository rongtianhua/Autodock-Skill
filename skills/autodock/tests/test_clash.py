"""
Tests for compute_clash_score — explicit-H system clash detection.

Validates that clash scoring correctly handles:
  - No-clash scenarios (score = 0.0)
  - Explicit-H system overlaps (H-H contacts)
  - Threshold boundary (1.2 Å for explicit-H, 0.5 Å for heavy-atom-only)
  - Error handling (invalid PDB input)
"""
import os
import sys
import tempfile
import pytest
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock._validation import compute_clash_score
from autodock._preparation import _read_ligand_from_pdbqt_3d


class TestClashScoreBasics:
    """Basic functionality: no-clash, explicit-H overlap, threshold boundaries."""

    def test_no_clash_returns_zero(self):
        """When ligand is far from protein, clash score should be 0.0."""
        # Create a minimal protein (2 atoms, far apart)
        protein_pdb = """ATOM      1  C   ALA     1       0.000   0.000   0.000  0.00  0.00           C
ATOM      2  N   ALA     1       1.500   0.000   0.000  0.00  0.00           N
ATOM      3  O   ALA     1       0.000   1.500   0.000  0.00  0.00           O
ATOM      4  H   ALA     1       0.000   0.000   1.000  0.00  0.00           H
END
"""
        # Ligand far away (50 Å from protein)
        ligand_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1      50.000  50.000  50.000  0.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(ligand_pdbqt)
            ligand_path = lf.name

        try:
            result = compute_clash_score(ligand_path, protein_path)
            assert result['clash_score'] == 0.0, f"Expected 0.0, got {result['clash_score']}"
            assert result['n_clashing_pairs'] == 0
            assert result['is_acceptable'] is True
            assert result['mean_overlap'] == 0.0
        finally:
            os.unlink(protein_path)
            os.unlink(ligand_path)

    def test_explicit_h_system_threshold(self):
        """Explicit-H system: threshold 1.2 Å should be acceptable for moderate H-H contacts."""
        # Protein with a single H atom
        # VDW(H) = 1.20, so two H atoms at 1.6 Å distance → overlap = 2.40 - 1.6 = 0.8 Å
        # This is < 1.2 Å threshold (acceptable) but > 0.5 Å (would fail heavy-atom-only)
        protein_pdb = """ATOM      1  H   ALA     1       0.000   0.000   0.000  0.00  0.00           H
END
"""
        # Ligand H at 1.6 Å from protein H → overlap = 0.8 Å
        ligand_pdbqt = """REMARK SMILES [H]
ATOM      1  H   UNL     1       1.600   0.000   0.000  0.00  0.00           H
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(ligand_pdbqt)
            ligand_path = lf.name

        try:
            # Test explicit-H threshold (1.2 Å)
            result = compute_clash_score(ligand_path, protein_path, clash_threshold=1.2)
            assert result['clash_score'] is not None
            # With two H atoms at 1.6 Å: VDW sum = 1.20 + 1.20 = 2.40, overlap = 0.80
            expected_overlap = 0.80
            assert abs(result['clash_score'] - expected_overlap) < 0.01, \
                f"Expected ~{expected_overlap} Å overlap, got {result['clash_score']}"
            assert result['is_acceptable'] is True, \
                f"clash_score={result['clash_score']} should be acceptable with threshold=1.2"
            assert result['n_clashing_pairs'] == 1

            # Test heavy-atom-only threshold (0.5 Å) — should fail
            result_strict = compute_clash_score(ligand_path, protein_path, clash_threshold=0.5)
            assert result_strict['is_acceptable'] is False, \
                f"clash_score={result_strict['clash_score']} should NOT be acceptable with threshold=0.5"
        finally:
            os.unlink(protein_path)
            os.unlink(ligand_path)

    def test_threshold_boundary_exact(self):
        """Test exact boundary: clash_score == threshold → acceptable (=<=)."""
        # Create a scenario where we can control the exact overlap
        # C-C: VDW sum = 3.40, distance = 2.20 → overlap = 1.20
        protein_pdb = """ATOM      1  C   ALA     1       0.000   0.000   0.000  0.00  0.00           C
END
"""
        ligand_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       2.200   0.000   0.000  0.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(ligand_pdbqt)
            ligand_path = lf.name

        try:
            result = compute_clash_score(ligand_path, protein_path, clash_threshold=1.2)
            # VDW(C) = 1.70, sum = 3.40, distance = 2.20, overlap = 1.20
            expected = 1.20
            assert abs(result['clash_score'] - expected) < 0.01, \
                f"Expected {expected} Å overlap, got {result['clash_score']}"
            assert result['is_acceptable'] is True, \
                "clash_score == threshold should be acceptable (<=)"
        finally:
            os.unlink(protein_path)
            os.unlink(ligand_path)

    def test_clash_above_threshold_unacceptable(self):
        """clash_score > threshold → is_acceptable = False."""
        # Strong clash: C-C at 1.5 Å → overlap = 3.40 - 1.5 = 1.9 Å
        protein_pdb = """ATOM      1  C   ALA     1       0.000   0.000   0.000  0.00  0.00           C
END
"""
        ligand_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       1.500   0.000   0.000  0.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(ligand_pdbqt)
            ligand_path = lf.name

        try:
            result = compute_clash_score(ligand_path, protein_path, clash_threshold=1.2)
            expected = 1.90  # 3.40 - 1.50
            assert abs(result['clash_score'] - expected) < 0.01
            assert result['is_acceptable'] is False, \
                f"clash_score={result['clash_score']} > 1.2 should be unacceptable"
        finally:
            os.unlink(protein_path)
            os.unlink(ligand_path)


class TestClashScoreErrorHandling:
    """Error handling: invalid inputs, missing files, parse failures."""

    def test_invalid_receptor_pdb(self):
        """Invalid receptor PDB should return error dict, not raise."""
        ligand_pdbqt = """REMARK SMILES C
ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(ligand_pdbqt)
            ligand_path = lf.name
        try:
            result = compute_clash_score(ligand_path, '/nonexistent/receptor.pdb')
            assert result['clash_score'] is None
            assert 'error' in result
            assert 'receptor' in result['error'].lower() or 'parse' in result['error'].lower()
        finally:
            os.unlink(ligand_path)

    def test_invalid_ligand_pdbqt(self):
        """Invalid ligand PDBQT should return error dict."""
        protein_pdb = """ATOM      1  C   ALA     1       0.000   0.000   0.000  0.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        try:
            result = compute_clash_score('/nonexistent/ligand.pdbqt', protein_path)
            assert result['clash_score'] is None
            assert 'error' in result
        finally:
            os.unlink(protein_path)

    def test_ligand_as_string_content(self):
        """compute_clash_score should accept ligand as string content (not just file path)."""
        protein_pdb = """ATOM      1  C   ALA     1       0.000   0.000   0.000  0.00  0.00           C
END
"""
        # Pass ligand as raw string content (not a file path)
        ligand_content = """REMARK SMILES C
ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        try:
            result = compute_clash_score(ligand_content, protein_path)
            # No clash because same coordinates but same atom → distance = 0
            # Actually C-C at 0 distance: overlap = 3.40 → very bad clash
            assert result['clash_score'] is not None
            assert result['n_clashing_pairs'] >= 1
        finally:
            os.unlink(protein_path)


class TestClashScoreAtomCounts:
    """Verify atom counts are correctly reported."""

    def test_atom_counts_reported(self):
        """Result should include n_protein_atoms and n_ligand_atoms."""
        protein_pdb = """ATOM      1  C   ALA     1       0.000   0.000   0.000  0.00  0.00           C
ATOM      2  N   ALA     1       1.500   0.000   0.000  0.00  0.00           N
ATOM      3  O   ALA     1       0.000   1.500   0.000  0.00  0.00           O
ATOM      4  H   ALA     1       0.000   0.000   1.000  0.00  0.00           H
END
"""
        ligand_pdbqt = """REMARK SMILES CCO
ATOM      1  C   UNL     1      50.000  50.000  50.000  0.00  0.00           C
ATOM      2  C   UNL     1      51.500  50.000  50.000  0.00  0.00           C
ATOM      3  O   UNL     1      52.500  50.000  50.000  0.00  0.00           O
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as pf:
            pf.write(protein_pdb)
            protein_path = pf.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write(ligand_pdbqt)
            ligand_path = lf.name

        try:
            result = compute_clash_score(ligand_path, protein_path)
            assert 'n_protein_atoms' in result
            assert 'n_ligand_atoms' in result
            assert result['n_protein_atoms'] == 4  # C, N, O, H
            assert result['n_ligand_atoms'] == 3   # C, C, O
        finally:
            os.unlink(protein_path)
            os.unlink(ligand_path)
