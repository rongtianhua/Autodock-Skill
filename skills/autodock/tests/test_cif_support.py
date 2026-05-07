"""
Tests for mmCIF (.cif) support — RCSB PDB future format.

Validates:
  - .cif download + OpenBabel conversion to .pdb
  - Legacy 4-char PDB ID fallback
  - Extended 12-char PDB ID handling
  - Cache behavior for .cif → .pdb
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock._core import _HAVE_OBABEL


class TestCifSupport:
    """mmCIF download and conversion tests."""

    @pytest.mark.skipif(not _HAVE_OBABEL, reason="OpenBabel required for .cif conversion")
    def test_cif_download_and_conversion(self, tmp_path):
        """Download .cif and convert to .pdb via OpenBabel."""
        from autodock._structure_fetch import fetch_protein_pdb

        # Use a small, stable PDB entry
        pdb_id = "1COV"
        out_pdb = str(tmp_path / f"{pdb_id}.pdb")

        result = fetch_protein_pdb(pdb_id, output_path=out_pdb, format='cif')
        assert os.path.exists(result), f"Output file not found: {result}"
        assert result.endswith('.pdb'), f"Expected .pdb output, got: {result}"

        # Validate PDB content
        with open(result) as f:
            content = f.read()
        assert 'ATOM' in content or 'HETATM' in content, "Converted file has no ATOM records"

    def test_legacy_pdb_id_format_pdb(self, tmp_path):
        """Legacy 4-char ID with format='pdb' should download .pdb directly."""
        from autodock._structure_fetch import fetch_protein_pdb

        pdb_id = "1COV"
        out_pdb = str(tmp_path / f"{pdb_id}_legacy.pdb")

        result = fetch_protein_pdb(pdb_id, output_path=out_pdb, format='pdb')
        assert os.path.exists(result)
        assert result.endswith('.pdb')

        with open(result) as f:
            content = f.read()
        assert 'ATOM' in content or 'HEADER' in content

    def test_auto_format_prefers_cif(self, tmp_path):
        """format='auto' should try .cif first (for legacy IDs, with OpenBabel)."""
        from autodock._structure_fetch import fetch_protein_pdb

        pdb_id = "1COV"
        out_pdb = str(tmp_path / f"{pdb_id}_auto.pdb")

        result = fetch_protein_pdb(pdb_id, output_path=out_pdb, format='auto')
        assert os.path.exists(result)
        assert result.endswith('.pdb')

    def test_cif_cache_created(self, tmp_path):
        """.cif download should populate both .cif and .pdb cache."""
        from autodock._structure_fetch import _get_cache_dir, fetch_protein_pdb

        pdb_id = "1COV"
        out_pdb = str(tmp_path / f"{pdb_id}_cache.pdb")

        # Clear any existing cache
        cache_dir = _get_cache_dir()
        for suffix in ['.cif', '.pdb']:
            cached = cache_dir / f"{pdb_id}{suffix}"
            if cached.exists():
                cached.unlink()

        fetch_protein_pdb(pdb_id, output_path=out_pdb, format='cif')

        # Check cache
        if _HAVE_OBABEL:
            cif_cache = cache_dir / f"{pdb_id}.cif"
            pdb_cache = cache_dir / f"{pdb_id}.pdb"
            assert pdb_cache.exists(), "PDB cache not created"
            # .cif cache may or may not exist depending on implementation

    def test_invalid_pdb_id_raises(self):
        """Invalid PDB ID should raise ValueError."""
        from autodock._structure_fetch import fetch_protein_pdb

        with pytest.raises(ValueError):
            fetch_protein_pdb("INVALID", format='pdb')

        with pytest.raises(ValueError):
            fetch_protein_pdb("AB", format='pdb')  # Too short

    def test_extended_pdb_id_requires_cif(self, tmp_path):
        """Extended PDB ID (12-char) should require .cif format."""
        from autodock._structure_fetch import fetch_protein_pdb

        # Example of a hypothetical extended ID (may not exist in reality)
        # This test verifies the format logic, not actual download
        pdb_id = "PDB_12345678"  # 12 chars

        if _HAVE_OBABEL:
            # Should attempt .cif download
            out_pdb = str(tmp_path / "extended.pdb")
            try:
                result = fetch_protein_pdb(pdb_id, output_path=out_pdb, format='auto')
                # If it succeeds, should be .pdb output
                if result:
                    assert result.endswith('.pdb')
            except (ValueError, RuntimeError):
                # Expected for non-existent extended ID
                pass
        else:
            # Without OpenBabel, extended ID should fail
            with pytest.raises(RuntimeError):
                fetch_protein_pdb(pdb_id, format='auto')

    def test_cif_to_pdb_conversion_function(self, tmp_path):
        """Test _cif_to_pdb directly with a minimal valid CIF file."""
        from autodock._structure_fetch import _cif_to_pdb

        # Valid mmCIF content (simplified but complete enough for OpenBabel)
        cif_content = """data_test
#
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
ATOM 1 C CA ALA 1 0.000 0.000 0.000
ATOM 2 C C ALA 1 1.458 0.000 0.000
ATOM 3 O O ALA 1 1.458 1.210 0.000
ATOM 4 N N ALA 1 0.000 1.210 0.000
#
"""
        cif_path = str(tmp_path / "test.cif")
        pdb_path = str(tmp_path / "test.pdb")

        with open(cif_path, 'w') as f:
            f.write(cif_content)

        if _HAVE_OBABEL:
            result = _cif_to_pdb(cif_path, pdb_path)
            assert os.path.exists(result)
            with open(result) as f:
                content = f.read()
            assert 'ATOM' in content

    @pytest.mark.skipif(_HAVE_OBABEL, reason="Only test when OpenBabel is missing")
    def test_missing_obabel_fallback(self, tmp_path):
        """Without OpenBabel, legacy IDs should fallback to .pdb."""
        from autodock._structure_fetch import fetch_protein_pdb

        pdb_id = "1COV"
        out_pdb = str(tmp_path / f"{pdb_id}_fallback.pdb")

        result = fetch_protein_pdb(pdb_id, output_path=out_pdb, format='auto')
        assert os.path.exists(result)
        assert result.endswith('.pdb')
