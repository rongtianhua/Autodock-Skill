"""
Tests for dock_ligand_flexible and prepare_receptor_with_waters.
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


class TestDockLigandFlexible:
    def test_flexible_basic_smoke(self, tmp_path):
        """dock_ligand_flexible should run without error (ensemble_mode=True)."""
        from autodock import dock_ligand_flexible, fetch_protein_pdb, prepare_receptor, prepare_ligand

        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        rec_pdbqt = tmp_path / "rec.pdbqt"
        prepare_receptor(str(rec_pdb), str(rec_pdbqt))

        lig_pdbqt = tmp_path / "lig.pdbqt"
        prepare_ligand("CC(=O)OC1=CC=CC=C1C(=O)O", str(lig_pdbqt))

        result = dock_ligand_flexible(
            receptor_pdb=str(rec_pdb),
            ligand_pdbqt=str(lig_pdbqt),
            center=(15.0, 65.0, 10.0),
            box_size=(20, 20, 20),
            ensemble_mode=True,
            exhaustiveness=8,
            n_poses=3,
        )
        assert 'best_energy' in result
        assert result['best_energy'] is not None
        assert result['n_ensembles'] >= 1
        assert 'softdock_note' in result

    def test_flexible_softdock_mode(self, tmp_path):
        """ensemble_mode=False should fall back to rigid docking."""
        from autodock import dock_ligand_flexible, fetch_protein_pdb, prepare_receptor, prepare_ligand

        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        rec_pdbqt = tmp_path / "rec.pdbqt"
        prepare_receptor(str(rec_pdb), str(rec_pdbqt))

        lig_pdbqt = tmp_path / "lig.pdbqt"
        prepare_ligand("CC(=O)OC1=CC=CC=C1C(=O)O", str(lig_pdbqt))

        result = dock_ligand_flexible(
            receptor_pdb=str(rec_pdb),
            ligand_pdbqt=str(lig_pdbqt),
            center=(15.0, 65.0, 10.0),
            box_size=(20, 20, 20),
            ensemble_mode=False,
            exhaustiveness=8,
        )
        assert result['n_ensembles'] == 1
        assert 'softdock_note' in result
        assert 'rigid' in result['softdock_note'].lower() or 'ensemble' in result['softdock_note'].lower()

    def test_flexible_flexible_residues_param(self, tmp_path):
        """Passing flexible_residues should be accepted without error."""
        from autodock import dock_ligand_flexible, fetch_protein_pdb, prepare_receptor, prepare_ligand

        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        rec_pdbqt = tmp_path / "rec.pdbqt"
        prepare_receptor(str(rec_pdb), str(rec_pdbqt))

        lig_pdbqt = tmp_path / "lig.pdbqt"
        prepare_ligand("CC(=O)OC1=CC=CC=C1C(=O)O", str(lig_pdbqt))

        result = dock_ligand_flexible(
            receptor_pdb=str(rec_pdb),
            ligand_pdbqt=str(lig_pdbqt),
            center=(15.0, 65.0, 10.0),
            box_size=(20, 20, 20),
            flexible_residues=["HIS:41", "ASP:85"],
            ensemble_mode=False,
            exhaustiveness=8,
        )
        assert result is not None


class TestPrepareReceptorWithWaters:
    def test_keep_waters(self, tmp_path):
        """keep_waters=True should preserve HOH residues."""
        from autodock import prepare_receptor_with_waters, fetch_protein_pdb

        # Get a protein that may have waters (1FBD has some)
        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        out_pdbqt = tmp_path / "rec_with_waters.pdbqt"
        result = prepare_receptor_with_waters(str(rec_pdb), str(out_pdbqt), keep_waters=True)
        assert os.path.exists(result)

        # The file should be non-empty
        with open(result) as f:
            content = f.read()
        assert len(content) > 1000

    def test_remove_waters(self, tmp_path):
        """keep_waters=False should remove HOH residues."""
        from autodock import prepare_receptor_with_waters, fetch_protein_pdb

        rec_pdb = tmp_path / "rec.pdb"
        fetch_protein_pdb("6LU7", str(rec_pdb))

        out_pdbqt = tmp_path / "rec_no_waters.pdbqt"
        result = prepare_receptor_with_waters(str(rec_pdb), str(out_pdbqt), keep_waters=False)
        assert os.path.exists(result)

    def test_nonexistent_input_raises(self):
        from autodock import prepare_receptor_with_waters
        with pytest.raises(FileNotFoundError):
            prepare_receptor_with_waters("/nonexistent.pdb", "/tmp/out.pdbqt")
