#!/usr/bin/env python3
"""
Autodock CLI — Molecular Docking Command Line Interface

Usage:
    python -m autodock status
    python -m autodock run --receptor 6LU7 --ligand aspirin
    python -m autodock fetch pdb 6LU7
    python -m autodock fetch ligand aspirin
    python -m autodock prepare-receptor 6LU7.pdb out.pdbqt
    python -m autodock prepare-ligand aspirin out.pdbqt
    python -m autodock find-site receptor.pdb
    python -m autodock dock rec.pdbqt lig.pdbqt --center 0 0 0 --box-size 20 20 20
    python -m autodock detect-interactions rec.pdb lig.pdbqt poses.pdbqt
    python -m autodock render-2d rec.pdb lig.pdbqt intx.pkl output.png
    python -m autodock render-pymol rec.pdb lig.pdbqt output.png
    python -m autodock virtual-screen rec.pdbqt library.csv out.csv
    python -m autodock validate rec.pdbqt crystal_lig.pdbqt

Environment: conda activate autodock313
"""
import os
import sys
import argparse
import logging
from pathlib import Path

# Add parent directory to path for autodock import
# __file__ is skills/autodock/__main__.py, so parent.parent = skills/
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodock import (
    fetch_protein_pdb,
    fetch_molecule_pubchem,
    prepare_receptor,
    prepare_ligand,
    prepare_ligand_conformers,
    find_binding_site,
    find_top_pockets,
    dock_ligand,
    dock_ligand_multi,
    dock_ligand_multi_conformer,
    virtual_screen,
    compute_rmsd,
    compute_clash_score,
    validate_docking_protocol,
    detect_interactions,
    detect_interactions_plip,
    render_interactions_2d,
    render_scene,
    render_pocket,
    render_interactions_pymol,
    render_ligand_2d,
    composite_summary,
    autodock_logger,
    clear_cache,
    get_cache_info,
)


def cmd_status(args):
    """Check environment and dependencies"""
    from autodock._autodock import _HAVE_PYMOL, _HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO

    print("=" * 50)
    print("🧬 Autodock CLI Status")
    print("=" * 50)
    print(f"  PyMOL:      {'✅ OK' if _HAVE_PYMOL else '❌ MISSING'}")
    print(f"  Vina:       {'✅ OK' if _HAVE_VINA else '❌ MISSING'}")
    print(f"  RDKit:      {'✅ OK' if _HAVE_RDKIT else '❌ MISSING'}")
    print(f"  Meeko:      {'✅ OK' if _HAVE_MEEKO else '❌ MISSING'}")
    print("=" * 50)

    if all([_HAVE_PYMOL, _HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO]):
        print("✅ All dependencies available — ready for docking!")
    else:
        print("⚠️  Some dependencies missing — run: conda activate autodock313")
        sys.exit(1)


def cmd_cache(args):
    """Show or clear the structure cache"""
    if args.clear:
        result = clear_cache(confirm=False)
        print(f"✅ Cleared {len(result['cleared'])} files, freed {result['size_mb']:.1f} MB")
    else:
        info = get_cache_info()
        print(f"📦 Cache: {info['n_files']} files, {info['size_mb']:.1f} MB")
        print(f"   Location: {info['cache_dir']}")
        for fname, size_kb in info['files']:
            print(f"   - {fname} ({size_kb:.0f} KB)")


def cmd_fetch(args):
    """Fetch protein or molecule structures"""
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    if args.type == 'pdb':
        output_path = str(outdir / f"{args.id}.pdb")
        path = fetch_protein_pdb(args.id, output_path,
                                 force_refresh=args.refresh)
        print(f"✅ Protein saved: {path}")
    elif args.type == 'ligand':
        output_sdf = str(outdir / f"{args.id}.sdf")
        result = fetch_molecule_pubchem(args.id, output_sdf=output_sdf,
                                        force_refresh=args.refresh)
        print(f"✅ Molecule saved: {result['sdf_path']}")
        print(f"   SMILES: {result['smiles']}")
        print(f"   Cached:  {result['cached']}")


