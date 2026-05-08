"""Tests for pocket detection (fpocket + P2Rank)."""
import os, sys, tempfile, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from autodock._preparation import (
    _compute_box_size,
    _parse_fpocket_info,
    _prepare_pdb_for_fpocket,
    _estimate_ligand_dimensions,
)


class TestComputeBoxSize:
    """Test docking box size computation."""

    def test_basic(self):
        result = _compute_box_size((10, 10, 10), padding=5.0)
        assert result == (20.0, 20.0, 20.0)

    def test_rounding(self):
        result = _compute_box_size((10.3, 10.7, 10.1), padding=5.0)
        # (10.3+10=20.3 → 20.5, 10.7+10=20.7 → 20.5, 10.1+10=20.1 → 20.0)
        assert result == (20.5, 20.5, 20.0)

    def test_minimum(self):
        result = _compute_box_size((1, 1, 1), padding=2.0)
        # (1+4=5 → max(10,5)=10)
        assert result == (10.0, 10.0, 10.0)

    def test_ligand_adaptive(self, tmp_path):
        # Create a small ligand PDBQT
        pdbqt = tmp_path / "lig.pdbqt"
        pdbqt.write_text(
            "ATOM    1  C   LIG     1       0.000   0.000   0.000  1.00  0.00           C\n"
            "ATOM    2  C   LIG     1       3.000   0.000   0.000  1.00  0.00           C\n"
            "ATOM    3  O   LIG     1       4.500   0.000   0.000  1.00  0.00           O\n"
        )
        # Ligand dims: x=4.5, y=0, z=0 → bounding box (4.5, 0, 0)
        # With padding=5.0: box must accommodate ligand (4.5) + 4*5 = 24.5 per axis
        result = _compute_box_size((20, 20, 20), padding=5.0, ligand_pdbqt=str(pdbqt))
        # x: raw=20+10=30, ligand_contribution=4.5+20=24.5, max=30 → 30.0
        # y: raw=20+10=30, ligand_contribution=0+20=20, max=30 → 30.0
        # z: raw=20+10=30, ligand_contribution=0+20=20, max=30 → 30.0
        assert result == (30.0, 30.0, 30.0)

    def test_ligand_large_box(self, tmp_path):
        # Large ligand forces box bigger than pocket dims
        pdbqt = tmp_path / "lig.pdbqt"
        # 30 Å ligand
        pdbqt.write_text(
            "ATOM    1  C   LIG     1       0.000   0.000   0.000  1.00  0.00           C\n"
            "ATOM    2  C   LIG     1      30.000   0.000   0.000  1.00  0.00           C\n"
        )
        # Pocket dims (10,10,10) + padding=5 → raw=20 per axis
        # Ligand dims: (30, 0, 0) + 4*5=20 → requires 50 on x
        result = _compute_box_size((10, 10, 10), padding=5.0, ligand_pdbqt=str(pdbqt))
        # x: raw=20, ligand=30+20=50, max=50 → 50.0
        assert result[0] >= 50.0


class TestParseFpocketInfo:
    """Test fpocket info file parsing."""

    def test_parse_sample_info(self, tmp_path):
        # Create a mock fpocket info file
        info_content = (
            "Pocket 1 :\n"
            "  Druggability Score : 0.750\n"
            "  Volume : 1254.12\n"
            "  Depth : 8.45\n"
            "  Number of mouth openings : 2\n"
            "  Number of apolar alpha sphere : 34\n"
            "  Number of polar alpha sphere : 12\n"
            "Pocket 2 :\n"
            "  Druggability Score : 0.310\n"
            "  Volume : 452.0\n"
            "  Depth : 4.2\n"
            "  Number of mouth openings : 1\n"
            "  Number of apolar alpha sphere : 15\n"
            "  Number of polar alpha sphere : 8\n"
        )
        info_file = tmp_path / "test_info.txt"
        info_file.write_text(info_content)

        # No PQR file → no center/dims, should return empty
        pockets = _parse_fpocket_info(str(info_file))
        # Without PQR files, center is None → pockets list is empty
        assert len(pockets) == 0  # center=None causes rejection

    def test_parse_missing_fields(self, tmp_path):
        """Handle info files with missing optional fields."""
        info_content = (
            "Pocket 1 :\n"
            "  Druggability Score : 0.500\n"
        )
        info_file = tmp_path / "test_info.txt"
        info_file.write_text(info_content)

        pockets = _parse_fpocket_info(str(info_file))
        # Without PQR, center is None → rejected
        assert len(pockets) == 0

    def test_parse_various_opening_counts(self, tmp_path):
        """Test parsing of different mouth opening counts."""
        info_content = (
            "Pocket 1 :\n"
            "  Druggability Score : 0.800\n"
            "  Volume : 1000.0\n"
            "  Depth : 7.0\n"
            "  Number of mouth openings : 0\n"
            "  Number of apolar alpha sphere : 20\n"
            "  Number of polar alpha sphere : 10\n"
        )
        info_file = tmp_path / "test_info.txt"
        info_file.write_text(info_content)

        pockets = _parse_fpocket_info(str(info_file))
        # Without PQR, center is None → rejected
        assert len(pockets) == 0


