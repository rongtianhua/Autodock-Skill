"""
Tests for AmberTools MM/PBSA module (_mmpbsa_amber.py).

Note: Most tests require AmberTools (autodock-amber conda environment).
Run with:
    conda activate autodock-amber
    pytest tests/test_mmpbsa_amber.py -v

Markers:
    @pytest.mark.amber - Requires AmberTools (skipped otherwise)
"""
import os
import sys
import tempfile
import shutil
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from autodock._mmpbsa_amber import _HAVE_AMBER, AmberMMPBSAResult

# Check if AmberTools are available
have_amber = _HAVE_AMBER and (
    shutil.which('tleap') and
    shutil.which('antechamber') and
    shutil.which('MMPBSA.py')
)

amber_mark = pytest.mark.skipif(
    not have_amber,
    reason="AmberTools not available. Activate autodock-amber environment: conda activate autodock-amber"
)

import shutil
from autodock._mmpbsa_amber import (
    prepare_amber_topology,
    run_amber_md,
    run_mmpbsa_amber,
    compute_mmpbsa_amber,
)


class TestAmberMMPBSAResult:
    """Tests for the AmberMMPBSAResult dataclass."""

    def test_result_creation(self):
        """AmberMMPBSAResult should be created with default values."""
        result = AmberMMPBSAResult()
        assert result.delta_g_bind is None
        assert result.delta_e_vdw is None
        assert result.delta_e_elec is None
        assert result.delta_g_gb is None
        assert result.delta_g_sa is None
        assert result.t_delta_s is None
        assert result.per_residue == {}
        assert result.method == 'gb'
        assert result.protocol == 'quick'
        assert not result.is_publication_ready  # 'quick' protocol

    def test_result_publication_grade(self):
        """is_publication_ready should be True only for production protocols with valid energy."""
        # Needs both proper protocol AND non-None delta_g_bind
        result = AmberMMPBSAResult(protocol='medium', delta_g_bind=-10.5)
        assert result.is_publication_ready is True

        result2 = AmberMMPBSAResult(protocol='full', delta_g_bind=-12.0)
        assert result2.is_publication_ready is True

        result3 = AmberMMPBSAResult(protocol='quick', delta_g_bind=-8.0)
        assert result3.is_publication_ready is False  # 'quick' protocol never qualifies

        result4 = AmberMMPBSAResult(protocol='medium', delta_g_bind=None)
        assert result4.is_publication_ready is False  # No energy means not complete yet

    def test_result_summary(self):
        """summary() should produce a human-readable string."""
        result = AmberMMPBSAResult(
            delta_g_bind=-10.5,
            delta_e_vdw=-15.2,
            delta_e_elec=-8.3,
            delta_g_gb=8.5,
            delta_g_sa=4.5,
            protocol='short',
            method='gb',
            n_frames=100,
        )
        summary = result.summary()
        assert 'Amber MM/PBSA' in summary
        assert 'ΔG_bind' in summary
        assert '-10.50' in summary


class TestPdbqtConversion:
    """Tests for PDBQT to PDB conversion helper."""

    def test_pdbqt_to_pdb_basic(self):
        """_pdbqt_to_pdb should convert PDBQT to PDB."""
        from autodock._mmpbsa_amber import _pdbqt_to_pdb

        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
            f.write("""ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C
ATOM      2  H   UNL     1       1.090   0.000   0.000  1.00  0.00     0.000 H
END
""")
            pdbqt_path = f.name

        try:
            with tempfile.NamedTemporaryFile(suffix='.pdb', delete=False) as out_f:
                output_pdb = out_f.name

            _pdbqt_to_pdb(pdbqt_path, output_pdb)

            with open(output_pdb) as f:
                content = f.read()

            assert 'ATOM' in content
            assert 'C' in content
            assert 'H' in content
        finally:
            os.unlink(pdbqt_path)
            if os.path.exists(output_pdb):
                os.unlink(output_pdb)


@amber_mark
class TestAmberTopologyPreparation:
    """Integration tests for topology preparation (requires AmberTools)."""

    def get_test_files(self):
        """Get paths to test structures (uses existing test structures)."""
        structures_dir = os.path.join(os.path.dirname(__file__), '..', 'structures')

        # Try common test files
        receptor_candidates = [
            os.path.join(structures_dir, '6LU7.pdb'),
            os.path.join(structures_dir, '6LU7_prepared.pdb'),
        ]
        ligand_candidates = [
            os.path.join(structures_dir, 'aspirin.pdbqt'),
            os.path.join(structures_dir, 'nirmatrelvir.pdbqt'),
        ]

        receptor_pdb = None
        for cand in receptor_candidates:
            if os.path.exists(cand):
                receptor_pdb = cand
                break

        ligand_pdbqt = None
        for cand in ligand_candidates:
            if os.path.exists(cand):
                ligand_pdbqt = cand
                break

        return receptor_pdb, ligand_pdbqt

    @pytest.mark.slow
    def test_prepare_topology_basic(self):
        """prepare_amber_topology should create topology files."""
        receptor_pdb, ligand_pdbqt = self.get_test_files()

        if receptor_pdb is None or ligand_pdbqt is None:
            pytest.skip("Test structures not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                result = prepare_amber_topology(
                    receptor_pdb=receptor_pdb,
                    ligand_pdbqt=ligand_pdbqt,
                    output_dir=tmpdir,
                )

                # Check return value structure
                assert 'complex_prmtop' in result
                assert 'complex_rst7' in result
                assert 'receptor_prmtop' in result
                assert 'ligand_prmtop' in result

                # Check files exist
                assert os.path.exists(result['complex_prmtop'])
                assert os.path.exists(result['receptor_prmtop'])
                assert os.path.exists(result['ligand_prmtop'])

            except Exception as e:
                pytest.fail(f"prepare_amber_topology raised {type(e).__name__}: {e}")

    def test_prepare_topology_invalid_receptor(self):
        """prepare_amber_topology should fail with invalid receptor PDB."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as rf:
            rf.write("INVALID PDB CONTENT\n")
            receptor_pdb = rf.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as lf:
            lf.write("""ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C
END
""")
            ligand_pdbqt = lf.name

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                with pytest.raises(Exception):  # AmberPreparationError or similar
                    prepare_amber_topology(
                        receptor_pdb=receptor_pdb,
                        ligand_pdbqt=ligand_pdbqt,
                        output_dir=tmpdir,
                    )
            finally:
                os.unlink(receptor_pdb)
                os.unlink(ligand_pdbqt)


@amber_mark
class TestAmberMD:
    """Integration tests for Amber MD (requires AmberTools)."""

    @pytest.mark.slow
    def test_quick_protocol(self):
        """run_amber_md should complete with 'quick' (minimization only) protocol."""
        # This test requires valid prmtop/rst7 files
        # Skip for now as topology preparation is tested separately
        pytest.skip("Requires pre-validated topology files")


@amber_mark
class TestAmberMMPBSA:
    """Integration tests for MMPBSA calculation (requires AmberTools)."""

    @pytest.mark.slow
    def test_mmpbsa_completes(self):
        """run_mmpbsa_amber should complete successfully."""
        # This test requires valid topology files and trajectory
        # Skip for now
        pytest.skip("Requires pre-validated topology and trajectory files")


class TestEnvironmentCheck:
    """Tests for AmberTools environment detection."""

    def test_have_amber_detection(self):
        """_HAVE_AMBER should be correctly detected."""
        # Just verify the import doesn't crash - actual value depends on environment
        assert isinstance(_HAVE_AMBER, bool)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
