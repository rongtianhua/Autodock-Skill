"""
Tests for _read_ligand_from_pdbqt_3d — PDBQT parsing with 3D coordinates.
"""
import os, sys, tempfile, pytest

# Add autodock to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
# Import from _autodock directly since autodock.__init__ re-exports it
from autodock._autodock import _read_ligand_from_pdbqt_3d


class TestPdbqtParsing:
    """Test PDBQT parsing edge cases."""

    def test_simple_molecule(self):
        """Test a simple benzene-like molecule."""
        pdbqt = """REMARK SMILES c1ccccc1
ATOM      1  C   UNL     1       0.000   1.400   0.000  0.00  0.00 C
ATOM      2  C   UNL     1      -1.212   0.700   0.000  0.00  0.00 C
ATOM      3  C   UNL     1      -1.212  -0.700   0.000  0.00  0.00 C
ATOM      4  C   UNL     1       0.000  -1.400   0.000  0.00  0.00 C
ATOM      5  C   UNL     1       1.212  -0.700   0.000  0.00  0.00 C
ATOM      6  C   UNL     1       1.212   0.700   0.000  0.00  0.00 C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write(pdbqt)
            path = f.name
        try:
            mol = _read_ligand_from_pdbqt_3d(path)
            assert mol is not None, "mol should not be None"
            assert mol.GetNumAtoms() == 6, f"Expected 6 atoms, got {mol.GetNumAtoms()}"
            assert mol.GetNumBonds() > 0, "Should have bonds inferred from SMILES"
        finally:
            os.unlink(path)

    def test_missing_smiles(self):
        """Test PDBQT without SMILES remark (bond order recovery via openbabel)."""
        pdbqt = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write(pdbqt)
            path = f.name
        try:
            mol = _read_ligand_from_pdbqt_3d(path)
            assert mol is not None, "mol should not be None even without SMILES"
            # Without SMILES, OpenBabel bond recovery should be attempted
        finally:
            os.unlink(path)

    def test_nonexistent_file(self):
        """Test that a nonexistent file returns None, not raises."""
        mol = _read_ligand_from_pdbqt_3d('/nonexistent/path/molecule.pdbqt')
        assert mol is None, "Should return None for nonexistent file"

    def test_coordinates_preserved(self):
        """Verify that parsed coordinates match the PDBQT source."""
        pdbqt = """REMARK SMILES CC
ATOM      1  C   UNL     1      -0.750   0.000   0.000  0.00  0.00 C
ATOM      2  C   UNL     1       0.750   0.000   0.000  0.00  0.00 C
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write(pdbqt)
            path = f.name
        try:
            mol = _read_ligand_from_pdbqt_3d(path)
            assert mol is not None
            conf = mol.GetConformer()
            # Atom 0 should be near (-0.75, 0, 0)
            pos0 = conf.GetAtomPosition(0)
            assert abs(pos0.x - (-0.750)) < 0.01, f"x={pos0.x}"
            assert abs(pos0.y) < 0.01, f"y={pos0.y}"
        finally:
            os.unlink(path)


class TestEdgeCases:
    """Test edge cases and potential failure modes."""

    def test_malformed_pdbqt(self):
        """Test that malformed lines don't crash the parser."""
        pdbqt = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
NOTALINE
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
ATOM      3  XX  UNL     1       2.000   0.000   0.000  0.00  0.00 XX
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write(pdbqt)
            path = f.name
        try:
            mol = _read_ligand_from_pdbqt_3d(path)
            # Should handle gracefully
            assert mol is not None
        finally:
            os.unlink(path)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])