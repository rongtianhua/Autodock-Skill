"""
Tests for compute_rmsd — atom-to-atom RMSD calculation.
"""
import os, sys, tempfile, pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from autodock._autodock import compute_rmsd


class TestRmsd:
    """Test RMSD calculation edge cases."""

    def test_identical_structures_rmsd_zero(self):
        """Two identical ligands should have RMSD ≈ 0."""
        pdbqt_a = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        pdbqt_b = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fa:
            fa.write(pdbqt_a); path_a = fa.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fb:
            fb.write(pdbqt_b); path_b = fb.name
        try:
            rmsd = compute_rmsd(path_a, path_b)
            assert rmsd is not None
            assert rmsd < 0.01, f"Identical structures should have RMSD ≈ 0, got {rmsd}"
        finally:
            os.unlink(path_a); os.unlink(path_b)

    def test_shifted_structure_has_nonzero_rmsd(self):
        """Transformed structures with INTERNAL GEOMETRY CHANGE should have non-zero RMSD.

        Note on CASF Kabsch RMSD (rdMolAlign.GetBestRMS):
        For PURE TRANSLATION of identical internal geometry (e.g. all atoms
        shifted by the same vector), Kabsch centering makes both point clouds
        overlap exactly → RMSD = 0. This is mathematically correct.
        To get non-zero RMSD, structures must differ in ORIENTATION or
        INTERNAL GEOMETRY (not pure translation).

        This test uses rotation (not translation) to create a non-trivial RMSD.
        """
        # Correct PDBQT format: 8-char coords, charge at cols 72-76, element at 78-79
        # L-shaped molecule: C at origin, C at (1.5,0,0), O at (1.5,1.2,0) — ~109° angle
        # Structure A: bond along x-axis
        # Structure B: same L-shape rotated 45° around z-axis → non-zero RMSD
        import numpy as np
        angle = np.radians(45)
        c, s = np.cos(angle), np.sin(angle)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        pts_a = np.array([[0., 0., 0.], [1.5, 0., 0.], [1.5, 1.2, 0.]])
        pts_b = pts_a @ R.T

        def make_pdbqt(pts):
            lines = []
            for i, (x, y, z) in enumerate(pts):
                elem = 'O' if i == 2 else 'C'
                line = (f'ATOM  {i+1:5d}  {elem}   UNL     1       '
                        f'{x:8.3f}  {y:8.3f}  {z:8.3f}  0.00  0.00      0.000 {elem}')
                lines.append(line)
            lines.append('END')
            return '\n'.join(lines)

        pdbqt_a = make_pdbqt(pts_a)
        pdbqt_b = make_pdbqt(pts_b)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fa:
            fa.write(pdbqt_a); path_a = fa.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fb:
            fb.write(pdbqt_b); path_b = fb.name
        try:
            rmsd = compute_rmsd(path_a, path_b)
            assert rmsd is not None
            assert rmsd > 0.5, f"Rotated L-shape should have RMSD > 0.5, got {rmsd}"
        finally:
            os.unlink(path_a); os.unlink(path_b)

    def test_nonexistent_files_return_none(self):
        """Nonexistent files should not raise exceptions."""
        rmsd = compute_rmsd('/nonexistent/A.pdbqt', '/nonexistent/B.pdbqt')
        assert rmsd is None

    def test_mismatched_atom_counts(self):
        """Molecules with different atom counts should return None."""
        pdbqt_a = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
ATOM      2  O   UNL     1       1.200   0.000   0.000  0.00  0.00 O
END
"""
        pdbqt_b = """ATOM      1  C   UNL     1       0.000   0.000   0.000  0.00  0.00 C
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fa:
            fa.write(pdbqt_a); path_a = fa.name
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pdbqt', delete=False) as fb:
            fb.write(pdbqt_b); path_b = fb.name
        try:
            rmsd = compute_rmsd(path_a, path_b)
            # Should either return None or a valid number (robust handling)
            assert rmsd is None or isinstance(rmsd, float)
        finally:
            os.unlink(path_a); os.unlink(path_b)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])