def cmd_prepare_receptor(args):
    """Prepare receptor PDB → PDBQT"""
    out = args.output or args.pdb.replace('.pdb', '.pdbqt')
    prepare_receptor(args.pdb, out, remove_waters=not args.keep_waters)
    print(f"✅ Receptor prepared: {out}")


def cmd_prepare_ligand(args):
    """Prepare ligand SMILES → PDBQT"""
    out = args.output or f"{args.smiles[:10]}.pdbqt"
    prepare_ligand(args.smiles, out, name=args.name)
    print(f"✅ Ligand prepared: {out}")


def cmd_prepare_conformers(args):
    """Generate multiple 3D conformers of a ligand."""
    paths = prepare_ligand_conformers(
        smiles=args.smiles,
        output_dir=args.output_dir,
        n_conformers=args.n,
        name=args.name,
    )
    print(f"✅ Generated {len(paths)} conformers in {args.output_dir}")
    for p in paths:
        print(f"   {p}")


def cmd_find_site(args):
    """Detect binding site (fpocket + P2Rank)"""
    center, box_size = find_binding_site(args.receptor, args.ligand)
    print(f"✅ Binding site detected:")
    print(f"   center:   {center}")
    print(f"   box_size: {box_size}")


def cmd_dock(args):
    """Run molecular docking"""
    center = tuple(args.center)
    box_size = tuple(args.box_size)

    energies, poses, meta = dock_ligand(
        args.receptor,
        args.ligand,
        center=center,
        box_size=box_size,
        exhaustiveness=args.exhaustiveness,
        n_poses=args.n_poses,
        output_dir=os.path.dirname(args.receptor) or '.',
    )

    print(f"✅ Docking complete:")
    print(f"   Best energy: {energies[0][0]:.2f} kcal/mol")
    print(f"   Best pose:   {meta.get('best_pose_path', 'N/A')}")


def cmd_dock_multi_conformer(args):
    """Dock multiple ligand conformers (publication-standard)."""
    import glob, os
    # Collect conformer PDBQTs from directory
    conformer_files = sorted(glob.glob(
        os.path.join(args.conformers_dir, 'conformer_*.pdbqt')))
    if not conformer_files:
        print(f"❌ No conformer_*.pdbqt files found in {args.conformers_dir}")
        sys.exit(1)
    print(f"[autodock] Found {len(conformer_files)} conformer files")

    # Detect binding site (requires receptor PDB)
    if args.receptor_pdb:
        center, box_size = find_binding_site(args.receptor_pdb)
    else:
        # Ligand-centered: use first conformer to estimate
        from autodock._autodock import _read_ligand_from_pdbqt_3d
        lig = _read_ligand_from_pdbqt_3d(conformer_files[0])
        if lig:
            from autodock._autodock import _compute_box_size
            conf = lig.GetConformer()
            xs = [conf.GetAtomPosition(i).x for i in range(lig.GetNumAtoms())]
            ys = [conf.GetAtomPosition(i).y for i in range(lig.GetNumAtoms())]
            zs = [conf.GetAtomPosition(i).z for i in range(lig.GetNumAtoms())]
            cx, cy, cz = sum(xs)/len(xs), sum(ys)/len(ys), sum(zs)/len(zs)
            box_size = _compute_box_size(
                (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs)), padding=10.0)
            center = (cx, cy, cz)
        else:
            print("❌ Cannot determine center without receptor PDB")
            sys.exit(1)

    result = dock_ligand_multi_conformer(
        receptor_pdbqt=args.receptor_pdbqt,
        conformer_pdbqts=conformer_files,
        receptor_pdb=args.receptor_pdb,
        exhaustiveness=args.exhaustiveness,
        n_poses=args.n_poses,
    )

    print(f"✅ Multi-conformer docking complete:")
    print(f"   Conformers docked: {result['n_conformers']}/{len(conformer_files)}")
    print(f"   Total poses:       {len(result['all_poses'])}")
    print(f"   Best energy:       {result['best_energy']:.2f} kcal/mol")
    print(f"   Best pose:          {result['best_pose_path']}")


