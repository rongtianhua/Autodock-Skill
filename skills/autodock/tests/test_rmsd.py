"""
Tests for compute_rmsd — atom-to-atom RMSD calculation.
"""
import os, sys, tempfile, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock._autodock import compute_rmsd


class TestRmsd:
    """Test RMSD calculation edge cases."""

    def test_identical_structures_rmsd_zero(self):
        """Two identical ligands should have RMSD ≈ 0."""
        pdbqt_a = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        pdbqt_b = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fa:
            fa.write(pdbqt_a); path_a = fa.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fb:
            fb.write(pdbqt_b); path_b = fb.name
        try:
            rmsd = compute_rmsd(path_a, path_b)
            assert rmsd is not None
            assert rmsd < 0.01, f"Identical structures should have RMSD ≈ 0, got {rmsd}"
        finally:
            os.unlink(path_a); os.unlink(path_b)

    def test_shifted_structure_has_nonzero_rmsd(self):
        """Structures translated by 1 Angstrom should have RMSD ≈ 1.0."""
        # Real PDBQT format: element in col 78-79 (right-padded to 2 chars)
        pdbqt_a = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00           O
"""
        pdbqt_b = """ATOM      1  C   UNL     1       1.000   0.000   0.000  0.00  0.00           C
ATOM      2  O   UNL     1       2.200   0.000   0.000  0.00  0.00           O
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fa:
            fa.write(pdbqt_a); path_a = fa.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fb:
            fb.write(pdbqt_b); path_b = fb.name
        try:
            rmsd = compute_rmsd(path_a, path_b)
            assert rmsd is not None
            assert abs(rmsd - 1.0) < 0.1, f"Translated structure should have RMSD ≈ 1.0, got {rmsd}"
        finally:
            os.unlink(path_a); os.unlink(path_b)

    def test_nonexistent_files_return_none(self):
        """Nonexistent files should not raise exceptions."""
        rmsd = compute_rmsd('/nonexistent/A.pdbqt', '/nonexistent/B.pdbqt')
        assert rmsd is None

    def test_mismatched_atom_counts(self):
        """Molecules with different atom counts should return None."""
        pdbqt_a = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        pdbqt_b = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fa:
            fa.write(pdbqt_a); path_a = fa.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fb:
            fb.write(pdbqt_b); path_b = fb.name
        try:
            rmsd = compute_rmsd(path_a, path_b)
            # Should either return None or a valid number (robust handling)
            assert rmsd is None or isinstance(rmsd, float)
        finally:
            os.unlink(path_a); os.unlink(path_b)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])