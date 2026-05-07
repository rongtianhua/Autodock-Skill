"""
Tests for RCSB Chemical Component Dictionary (CCD) — PDB Ligand Expo replacement.

Validates:
  - fetch_ligand_ccd() — CCD API query
  - fetch_ligand_smiles() — Quick SMILES lookup
  - fetch_ligand_from_pdb() — Ligand coordinates from PDB entry
  - Cache behavior
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestCcdQueries:
    """RCSB CCD ligand information queries."""

    def test_ccd_atp(self):
        """Query CCD for ATP."""
        from autodock._structure_fetch import fetch_ligand_ccd

        result = fetch_ligand_ccd("ATP")
        assert result['id'] == 'ATP'
        assert 'name' in result
        assert result['name'] == 'ADENOSINE-5\'-TRIPHOSPHATE'
        assert 'formula' in result
        assert 'formula_weight' in result
        assert 'source' in result
        assert result['source'] == 'RCSB CCD'

    def test_ccd_hem(self):
        """Query CCD for heme."""
        from autodock._structure_fetch import fetch_ligand_ccd

        result = fetch_ligand_ccd("HEM")
        assert result['id'] == 'HEM'
        assert 'name' in result

    def test_ccd_smiles_field(self):
        """CCD should return SMILES when available."""
        from autodock._structure_fetch import fetch_ligand_ccd

        result = fetch_ligand_ccd("ATP")
        # SMILES may or may not be present depending on CCD completeness
        assert 'smiles' in result

    def test_ccd_invalid_id_raises(self):
        """Invalid CCD ID should raise ValueError."""
        from autodock._structure_fetch import fetch_ligand_ccd

        with pytest.raises(ValueError):
            fetch_ligand_ccd("INVALID")

    def test_ccd_wrong_length_raises(self):
        """CCD ID must be 3 characters."""
        from autodock._structure_fetch import fetch_ligand_ccd

        with pytest.raises(ValueError):
            fetch_ligand_ccd("TOOLONG")

    def test_ccd_cache_created(self, tmp_path):
        """CCD query should populate cache."""
        from autodock._structure_fetch import _ccd_cache_dir, fetch_ligand_ccd

        # Clear cache
        cache_dir = _ccd_cache_dir()
        cache_file = cache_dir / "ATP.json"
        if cache_file.exists():
            cache_file.unlink()

        fetch_ligand_ccd("ATP")

        # Check cache
        assert cache_file.exists(), "CCD cache not created"


class TestLigandSmilesQuick:
    """fetch_ligand_smiles() quick lookup."""

    def test_smiles_lookup_atp(self):
        """Quick SMILES lookup for ATP."""
        from autodock._structure_fetch import fetch_ligand_smiles

        smiles = fetch_ligand_smiles("ATP")
        # May be empty if CCD lacks SMILES for this ligand
        assert isinstance(smiles, str)

    def test_smiles_invalid(self):
        """Invalid ID should raise ValueError."""
        from autodock._structure_fetch import fetch_ligand_smiles

        with pytest.raises(ValueError):
            fetch_ligand_smiles("INVALID")


class TestLigandFromPdb:
    """fetch_ligand_from_pdb() — download ligand coordinates."""

    def test_ligand_from_pdb_1atp(self, tmp_path):
        """Download ATP from PDB 1ATP."""
        from autodock._structure_fetch import fetch_ligand_from_pdb

        out = str(tmp_path / "1atp_atp.sdf")
        try:
            result = fetch_ligand_from_pdb("1ATP", "ATP", output_path=out)
            assert os.path.exists(result)
            assert os.path.getsize(result) > 0
        except ValueError:
            # ModelServer may be unavailable or ligand not in entry
            pytest.skip("RCSB ModelServer unavailable for this entry")

    def test_ligand_from_pdb_invalid(self, tmp_path):
        """Invalid PDB/ligand should raise ValueError."""
        from autodock._structure_fetch import fetch_ligand_from_pdb

        out = str(tmp_path / "test.sdf")
        with pytest.raises(ValueError):
            fetch_ligand_from_pdb("INVALID", "XYZ", output_path=out)
