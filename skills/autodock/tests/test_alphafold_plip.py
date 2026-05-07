"""
Integration tests for AlphaFold receptor + PLIP interaction detection.
Verifies that predicted structures (without REMARK 800) work with PLIP fallback.

Run with: conda activate autodock313 && python -m pytest autodock/tests/test_alphafold_plip.py -v
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAlphaFoldPlipFallback:
    """Test PLIP interaction detection with AlphaFold-predicted receptors."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Use the pre-generated 1GKC docking result."""
        self.receptor = '/tmp/autodock_test8/1GKC.pdb'
        self.ligand = '/tmp/autodock_test8/docking_best.pdbqt'
        if not os.path.exists(self.receptor) or not os.path.exists(self.ligand):
            pytest.skip("Docking test files not available")

    def test_plip_fallback_returns_list(self):
        """PLIP should return a list even if no interactions are detected."""
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip

        intx, meta = detect_interactions_plip(self.receptor, self.ligand)
        assert isinstance(intx, list), f"Expected list, got {type(intx)}"
        # PLIP may return empty list if no interactions match thresholds
        # but should never crash

    def test_alphafold_source_detection(self):
        """Verify receptor source auto-detection works for AlphaFold headers."""
        from autodock._core import _detect_receptor_source

        # Mock AlphaFold header in temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as f:
            f.write("TITLE  ALPHAFOLD MODEL\n")
            f.write("ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00           N\n")
            f.flush()
            path = f.name
        try:
            source = _detect_receptor_source(path)
            assert source == 'AlphaFold', f"Expected AlphaFold, got {source}"
        finally:
            os.unlink(path)

    def test_pdb_source_detection(self):
        """Verify receptor source auto-detection works for X-ray PDB headers."""
        from autodock._core import _detect_receptor_source

        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as f:
            f.write("EXPDTA  X-RAY DIFFRACTION\n")
            f.write("ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00           N\n")
            f.flush()
            path = f.name
        try:
            source = _detect_receptor_source(path)
            assert source == 'PDB', f"Expected PDB, got {source}"
        finally:
            os.unlink(path)

    def test_swissmodel_source_detection(self):
        """Verify receptor source auto-detection works for SWISS-MODEL headers."""
        from autodock._core import _detect_receptor_source

        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdb', delete=False) as f:
            f.write("EXPDTA  THEORETICAL MODEL\n")
            f.write("ATOM      1  N   ALA     1       0.000   0.000   0.000  1.00  0.00           N\n")
            f.flush()
            path = f.name
        try:
            source = _detect_receptor_source(path)
            assert source == 'SWISS-MODEL', f"Expected SWISS-MODEL, got {source}"
        finally:
            os.unlink(path)


class TestRenderSceneSmoke:
    """Smoke tests for render_scene 3D rendering (requires PyMOL)."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.receptor = '/tmp/autodock_test8/1GKC.pdb'
        self.ligand = '/tmp/autodock_test8/docking_best.pdbqt'
        if not os.path.exists(self.receptor) or not os.path.exists(self.ligand):
            pytest.skip("Test files not available")
        from autodock._core import _HAVE_PYMOL
        if not _HAVE_PYMOL:
            pytest.skip("PyMOL not available")

    def test_render_scene_complex(self):
        """render_scene with scene='complex' should produce a PNG."""
        from autodock import render_scene
        import tempfile

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out = f.name
        try:
            result = render_scene(
                self.receptor, out,
                scene='complex',
                ligand_pdbqt=self.ligand,
                width=800, height=600, dpi=150,
            )
            assert result is True, f"render_scene returned {result}"
            assert os.path.exists(out), "Output PNG not created"
            assert os.path.getsize(out) > 1000, f"PNG too small: {os.path.getsize(out)} bytes"
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_render_scene_pocket(self):
        """render_scene with scene='pocket' should produce a PNG."""
        from autodock import render_scene, find_binding_site
        import tempfile

        center, box_size = find_binding_site(self.receptor)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out = f.name
        try:
            result = render_scene(
                self.receptor, out,
                scene='pocket',
                center=center,
                ligand_pdbqt=self.ligand,
                width=800, height=600, dpi=150,
            )
            assert result is True
            assert os.path.exists(out)
            assert os.path.getsize(out) > 1000
        finally:
            if os.path.exists(out):
                os.unlink(out)

    def test_render_interactions_pymol(self):
        """render_interactions_pymol should produce a PNG with interactions."""
        from autodock import detect_interactions_plip, render_interactions_pymol, find_binding_site
        import tempfile

        center, box_size = find_binding_site(self.receptor)
        intx, _ = detect_interactions_plip(self.receptor, self.ligand)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out = f.name
        try:
            result = render_interactions_pymol(
                self.receptor, self.ligand, intx, out, center,
                distance=5.0, dash_preset='fine', dpi=150,
            )
            assert result is True
            assert os.path.exists(out)
            assert os.path.getsize(out) > 1000
        finally:
            if os.path.exists(out):
                os.unlink(out)
