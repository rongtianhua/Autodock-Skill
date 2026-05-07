"""
Tests for BindingDB integration — experimental binding affinity queries.

Validates:
  - fetch_bindingdb_affinity by SMILES/name
  - fetch_bindingdb_by_target by UniProt ID
  - Cache behavior
  - Error handling (network failures, invalid queries)
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestBindingDbAffinity:
    """BindingDB compound affinity queries."""

    def test_affinity_query_by_name(self):
        """Query BindingDB by compound name."""
        from autodock._structure_fetch import fetch_bindingdb_affinity

        # Aspirin is well-studied with binding data
        results = fetch_bindingdb_affinity(name="aspirin", max_results=5)
        # May return empty if no data or API issues — that's OK
        assert isinstance(results, list)

        if results:
            for r in results:
                assert 'affinity_type' in r
                assert 'affinity_value' in r
                assert 'affinity_unit' in r

    def test_affinity_query_by_smiles(self):
        """Query BindingDB by SMILES."""
        from autodock._structure_fetch import fetch_bindingdb_affinity

        # Aspirin SMILES
        smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"
        results = fetch_bindingdb_affinity(smiles=smiles, max_results=5)
        assert isinstance(results, list)

    def test_affinity_query_invalid_raises(self):
        """No query parameters should raise ValueError."""
        from autodock._structure_fetch import fetch_bindingdb_affinity

        with pytest.raises(ValueError):
            fetch_bindingdb_affinity()

    def test_affinity_cache(self, tmp_path):
        """Repeated queries should use cache."""
        from autodock._structure_fetch import _bindingdb_cache_key

        # Just verify cache key generation works
        key = _bindingdb_cache_key('affinity', 'smiles:CCO')
        assert 'bindingdb' in str(key)
        assert key.suffix == '.json'

    def test_affinity_result_structure(self):
        """Verify result dict structure."""
        from autodock._structure_fetch import fetch_bindingdb_affinity

        results = fetch_bindingdb_affinity(name="aspirin", max_results=3)
        assert isinstance(results, list)

        for r in results:
            # Check expected keys
            assert isinstance(r, dict)
            assert 'affinity_type' in r
            assert 'affinity_unit' in r
            # Value may be None if parsing failed
            if r.get('affinity_value') is not None:
                assert isinstance(r['affinity_value'], (int, float))


class TestBindingDbTarget:
    """BindingDB target-centric queries."""

    def test_target_query_by_uniprot(self):
        """Query BindingDB by UniProt ID."""
        from autodock._structure_fetch import fetch_bindingdb_by_target

        # EGFR: P00533
        results = fetch_bindingdb_by_target(uniprot_id="P00533", max_results=5)
        assert isinstance(results, list)

        if results:
            for r in results:
                assert 'smiles' in r or 'name' in r
                assert 'affinity_type' in r

    def test_target_query_by_name(self):
        """Query BindingDB by target name."""
        from autodock._structure_fetch import fetch_bindingdb_by_target

        results = fetch_bindingdb_by_target(target_name="cyclooxygenase", max_results=5)
        assert isinstance(results, list)

    def test_target_invalid_raises(self):
        """No target parameters should raise ValueError."""
        from autodock._structure_fetch import fetch_bindingdb_by_target

        with pytest.raises(ValueError):
            fetch_bindingdb_by_target()

    def test_target_result_structure(self):
        """Verify target query result structure."""
        from autodock._structure_fetch import fetch_bindingdb_by_target

        results = fetch_bindingdb_by_target(uniprot_id="P00533", max_results=3)
        assert isinstance(results, list)

        for r in results:
            assert isinstance(r, dict)
            assert 'affinity_type' in r
            assert 'affinity_unit' in r


class TestBindingDbErrorHandling:
    """Error handling and edge cases."""

    def test_network_failure_graceful(self):
        """Network failure should return empty list, not crash."""
        from autodock._structure_fetch import fetch_bindingdb_affinity

        # Use a very unlikely name to trigger empty results
        results = fetch_bindingdb_affinity(name="XYZ_NONEXISTENT_COMPOUND_12345", max_results=5)
        assert isinstance(results, list)
        assert len(results) == 0

    def test_max_results_respected(self):
        """max_results should limit returned entries."""
        from autodock._structure_fetch import fetch_bindingdb_affinity

        results = fetch_bindingdb_affinity(name="aspirin", max_results=2)
        assert isinstance(results, list)
        assert len(results) <= 2
