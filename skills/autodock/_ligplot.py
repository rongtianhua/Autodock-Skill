"""
Autodock LigPlot Module
=======================
LigPlot+ integration: parse .drw files and render 2D interaction diagrams.
"""
import os
import re
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from autodock._core import autodock_logger, _HAVE_RDKIT

# Backward-compat logger alias
logger = autodock_logger
from rdkit import Chem
from rdkit.Chem import AllChem, Draw
from rdkit.Chem.Draw import rdMolDraw2D

def parse_ligplot_drw(drw_path: str) -> dict:
    """
    Parse LIGPLOT .drw file and return structured data.

    Returns:
        dict with keys: colors, color_map, sizes, atoms, bonds, residue, title
    """
    data = {
        'colors': {},      # idx -> (r, g, b, name)
        'color_map': {},   # feature -> color_idx
        'sizes': {},       # name -> value
        'atoms': [],       # {idx, name, x2d, y2d, x3d, y3d, z3d, charge}
        'bonds': [],       # {style, a1, a2}
        'residue': None,   # (resn, resi, chain, x, y)
        'title': None,     # (text, x, y)
    }

    section = None
    for line in open(drw_path):
        ls = line.strip()
        if ls.startswith('#'):
            section = ls[1:].strip()
            continue

        if section == 'M':
            parts = ls.split()
            if len(parts) >= 5:
                idx = int(parts[0])
                r, g, b = float(parts[1]), float(parts[2]), float(parts[3])
                name = ' '.join(parts[4:])
                data['colors'][idx] = (r, g, b, name)

        elif section == 'C':
            parts = ls.split(None, 3)
            if len(parts) >= 4:
                data['color_map'][parts[3]] = int(parts[0])

        elif section == 'S':
            parts = ls.split(None, 1)
            if len(parts) >= 2:
                try:
                    data['sizes'][parts[1]] = float(parts[0])
                except ValueError:
                    pass

        elif section == 'R':
            parts = ls.split()
            if len(parts) >= 5:
                data['residue'] = {
                    'resn': parts[0], 'resi': parts[1], 'chain': parts[2],
                    'x': float(parts[3]), 'y': float(parts[4])
                }

        elif section == 'A':
            parts = ls.split()
            if len(parts) >= 4:
                name = parts[0]
                x2d, y2d = float(parts[1]), float(parts[2])
                charge = float(parts[3]) if parts[3] != '#' else 0.0

                x3d = y3d = z3d = 0.0
                if '#' in line:
                    coords3d = line.split('#')[1].strip().split()
                    if len(coords3d) >= 3:
                        x3d, y3d, z3d = float(coords3d[0]), float(coords3d[1]), float(coords3d[2])

                data['atoms'].append({
                    'name': name, 'x2d': x2d, 'y2d': y2d, 'charge': charge,
                    'x3d': x3d, 'y3d': y3d, 'z3d': z3d
                })

        elif section == 'B':
            parts = ls.split()
            if len(parts) >= 3:
                data['bonds'].append({
                    'style': int(parts[0]),
                    'a1': int(parts[1]),
                    'a2': int(parts[2])
                })

        elif section == 'T':
            parts = ls.split(None, 2)
            if len(parts) >= 3:
                data['title'] = {
                    'text': parts[0],
                    'x': float(parts[1]),
                    'y': float(parts[2])
                }

    return data


