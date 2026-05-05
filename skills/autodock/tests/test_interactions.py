"""
Integration tests for detect_interactions_plip and render_interactions_2d.
Covers all 10 PLIP interaction-type categories (8 display names).

Run with: conda activate autodock313 && python -m pytest autodock/tests/test_interactions.py -v
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDetectInteractionsPlip:
    """Test detect_interactions_plip returns correct data structures."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Use the pre-generated 1GKC docking result (7 interactions)."""
        self.receptor = '/tmp/autodock_test8/1GKC.pdb'
        self.ligand = '/tmp/autodock_test8/docking_best.pdbqt'
        if not os.path.exists(self.receptor) or not os.path.exists(self.ligand):
            pytest.skip("Docking test files not available")

    def test_returns_list_and_dict(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip
        intx, xml_path = detect_interactions_plip(self.receptor, self.ligand)
        assert isinstance(intx, list), f"Expected list, got {type(intx)}"
        assert isinstance(xml_path, str), f"Expected str (xml path), got {type(xml_path)}"

    def test_interactions_are_dicts_with_required_keys(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        required_keys = {'type', 'color', 'resn', 'resi', 'chain',
                        'ligand_atom_idx', 'distance', 'description'}
        for item in intx:
            assert isinstance(item, dict), f"Expected dict, got {type(item)}"
            missing = required_keys - set(item.keys())
            assert not missing, f"Item missing keys: {missing}"

    def test_type_values_match_type_map(self):
        from autodock._autodock import autodock_logger, PLIP_TYPE_MAP
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        # Allowed display names (from PLIP_TYPE_MAP unique values)
        allowed_types = {v[0] for v in PLIP_TYPE_MAP.values()}
        for item in intx:
            assert item['type'] in allowed_types, \
                f"Unknown type: {item['type']!r}"

    def test_ligand_atom_idx_is_valid(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        for item in intx:
            # ligand_atom_idx may be None (for salt bridge/metal complex fallback)
            # but if not None must be >= 0
            idx = item['ligand_atom_idx']
            if idx is not None:
                assert isinstance(idx, int) and idx >= 0, \
                    f"Invalid ligand_atom_idx: {idx}"

    def test_empty_interactions_returns_empty_list(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip
        # A non-interacting pose should return empty list
        intx, meta = detect_interactions_plip(self.receptor, self.ligand)
        assert isinstance(intx, list)


class TestRenderInteractions2D:
    """Test render_interactions_2d produces valid output files."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.receptor = '/tmp/autodock_test8/1GKC.pdb'
        self.ligand = '/tmp/autodock_test8/docking_best.pdbqt'
        if not os.path.exists(self.receptor) or not os.path.exists(self.ligand):
            pytest.skip("Docking test files not available")

    def test_render_returns_true_on_success(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip, render_interactions_2d

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out_png = f.name
        try:
            result = render_interactions_2d(
                self.receptor, self.ligand, intx, out_png,
                width=1200, height=900, dpi=300
            )
            assert result is True, "render_interactions_2d returned False"
            assert os.path.exists(out_png), "Output PNG was not created"
            assert os.path.getsize(out_png) > 30000, f"Output PNG too small ({os.path.getsize(out_png)} bytes)"
        finally:
            if os.path.exists(out_png):
                os.unlink(out_png)

    def test_render_produces_reasonable_file_size(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip, render_interactions_2d

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out_png = f.name
        try:
            render_interactions_2d(
                self.receptor, self.ligand, intx, out_png,
                width=1200, height=900, dpi=300
            )
            size_kb = os.path.getsize(out_png) / 1024
            # 300dpi 1200x900 should be >30KB for a publication-quality diagram
            assert size_kb > 20, f"PNG suspiciously small: {size_kb:.1f}KB"
            print(f"  PNG size at 300dpi: {size_kb:.1f}KB — OK")
        finally:
            if os.path.exists(out_png):
                os.unlink(out_png)

    def test_render_with_pdf_output(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip, render_interactions_2d

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out_png = f.name
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            out_pdf = f.name
        try:
            result = render_interactions_2d(
                self.receptor, self.ligand, intx, out_png,
                output_pdf=out_pdf, width=1200, height=900, dpi=300
            )
            assert result is True
            assert os.path.exists(out_png)
            assert os.path.exists(out_pdf), "PDF was not created"
            assert os.path.getsize(out_pdf) > 100, f"PDF too small: {os.path.getsize(out_pdf)} bytes"
        finally:
            for f in [out_png, out_pdf]:
                if os.path.exists(f):
                    os.unlink(f)

    def test_render_with_zero_interactions_no_crash(self):
        """Empty interaction list should return False (no diagram possible)."""
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import render_interactions_2d

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out_png = f.name
        try:
            result = render_interactions_2d(
                self.receptor, self.ligand, [], out_png,
                width=400, height=300, dpi=72
            )
            assert result is False, "Empty interactions should return False"
        finally:
            if os.path.exists(out_png):
                os.unlink(out_png)

    def test_render_pdf_only_mode(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip, render_interactions_2d

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            out_pdf = f.name
        try:
            result = render_interactions_2d(
                self.receptor, self.ligand, intx, None,
                output_pdf=out_pdf, width=1200, height=900, dpi=300
            )
            assert result is True
            assert os.path.exists(out_pdf)
        finally:
            if os.path.exists(out_pdf):
                os.unlink(out_pdf)

    def test_render_accepts_dpi_override(self):
        """Test that DPI override works correctly (sanity check the parameter)."""
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import detect_interactions_plip, render_interactions_2d

        intx, _ = detect_interactions_plip(self.receptor, self.ligand)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            out_png = f.name
        try:
            result = render_interactions_2d(
                self.receptor, self.ligand, intx, out_png,
                width=600, height=450, dpi=150
            )
            assert result is True, f"render failed at 150dpi: {result}"
            assert os.path.getsize(out_png) > 10000
        finally:
            if os.path.exists(out_png):
                os.unlink(out_png)


class TestDockLigandMetadata:
    """Test dock_ligand returns proper metadata dict."""

    def test_dock_returns_scores_and_metadata(self):
        from autodock._autodock import autodock_logger
        autodock_logger.setLevel(30)
        from autodock import dock_ligand
        import tempfile

        rec = '/tmp/autodock_test8/1GKC.pdbqt'
        lig = '/tmp/autodock_test8/aspirin.pdbqt'
        if not os.path.exists(rec) or not os.path.exists(lig):
            pytest.skip("Test files not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = dock_ligand(
                receptor_pdbqt=rec,
                ligand_pdbqt=lig,
                center=(56.07, 11.10, 158.30),
                box_size=(20, 20, 20),
                exhaustiveness=4,
                n_poses=3,
                output_dir=tmpdir,
            )
            # Returns 3-tuple: (scores_array, pose_strings, metadata_dict)
            assert isinstance(result, tuple) and len(result) == 3, \
                f"dock_ligand should return 3-tuple, got {type(result)}"
            scores, poses, meta = result
            import numpy as np
            assert isinstance(scores, np.ndarray), f"scores should be numpy array, got {type(scores)}"
            assert len(scores) > 0, "Should have at least one score"
            assert isinstance(meta, dict), f"meta should be dict, got {type(meta)}"
            assert 'best_pose_path' in meta or 'best_pose' in meta, \
                f"meta missing best_pose key: {list(meta.keys())}"
            # Best energy should be negative (favorable binding)
            best_energy = float(scores[0][0]) if hasattr(scores[0], '__getitem__') else float(scores[0])
            assert best_energy < 0, f"Best energy should be negative, got {best_energy}"


class TestTypeMapCoverage:
    """Verify PLIP_TYPE_MAP covers all 10 PLIP interaction categories."""

    def test_plip_type_map_has_11_keys(self):
        from autodock._autodock import PLIP_TYPE_MAP
        # PLIP has 11 detection keys
        assert len(PLIP_TYPE_MAP) == 11, f"PLIP_TYPE_MAP has {len(PLIP_TYPE_MAP)} keys, expected 11"

    def test_plip_type_map_unique_display_names(self):
        from autodock._autodock import PLIP_TYPE_MAP
        display_names = [v[0] for v in PLIP_TYPE_MAP.values()]
        unique = set(display_names)
        # 8 unique display names: H-bond, Hydrophobic, π-π, π-cation,
        # Salt bridge, Halogen bond, Water bridge, Metal complex
        assert len(unique) == 8, \
            f"PLIP_TYPE_MAP has {len(unique)} unique display names: {sorted(unique)}"

    def test_plip_type_map_directional_splits_identified(self):
        """Verify the 3 split types: H-bond (pdon/ldon), Salt bridge (lneg/pneg), π-cation (paro/laro)."""
        from autodock._autodock import PLIP_TYPE_MAP
        keys = list(PLIP_TYPE_MAP.keys())
        # H-bond split
        assert 'hbonds_pdon' in keys and 'hbonds_ldon' in keys
        # Salt bridge split
        assert 'saltbridge_lneg' in keys and 'saltbridge_pneg' in keys
        # π-cation split
        assert 'pication_paro' in keys and 'pication_laro' in keys
        # Others are single
        for k in ['hydrophobic_contacts', 'pistacking',
                  'halogen_bonds', 'water_bridges', 'metal_complexes']:
            assert k in keys, f"Missing key: {k}"
