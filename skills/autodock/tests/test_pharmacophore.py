"""
Tests for autodock Pharmacophore Module.
"""
import pytest
import os

from autodock._pharmacophore import (
    detect_pharmacophore, render_pharmacophore, summarize_features,
    FEAT_DONOR, FEAT_ACCEPTOR, FEAT_HYDROPHOBIC,
    FEAT_AROMATIC, FEAT_POSITIVE, FEAT_NEGATIVE,
    _DONOR_RESIDUES, _ACCEPTOR_RESIDUES,
)
from autodock._core import PreparationError


class TestPharmacophore:
    @pytest.fixture
    def receptor_pdb(self):
        """Return path to test receptor (1COV)."""
        return "/Users/allenrong/.openclaw/workspace/skills/autodock/tests/data/1COV.pdb"

    def test_summarize_features_empty(self):
        """Test summary of empty feature list."""
        result = summarize_features([])
        assert "No pharmacophore features" in result

    def test_summarize_features_nonempty(self):
        """Test summary of feature list."""
        features = [
            {"type": FEAT_DONOR, "center": (1.0, 2.0, 3.0), "atoms": [0],
             "radius": 1.0, "residue": "SER42.A", "description": "OG of SER42"},
            {"type": FEAT_ACCEPTOR, "center": (4.0, 5.0, 6.0), "atoms": [1],
             "radius": 1.0, "residue": "ASP88.A", "description": "OD1 of ASP88"},
        ]
        result = summarize_features(features)
        assert "DONOR" in result
        assert "ACCEPTOR" in result

    def test_detect_with_nonexistent_receptor(self):
        """Test that missing receptor raises error."""
        with pytest.raises(PreparationError):
            detect_pharmacophore("/nonexistent/path.pdb")

    def test_detect_with_ligand_and_center_raises(self):
        """Test that providing both ligand and center raises error."""
        with pytest.raises(PreparationError):
            detect_pharmacophore(
                receptor_pdb="/dummy.pdb",
                ligand_pdbqt="/dummy.pdbqt",
                center=(1.0, 2.0, 3.0),
            )

    def test_detect_with_neither_ligand_nor_center_raises(self):
        """Test that missing center definition raises error."""
        with pytest.raises(PreparationError):
            detect_pharmacophore(receptor_pdb="/dummy.pdb")

    def test_feature_type_constants(self):
        """Test feature type constants are defined."""
        assert FEAT_DONOR == "DONOR"
        assert FEAT_ACCEPTOR == "ACCEPTOR"
        assert FEAT_HYDROPHOBIC == "HYDROPHOBIC"
        assert FEAT_AROMATIC == "AROMATIC"
        assert FEAT_POSITIVE == "POSITIVE"
        assert FEAT_NEGATIVE == "NEGATIVE"

    def test_donor_residues_defined(self):
        """Test donor residue definitions."""
        assert "SER" in _DONOR_RESIDUES
        assert "LYS" in _DONOR_RESIDUES
        assert "ARG" in _DONOR_RESIDUES
        assert _DONOR_RESIDUES["SER"] == ("OG",)

    def test_acceptor_residues_defined(self):
        """Test acceptor residue definitions."""
        assert "ASP" in _ACCEPTOR_RESIDUES
        assert "GLU" in _ACCEPTOR_RESIDUES
        assert "SER" in _ACCEPTOR_RESIDUES
        assert _ACCEPTOR_RESIDUES["ASP"] == ("OD1", "OD2")