def render_ligplot_from_drw(drw_path: str, output_png: str, dpi: int = 300,
                      bg_color: tuple[int, int, int] = (255, 255, 255)) -> bool:
    """
    Phase 2: Render ligand 2D structure from LIGPLOT .drw file using PIL.

    Parses the .drw internal format and renders directly, bypassing PostScript.
    Does not include interaction arcs/hydrophobic contacts - only ligand structure.

    Args:
        drw_path: Path to LIGPLOT .drw file
        output_png: Output PNG path
        dpi: Output resolution
        interactions: Optional list of interaction dicts from detect_interactions_plip():
                     [{type, resn, resi, chain, ligand_atom_idx, distance, ...}]
                     If provided, LIGPLOT is skipped for interaction detection (PLIP-driven path).

    Returns:
        True if successful
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.error("[autodock] PIL not available - render_ligplot_from_drw skipped")
        return False

    data = parse_ligplot_drw(drw_path)
    atoms = data['atoms']
    bonds = data['bonds']
    colors = data['colors']

    if not atoms:
        logger.error("[autodock] No atoms in .drw file")
        return False

    # Element color lookup from LIGPLOT palette
    def get_element_color(elem):
        elem_key = f'{elem.capitalize()}ogen_colour'
        if elem_key in data['color_map']:
            cidx = data['color_map'][elem_key]
            return tuple(int(round(c * 255)) for c in colors[cidx][:3])
        # Fallbacks if not in palette
        if elem == 'C': return (128, 128, 128)  # gray
        if elem == 'O': return (255, 0, 0)       # red
        if elem == 'N': return (0, 0, 255)       # blue
        if elem == 'H': return (255, 255, 255)   # white
        if elem == 'S': return (255, 200, 50)    # yellow
        return (0, 0, 0)

    # Bounds calculation
    x_coords = [a['x2d'] for a in atoms]
    y_coords = [a['y2d'] for a in atoms]
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)

    padding = 50
    scale = (dpi / 300) * 100  # Å to pixel scale

    width_px = int((x_max - x_min) * scale) + 2 * padding
    height_px = int((y_max - y_min) * scale) + 2 * padding

    def to_pixel(x, y):
        return (int((x - x_min) * scale + padding),
                int((y - y_min) * scale + padding))

    # Create image with configurable background (default white, publication standard)
    img = Image.new('RGB', (width_px, height_px), bg_color)
    draw = ImageDraw.Draw(img)

    # Draw bonds first (under atoms)
    bond_width = max(2, int(scale * 0.06))
    bond_color = (128, 128, 128)

    for bond in bonds:
        a1 = atoms[bond['a1']]
        a2 = atoms[bond['a2']]
        x1, y1 = to_pixel(a1['x2d'], a1['y2d'])
        x2, y2 = to_pixel(a2['x2d'], a2['y2d'])
        draw.line([(x1, y1), (x2, y2)], fill=bond_color, width=bond_width)

    # Draw atoms (circles)
    atom_radius = max(6, int(scale * 0.25))
    for atom in atoms:
        elem = atom['name'][0]  # First character is element
        color = get_element_color(elem)
        x, y = to_pixel(atom['x2d'], atom['y2d'])
        draw.ellipse([x - atom_radius, y - atom_radius,
                      x + atom_radius, y + atom_radius],
                     fill=color, outline=(0, 0, 0))

        # Atom label (element symbol)
        try:
            font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',
                                       max(10, int(scale * 0.3)))
        except:
            font = ImageFont.load_default()

        label = atom['name'].strip()
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((x - tw // 2, y - th // 2), label, fill=(0, 0, 0), font=font)

    # Title if present
    if data['title']:
        try:
            title_font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',
                                              max(14, int(scale * 0.4)))
        except:
            title_font = ImageFont.load_default()
        draw.text((padding, height_px - padding - 20), data['title']['text'],
                  fill=(0, 0, 0), font=title_font)

    os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)
    img.save(output_png, dpi=(dpi, dpi))
    logger.info(f"[autodock] DRW→PNG: {output_png} ({os.path.getsize(output_png)//1024}KB)")
    return True


def _get_ligand_smiles(pdbqt_path: str) -> str | None:
    """Extract SMILES from PDBQT REMARK line if present."""
    try:
        for line in open(pdbqt_path):
            if line.startswith('REMARK SMILES '):
                parts = line.strip().split()
                if len(parts) >= 3:
                    return parts[2]
    except Exception:
        pass
    return None


def render_ligplot_2d(receptor_pdb: str,
                      ligand_pdbqt: str,
                      output_png: str,
                      output_pdf: str | None = None,
                      output_drw: str | None = None,
                      dpi: int = 300,
                      interactions: list | None = None,
                      bg_color: tuple[int, int, int] = (255, 255, 255)) -> bool:
    """
    Hybrid protein-ligand 2D diagram: RDKit for structure + PIL for arcs.

    Pipeline (hybrid approach):
      1. Build complex PDB and run LIGPLOT to detect interactions + generate .drw
      2. Parse interaction data from LIGPLOT .drw/.hhb/.nnb files
      3. Render ligand 2D structure using RDKit (proper bond orders from SMILES)
      4. Composite: overlay interaction arcs + residue labels on RDKit structure

    This produces publication-quality output that LIGPLOT's native PostScript
    cannot match for small-molecule structure rendering.

    Args:
        receptor_pdb: Crystal protein PDB path (must have valid CONECT records)
        ligand_pdbqt: Docked ligand PDBQT path
        output_png: Output PNG path
        output_pdf: Optional PDF output (via cairosvg)
        output_drw: Optional path to save LIGPLOT .drw file
        dpi: Output resolution
        bg_color: RGB tuple for background color (default white, publication standard)

    Returns:
        True if successful
    """
    if not HAVE_LIGPLOT:
        logger.error(f"[autodock] LIGPLOT binary not found at {LIGPLOT_BIN}")
        return False

    if not _HAVE_RDKIT:
        logger.error("[autodock] RDKit required for ligand 2D rendering")
        return False

    import tempfile, shutil, subprocess
    from PIL import Image, ImageDraw, ImageFont
    from rdkit import Chem
    from rdkit.Chem import rdDepictor
    from rdkit import RDLogger
    RDLogger.DisableLog('rdApp.*')

    tmpdir = tempfile.mkdtemp(prefix='ligplot_hybrid_')
    try:
        # ── Step 1: Build complex PDB for LIGPLOT ──────────────────
        # Filter receptor: keep ATOM records + standard-residue HETATMs only.
        # LIGPLOT treats any HETATM with non-standard residue as a ligand candidate.
        # Exclude: HOH (water), PJE/02J/010 (crystal ligands), metal ions, etc.
        STANDARD_AAS = {
            'ALA','ARG','ASN','ASP','CYS','GLN','GLU','GLY','HIS','ILE',
            'LEU','LYS','MET','PHE','PRO','SER','THR','TRP','TYR','VAL',
            'MSE','SEC','PYL','UNK',
        }
        rec_atoms, rec_conect = [], []
        serial_map = {}
        for line in open(receptor_pdb):
            if line.startswith('ATOM'):
                rec_atoms.append(line.rstrip())
            elif line.startswith('HETATM'):
                resn = line[17:20].strip()
                if resn in STANDARD_AAS:
                    rec_atoms.append(line.rstrip())
                # else: skip non-standard HETATM (water, metals, crystal ligands)
            elif line.startswith('CONECT'):
                rec_conect.append(line.rstrip())

        ns = 1
        for line in rec_atoms:
            serial_map[int(line[6:11])] = ns; ns += 1
        n_rec = len(rec_atoms)
        lig_offset = n_rec

        # Parse ligand from PDBQT via RDKit
        pdbqt_raw = open(ligand_pdbqt).read()
        lig_mol = Chem.MolFromPDBBlock(pdbqt_raw, flavor=0)
        if lig_mol is None:
            logger.error(f"[autodock] Cannot parse ligand PDBQT: {ligand_pdbqt}")
            return False

        lig_mol_noh = Chem.RemoveHs(lig_mol)
        lig_pdb_block = Chem.MolToPDBBlock(lig_mol_noh)
        lig_atoms = []
        for line in lig_pdb_block.split('\n'):
            if line.startswith('ATOM'):
                elem = line[76:78].strip() or 'C'
                aname = line[12:16].strip()
                x = float(line[30:38]); y = float(line[38:46]); z = float(line[46:54])
                lig_atoms.append({'elem': elem, 'aname': aname, 'x': x, 'y': y, 'z': z})

        # LIGPLOT 配体识别需要特定的残基名格式。
        # 根据 LIGPLOT 文档，配体必须是 HETATM 且使用非标准残基名。
        # UNL 是通用非标准残基名，应该被识别。但 LIGPLOT 可能需要
        # 特定的原子命名或 CONECT 记录。
        
        # 添加 CONECT 记录以帮助 LIGPLOT 识别配体结构
        lig_conect = []
        if lig_mol is not None and lig_mol.GetNumBonds() > 0:
            for bond in lig_mol.GetBonds():
                i = bond.GetBeginAtomIdx()
                j = bond.GetEndAtomIdx()
                # PDB 序号从 1 开始，加上配体偏移
                lig_conect.append((lig_offset + i + 1, lig_offset + j + 1))
        
        # Write complex PDB with CONECT records for ligand
        complex_pdb = os.path.join(tmpdir, 'complex.pdb')
        with open(complex_pdb, 'w') as f:
            f.write('TITLE    Complex: receptor + ligand\n')
            for line in rec_atoms:
                old_s = int(line[6:11])
                f.write(f'{line[:6]}{serial_map[old_s]:5d}{line[11:]}\n')
            for i, info in enumerate(lig_atoms):
                fs = lig_offset + i + 1
                aname5 = f"{info['aname']:<5}"
                f.write('HETATM%5d %-5sUNL L%4s    %8.3f%8.3f%8.3f  1.00  0.00          %2s\n'
                        % (fs, aname5, '1', info['x'], info['y'], info['z'], info['elem']))
            # 添加配体的 CONECT 记录
            for a1, a2 in lig_conect:
                f.write(f'CONECT{a1:5d}{a2:5d}\n')
            for line in rec_conect:
                parts = line.split()
                if len(parts) < 2: continue
                new_sers = [serial_map[int(s)] for s in parts[1:] if int(s) in serial_map]
                if new_sers:
                    f.write('CONECT' + ''.join('%5d' % s for s in new_sers) + '\n')
            f.write('END\n')

        shutil.copy(LIGPLOT_PRM, os.path.join(tmpdir, 'ligplot.prm'))

        # ── Step 2: Run LIGPLOT for interaction detection ─────────
        ligplot_interactions = []
        if interactions is None:
            # PLIP not provided: use LIGPLOT for detection (legacy path)
            orig_dir = os.getcwd()
            os.chdir(tmpdir)
            result = subprocess.run(
                [LIGPLOT_BIN, os.path.abspath(complex_pdb), '1', '1', 'L', '-pl'],
                capture_output=True, text=True, timeout=120
            )
            os.chdir(orig_dir)
        else:
            # PLIP-driven path: still run LIGPLOT for .drw/.ps output if requested
            if output_drw or output_pdf:
                orig_dir = os.getcwd()
                os.chdir(tmpdir)
                subprocess.run(
                    [LIGPLOT_BIN, os.path.abspath(complex_pdb), '1', '1', 'L', '-pl'],
                    capture_output=True, text=True, timeout=120
                )
                os.chdir(orig_dir)

        # Copy output files (always, regardless of path)
        if output_drw:
            drw_src = os.path.join(tmpdir, 'ligplot.drw')
            if os.path.exists(drw_src):
                os.makedirs(os.path.dirname(output_drw) or '.', exist_ok=True)
                shutil.copy(drw_src, output_drw)

        # Copy output files
        if output_drw:
            drw_src = os.path.join(tmpdir, 'ligplot.drw')
            if os.path.exists(drw_src):
                os.makedirs(os.path.dirname(output_drw) or '.', exist_ok=True)
                shutil.copy(drw_src, output_drw)

        if output_pdf:
            ps_src = os.path.join(tmpdir, 'ligplot.ps')
            if os.path.exists(ps_src):
                os.makedirs(os.path.dirname(output_pdf) or '.', exist_ok=True)
                shutil.copy(ps_src, output_pdf)

        # ── Step 3: Build RDKit mol with SMILES bond orders ────────
        smiles = _get_ligand_smiles(ligand_pdbqt)
        if smiles:
            mol = Chem.MolFromSmiles(smiles)
            if mol:
                mol = Chem.RemoveHs(mol)
        else:
            # Fallback: use PDBQT coords but no bond order info
            mol = Chem.MolFromPDBBlock(pdbqt_raw, flavor=0)
            if mol:
                mol = Chem.RemoveHs(mol)

        if mol is None:
            logger.error("[autodock] Cannot build RDKit mol")
            return False

        # Get 2D coords (RDKit generates publication-quality 2D)
        rdDepictor.Compute2DCoords(mol)

        # Collect 2D coords for arc mapping
        conf = mol.GetConformer()
        n_atoms = mol.GetNumAtoms()

        # ── Step 4: Map interactions to ligand atom 2D positions ─────
        # Build mapping from RDKit atom index -> 2D position
        rdkit_2d = {}
        for i in range(n_atoms):
            pos = conf.GetAtomPosition(i)
            rdkit_2d[i] = (pos.x, pos.y)

        # Merge interaction sources:
        # - PLIP interactions (if provided) take precedence
        # - LIGPLOT interactions as fallback
        all_interactions = []
        if interactions is not None:
            # First pass: collect all interactions per (p2, arc_type) group
            # so we can assign radial offsets for shared endpoints
            ix_groups = {}  # (p2_tuple, arc_type) -> list of ix dicts
            
            for ix in interactions:
                int_type = ix.get('type', '')
                res_label = f"{ix.get('resn', '')}{ix.get('resi', '')}"
                lig_idx = ix.get('ligand_atom_idx')

                if int_type in ('H-bond', 'hbond'):
                    arc_type = 'hbond'
                elif int_type in ('Hydrophobic', 'hydrophobic', 'pi-stacking',
                                  'π-π stacking', 'π-cation', 'π-cation'):
                    arc_type = 'hydrophobic'
                else:
                    arc_type = 'hydrophobic'

                # For hydrophobic with lig_idx=None: find nearest ligand atom to protein
                if lig_idx is not None:
                    p2 = rdkit_2d.get(lig_idx)
                else:
                    # Hydrophobic: use protein 3D pos -> find nearest ligand atom in 2D
                    prot_x = ix.get('prot_x')
                    prot_y = ix.get('prot_y')
                    prot_z = ix.get('prot_z')
                    if prot_x is not None and prot_y is not None and prot_z is not None:
                        # Find ligand atom closest to protein position (3D proximity proxy)
                        # Use RDKit 3D conformer if available, else use nearest 2D neighbor
                        p2 = None
                        min_dist_3d = float('inf')
                        for i in range(n_atoms):
                            atom_pos = conf.GetAtomPosition(i)
                            d3 = ((atom_pos.x - prot_x)**2 + (atom_pos.y - prot_y)**2 + (atom_pos.z - prot_z)**2) ** 0.5
                            if d3 < min_dist_3d:
                                min_dist_3d = d3
                                p2 = rdkit_2d[i]
                    else:
                        p2 = None

                key = (tuple(p2) if p2 else None, arc_type)
                if key not in ix_groups:
                    ix_groups[key] = []
                ix_groups[key].append({'ix': ix, 'res_label': res_label, 'arc_type': arc_type, 'p2': p2})

            # Second pass: build all_interactions with angular rank
            for (p2, arc_type), group in ix_groups.items():
                n_group = len(group)
                for rank, item in enumerate(group):
                    ix = item['ix']
                    res_label = item['res_label']
                    
                    # Angular offset: spread arcs by ±20° per rank from center direction
                    if n_group > 1:
                        angle_offset = (rank - (n_group - 1) / 2) * 0.35  # radians ~20° per step
                    else:
                        angle_offset = 0

                    all_interactions.append({
                        'type': arc_type,
                        'p1': None,
                        'p2': p2,
                        'res_label': res_label,
                        'distance': ix.get('distance'),
                        '_angle_offset': angle_offset,
                        '_n_group': n_group,
                        '_rank': rank,
                    })
        else:
            # Legacy LIGPLOT path: parse from .hhb/.nnb
            hhb_path = os.path.join(tmpdir, 'ligplot.hhb')
            nnb_path = os.path.join(tmpdir, 'ligplot.nnb')
            all_interactions = []
            all_interactions.extend(_parse_ligplot_hhb(hhb_path, rdkit_2d, n_atoms))
            all_interactions.extend(_parse_ligplot_nnb(nnb_path, rdkit_2d, n_atoms))

        # ── Step 5: Render with PIL (LigPlot+ v4.0 publication-quality) ──
        # High-resolution canvas: 8×6 inches at requested DPI (default 300)
        width = int(dpi * 8)
        height = int(dpi * 6)

        # Get molecular bounds
        xs = [conf.GetAtomPosition(i).x for i in range(n_atoms)]
        ys = [conf.GetAtomPosition(i).y for i in range(n_atoms)]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)

        # Scale to canvas (with margin for labels — 0.8" extend + label + safety)
        scale = min((width - 600) / (x_max - x_min + 1),
                    (height - 600) / (y_max - y_min + 1)) if x_max > x_min else 50
        padding = 350

        canvas_w = max(width, int((x_max - x_min) * scale) + 2 * padding)
        canvas_h = max(height, int((y_max - y_min) * scale) + 2 * padding)

        def to_px(x, y):
            return (int((x - x_min) * scale + padding),
                    int((y - y_min) * scale + padding))

        # Draw base: white background (publication standard)
        img = Image.new('RGB', (canvas_w, canvas_h), bg_color)
        draw = ImageDraw.Draw(img)

        # Element → color
        # LigPlot+ v4.0 official colours
        elem_color = {
            'C': (0, 0, 0),      # BLACK  — Carbon
            'O': (255, 0, 0),        # RED    — Oxygen
            'N': (0, 0, 255),       # BLUE   — Nitrogen
            'S': (255, 255, 0),     # YELLOW — Sulphur
            'P': (128, 0, 255),     # PURPLE — Phosphorus
            'F': (128, 255, 0),       # LIME GREEN — Fluorine (other)
            'Cl': (128, 255, 0),      # LIME GREEN — Chlorine (other)
            'Br': (128, 255, 0),      # LIME GREEN — Bromine (other)
            'I': (128, 255, 0),       # LIME GREEN — Iodine (other)
        }

        # ── Kekulé aromatic bond detection ──
        ring_info = mol.GetRingInfo()
        kekule_double_bonds = set()
        for ring in ring_info.AtomRings():
            if len(ring) == 6 and all(mol.GetAtomWithIdx(a).GetIsAromatic() for a in ring):
                ring_bonds = []
                for i in range(6):
                    a1, a2 = ring[i], ring[(i + 1) % 6]
                    bond = mol.GetBondBetweenAtoms(int(a1), int(a2))
                    if bond:
                        ring_bonds.append((min(int(a1), int(a2)), max(int(a1), int(a2))))
                for idx in [0, 2, 4]:
                    if idx < len(ring_bonds):
                        kekule_double_bonds.add(ring_bonds[idx])

        # ── Draw all bonds ──
        for bond in mol.GetBonds():
            i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            p1 = conf.GetAtomPosition(i)
            p2 = conf.GetAtomPosition(j)
            x1, y1 = to_px(p1.x, p1.y)
            x2, y2 = to_px(p2.x, p2.y)
            w = max(1, int(scale * 0.04))  # LigPlot+ 0.19 Å (ligand bonds)
            color = (0, 0, 0)  # LigPlot+ ligand bonds: BLACK (closest to PURPLE for C-based)
            
            if bond.GetIsAromatic():
                key = (min(i, j), max(i, j))
                if key in kekule_double_bonds:
                    dx, dy = x2 - x1, y2 - y1
                    length = (dx**2 + dy**2) ** 0.5
                    if length > 0:
                        offset = max(6.0, length * 0.03)
                        ox = -dy / length * offset
                        oy = dx / length * offset
                        draw.line([(x1 + ox, y1 + oy), (x2 + ox, y2 + oy)], fill=color, width=max(2, w))
                        draw.line([(x1 - ox, y1 - oy), (x2 - ox, y2 - oy)], fill=color, width=max(2, w))
                    else:
                        draw.line([(x1, y1), (x2, y2)], fill=color, width=max(2, w))
                else:
                    draw.line([(x1, y1), (x2, y2)], fill=color, width=max(2, w))
            else:
                bond_type = bond.GetBondType()
                if bond_type == Chem.BondType.DOUBLE or bond_type == Chem.BondType.TRIPLE:
                    draw.line([(x1, y1), (x2, y2)], fill=color, width=max(2, w))
                    dx, dy = x2 - x1, y2 - y1
                    length = (dx**2 + dy**2) ** 0.5
                    if length > 0:
                        offset = max(6.0, length * 0.03)
                        ox = -dy / length * offset
                        oy = dx / length * offset
                        draw.line([(x1 + ox, y1 + oy), (x2 + ox, y2 + oy)], fill=color, width=max(2, w))
                        draw.line([(x1 - ox, y1 - oy), (x2 - ox, y2 - oy)], fill=color, width=max(2, w))
                    else:
                        draw.line([(x1, y1), (x2, y2)], fill=color, width=max(2, w))
                else:
                    draw.line([(x1, y1), (x2, y2)], fill=color, width=max(2, w))

        # Draw atoms (with circles and labels)
        atom_radius = max(8, int(scale * 0.22))  # LigPlot+ 0.33 Å (relative to bond length)
        for i in range(n_atoms):
            atom = mol.GetAtomWithIdx(i)
            elem = atom.GetSymbol()
            pos = conf.GetAtomPosition(i)
            x, y = to_px(pos.x, pos.y)
            color = elem_color.get(elem, (100, 100, 100))

            # Circle fill
            draw.ellipse([x - atom_radius, y - atom_radius,
                          x + atom_radius, y + atom_radius],
                         fill=color, outline=(0, 0, 0), width=2)

            # Label
            try:
                # LigPlot+ TEXT SIZES: atom names = 0.31 Å
                font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',
                                           max(7, int(scale * 0.20)))
            except:
                font = ImageFont.load_default()
            label = elem
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((x - tw // 2, y - th // 2), label, fill=bg_color, font=font)

        # Draw interaction arcs
        # LigPlot+ COLOURS: H-bonds = OLIVE GREEN, Hydrophobic = BRICK RED
        arc_color_hbond = (26, 128, 0)
        arc_color_hydro = (204, 0, 0)

        for interaction in all_interactions:
            arc_type = interaction.get('type')
            color = arc_color_hbond if arc_type == 'hbond' else arc_color_hydro

            p1 = interaction.get('p1')
            p2 = interaction.get('p2')
            res_label = interaction.get('res_label', '')
            angle_offset = interaction.get('_angle_offset', 0)

            if p2 is not None:
                x2, y2 = to_px(*p2)

                if p1 is not None:
                    x1, y1 = to_px(*p1)
                    _draw_dashed_line(draw, (x1, y1), (x2, y2), fill=color, width=max(1, int(scale*0.025)))  # LigPlot+ non-bonded contact thickness
                    mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2
                else:
                    # PLIP-driven: draw arc from ligand atom outward
                    import math
                    dx_main = x2 - canvas_w // 2
                    dy_main = y2 - canvas_h // 2
                    dist_main = (dx_main**2 + dy_main**2) ** 0.5
                    
                    n_group = interaction.get('_n_group', 1)
                    angle_offset = interaction.get('_angle_offset', 0)
                    extend = int(dpi * 0.8)  # Long extension
                    start_gap = atom_radius + 20
                    
                    if dist_main > 0:
                        base_angle = math.atan2(dy_main, dx_main)
                        rotated_angle = base_angle + angle_offset
                        
                        x_out = int(x2 + math.cos(rotated_angle) * extend)
                        y_out = int(y2 + math.sin(rotated_angle) * extend)
                        x_start = int(x2 + math.cos(rotated_angle) * start_gap)
                        y_start = int(y2 + math.sin(rotated_angle) * start_gap)
                        
                        mid_x, mid_y = x_out, y_out
                    else:
                        x_out, y_out = x2 + extend, y2
                        x_start, y_start = x2 + start_gap, y2
                        mid_x, mid_y = x_out, y_out
                    
                    _draw_dashed_line(draw, (x_start, y_start), (x_out, y_out),
                                     fill=color, width=max(1, int(scale*0.025)))  # LigPlot+ H-bond thickness: 0.07 Å

        # ── Label rendering: energy minimization (LigPlot+ style) ──
        # Prepare label data with dimensions
        label_data = []
        try:
            label_font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',
                                             max(14, int(scale * 0.4)))
        except:
            label_font = ImageFont.load_default()
        
        for idx, interaction in enumerate(all_interactions):
            arc_type = interaction.get('type')
            color = arc_color_hbond if arc_type == 'hbond' else arc_color_hydro
            p1 = interaction.get('p1')
            p2 = interaction.get('p2')
            res_label = interaction.get('res_label', '')
            if not res_label or p2 is None:
                continue
            
            x2, y2 = to_px(*p2)
            if p1 is not None:
                x1, y1 = to_px(*p1)
                mid_x, mid_y = (x1 + x2) // 2, (y1 + y2) // 2
            else:
                dx_main = x2 - canvas_w // 2
                dy_main = y2 - canvas_h // 2
                dist_main = (dx_main**2 + dy_main**2) ** 0.5
                angle_offset = interaction.get('_angle_offset', 0)
                extend = int(dpi * 0.8)
                if dist_main > 0:
                    base_angle = math.atan2(dy_main, dx_main)
                    rotated_angle = base_angle + angle_offset
                    x_out = int(x2 + math.cos(rotated_angle) * extend)
                    y_out = int(y2 + math.sin(rotated_angle) * extend)
                else:
                    x_out, y_out = x2 + extend, y2
                mid_x, mid_y = x_out, y_out
            
            # Measure text size
            bbox = draw.textbbox((0, 0), res_label, font=label_font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            
            label_data.append({
                'text': res_label,
                'color': color,
                'desired_x': mid_x,
                'desired_y': mid_y,
                'width': tw,
                'height': th,
            })
        
        # Prepare atom data
        atom_data = []
        for i in range(n_atoms):
            pos = conf.GetAtomPosition(i)
            x, y = to_px(pos.x, pos.y)
            atom_data.append({
                'x': x,
                'y': y,
                'radius': atom_radius,
            })
        
        # Run energy minimization
        final_positions = _optimize_label_positions(
            label_data, atom_data, canvas_w, canvas_h, n_iter=80
        )
        
        # Draw labels at optimized positions
        for idx, pos in final_positions.items():
            lbl = label_data[idx]
            draw.text(pos, lbl['text'], fill=lbl['color'], font=label_font)

        os.makedirs(os.path.dirname(output_png) or '.', exist_ok=True)
        img.save(output_png, dpi=(dpi, dpi))

        ok = os.path.exists(output_png) and os.path.getsize(output_png) > 1000
        size_kb = os.path.getsize(output_png) // 1024 if ok else 0
        logger.info(f"[autodock] Hybrid LIGPLOT+RDKit render: {'OK' if ok else 'FAILED'} ({size_kb}KB)")
        return ok

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _optimize_label_positions(labels, atoms, canvas_w, canvas_h, n_iter=80):
    """LigPlot+-style energy minimization for label placement.
    
    Simulates the minimization algorithm from ligplot.prm:
      - Anchor spring: pulls label toward desired (virtual line endpoint)
      - Label-label repulsion: soft-core, like atom-atom clash
      - Label-atom repulsion: hard-core, like bond-atom clash
      - Boundary penalty: keeps labels inside canvas
    
    Args:
        labels: list of dicts with 'desired_x','desired_y','width','height','text','color'
        atoms:  list of dicts with 'x','y','radius'
        canvas_w, canvas_h: canvas dimensions
        n_iter: number of minimization steps (default 80)
    
    Returns:
        dict mapping label_index -> (x, y) final position
    """
    import math
    
    # Initialize at desired positions
    positions = {}
    for i, lbl in enumerate(labels):
        positions[i] = [float(lbl['desired_x']), float(lbl['desired_y'])]
    
    # Pre-compute label dimensions
    dims = {}
    for i, lbl in enumerate(labels):
        dims[i] = (lbl['width'], lbl['height'])
    
    # Minimization loop (gradient descent with decaying step size)
    for step in range(n_iter):
        # Decaying step size: starts at 2.0, ends at 0.1
        step_size = 2.0 * (0.95 ** step)
        
        for i in range(len(labels)):
            x, y = positions[i]
            w, h = dims[i]
            lbl = labels[i]
            
            # Compute gradient (force on this label)
            gx, gy = 0.0, 0.0
            
            # ── Term 1: Anchor spring (keep near desired position) ──
            # Matches ligplot.prm: Weight for anchor-position energy term = 20.0
            k_anchor = 0.8
            gx += k_anchor * (lbl['desired_x'] - x)
            gy += k_anchor * (lbl['desired_y'] - y)
            
            # ── Term 2: Label-label repulsion (soft-core) ──
            # Matches ligplot.prm: Atom-atom clash parameter = 10.00
            k_label = 25.0
            for j in range(len(labels)):
                if j == i:
                    continue
                x2, y2 = positions[j]
                w2, h2 = dims[j]
                
                # Compute overlap in x and y
                # Box i: [x, x+w] × [y, y+h]
                # Box j: [x2, x2+w2] × [y2, y2+h2]
                overlap_x = min(x + w, x2 + w2) - max(x, x2)
                overlap_y = min(y + h, y2 + h2) - max(y, y2)
                
                if overlap_x > 0 and overlap_y > 0:
                    # OVERLAPPING: strong repulsion proportional to overlap
                    # Push in the direction of smaller overlap (least resistance)
                    if overlap_x < overlap_y:
                        # Push horizontally
                        cx = (x + w/2) - (x2 + w2/2)  # center-to-center
                        gx += k_label * (1 if cx > 0 else -1) * max(10, abs(overlap_x) + 5)
                    else:
                        # Push vertically
                        cy = (y + h/2) - (y2 + h2/2)
                        gy += k_label * (1 if cy > 0 else -1) * max(10, abs(overlap_y) + 5)
                else:
                    # NOT overlapping but close: gentle repulsion
                    # Minimum distance between box edges
                    dist_x = max(0, max(x, x2) - min(x + w, x2 + w2))
                    dist_y = max(0, max(y, y2) - min(y + h, y2 + h2))
                    
                    if dist_x < 30 and dist_y < 30:
                        # Close proximity: add small repulsive force
                        cx = (x + w/2) - (x2 + w2/2)
                        cy = (y + h/2) - (y2 + h2/2)
                        dist = math.sqrt(cx**2 + cy**2)
                        if dist > 0 and dist < 80:
                            force = k_label * 0.3 * (80 - dist) / dist
                            gx += cx * force / dist
                            gy += cy * force / dist
            
            # ── Term 3: Label-atom repulsion (hard-core) ──
            # Matches ligplot.prm: Bond-atom clash parameter = 0.20
            # (treat labels like bonds, atoms like atoms)
            k_atom = 40.0
            margin = 8  # pixels clearance
            
            for atom in atoms:
                ax, ay = atom['x'], atom['y']
                ar = atom['radius'] + margin
                
                # Label center
                cx = x + w/2
                cy = y + h/2
                
                # Distance from label center to atom center
                dx_at = cx - ax
                dy_at = cy - ay
                dist = math.sqrt(dx_at**2 + dy_at**2)
                
                # Threshold: label should stay outside atom radius + label half-diagonal
                threshold = ar + max(w, h) * 0.4
                
                if dist < threshold and dist > 0:
                    # Too close: repel
                    force = k_atom * (threshold - dist)
                    gx += dx_at / dist * force
                    gy += dy_at / dist * force
                elif dist == 0:
                    gx += k_atom * 50
                    gy += k_atom * 50
            
            # ── Term 4: Boundary penalty ──
            # Keep labels inside canvas with soft walls
            margin = 5
            if x < margin:
                gx += 10.0
            if x + w > canvas_w - margin:
                gx -= 10.0
            if y < margin:
                gy += 10.0
            if y + h > canvas_h - margin:
                gy -= 10.0
            
            # ── Update position ──
            positions[i][0] += gx * step_size
            positions[i][1] += gy * step_size
            
            # Hard clamp to canvas
            positions[i][0] = max(0, min(canvas_w - w, positions[i][0]))
            positions[i][1] = max(0, min(canvas_h - h, positions[i][1]))
    
    # Return final positions as integers
    return {i: (int(positions[i][0]), int(positions[i][1])) for i in positions}


def _boxes_overlap(a, b, margin=0):
    """Check if two bounding boxes overlap (with optional margin)."""
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or
                a[3] + margin < b[1] or b[3] + margin < a[1])


def _parse_ligplot_hhb(hhb_path: str, rdkit_2d: dict, n_lig_atoms: int) -> list:
    """Parse LIGPLOT .hhb H-bond file. Returns list of interaction dicts.
    
    Args:
        hhb_path: Path to LIGPLOT .hhb file
        rdkit_2d: Dict mapping RDKit atom index -> (x, y) 2D coords
        n_lig_atoms: Number of ligand atoms
    
    Returns:
        List of interaction dicts with keys: type, p1, p2, res_label
        p2 is set to the centroid of all ligand atoms if rdkit_2d is provided,
        otherwise None (rendering will use dummy position fallback).
    """
    interactions = []
    if not os.path.exists(hhb_path) or os.path.getsize(hhb_path) < 100:
        return interactions

    # Compute ligand centroid from rdkit_2d for default p2
    lig_centroid_2d = None
    if rdkit_2d and n_lig_atoms > 0:
        xs = [rdkit_2d[i][0] for i in range(n_lig_atoms) if i in rdkit_2d]
        ys = [rdkit_2d[i][1] for i in range(n_lig_atoms) if i in rdkit_2d]
        if xs and ys:
            lig_centroid_2d = (sum(xs) / len(xs), sum(ys) / len(ys))

    content = open(hhb_path).read()
    lines = content.split('\n')
    
    # Skip header lines (first 2 lines are typically headers)
    data_started = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Detect header end
        if 'Donor' in stripped and 'Acceptor' in stripped:
            data_started = True
            continue
        
        if not data_started:
            continue
            
        # Parse data line: donor_atom  acceptor_atom  distance
        # Example: TYR32.A    UNL1.L       2.85
        parts = stripped.split()
        if len(parts) >= 3:
            try:
                donor = parts[0]
                acceptor = parts[1] if len(parts) > 1 else ''
                distance = float(parts[2]) if len(parts) > 2 else None
                
                # Extract residue label from protein atom (not UNL)
                res_label = ''
                for atom_name in [donor, acceptor]:
                    if atom_name and 'UNL' not in atom_name.upper():
                        # Parse format like TYR32.A -> TYR32
                        res_label = atom_name
                        break
                
                interactions.append({
                    'type': 'hbond',
                    'p1': None,  # Protein position not available from .hhb
                    'p2': lig_centroid_2d,  # Use ligand centroid as fallback
                    'res_label': res_label,
                    'distance': distance,
                })
            except (ValueError, IndexError):
                pass
    return interactions


def _parse_ligplot_nnb(nnb_path: str, rdkit_2d: dict, n_lig_atoms: int) -> list:
    """Parse LIGPLOT .nnb non-bonded contacts file. Returns list of interaction dicts.
    
    Args:
        nnb_path: Path to LIGPLOT .nnb file
        rdkit_2d: Dict mapping RDKit atom index -> (x, y) 2D coords
        n_lig_atoms: Number of ligand atoms
    
    Returns:
        List of interaction dicts with keys: type, p1, p2, res_label
    """
    interactions = []
    if not os.path.exists(nnb_path) or os.path.getsize(nnb_path) < 100:
        return interactions

    # Compute ligand centroid from rdkit_2d for default p2
    lig_centroid_2d = None
    if rdkit_2d and n_lig_atoms > 0:
        xs = [rdkit_2d[i][0] for i in range(n_lig_atoms) if i in rdkit_2d]
        ys = [rdkit_2d[i][1] for i in range(n_lig_atoms) if i in rdkit_2d]
        if xs and ys:
            lig_centroid_2d = (sum(xs) / len(xs), sum(ys) / len(ys))

    content = open(nnb_path).read()
    lines = content.split('\n')
    
    # Skip header lines
    data_started = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        
        # Detect header end
        if 'Atom' in stripped and 'Distance' in stripped:
            data_started = True
            continue
        
        if not data_started:
            continue
            
        # Parse data line: atom1  atom2  distance
        parts = stripped.split()
        if len(parts) >= 3:
            try:
                atom1 = parts[0]
                atom2 = parts[1] if len(parts) > 1 else ''
                distance = float(parts[2]) if len(parts) > 2 else None
                
                # Extract residue label from protein atom (not UNL)
                res_label = ''
                for atom_name in [atom1, atom2]:
                    if atom_name and 'UNL' not in atom_name.upper():
                        res_label = atom_name
                        break
                
                interactions.append({
                    'type': 'hydrophobic',
                    'p1': None,
                    'p2': lig_centroid_2d,
                    'res_label': res_label,
                    'distance': distance,
                })
            except (ValueError, IndexError):
                pass
    return interactions


def _draw_dashed_line(draw, start, end, fill, width):
    """Draw a dashed line using PIL with long visible segments."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = (dx**2 + dy**2) ** 0.5
    if length == 0:
        return
    dash_len = 14   # long visible dash
    gap_len = 6     # shorter gap
    n_dashes = int(length / (dash_len + gap_len))
    for i in range(n_dashes):
        t1 = i * (dash_len + gap_len) / length
        t2 = (i * (dash_len + gap_len) + dash_len) / length
        x1 = int(start[0] + dx * t1)
        y1 = int(start[1] + dy * t1)
        x2 = int(start[0] + dx * t2)
        y2 = int(start[1] + dy * t2)
        draw.line([(x1, y1), (x2, y2)], fill=fill, width=width)



