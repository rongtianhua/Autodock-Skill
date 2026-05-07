"""
Tests for prepare_receptor() with .cif / .pdbx input support via ProDy.

Validates:
  - Auto-detection of .cif extension
  - Explicit input_format='cif'
  - ProDy conversion → meeko pipeline
  - Output PDBQT validity
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestReceptorCifSupport:
    """Receptor preparation from mmCIF format."""

    def test_prepare_receptor_pdb_baseline(self, tmp_path):
        """Baseline: .pdb input should still work."""
        from autodock import prepare_receptor

        # Use a known small PDB
        pdb_path = str(tmp_path / "test.pdb")
        with open(pdb_path, 'w') as f:
            f.write("""HEADER    TEST
ATOM      1  N   ALA A   1      10.000  10.000  10.000  1.00 20.00           N
ATOM      2  CA  ALA A   1      11.458  10.000  10.000  1.00 20.00           C
ATOM      3  C   ALA A   1      12.000  11.420  10.000  1.00 20.00           C
ATOM      4  O   ALA A   1      12.000  12.000  11.200  1.00 20.00           O
ATOM      5  CB  ALA A   1      12.000   9.000   9.000  1.00 20.00           C
END
""")

        out_pdbqt = str(tmp_path / "test.pdbqt")
        result = prepare_receptor(pdb_path, out_pdbqt, remove_waters=True)
        assert os.path.exists(result)
        assert result.endswith('.pdbqt')
        with open(result) as f:
            content = f.read()
        assert 'ATOM' in content or 'REMARK' in content

    def test_prepare_receptor_cif_auto_detect(self, tmp_path):
        """Auto-detect .cif extension and convert via ProDy."""
        from autodock import prepare_receptor

        # Download a small .cif file
        cif_path = str(tmp_path / "1aco.cif")
        try:
            import urllib.request
            urllib.request.urlretrieve(
                "https://files.rcsb.org/download/1ACO.cif", cif_path
            )
        except Exception:
            pytest.skip("RCSB download unavailable")

        out_pdbqt = str(tmp_path / "1aco.pdbqt")
        result = prepare_receptor(cif_path, out_pdbqt, remove_waters=True)
        assert os.path.exists(result)
        assert result.endswith('.pdbqt')
        with open(result) as f:
            content = f.read()
        assert 'ATOM' in content

    def test_prepare_receptor_cif_explicit_format(self, tmp_path):
        """Explicit input_format='cif' on a file with any extension."""
        from autodock import prepare_receptor

        # Download .cif but rename to .txt to test explicit format
        cif_path = str(tmp_path / "structure.txt")
        try:
            import urllib.request
            urllib.request.urlretrieve(
                "https://files.rcsb.org/download/1ACO.cif", cif_path
            )
        except Exception:
            pytest.skip("RCSB download unavailable")

        out_pdbqt = str(tmp_path / "structure.pdbqt")
        result = prepare_receptor(cif_path, out_pdbqt,
                                 remove_waters=True, input_format='cif')
        assert os.path.exists(result)

    def test_prepare_receptor_invalid_format_raises(self, tmp_path):
        """Invalid input_format should raise ValueError."""
        from autodock import prepare_receptor

        pdb_path = str(tmp_path / "dummy.pdb")
        with open(pdb_path, 'w') as f:
            f.write("ATOM    1  N   ALA A   1      0.000   0.000   0.000\n")

        with pytest.raises(ValueError):
            prepare_receptor(pdb_path, str(tmp_path / "out.pdbqt"),
                             input_format='xyz')

    def test_prepare_receptor_cif_with_waters(self, tmp_path):
        """.cif with waters: remove_waters=True should strip HOH."""
        from autodock import prepare_receptor

        cif_path = str(tmp_path / "1aco.cif")
        try:
            import urllib.request
            urllib.request.urlretrieve(
                "https://files.rcsb.org/download/1ACO.cif", cif_path
            )
        except Exception:
            pytest.skip("RCSB download unavailable")

        out_pdbqt = str(tmp_path / "1aco_nowater.pdbqt")
        result = prepare_receptor(cif_path, out_pdbqt, remove_waters=True)

        with open(result) as f:
            content = f.read()
        # Should not contain water residues
        lines = content.split('\n')
        water_lines = [l for l in lines
                        if (l.startswith('ATOM') or l.startswith('HETATM'))
                        and l[17:20].strip() in ('HOH', 'WAT', 'H2O')]
        assert len(water_lines) == 0, "Waters were not removed from .cif"