def cmd_detect_interactions(args):
    """Detect protein-ligand interactions"""
    interactions = detect_interactions_plip(
        args.receptor,
        args.ligand,
        args.poses,
    )
    print(f"✅ Interactions detected:")
    for itype, count in interactions.items():
        if isinstance(count, int):
            print(f"   {itype}: {count}")


def cmd_render_2d(args):
    """Render 2D interaction diagram"""
    render_interactions_2d(
        args.receptor,
        args.ligand,
        args.poses,
        args.output,
    )
    print(f"✅ 2D diagram saved: {args.output}")


def cmd_render_pymol(args):
    """Render 3D scene with PyMOL"""
    render_scene(
        args.receptor,
        args.ligand,
        args.poses,
        output=args.output,
    )
    print(f"✅ 3D scene saved: {args.output}")


def cmd_virtual_screen(args):
    """Virtual screen a library of compounds"""
    center = tuple(args.center)
    box_size = tuple(args.box_size)

    results, _ = virtual_screen(
        args.receptor,
        args.library,
        center=center,
        box_size=box_size,
        output_dir=str(Path(args.output).parent) if args.output else './docking_results',
    )
    print(f"✅ Virtual screen complete: {len(results)} compounds scored")
    print(f"   Results saved: {args.output}")


def cmd_validate(args):
    """Validate docking protocol (redocking)"""
    center, box_size = find_binding_site(args.receptor, args.crystal_ligand)

    result = validate_docking_protocol(
        args.receptor,
        args.crystal_ligand,
        center=center,
        box_size=box_size,
    )

    print(f"✅ Validation complete:")
    print(f"   RMSD:      {result['rmsd_atom']:.2f} Å")
    print(f"   Best energy: {result['best_affinity']:.2f} kcal/mol")
    passed = result['is_valid']
    print(f"   Result:    {'✅ PASSED' if passed else '⚠️  FAILED'} (threshold: {result['threshold']} Å)")


def cmd_run(args):
    """Full end-to-end workflow: fetch → prepare → dock → visualize"""
    outdir = Path(args.outdir or "./docking_results")
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch
    print("\n" + "="*50)
    print("📥 Step 1: Fetching structures")
    print("="*50)

    receptor_file = fetch_protein_pdb(args.receptor, str(outdir / f"{args.receptor}.pdb"))
    ligand_result = fetch_molecule_pubchem(args.ligand, output_sdf=str(outdir / f"{args.ligand}.sdf"))
    ligand_file = ligand_result['sdf_path']
    ligand_smiles = ligand_result['smiles']

    # 2. Prepare
    print("\n" + "="*50)
    print("🔧 Step 2: Preparing for docking")
    print("="*50)

    receptor_pdbqt = outdir / f"{Path(receptor_file).stem}.pdbqt"
    ligand_pdbqt = outdir / f"{args.ligand}.pdbqt"

    prepare_receptor(receptor_file, str(receptor_pdbqt))
    prepare_ligand(ligand_smiles, str(ligand_pdbqt), name=args.ligand)

    # 3. Find binding site
    print("\n" + "="*50)
    print("🔍 Step 3: Detecting binding site")
    print("="*50)

    center, box_size = find_binding_site(str(receptor_pdbqt))

    # 4. Dock
    print("\n" + "="*50)
    print("🧬 Step 4: Running docking")
    print("="*50)

    energies, poses, meta = dock_ligand(
        str(receptor_pdbqt),
        str(ligand_pdbqt),
        center=center,
        box_size=box_size,
        output_dir=str(outdir),
        return_structured=False,
    )
    best_pose = meta.get('best_pose_path', str(outdir / 'docking_best.pdbqt'))
    best_energy = energies[0][0]

    # 5. Visualize
    print("\n" + "="*50)
    print("🎨 Step 5: Generating visualizations")
    print("="*50)

    scene_out = outdir / "docking_scene.png"
    diagram_out = outdir / "interaction_diagram.png"

    # Detect interactions via PLIP (needed for both renderers)
    try:
        intx_list, _ = detect_interactions_plip(receptor_file, str(ligand_pdbqt))
    except Exception as e:
        logger.warning(f"[autodock] Interaction detection failed: {e}")
        intx_list = []

    render_scene(
        str(receptor_pdbqt),
        str(scene_out),
        scene='pocket',
        center=center,
        interactions=intx_list,
        ligand_pdbqt=best_pose,
    )

    render_interactions_2d(
        receptor_file,
        str(ligand_pdbqt),
        intx_list,
        str(diagram_out),
    )

    # Summary
    print("\n" + "="*50)
    print("✅ Docking Workflow Complete!")
    print("="*50)
    print(f"  📂 Output directory: {outdir.absolute()}")
    print(f"  🔬 Best energy:     {best_energy:.2f} kcal/mol")
    print(f"  🖼️  3D scene:        {scene_out}")
    print(f"  📊 2D diagram:      {diagram_out}")


