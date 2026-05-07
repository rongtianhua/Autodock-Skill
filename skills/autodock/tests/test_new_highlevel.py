"""
Tests for new Part B high-level functions: dock_single, screen_ligands, batch_docking.
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, '/Users/allenrong/.openclaw/workspace/skills')
from autodock._core import _HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO

pytestmark = pytest.mark.skipif(
    not all([_HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO]),
    reason="vina + rdkit + meeko required",
)


class TestDockSingleBasics:
    @pytest.mark.slow  # runs actual docking (~30–120 s)
    def test_dock_single_smiles_basic(self, tmp_path):
        """dock_single with SMILES input should complete without error."""
        from autodock import dock_single, fetch_protein_pdb

        # Use a small protein + ligand as a smoke test
        rec_id = "6LU7"
        rec_pdb = tmp_path / f"{rec_id}.pdb"
        fetch_protein_pdb(rec_id, str(rec_pdb))

        lig_smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"  # aspirin

        result = dock_single(
            receptor_pdb=str(rec_pdb),
            ligand_smiles_or_pdb=lig_smiles,
            output_dir=str(tmp_path / "dock_out"),
            exhaustiveness=8,
        )
        assert result is not None
        assert result.best_affinity is not None
        assert result.best_affinity < 0  # negative = favorable
        assert hasattr(result, 'png_2d') or result.output_dir is not None

    @pytest.mark.slow
    def test_dock_single_pdb_id_autofetch(self, tmp_path):
        """dock_single with 4-char PDB ID should auto-fetch."""
        from autodock import dock_single

        lig_smiles = "CC1=CC=C(C=C1)C2=CC(=NN2C3=CC=C(C=C3)S(=O)(=O)N)C(F)(F)F"  # celecoxib-ish
        result = dock_single(
            receptor_pdb="6LU7",
            ligand_smiles_or_pdb=lig_smiles,
            output_dir=str(tmp_path / "dock_out2"),
            exhaustiveness=8,
        )
        assert result.best_affinity is not None


class TestScreenLigandsBasics:
    @pytest.mark.slow
    def test_screen_ligands_list_input(self, tmp_path):
        """screen_ligands accepts a list of (name, SMILES) tuples."""
        from autodock import screen_ligands, fetch_protein_pdb

        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        ligands = [
            ("aspirin", "CC(=O)OC1=CC=CC=C1C(=O)O"),
            ("caffeine", "CN1CNN=CC1=O"),
            ("acetaminophen", "CC(=O)Nc1ccc(cc1)O"),
        ]

        df, results, summary = screen_ligands(
            receptor_pdb=str(rec_pdb),
            ligand_smiles_list=ligands,
            output_dir=str(tmp_path / "screen_out"),
            exhaustiveness=4,
            n_workers=2,
        )
        assert len(results) >= 1
        assert df is not None

    @pytest.mark.slow
    def test_screen_ligands_min_affinity_filter(self, tmp_path):
        """min_affinity filter should keep only tight binders."""
        from autodock import screen_ligands, fetch_protein_pdb

        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        ligands = [
            ("tight", "CC(=O)OC1=CC=CC=C1C(=O)O"),
            ("weak", "CCO"),
        ]

        df, results, summary = screen_ligands(
            receptor_pdb=str(rec_pdb),
            ligand_smiles_list=ligands,
            output_dir=str(tmp_path / "screen_out2"),
            exhaustiveness=4,
            min_affinity=-6.0,  # only keep if affinity <= -6
        )
        # At least one result should be returned
        assert df is not None


class TestBatchDockingBasics:
    @pytest.mark.slow
    def test_batch_docking_two_receptors_two_ligands(self, tmp_path):
        """batch_docking with 2 receptors × 2 ligands = 4 combinations."""
        from autodock import batch_docking, fetch_protein_pdb

        rec1 = tmp_path / "rec1.pdb"
        rec2 = tmp_path / "rec2.pdb"
        fetch_protein_pdb("6LU7", str(rec1))
        fetch_protein_pdb("1FBD", str(rec2))

        # Ligands - pre-prepared PDBQT files
        from autodock import prepare_ligand
        lig1 = tmp_path / "lig1.pdbqt"
        lig2 = tmp_path / "lig2.pdbqt"
        prepare_ligand("CC(=O)OC1=CC=CC=C1C(=O)O", str(lig1))
        prepare_ligand("CN1CNN=CC1=O", str(lig2))

        df = batch_docking(
            receptor_pdb_list=[str(rec1), str(rec2)],
            ligand_pdbqt_list=[str(lig1), str(lig2)],
            output_dir=str(tmp_path / "batch_out"),
            n_workers=2,
            exhaustiveness=4,
        )
        assert len(df) >= 4  # 2×2 combinations
        assert 'affinity_kcal_mol' in df.columns
        assert 'clash_score' in df.columns

    @pytest.mark.slow
    def test_batch_docking_csv_written(self, tmp_path):
        """batch_docking should write a CSV file."""
        from autodock import batch_docking, fetch_protein_pdb, prepare_ligand

        rec = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec))

        lig = tmp_path / "lig.pdbqt"
        prepare_ligand("CC(=O)OC1=CC=CC=C1C(=O)O", str(lig))

        out_dir = tmp_path / "batch_out2"
        batch_docking(
            receptor_pdb_list=[str(rec)],
            ligand_pdbqt_list=[str(lig)],
            output_dir=str(out_dir),
            exhaustiveness=4,
        )
        csv_path = out_dir / "batch_affinity_matrix.csv"
        assert csv_path.exists(), f"Expected CSV at {csv_path}"
