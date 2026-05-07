"""
Tests for SwissModel enhanced functions: quality scoring, advanced selection, and REST API.

Validates:
  - fetch_protein_swissmodel() with provider_filter, return_all
  - fetch_protein_swissmodel_advanced() with quality thresholds
  - Quality scoring extraction (GMQE, QMEAN, identity, coverage)
  - swissmodel_get_token() (mock test)
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestSwissModelEnhanced:
    """SwissModel Repository enhanced query tests."""

    @pytest.mark.slow
    def test_swissmodel_basic(self):
        """Basic fetch should work."""
        from autodock import fetch_protein_swissmodel

        result = fetch_protein_swissmodel("P00533")
        assert isinstance(result, str)
        assert os.path.exists(result)
        assert result.endswith('.pdb')

    @pytest.mark.slow
    def test_swissmodel_provider_filter_swissmodel(self):
        """Filter to SWISSMODEL provider only."""
        from autodock import fetch_protein_swissmodel

        # P00533 has 2 SWISSMODEL entries
        results = fetch_protein_swissmodel(
            "P00533",
            return_all=True,
            provider_filter='swissmodel'
        )
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert r['provider'] == 'SWISSMODEL'
            assert 'gmqe' in r  # SWISSMODEL entries have quality scores

    @pytest.mark.slow
    def test_swissmodel_provider_filter_pdb(self):
        """Filter to PDB provider only."""
        from autodock import fetch_protein_swissmodel

        results = fetch_protein_swissmodel(
            "P00533",
            return_all=True,
            provider_filter='pdb'
        )
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert r['provider'] == 'PDB'

    @pytest.mark.slow
    def test_swissmodel_return_all_quality(self):
        """return_all should include quality scores."""
        from autodock import fetch_protein_swissmodel

        results = fetch_protein_swissmodel("P00533", return_all=True)
        assert isinstance(results, list)

        # Check at least one result has quality info
        swiss = [r for r in results if r['provider'] == 'SWISSMODEL']
        if swiss:
            assert 'gmqe' in swiss[0]
            assert 'qmean' in swiss[0]
            assert 'identity' in swiss[0]
            assert 'coverage' in swiss[0]

    @pytest.mark.slow
    def test_swissmodel_coverage_filter(self):
        """min_coverage should filter low-coverage models."""
        from autodock import fetch_protein_swissmodel

        with pytest.raises(ValueError):
            fetch_protein_swissmodel("P00533", min_coverage=0.99)

    @pytest.mark.slow
    def test_swissmodel_identity_filter(self):
        """min_identity should filter low-identity models."""
        from autodock import fetch_protein_swissmodel

        # Very high identity should fail
        with pytest.raises(ValueError):
            fetch_protein_swissmodel("P00533", min_identity=0.99)


class TestSwissModelAdvanced:
    """fetch_protein_swissmodel_advanced() tests."""

    @pytest.mark.slow
    def test_advanced_basic(self):
        """Advanced fetch with quality report."""
        from autodock import fetch_protein_swissmodel_advanced

        result = fetch_protein_swissmodel_advanced("P00533")
        assert isinstance(result, dict)
        assert 'path' in result
        assert 'source' in result
        assert 'quality_grade' in result
        assert os.path.exists(result['path'])

    @pytest.mark.slow
    def test_advanced_quality_grade(self):
        """Quality grade should be one of expected values."""
        from autodock import fetch_protein_swissmodel_advanced

        result = fetch_protein_swissmodel_advanced("P00533")
        assert result['quality_grade'] in ('excellent', 'good', 'moderate', 'poor')

    @pytest.mark.slow
    def test_advanced_all_candidates(self):
        """Should return all candidates list."""
        from autodock import fetch_protein_swissmodel_advanced

        result = fetch_protein_swissmodel_advanced("P00533")
        assert 'all_candidates' in result
        assert isinstance(result['all_candidates'], list)

    @pytest.mark.slow
    def test_advanced_fallback_disabled(self):
        """With fallback disabled and no models, should raise."""
        from autodock import fetch_protein_swissmodel_advanced

        # Use a bogus ID
        with pytest.raises(ValueError):
            fetch_protein_swissmodel_advanced(
                "BOGUS_ID_12345",
                fallback_alphafold=False
            )

    @pytest.mark.slow
    def test_advanced_with_alphafold_fallback(self):
        """With fallback enabled, should get AlphaFold."""
        from autodock import fetch_protein_swissmodel_advanced

        result = fetch_protein_swissmodel_advanced(
            "Q9H825",  # METTL8 (may not have SwissModel)
            fallback_alphafold=True
        )
        assert isinstance(result, dict)
        assert 'path' in result
        assert result['source'] in ('swissmodel', 'alphafold')

    @pytest.mark.slow
    def test_advanced_thresholds(self):
        """High thresholds may trigger fallback."""
        from autodock import fetch_protein_swissmodel_advanced

        result = fetch_protein_swissmodel_advanced(
            "P00533",
            min_gmqe=0.8,
            min_qmean=-2.0,
            fallback_alphafold=True
        )
        assert isinstance(result, dict)
        assert 'path' in result


class TestSwissModelToken:
    """SwissModel REST API token management tests (mocked)."""

    def test_token_no_credentials_no_cache(self):
        """Without credentials and no cache, should raise."""
        from autodock._structure_fetch import swissmodel_get_token

        # Clear any existing token
        from autodock._structure_fetch import swissmodel_clear_token, _SWISSMODEL_TOKEN_FILE
        swissmodel_clear_token()

        with pytest.raises(ValueError) as exc_info:
            swissmodel_get_token()
        assert "No cached SwissModel token" in str(exc_info.value)

    def test_clear_token(self):
        """Clear token should remove file."""
        from autodock._structure_fetch import swissmodel_clear_token, _SWISSMODEL_TOKEN_FILE
        swissmodel_clear_token()
        assert not _SWISSMODEL_TOKEN_FILE.exists()

    def test_token_with_mock_credentials(self):
        """Test token caching with mock."""
        from autodock._structure_fetch import _SWISSMODEL_TOKEN_FILE
        import json

        # Create a mock token
        _SWISSMODEL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SWISSMODEL_TOKEN_FILE, 'w') as f:
            json.dump({"token": "mock_token_123"}, f)

        from autodock._structure_fetch import swissmodel_get_token
        token = swissmodel_get_token()
        assert token == "mock_token_123"

        # Cleanup
        from autodock._structure_fetch import swissmodel_clear_token
        swissmodel_clear_token()
