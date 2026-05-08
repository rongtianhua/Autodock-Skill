"""
Tests for autodock MD Validation Module.
"""
import pytest

from autodock._md_validation import (
    validate_pose_stability,
    _extract_ligand_from_pdbqt,
)
from autodock._core import ValidationError


class TestMDValidation:
    def test_validate_nonexistent_receptor_raises(self):
        """Test that missing receptor raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_pose_stability("/nonexistent.pdb", "/dummy.pdbqt")

    def test_validate_nonexistent_ligand_raises(self):
        """Test that missing ligand raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_pose_stability("/dummy.pdb", "/nonexistent.pdbqt")

    def test_unknown_protocol_raises(self):
        """Test that unknown protocol raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_pose_stability(
                receptor_pdb="/dummy.pdb",
                ligand_pdbqt="/dummy.pdbqt",
                protocol="invalid",
            )

    def test_extract_ligand_from_nonexistent_pdbqt(self):
        """Test that missing PDBQT raises."""
        with pytest.raises(Exception):
            _extract_ligand_from_pdbqt("/nonexistent.pdbqt")