"""
Tests for pose clustering.
"""
import os
import sys
import tempfile
import pytest
import numpy as np

sys.path.insert(0, '/Users/allenrong/.openclaw/workspace/skills')
from autodock._core import _HAVE_RDKIT

pytestmark = pytest.mark.skipif(not _HAVE_RDKIT, reason="RDKit not available")


from autodock._clustering import cluster_poses


def _make_pose_pdbqt(smiles, seed=42):
    """Helper: make a PDBQT string from SMILES."""
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from meeko import MoleculePreparation, PDBQTWriterLegacy

    mol = Chem.MolFromSmiles(smiles)
    mol = Chem.AddHs(mol, addCoords=True)
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    AllChem.EmbedMolecule(mol, params)
    AllChem.MMFFOptimizeMolecule(mol)

    mk_prep = MoleculePreparation(charge_model='gasteiger')
    mol_setup = mk_prep.prepare(mol)
    setup = mol_setup[0] if isinstance(mol_setup, list) else mol_setup
    pdbqt_str, success, err = PDBQTWriterLegacy.write_string(setup)
    if not success:
        raise RuntimeError(f"Meeko failed: {err}")
    return pdbqt_str


def _write_multimodel_pdbqt(poses_str_list):
    """Write a multi-MODEL PDBQT file and return the path."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as f:
        for i, pstr in enumerate(poses_str_list, 1):
            f.write(f"MODEL {i}\n")
            f.write(pstr)
            f.write("ENDMDL\n")
        path = f.name
    return path


class TestClusterPosesBasics:
    def test_two_poses_same_returns_one_cluster(self):
        """Two identical poses should cluster together."""
        smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"  # aspirin
        pdbqt1 = _make_pose_pdbqt(smiles, seed=42)
        pdbqt2 = _make_pose_pdbqt(smiles, seed=42)  # same, same seed

        path = _write_multimodel_pdbqt([pdbqt1, pdbqt2])
        try:
            clusters = cluster_poses(path, n_clusters=1)
            assert len(clusters) == 1
            assert clusters[0]['n_poses'] == 2
        finally:
            os.unlink(path)

    def test_two_poses_different_return_two_clusters(self):
        """Two structurally different poses should be separate clusters."""
        smiles1 = "CC(=O)OC1=CC=CC=C1C(=O)O"  # aspirin
        smiles2 = "CC1=CC=C(C=C1)C2=CC(=NN2C3=CC=C(C=C3)S(=O)(=O)N)C(F)(F)F"  # caffeine-ish

        pdbqt1 = _make_pose_pdbqt(smiles1, seed=42)
        pdbqt2 = _make_pose_pdbqt(smiles2, seed=43)

        path = _write_multimodel_pdbqt([pdbqt1, pdbqt2])
        try:
            clusters = cluster_poses(path, n_clusters=2)
            assert len(clusters) == 2
        finally:
            os.unlink(path)

    def test_less_than_two_poses_raises(self):
        """Single pose should raise ValueError."""
        smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"
        pdbqt = _make_pose_pdbqt(smiles, seed=42)
        path = _write_multimodel_pdbqt([pdbqt])
        try:
            with pytest.raises(ValueError, match="Need at least 2 poses"):
                cluster_poses(path)
        finally:
            os.unlink(path)

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            cluster_poses("/nonexistent/file.pdbqt")

    def test_output_dir_writes_files(self):
        """When output_dir is set, representative PDBQTs are written."""
        smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"
        pdbqt = _make_pose_pdbqt(smiles, seed=42)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = _write_multimodel_pdbqt([pdbqt, pdbqt])
            clusters = cluster_poses(path, n_clusters=2, output_dir=tmpdir)
            # At least cluster_0_representative.pdbqt should exist
            rep_path = os.path.join(tmpdir, 'cluster_0_representative.pdbqt')
            assert os.path.exists(rep_path), f"Expected {rep_path}"
            os.unlink(path)


class TestClusterPosesNClusters:
    def test_n_clusters_respected(self):
        smiles = "CC(=O)OC1=CC=CC=C1C(=O)O"
        poses = [_make_pose_pdbqt(smiles, seed=42+i) for i in range(10)]
        path = _write_multimodel_pdbqt(poses)
        try:
            clusters = cluster_poses(path, n_clusters=3)
            assert len(clusters) == 3
            total = sum(c['n_poses'] for c in clusters)
            assert total == 10
        finally:
            os.unlink(path)
