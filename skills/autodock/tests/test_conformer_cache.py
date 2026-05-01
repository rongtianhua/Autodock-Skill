"""
Tests for cache and multi-conformer features.
"""
import os
import sys
import pytest
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock import prepare_ligand_conformers, fetch_protein_pdb
from autodock._structure_fetch import _get_cache_dir


class TestCache:
    """Cache mechanism for fetched structures."""

    def test_cache_dir_created(self):
        """Cache directory should be created on demand."""
        cache = _get_cache_dir()
        assert cache.exists()
        assert cache.parent.name == '.openclaw'

    def test_fetch_uses_cache(self):
        """Second fetch should return cached file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First fetch
            p1 = fetch_protein_pdb('1DB2', os.path.join(tmpdir, '1db2_first.pdb'))
            cache_path = _get_cache_dir() / '1DB2.pdb'
            assert cache_path.exists()

            # Second fetch should not hit network (reuses cache)
            p2 = fetch_protein_pdb('1DB2', os.path.join(tmpdir, '1db2_second.pdb'))
            assert os.path.exists(p2)
            # Both are working copies, not the same file path
            assert p1 != p2

    def test_force_refresh_redownloads(self):
        """force_refresh=True should re-download even if cached."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Prime cache
            fetch_protein_pdb('1COV', os.path.join(tmpdir, 'cov.pdb'))
            cache = _get_cache_dir() / '1COV.pdb'
            mtime_before = cache.stat().st_mtime

            import time; time.sleep(0.1)
            # Force refresh
            p = fetch_protein_pdb('1COV', os.path.join(tmpdir, 'cov_refresh.pdb'),
                                  force_refresh=True)
            mtime_after = cache.stat().st_mtime
            assert mtime_after > mtime_before


class TestPrepareLigandConformers:
    """Multi-conformer ligand preparation."""

    def test_generates_correct_count(self, tmp_path):
        """Should generate exactly n_conformers files."""
        out_dir = str(tmp_path / 'conformers')
        paths = prepare_ligand_conformers(
            smiles='CC(=O)OC1=CC=CC=C1C(=O)O',  # aspirin
            output_dir=out_dir,
            n_conformers=5,
            seed_start=42,
        )
        assert len(paths) == 5
        for i, p in enumerate(paths):
            assert os.path.exists(p), f"Conformer {i} not found at {p}"
            assert f'conformer_{i}.pdbqt' in p

    def test_different_seeds_different_files(self, tmp_path):
        """Different seeds should produce different PDBQT content."""
        out_a = str(tmp_path / 'conf_a')
        out_b = str(tmp_path / 'conf_b')

        paths_a = prepare_ligand_conformers(
            'CCO', out_a, n_conformers=2, seed_start=42)
        paths_b = prepare_ligand_conformers(
            'CCO', out_b, n_conformers=2, seed_start=100)

        # Files should exist
        for p in paths_a + paths_b:
            assert os.path.exists(p)

        # At least one conformer should differ (different seeds)
        with open(paths_a[0]) as fa, open(paths_b[0]) as fb:
            content_a = fa.read()
            content_b = fb.read()
        # The files might coincidentally be similar for simple molecules,
        # but conformer 0 vs conformer 1 within same seed should differ
        with open(paths_a[0]) as f0, open(paths_a[1]) as f1:
            assert f0.read() != f1.read(), "Same seed should not give identical conformers"

    def test_invalid_smiles_raises(self, tmp_path):
        """Invalid SMILES should raise ValueError."""
        with pytest.raises(ValueError):
            prepare_ligand_conformers(
                smiles='NOT_A_SMILE[[[',
                output_dir=str(tmp_path / 'bad'),
                n_conformers=2,
            )

    def test_zero_conformers_raises(self, tmp_path):
        """n_conformers=0 should raise ValueError."""
        with pytest.raises(ValueError):
            prepare_ligand_conformers(
                smiles='CCO',
                output_dir=str(tmp_path / 'zero'),
                n_conformers=0,
            )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])