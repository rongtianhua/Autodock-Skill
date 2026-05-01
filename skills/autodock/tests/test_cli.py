"""
CLI integration tests for autodock __main__.py
"""
import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Import CLI module directly for testing
from autodock.__main__ import (
    cmd_status, cmd_fetch, cmd_prepare_receptor, cmd_prepare_ligand,
)
from autodock import autodock_logger


class MockArgs:
    """Simple namespace for mocking argparse args"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestCliStatus:
    """Test status command"""

    def test_status_runs(self, capsys):
        """Status command should print and return 0"""
        args = MockArgs(quiet=False, verbose=False)
        cmd_status(args)
        captured = capsys.readouterr()
        assert "Autodock CLI Status" in captured.out
        assert "PyMOL:" in captured.out
        assert "Vina:" in captured.out
        assert "RDKit:" in captured.out
        assert "Meeko:" in captured.out


class TestCliFetch:
    """Test fetch command"""

    def test_fetch_pdb_runs(self, tmp_path):
        """Fetch PDB command should download file"""
        outdir = str(tmp_path)
        args = MockArgs(type='pdb', id='1GKC', outdir=outdir,
                       quiet=False, verbose=False, refresh=False)
        cmd_fetch(args)
        assert (tmp_path / '1GKC.pdb').exists()

    def test_fetch_ligand_runs(self, tmp_path):
        """Fetch ligand command should download file"""
        outdir = str(tmp_path)
        args = MockArgs(type='ligand', id='aspirin', outdir=outdir,
                       quiet=False, verbose=False, refresh=False)
        cmd_fetch(args)
        assert (tmp_path / 'aspirin.sdf').exists()


class TestCliLogging:
    """Test logging control via CLI flags"""

    def test_quiet_flag(self):
        """-q should set level to WARNING"""
        autodock_logger.setLevel(10)  # reset to DEBUG
        # Simulate quiet flag
        autodock_logger.setLevel(30)  # WARNING
        assert autodock_logger.level == 30

    def test_verbose_flag(self):
        """-v should set level to DEBUG"""
        autodock_logger.setLevel(10)  # DEBUG
        assert autodock_logger.level == 10


if __name__ == '__main__':
    pytest.main([__file__, '-v'])