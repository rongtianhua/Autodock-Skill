"""
Tests for NIH CACTUS and EBI OPSIN chemical identifier resolvers.

Validates:
  - fetch_molecule_cactus() — NIH CACTUS API
  - fetch_molecule_opsin() — EBI OPSIN IUPAC parser
  - fetch_molecule() unified source routing (cactus, opsin)
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestCactusResolver:
    """NIH CACTUS Chemical Identifier Resolver tests."""

    def test_cactus_name_to_smiles(self):
        """Resolve common chemical name via CACTUS."""
        from autodock._structure_fetch import fetch_molecule_cactus

        result = fetch_molecule_cactus("aspirin")
        assert 'smiles' in result
        assert len(result['smiles']) > 0
        assert result['source'] == 'NIH CACTUS'

    def test_cactus_smiles_to_smiles(self):
        """CACTUS can also accept SMILES and return canonical form."""
        from autodock._structure_fetch import fetch_molecule_cactus

        result = fetch_molecule_cactus("CCO")  # ethanol
        assert 'smiles' in result
        assert len(result['smiles']) > 0

    def test_cactus_invalid_raises(self):
        """Invalid identifier should raise ValueError."""
        from autodock._structure_fetch import fetch_molecule_cactus

        with pytest.raises(ValueError):
            fetch_molecule_cactus("XYZ_NONEXISTENT_COMPOUND_12345")

    def test_cactus_result_structure(self):
        """Verify result dict has expected keys."""
        from autodock._structure_fetch import fetch_molecule_cactus

        result = fetch_molecule_cactus("aspirin")
        assert 'name' in result
        assert 'smiles' in result
        assert 'source' in result
        assert result['source'] == 'NIH CACTUS'


class TestOpsinResolver:
    """EBI OPSIN IUPAC nomenclature parser tests."""

    def test_opsin_iupac_name(self):
        """Parse systematic IUPAC name via OPSIN."""
        from autodock._structure_fetch import fetch_molecule_opsin

        # Aspirin IUPAC name
        result = fetch_molecule_opsin("2-acetoxybenzoic acid")
        assert 'smiles' in result
        assert len(result['smiles']) > 0
        assert result['source'] == 'EBI OPSIN'

    def test_opsin_common_name_fallback(self):
        """Common names should fallback to PubChem."""
        from autodock._structure_fetch import fetch_molecule_opsin

        # OPSIN often fails on common names; should fallback
        result = fetch_molecule_opsin("caffeine")
        assert 'smiles' in result
        assert len(result['smiles']) > 0
        # source should indicate fallback if OPSIN failed
        assert 'PubChem' in result['source'] or 'OPSIN' in result['source']

    def test_opsin_invalid_raises(self):
        """Invalid IUPAC name should raise ValueError."""
        from autodock._structure_fetch import fetch_molecule_opsin

        with pytest.raises(ValueError):
            fetch_molecule_opsin("XYZ_NONEXISTENT_COMPOUND_12345")

    def test_opsin_result_structure(self):
        """Verify result dict has expected keys."""
        from autodock._structure_fetch import fetch_molecule_opsin

        result = fetch_molecule_opsin("2-acetoxybenzoic acid")
        assert 'name' in result
        assert 'smiles' in result
        assert 'source' in result


class TestUnifiedFetchRouting:
    """fetch_molecule() source parameter routing."""

    def test_fetch_cactus_source(self):
        """source='cactus' should route to NIH CACTUS."""
        from autodock._structure_fetch import fetch_molecule

        result = fetch_molecule("aspirin", source='cactus')
        assert result['source'] == 'NIH CACTUS'

    def test_fetch_opsin_source(self):
        """source='opsin' should route to EBI OPSIN."""
        from autodock._structure_fetch import fetch_molecule

        result = fetch_molecule("2-acetoxybenzoic acid", source='opsin')
        assert 'EBI OPSIN' in result['source']

    def test_fetch_unknown_source_raises(self):
        """Unknown source should raise ValueError with helpful message."""
        from autodock._structure_fetch import fetch_molecule

        with pytest.raises(ValueError) as exc_info:
            fetch_molecule("aspirin", source='unknown')
        assert "pubchem, chembl, opsin, cactus" in str(exc_info.value)