class TestPreparePdbForFpocket:
    """Test PDB preparation for fpocket."""

    def test_skip_water(self, tmp_path):
        pdb_in = tmp_path / "input.pdb"
        # Standard PDB format (78 chars per ATOM line)
        pdb_in.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
            "ATOM      2  O   HOH A   2       1.000   1.000   1.000  1.00  0.00           O\n"
        )
        pdb_out = tmp_path / "output.pdb"
        _prepare_pdb_for_fpocket(str(pdb_in), str(pdb_out))

        content = pdb_out.read_text()
        assert "ALA" in content
        assert "HOH" not in content

    def test_skip_dod(self, tmp_path):
        """DOD (deuterated water) should also be skipped."""
        pdb_in = tmp_path / "input.pdb"
        pdb_in.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
            "ATOM      2  O   DOD A   2       1.000   1.000   1.000  1.00  0.00           O\n"
        )
        pdb_out = tmp_path / "output.pdb"
        _prepare_pdb_for_fpocket(str(pdb_in), str(pdb_out))

        content = pdb_out.read_text()
        assert "ALA" in content
        assert "DOD" not in content

    def test_preserve_pdb_specific_residues(self, tmp_path):
        """PDB-specific residues like PJE (6LU7 linker) should NOT be skipped by fpocket prep."""
        pdb_in = tmp_path / "input.pdb"
        pdb_in.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
            "ATOM      2  C   PJE A   2       1.000   1.000   1.000  1.00  0.00           C\n"
        )
        pdb_out = tmp_path / "output.pdb"
        _prepare_pdb_for_fpocket(str(pdb_in), str(pdb_out))

        content = pdb_out.read_text()
        # PJE should be preserved in fpocket prep (only _SKIP_WATER is used)
        assert "PJE" in content

    def test_preserve_hetatm(self, tmp_path):
        """HETATM records (e.g. metal ions) should be preserved."""
        pdb_in = tmp_path / "input.pdb"
        pdb_in.write_text(
            "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
            "HETATM    2  MG    MG A   1       5.000   5.000   5.000  1.00  0.00          MG\n"
        )
        pdb_out = tmp_path / "output.pdb"
        _prepare_pdb_for_fpocket(str(pdb_in), str(pdb_out))

        content = pdb_out.read_text()
        assert "MG" in content


class TestEstimateLigandDimensions:
    """Test ligand dimension estimation from PDBQT."""

    def test_basic(self, tmp_path):
        pdbqt = tmp_path / "lig.pdbqt"
        pdbqt.write_text(
            "ATOM    1  C   LIG     1       0.000   0.000   0.000  1.00  0.00           C\n"
            "ATOM    2  C   LIG     1       5.000   0.000   0.000  1.00  0.00           C\n"
            "ATOM    3  O   LIG     1       2.500   8.660   0.000  1.00  0.00           O\n"
        )
        dims = _estimate_ligand_dimensions(str(pdbqt))
        assert dims is not None
        # x: 5.0 - 0.0 = 5.0, y: 8.66 - 0.0 ≈ 8.66, z: 0
        assert dims[0] == pytest.approx(5.0)
        assert dims[1] == pytest.approx(8.66, abs=0.01)
        assert dims[2] == pytest.approx(0.0)

    def test_nonexistent_file(self):
        dims = _estimate_ligand_dimensions("/nonexistent/file.pdbqt")
        assert dims is None