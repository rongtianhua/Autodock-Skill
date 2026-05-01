"""
Tests for input validation — file existence, type checks, value constraints.
"""
import os, sys, tempfile, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock._autodock import (
    prepare_receptor, prepare_ligand,
    find_binding_site, dock_ligand,
)


class TestPrepareReceptorValidation:
    """Input validation for prepare_receptor."""

    def test_nonexistent_file_raises(self):
        """Nonexistent PDB should raise FileNotFoundError."""
        with tempfile.NamedTemporaryFile(suffix='.pdbqt', delete=False) as f:
            out = f.name
        try:
            with pytest.raises(FileNotFoundError):
                prepare_receptor('/nonexistent.pdb', out)
        finally:
            os.unlink(out)

    def test_wrong_type_raises(self):
        """Non-string path should raise TypeError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as f:
            f.write('ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C\n')
            pdb_path = f.name
        with tempfile.NamedTemporaryFile(suffix='.pdbqt', delete=False) as f:
            out = f.name
        try:
            with pytest.raises(TypeError):
                prepare_receptor(123, out)  # int, not str
            with pytest.raises(TypeError):
                prepare_receptor(pdb_path, 456)  # int, not str
        finally:
            os.unlink(pdb_path)
            if os.path.exists(out):
                os.unlink(out)


class TestPrepareLigandValidation:
    """Input validation for prepare_ligand."""

    def test_invalid_smiles_raises(self):
        """Invalid SMILES should raise ValueError."""
        with tempfile.NamedTemporaryFile(suffix='.pdbqt', delete=False) as f:
            out = f.name
        try:
            with pytest.raises(ValueError):
                prepare_ligand('INVALID_SMILE[[[', out)
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_wrong_type_raises(self):
        """Non-string SMILES should raise TypeError."""
        with tempfile.NamedTemporaryFile(suffix='.pdbqt', delete=False) as f:
            out = f.name
        try:
            with pytest.raises(TypeError):
                prepare_ligand(123, out)
        finally:
            if os.path.exists(out):
                os.unlink(out)


class TestDockLigandValidation:
    """Input validation for dock_ligand."""

    def test_nonexistent_receptor_raises(self):
        """Nonexistent receptor PDBQT should raise FileNotFoundError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write('ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C\n')
            pdbqt = f.name
        try:
            with pytest.raises(FileNotFoundError):
                dock_ligand('/nonexistent.pdbqt', pdbqt, center=(0,0,0), box_size=(20,20,20))
        finally:
            os.unlink(pdbqt)

    def test_wrong_center_type_raises(self):
        """Wrong center type should raise TypeError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write('ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C\n')
            pdbqt = f.name
        try:
            with pytest.raises(TypeError):
                dock_ligand(pdbqt, pdbqt, center='x,y,z', box_size=(20,20,20))  # str
            with pytest.raises(TypeError):
                dock_ligand(pdbqt, pdbqt, center=(0,0), box_size=(20,20,20))     # too short
            with pytest.raises(TypeError):
                dock_ligand(pdbqt, pdbqt, center=(0,0,0), box_size=(20,20))      # too short
        finally:
            os.unlink(pdbqt)

    def test_negative_box_size_raises(self):
        """Negative box_size should raise ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write('ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00           C\n')
            pdbqt = f.name
        try:
            with pytest.raises(ValueError):
                dock_ligand(pdbqt, pdbqt, center=(0,0,0), box_size=(-20,20,20))
        finally:
            os.unlink(pdbqt)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])