def main():
    parser = argparse.ArgumentParser(
        prog='autodock',
        description='Molecular Docking CLI — AutoDock Vina + PyMOL + PLIP',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Global options
    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Silence info messages (only warnings/errors)',
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable debug logging',
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # status
    p_status = subparsers.add_parser('status', help='Check dependencies and environment')
    p_status.set_defaults(func=cmd_status)

    # cache
    p_cache = subparsers.add_parser('cache', help='Show or clear the structure cache')
    p_cache.add_argument('--clear', action='store_true',
                        help='Delete all cached structure files')
    p_cache.set_defaults(func=cmd_cache)

    # fetch
    p_fetch = subparsers.add_parser('fetch', help='Fetch protein or ligand structures')
    p_fetch.add_argument('type', choices=['pdb', 'ligand'], help='Type: pdb or ligand')
    p_fetch.add_argument('id', help='PDB ID or ligand name/SMILES')
    p_fetch.add_argument('-o', '--outdir', default='.', help='Output directory')
    p_fetch.add_argument('--refresh', action='store_true',
                         help='Force re-download even if cached')
    p_fetch.set_defaults(func=cmd_fetch)

    # prepare-receptor
    p_prep_rec = subparsers.add_parser('prepare-receptor', help='Prepare receptor PDB → PDBQT')
    p_prep_rec.add_argument('pdb', help='Input PDB file')
    p_prep_rec.add_argument('output', nargs='?', help='Output PDBQT file (auto if omitted)')
    p_prep_rec.add_argument('--keep-waters', action='store_true', help='Keep water molecules')
    p_prep_rec.set_defaults(func=cmd_prepare_receptor)

    # prepare-ligand
    p_prep_lig = subparsers.add_parser('prepare-ligand', help='Prepare ligand SMILES → PDBQT')
    p_prep_lig.add_argument('smiles', help='SMILES string or ligand name')
    p_prep_lig.add_argument('output', nargs='?', help='Output PDBQT file')
    p_prep_lig.add_argument('--name', help='Ligand name for output')
    p_prep_lig.set_defaults(func=cmd_prepare_ligand)

    # prepare-conformers
    p_conf = subparsers.add_parser('prepare-conformers',
                                   help='Generate multiple ligand conformers')
    p_conf.add_argument('smiles', help='SMILES string or ligand name')
    p_conf.add_argument('output_dir', help='Directory for conformer PDBQT files')
    p_conf.add_argument('--n', type=int, default=10,
                        help='Number of conformers (default: 10)')
    p_conf.add_argument('--name', default='LIG', help='Residue name (default: LIG)')
    p_conf.set_defaults(func=cmd_prepare_conformers)

    # find-site
    p_find = subparsers.add_parser('find-site', help='Detect binding site with fpocket + P2Rank')
    p_find.add_argument('receptor', help='Receptor PDB or PDBQT')
    p_find.add_argument('--ligand', help='Optional co-crystallized ligand for centering')
    p_find.set_defaults(func=cmd_find_site)

    # dock
    p_dock = subparsers.add_parser('dock', help='Run AutoDock Vina docking')
    p_dock.add_argument('receptor', help='Receptor PDBQT')
    p_dock.add_argument('ligand', help='Ligand PDBQT')
    p_dock.add_argument('--center', nargs=3, type=float, required=True,
                       metavar=('X', 'Y', 'Z'), help='Search box center')
    p_dock.add_argument('--box-size', nargs=3, type=float, required=True,
                       metavar=('W', 'H', 'D'), help='Search box dimensions (Å)')
    p_dock.add_argument('--exhaustiveness', type=int, default=32,
                       help='Search exhaustiveness (default: 32)')
    p_dock.add_argument('--n-poses', type=int, default=10,
                       help='Number of poses to output (default: 10)')
    p_dock.set_defaults(func=cmd_dock)

    # dock-multi-conformer
    p_mc = subparsers.add_parser('dock-multi-conformer',
                                  help='Dock multiple ligand conformers (publication-standard)')
    p_mc.add_argument('receptor_pdbqt', help='Prepared receptor PDBQT')
    p_mc.add_argument('conformers_dir', help='Directory with conformer_0.pdbqt, conformer_1.pdbqt, ...')
    p_mc.add_argument('--receptor-pdb', help='Original receptor PDB for fpocket detection')
    p_mc.add_argument('--exhaustiveness', type=int, default=32)
    p_mc.add_argument('--n-poses', type=int, default=10,
                     help='Number of top poses to return (default: 10)')
    p_mc.set_defaults(func=cmd_dock_multi_conformer)

    # detect-interactions
    p_det = subparsers.add_parser('detect-interactions', help='Detect protein-ligand interactions')
    p_det.add_argument('receptor', help='Receptor PDB')
    p_det.add_argument('ligand', help='Ligand PDBQT')
    p_det.add_argument('poses', help='Docked poses PDBQT')
    p_det.set_defaults(func=cmd_detect_interactions)

    # render-2d
    p_r2d = subparsers.add_parser('render-2d', help='Render 2D interaction diagram')
    p_r2d.add_argument('receptor', help='Receptor PDB')
    p_r2d.add_argument('ligand', help='Ligand PDBQT')
    p_r2d.add_argument('poses', help='Docked poses PDBQT')
    p_r2d.add_argument('output', help='Output PNG file')
    p_r2d.set_defaults(func=cmd_render_2d)

    # render-pymol
    p_3d = subparsers.add_parser('render-pymol', help='Render 3D scene with PyMOL')
    p_3d.add_argument('receptor', help='Receptor PDB or PDBQT')
    p_3d.add_argument('ligand', help='Ligand PDB or PDBQT')
    p_3d.add_argument('poses', nargs='?', help='Docked poses PDBQT')
    p_3d.add_argument('-o', '--output', required=True, help='Output PNG file')
    p_3d.set_defaults(func=cmd_render_pymol)

    # virtual-screen
    p_screen = subparsers.add_parser('virtual-screen', help='Virtual screen a compound library')
    p_screen.add_argument('receptor', help='Receptor PDBQT')
    p_screen.add_argument('library', help='CSV with SMILES column')
    p_screen.add_argument('output', help='Output CSV file')
    p_screen.add_argument('--center', nargs=3, type=float, required=True,
                         metavar=('X', 'Y', 'Z'), help='Search box center')
    p_screen.add_argument('--box-size', nargs=3, type=float, required=True,
                         metavar=('W', 'H', 'D'), help='Search box dimensions')
    p_screen.set_defaults(func=cmd_virtual_screen)

    # validate
    p_val = subparsers.add_parser('validate', help='Validate docking protocol via redocking')
    p_val.add_argument('receptor', help='Receptor PDBQT')
    p_val.add_argument('crystal_ligand', help='Crystal ligand PDBQT')
    p_val.set_defaults(func=cmd_validate)

    # run (full workflow)
    p_run = subparsers.add_parser('run', help='Full workflow: fetch → prepare → dock → visualize')
    p_run.add_argument('--receptor', required=True, help='PDB ID of protein (e.g. 6LU7)')
    p_run.add_argument('--ligand', required=True, help='Ligand name (e.g. aspirin)')
    p_run.add_argument('--outdir', default='./docking_results', help='Output directory')
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()

    # Handle logging
    if args.quiet:
        autodock_logger.setLevel(logging.WARNING)
    elif args.verbose:
        autodock_logger.setLevel(logging.DEBUG)
    else:
        autodock_logger.setLevel(logging.INFO)

    # Check subcommand
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Run command
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()