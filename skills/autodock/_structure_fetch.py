"""
Structure Fetching Module
=========================
Fetch protein structures and small molecule structures for docking.
No external software required — pure HTTP + RDKit.

Caching: All fetched structures are cached at ~/.openclaw/structures_cache/
to avoid repeated downloads.

Author: PrimeClaw (OpenClaw)
"""

import os
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from autodock._core import autodock_logger, _HAVE_OBABEL
logger = autodock_logger

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Draw
    _HAVE_RDKIT = True
except ImportError:
    _HAVE_RDKIT = False


# ─── Centralized Cache Manager ──────────────────────────────────────────────────

def _get_cache_dir() -> Path:
    """Get or create the central structure cache directory."""
    cache = Path.home() / ".openclaw" / "structures_cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _cache_path(pdb_id: str = None, cid: str = None,
                suffix: str = None, format: str = 'pdb') -> Path:
    """Build a cache file path for a given identifier."""
    cache = _get_cache_dir()
    if pdb_id:
        stem = pdb_id.upper()
        ext = suffix or f'.{format}'
        return cache / f"{stem}{ext}"
    if cid:
        stem = f"pubchem_cid_{cid}"
        return cache / f"{stem}{suffix or '.sdf'}"
    raise ValueError("Must provide either pdb_id or cid")


def clear_cache(confirm: bool = True) -> dict:
    """
    Clear all cached structure files.

    By default requires user confirmation (confirm=True).  Set confirm=False
    to skip the confirmation prompt (useful for scripts / automated pipelines).

    Args:
        confirm: If True (default), raise an exception if the user does not
                 respond 'y' to the interactive prompt.  If False, clear
                 without asking.

    Returns:
        dict with keys:
          'cleared': list of file paths that were deleted
          'size_mb':  total size freed (megabytes)

    Raises:
        ValueError: If confirm=True and the user does not type 'y'
    """
    cache = _get_cache_dir()
    files = [f for f in cache.iterdir() if f.is_file()]
    if not files:
        print(f"[structure_fetch] Cache is already empty: {cache}")
        return {'cleared': [], 'size_mb': 0.0}

    total_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
    print(f"[structure_fetch] Cache: {len(files)} files, {total_mb:.1f} MB")
    print(f"  Location: {cache}")
    for f in sorted(files):
        print(f"    {f.name} ({f.stat().st_size / 1024:.0f} KB)")

    if confirm:
        response = input("\n  Delete all cached files? [y/N]: ").strip().lower()
        if response != 'y':
            print("  Aborted — cache not modified.")
            return {'cleared': [], 'size_mb': 0.0}

    cleared = []
    for f in files:
        f.unlink()
        cleared.append(str(f))

    freed_mb = total_mb
    print(f"[structure_fetch] Cleared {len(cleared)} files, freed {freed_mb:.1f} MB")
    return {'cleared': cleared, 'size_mb': freed_mb}


def get_cache_info() -> dict:
    """
    Return information about the structure cache without deleting anything.

    Returns:
        dict with keys:
          'cache_dir':   Path to the cache directory (str)
          'n_files':     Number of cached files
          'size_mb':      Total size in MB
          'files':       List of (filename, size_kb) tuples
    """
    cache = _get_cache_dir()
    files = sorted([f for f in cache.iterdir() if f.is_file()])
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        'cache_dir': str(cache),
        'n_files': len(files),
        'size_mb': total_bytes / (1024 * 1024),
        'files': [(f.name, f.stat().st_size / 1024) for f in files],
    }


# ─── mmCIF → PDB conversion (OpenBabel) ─────────────────────────────────────

def _cif_to_pdb(cif_path: str, pdb_path: str) -> str:
    """
    Convert mmCIF to PDB format using OpenBabel.

    Args:
        cif_path: Path to input .cif file
        pdb_path: Path to output .pdb file

    Returns:
        Path to converted PDB file

    Raises:
        RuntimeError: If OpenBabel is not available or conversion fails
    """
    import subprocess

    # Verify OpenBabel is available
    try:
        result = subprocess.run(['obabel', '-V'], capture_output=True, timeout=5)
        if result.returncode != 0:
            raise RuntimeError("OpenBabel not available")
    except Exception as e:
        raise RuntimeError(f"OpenBabel check failed: {e}")

    # Run conversion: obabel -icif input.cif -opdb -O output.pdb
    cmd = ['obabel', '-icif', cif_path, '-opdb', '-O', pdb_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        raise RuntimeError(f"OpenBabel conversion failed: {result.stderr}")

    # Validate output
    if not os.path.exists(pdb_path) or os.path.getsize(pdb_path) == 0:
        raise RuntimeError("OpenBabel produced empty output")

    with open(pdb_path) as f:
        content = f.read()
    if 'ATOM' not in content:
        raise RuntimeError("Converted file has no ATOM records")

    return pdb_path


# ─── Protein Structure Sources ─────────────────────────────────────────────────

def fetch_protein_pdb(pdb_id: str, output_path: str = None,
                   force_refresh: bool = False,
                   format: str = 'auto') -> str:
    """
    Download protein structure from RCSB PDB.

    Supports legacy PDB format and modern mmCIF format.
    When format='auto', prefers .cif for new entries (12-char PDB IDs)
    and falls back to .pdb for legacy 4-char entries.
    Automatic .cif → .pdb conversion via OpenBabel for downstream compatibility.

    Cached at ~/.openclaw/structures_cache/{pdb_id}.{format} after first download.

    Args:
        pdb_id: PDB ID (4 chars legacy, or 12 chars for new entries)
        output_path: Optional working copy path (default: ./structures/{pdb_id}.pdb).
                     When provided the file is copied from cache to this path.
        force_refresh: If True, re-download even if cached (default: False).
        format: 'auto' | 'pdb' | 'cif'
                'auto' (default): try .cif first, fallback .pdb for 4-char IDs
                'pdb': force legacy PDB format
                'cif': force mmCIF format (requires OpenBabel for conversion)

    Returns:
        Path to downloaded PDB file (always .pdb for downstream compatibility)

    Raises:
        ValueError: If PDB ID invalid or download fails
        RuntimeError: If .cif conversion fails (OpenBabel missing)
    """
    pdb_id = pdb_id.upper()

    # Validate PDB ID
    is_legacy = len(pdb_id) == 4
    is_extended = len(pdb_id) > 4
    if not (is_legacy or is_extended):
        raise ValueError(f"Invalid PDB ID: {pdb_id} (must be 4 or 12+ characters)")

    # Determine format strategy
    if format == 'auto':
        # Extended IDs (12-char) only available in .cif
        if is_extended:
            format = 'cif'
        else:
            # Legacy IDs: prefer .cif for future-proofing, but .pdb fallback
            format = 'cif'  # always try .cif first
    elif format not in ('pdb', 'cif'):
        raise ValueError(f"format must be 'auto' | 'pdb' | 'cif', got: {format}")

    # .cif format requires OpenBabel
    if format == 'cif' and not _HAVE_OBABEL:
        if is_extended:
            raise RuntimeError(
                f"Extended PDB ID {pdb_id} requires .cif format, "
                f"but OpenBabel is not available. Install: conda install -c conda-forge openbabel"
            )
        # Fallback to .pdb for legacy IDs
        print(f"[structure_fetch] OpenBabel not available, falling back to .pdb for {pdb_id}")
        format = 'pdb'

    # Cache and download paths
    if format == 'cif':
        cif_cache = _cache_path(pdb_id, format='cif')
        cif_url = f"https://files.rcsb.org/download/{pdb_id}.cif"
        pdb_cache = _cache_path(pdb_id, format='pdb')
    else:
        cif_cache = None
        cif_url = None
        pdb_cache = _cache_path(pdb_id, format='pdb')

    pdb_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    working = output_path or f"./structures/{pdb_id}.pdb"
    working_dir = os.path.dirname(working) or '.'

    # ── Return from cache if present ────────────────────────────────────
    if pdb_cache.exists() and not force_refresh:
        if working != str(pdb_cache):
            os.makedirs(working_dir, exist_ok=True)
            import shutil
            shutil.copy2(pdb_cache, working)
        print(f"[structure_fetch] PDB cached: {pdb_cache} → {working}")
        return working

    # ── Download .cif, convert to .pdb ──────────────────────────────────
    if format == 'cif':
        os.makedirs(working_dir, exist_ok=True)
        try:
            # Download .cif
            urllib.request.urlretrieve(cif_url, str(cif_cache))
            print(f"[structure_fetch] CIF downloaded: {cif_url} → {cif_cache}")

            # Convert to .pdb
            _cif_to_pdb(str(cif_cache), str(pdb_cache))
            print(f"[structure_fetch] CIF→PDB converted: {cif_cache} → {pdb_cache}")

            # Copy to working path
            if working != str(pdb_cache):
                import shutil
                shutil.copy2(pdb_cache, working)
            return working

        except (urllib.error.HTTPError, RuntimeError) as e:
            # .cif failed — try .pdb fallback (only for legacy 4-char IDs)
            if is_legacy:
                print(f"[structure_fetch] .cif failed ({e}), falling back to .pdb...")
                # Continue to .pdb download below
            else:
                raise RuntimeError(f"Extended PDB ID {pdb_id} only available in .cif: {e}")

    # ── Download .pdb (legacy format or fallback) ─────────────────────────
    os.makedirs(working_dir, exist_ok=True)
    try:
        urllib.request.urlretrieve(pdb_url, working)
        with open(working) as f:
            content = f.read()
        if 'HEADER' not in content and 'ATOM' not in content:
            raise ValueError(f"Downloaded file is not a valid PDB: {pdb_id}")
        # Populate cache
        import shutil
        shutil.copy2(working, pdb_cache)
        print(f"[structure_fetch] PDB downloaded: {pdb_id} → {working} (cached at {pdb_cache})")
        return working
    except urllib.error.HTTPError as e:
        raise ValueError(f"PDB not found: {pdb_id} (HTTP {e.code})")


def fetch_protein_alphafold(uniprot_id: str, output_path: str = None) -> str:
    """
    Download predicted protein structure from AlphaFold DB.

    Args:
        uniprot_id: UniProt accession (e.g. 'P00533', 'Q9Y5Y9')
        output_path: Optional output path

    Returns:
        Path to downloaded PDB file

    Raises:
        ValueError: If UniProt ID not found
    """
    uniprot_id = uniprot_id.upper()
    url = f"https://alphafold.ebi.ac.uk/files/AF-{uniprot_id}-F1-model_v6.pdb"
    dest = output_path or f"./structures/AF-{uniprot_id}.pdb"

    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)

    try:
        urllib.request.urlretrieve(url, dest)
        with open(dest) as f:
            content = f.read()
        # Use regex to ensure at least one real ATOM record (not REMARK/HEADER/COMPND)
        if not re.search(r'^ATOM ', content, re.MULTILINE):
            raise ValueError(f"AlphaFold structure has no ATOM records: {uniprot_id}")
        print(f"[structure_fetch] AlphaFold downloaded: {dest}")
        return dest
    except urllib.error.HTTPError as e:
        raise ValueError(f"AlphaFold entry not found: {uniprot_id} (HTTP {e.code})")


def fetch_protein_swissmodel(uniprot_id: str, output_path: str = None) -> str:
    """
    Download protein structure from SWISS-MODEL Repository (homology modeling).

    Args:
        uniprot_id: UniProt accession (e.g. 'P00533')
        output_path: Optional output path

    Returns:
        Path to downloaded PDB file

    Raises:
        ValueError: If no model available for this UniProt entry
    """
    uniprot_id = uniprot_id.upper()
    # SWISS-MODEL API to get best model
    api_url = f"https://swissmodel.expasy.org/repository/uniprot/{uniprot_id}.json"
    model_url = None

    try:
        req = urllib.request.Request(api_url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            data = json.loads(resp.read())
            results = data.get('result', {}).get('structures', [])
            if results:
                # Get the first/best model — use 'coordinates' field for .pdb URL
                best = results[0]
                model_url = best.get('coordinates')
    except Exception as e:
        raise ValueError(f"SWISS-MODEL lookup failed: {e}")

    if not model_url:
        raise ValueError(f"No SWISS-MODEL structure available for: {uniprot_id}")

    dest = output_path or f"./structures/{uniprot_id}_swissmodel.pdb"
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)

    try:
        urllib.request.urlretrieve(model_url, dest)
        print(f"[structure_fetch] SWISS-MODEL downloaded: {dest}")
        return dest
    except urllib.error.HTTPError as e:
        raise ValueError(f"SWISS-MODEL download failed: {uniprot_id} (HTTP {e.code})")


def fetch_protein_pdb_redo(pdb_id: str, output_path: str = None) -> str:
    """
    Download refined/optimized structure from PDBredo.

    Args:
        pdb_id: 4-character PDB ID
        output_path: Optional output path

    Returns:
        Path to downloaded PDB file
    """
    pdb_id = pdb_id.upper()
    # PDB-REDO Databank at pdb-redo.eu — free, no auth
    # Format: https://pdb-redo.eu/db/{pdb_id_lower}/{pdb_id_lower}_final.pdb
    url = f"https://pdb-redo.eu/db/{pdb_id.lower()}/{pdb_id.lower()}_final.pdb"
    dest = output_path or f"./structures/{pdb_id}_redo.pdb"

    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)

    try:
        urllib.request.urlretrieve(url, dest)
        with open(dest) as f:
            content = f.read()
        if 'ATOM' not in content:
            raise ValueError(f"PDBredo fetch returned non-PDB content for: {pdb_id}")
        print(f"[structure_fetch] PDBredo downloaded: {dest}")
        return dest
    except urllib.error.HTTPError as e:
        raise ValueError(f"PDBredo entry not found: {pdb_id} (HTTP {e.code})")


def fetch_protein(pdb_id: str = None,
                  uniprot_id: str = None,
                  source: str = 'auto',
                  output_dir: str = "./structures") -> str:
    """
    Unified protein structure fetch with automatic fallback chain.

    Priority: RCSB PDB → PDB-REDO → AlphaFold → SwissModel

    Args:
        pdb_id:      RCSB PDB ID (4 chars). If provided, starts from PDB.
        uniprot_id:  UniProt accession (e.g. 'Q9H825'). Used when pdb_id not given.
        source:      'pdb' | 'alphafold' | 'swissmodel' | 'pdbredo' | 'auto'
                     'auto' (default): follows the fallback chain above.
        output_dir:  Directory to save structure

    Returns:
        Path to downloaded PDB file

    Raises:
        ValueError: If all sources fail
    """
    os.makedirs(output_dir, exist_ok=True)

    # Build output path
    def out_path(name):
        return os.path.join(output_dir, f"{name}.pdb")

    # ── Explicit source selection ─────────────────────────────────────
    if source != 'auto':
        if source == 'pdb' and pdb_id:
            return fetch_protein_pdb(pdb_id, out_path(pdb_id))
        elif source == 'pdbredo' and pdb_id:
            return fetch_protein_pdb_redo(pdb_id, out_path(f"{pdb_id}_redo"))
        elif source == 'alphafold' and uniprot_id:
            return fetch_protein_alphafold(uniprot_id, out_path(f"AF-{uniprot_id}"))
        elif source == 'swissmodel' and uniprot_id:
            return fetch_protein_swissmodel(uniprot_id, out_path(f"{uniprot_id}_swissmodel"))
        else:
            raise ValueError(
                f"source='{source}' requires pdb_id (for pdb/pdbredo) or "
                f"uniprot_id (for alphafold/swissmodel)"
            )

    # ── Auto fallback chain ────────────────────────────────────────────
    if pdb_id:
        pdb_id = pdb_id.upper()
        try:
            return fetch_protein_pdb(pdb_id, out_path(pdb_id))
        except Exception as e:
            print(f"[fetch_protein] PDB failed ({e}), trying PDB-REDO...")
            try:
                return fetch_protein_pdb_redo(pdb_id, out_path(f"{pdb_id}_redo"))
            except Exception:
                pass
        # Fall through to AlphaFold if PDB both fail
        if uniprot_id:
            print(f"[fetch_protein] PDB/PDBREDO failed, falling back to AlphaFold...")
            return fetch_protein_alphafold(uniprot_id, out_path(f"AF-{uniprot_id}"))
        raise ValueError(f"All PDB sources failed for: {pdb_id}")

    elif uniprot_id:
        uniprot_id = uniprot_id.upper()
        tried = []
        for src_name, src_fn, path_fn in [
            ('AlphaFold',  fetch_protein_alphafold,  lambda uid: out_path(f"AF-{uid}")),
            ('SwissModel', fetch_protein_swissmodel, lambda uid: out_path(f"{uid}_swissmodel")),
        ]:
            try:
                return src_fn(uniprot_id, path_fn(uniprot_id))
            except Exception as e:
                print(f"[fetch_protein] {src_name} failed ({e})")
                tried.append(src_name)
                continue
        raise ValueError(f"All sources failed for UniProt {uniprot_id}: {tried}")

    else:
        raise ValueError("fetch_protein requires pdb_id or uniprot_id")



# ─── Small Molecule Sources ───────────────────────────────────────────────────

def fetch_molecule_pubchem(identifier: str,
                           identifier_type: str = 'name',
                           output_sdf: str = None,
                           force_refresh: bool = False) -> dict:
    """
    Fetch small molecule from PubChem.

    SDF is cached at ~/.openclaw/structures_cache/pubchem_cid_{cid}.sdf
    after first download.

    Args:
        identifier: Compound name, SMILES, InChI, or CID
        identifier_type: 'name' | 'smiles' | 'inchi' | 'cid'
        output_sdf: Optional working copy path for SDF file
        force_refresh: If True, re-fetch even if cached (default: False)

    Returns:
        dict with keys: name, smiles, inchi, cid, sdf_path, cached
    """
    import json

    encoded_id = urllib.parse.quote(identifier, safe='')
    prop_list = 'IsomericSMILES,CanonicalSMILES,InChI,Title'
    if identifier_type == 'name':
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{encoded_id}/property/{prop_list}/JSON"
    elif identifier_type == 'smiles':
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{encoded_id}/property/{prop_list}/JSON"
    elif identifier_type == 'cid':
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{identifier}/property/{prop_list}/JSON"
    else:
        raise ValueError(f"Unknown identifier_type: {identifier_type}")

    # ── Property lookup (always needed to get CID + SMILES) ──────────────
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    props = data['PropertyTable']['Properties'][0]
    smiles = props.get('IsomericSMILES') or props.get('CanonicalSMILES') or props.get('SMILES') or ''
    inchi = props.get('InChI', '')
    name = props.get('Title', identifier)
    cid = str(props.get('CID', ''))

    result = {
        'name': name,
        'smiles': smiles,
        'inchi': inchi,
        'cid': cid,
        'sdf_path': None,
        'cached': False,
    }

    if not output_sdf:
        print(f"[structure_fetch] PubChem: {name} (CID: {cid})")
        return result

    # ── SDF: check cache first, then download ────────────────────────────
    cache_sdf = _cache_path(cid=cid, suffix='.sdf')
    if cache_sdf.exists() and not force_refresh:
        import shutil
        working_dir = os.path.dirname(output_sdf) or '.'
        os.makedirs(working_dir, exist_ok=True)
        shutil.copy2(cache_sdf, output_sdf)
        result['sdf_path'] = output_sdf
        result['cached'] = True
        print(f"[structure_fetch] PubChem SDF cached: {cache_sdf} → {output_sdf}")
        return result

    # Download SDF and populate cache.
    # Fallback to RDKit ETKDGv3 if SDF is empty/truncated (complex molecules
    # like nirmatrelvir often return incomplete SDF from PubChem PUG REST).
    sdf_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF"
    import shutil as _shutil
    working_dir = os.path.dirname(output_sdf) or '.'
    os.makedirs(working_dir, exist_ok=True)
    urllib.request.urlretrieve(sdf_url, output_sdf)
    # Validate SDF: must have V2000 header + at least one atom record
    sdf_valid = False
    try:
        with open(output_sdf, 'rb') as f:
            raw = f.read()
        sdf_valid = b'V2000' in raw and len(raw) > 5000
    except Exception:
        sdf_valid = False

    if sdf_valid:
        _shutil.copy2(output_sdf, cache_sdf)
        result['sdf_path'] = output_sdf
        print(f"[structure_fetch] PubChem: {name} (CID: {cid}) → {output_sdf} (cached at {cache_sdf})")
    else:
        # SDF missing/truncated: generate 3D from SMILES using RDKit ETKDGv3
        if _HAVE_RDKIT:
            from rdkit import Chem
            from rdkit.Chem import AllChem
            mol = Chem.MolFromSmiles(smiles)
            if mol is not None:
                mol = Chem.AddHs(mol, addCoords=True)
                params_etkdg = AllChem.ETKDGv3()
                params_etkdg.randomSeed = 42
                AllChem.EmbedMolecule(mol, params_etkdg)
                AllChem.MMFFOptimizeMolecule(mol)
                writer = Chem.SDWriter(output_sdf)
                writer.write(mol)
                writer.close()
                _shutil.copy2(output_sdf, cache_sdf)
                result['sdf_path'] = output_sdf
                print(f"[structure_fetch] PubChem SDF truncated; RDKit ETKDGv3 generated 3D: {output_sdf}")
                return result
        # RDKit not available: keep output_sdf as-is (degraded but usable)
        result['sdf_path'] = output_sdf
        print(f"[structure_fetch] PubChem: {name} (CID: {cid}) → {output_sdf} (SDF may be incomplete, SMILES OK)")
    return result


def fetch_molecule_chembl(chembl_id: str = None,
                         molecule_name: str = None) -> dict:
    """
    Fetch small molecule from ChEMBL.

    Args:
        chembl_id: ChEMBL ID (e.g. 'CHEMBL25')
        molecule_name: Or search by name

    Returns:
        dict with keys: chembl_id, name, smiles, max_phase
    """
    import json

    if chembl_id:
        url = f"https://www.ebi.ac.uk/chembl/api/data/molecule/{chembl_id}.json"
    elif molecule_name:
        url = f"https://www.ebi.ac.uk/chembl/api/data/molecule?name={molecule_name}.json"
    else:
        raise ValueError("Provide chembl_id or molecule_name")

    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        mol = data.get('molecule_structures', {})
        smiles = mol.get('canonical_smiles', '') if mol else ''
        result = {
            'chembl_id': data.get('molecule_chembl_id', ''),
            'name': data.get('preferred_name', ''),
            'smiles': smiles,
            'max_phase': data.get('max_phase', ''),
        }
        print(f"[structure_fetch] ChEMBL: {result['name']} ({result['chembl_id']})")
        return result

    except urllib.error.HTTPError as e:
        raise ValueError(f"ChEMBL not found: HTTP {e.code}")
    except Exception as e:
        raise ValueError(f"ChEMBL error: {e}")


def fetch_molecule_drugbank(drugbank_id: str = None,
                            drug_name: str = None) -> dict:
    """
    Fetch small molecule from DrugBank.

    Note: DrugBank 已停止公开API（需注册+付费Key）。
    本函数通过 PubChem 代理提供 DrugBank 名称搜索。
    若需完整 DrugBank 数据，请使用 PubChem 或 ChEMBL。

    Args:
        drugbank_id: DrugBank ID (e.g. 'DB00102') — 需要 API Key，暂不支持
        drug_name: 按药物名称搜索（通过 PubChem 代理）

    Returns:
        dict with keys: drugbank_id, name, smiles, source
    """
    if drugbank_id:
        raise NotImplementedError(
            "DrugBank ID lookup requires API key which is no longer publicly available. "
            "Use fetch_molecule_pubchem(name) or fetch_molecule_chembl(name) instead."
        )
    elif drug_name:
        result = fetch_molecule_pubchem(drug_name, identifier_type='name')
        result['source'] = 'PubChem (DrugBank name search)'
        return result
    else:
        raise ValueError("Provide drugbank_id or drug_name")



def fetch_molecule(identifier: str,
                   source: str = 'pubchem',
                   identifier_type: str = 'name',
                   output_dir: str = "./structures") -> dict:
    """
    Unified small molecule structure fetch.

    Args:
        identifier: Compound name, SMILES, ID, etc.
        source: 'pubchem' | 'chembl' | 'cactus'
        identifier_type: 'name' | 'smiles' | 'inchi' | 'cid' (for pubchem)
        output_dir: Directory to save SDF/SMILES files

    Returns:
        dict with molecule info
    """
    os.makedirs(output_dir, exist_ok=True)

    if source == 'pubchem':
        sdf = os.path.join(output_dir, f"{identifier}.sdf")
        return fetch_molecule_pubchem(identifier, identifier_type, output_sdf=sdf)
    elif source == 'chembl':
        return fetch_molecule_chembl(chembl_id=identifier) if identifier.startswith('CHEMBL') else fetch_molecule_chembl(molecule_name=identifier)
    elif source == 'cactus':
        return fetch_molecule_cactus(identifier)
    else:
        raise ValueError(f"Unknown source: {source}")


def fetch_molecule_cactus(identifier: str) -> dict:
    """
    Resolve a chemical name to SMILES via EBI OPSIN (Open Parser for Systematic
    IUPAC Nomenclature).

    Best for **IUPAC names**; common names (caffeine, ibuprofen, aspirin)
    often fail because OPSIN is a grammar-based parser for systematic IUPAC
    nomenclature, not a chemical-name search engine.  In those cases the
    function automatically falls back to PubChem name search.

    Args:
        identifier: Chemical name (IUPAC or common)

    Returns:
        dict with keys: name, smiles, source

    Raises:
        ValueError: if the name cannot be parsed by OPSIN or PubChem
    """
    encoded = urllib.parse.quote(identifier, safe='')
    url = f"https://www.ebi.ac.uk/opsin/ws/{encoded}.smi"

    try:
        req = urllib.request.Request(url, headers={'Accept': 'text/plain'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            smiles = resp.read().decode().strip()

        # OPSIN returns an error XML if parsing fails
        if smiles.startswith('<?xml') or not smiles:
            raise ValueError(f"OPSIN could not parse: {identifier}")
        if len(smiles) > 2000:
            raise ValueError(f"OPSIN returned invalid SMILES for: {identifier}")

        print(f"[structure_fetch] OPSIN: {identifier} → {smiles[:50]}...")
        return {
            'name': identifier,
            'smiles': smiles,
            'source': 'EBI OPSIN',
        }
    except urllib.error.HTTPError as e:
        # HTTP error from OPSIN — try PubChem fallback
        logger.warning(f"[structure_fetch] OPSIN lookup failed for '{identifier}' (HTTP {e.code}), trying PubChem...")
    except Exception as e:
        logger.warning(f"[structure_fetch] OPSIN error for '{identifier}': {e}, trying PubChem...")

    # ── PubChem fallback ────────────────────────────────────────────────
    try:
        result = fetch_molecule_pubchem(identifier, identifier_type='name')
        result['source'] = f"PubChem (OPSIN fallback for '{identifier}')"
        print(f"[structure_fetch] PubChem fallback: {identifier} → {result['smiles'][:50]}...")
        return result
    except Exception as e2:
        raise ValueError(
            f"Neither OPSIN nor PubChem could resolve '{identifier}'. "
            f"OPSIN requires IUPAC names; PubChem name search also failed ({e2}). "
            f"Try providing a SMILES string directly."
        )


# ─── BindingDB Affinity Queries ─────────────────────────────────────────────────

import json

def _bindingdb_cache_dir() -> Path:
    """Get or create the BindingDB cache directory."""
    cache = Path.home() / ".openclaw" / "structures_cache" / "bindingdb"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _bindingdb_cache_key(prefix: str, query: str) -> Path:
    """Build a cache file path for a BindingDB query."""
    cache = _bindingdb_cache_dir()
    h = hashlib.md5(query.encode()).hexdigest()[:12]
    return cache / f"{prefix}_{h}.json"


def fetch_bindingdb_affinity(smiles: str = None,
                             name: str = None,
                             inchi: str = None,
                             max_results: int = 10) -> list:
    """
    Query BindingDB for experimental binding affinities (Ki/Kd/IC50).

    Args:
        smiles: Compound SMILES string
        name:   Compound name (fallback if SMILES not provided)
        inchi:  InChI string (highest priority if provided)
        max_results: Maximum records to return (default 10)

    Returns:
        list of dicts, each with:
          - affinity_type: 'Ki' | 'Kd' | 'IC50'
          - affinity_value: float (µM or nM — check unit field)
          - affinity_unit: 'µM' | 'nM' | 'pM'
          - target_name: str
          - target_uniprot: str or None
          - assay_description: str
          - reference: PubMed ID or DOI
          - smiles: compound SMILES
    """
    if not (smiles or name or inchi):
        raise ValueError("Provide at least one of: smiles, name, inchi")

    # Build query string
    if inchi:
        query = inchi
        query_type = 'inchi'
    elif smiles:
        query = smiles
        query_type = 'smiles'
    else:
        query = name
        query_type = 'name'

    # Check cache
    cache_key = _bindingdb_cache_key('affinity', f"{query_type}:{query}")
    if cache_key.exists():
        with open(cache_key) as f:
            return json.load(f)

    # BindingDB REST API
    # Format: https://www.bindingdb.org/bind/xmlsearch?{param}={query}&format=json
    if query_type == 'smiles':
        url = f"https://www.bindingdb.org/bind/xmlsearch?smiles={urllib.parse.quote(query)}&format=json"
    elif query_type == 'inchi':
        url = f"https://www.bindingdb.org/bind/xmlsearch?inchi={urllib.parse.quote(query)}&format=json"
    else:
        url = f"https://www.bindingdb.org/bind/xmlsearch?compound={urllib.parse.quote(query)}&format=json"

    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[structure_fetch] BindingDB query failed: {e}")
        return []

    # Parse results
    results = []
    entries = data if isinstance(data, list) else data.get('results', [])

    for entry in entries[:max_results]:
        # Extract affinity data
        affinity_type = entry.get('affinity_type') or entry.get('type') or 'unknown'
        value = entry.get('affinity') or entry.get('value')
        unit = entry.get('unit') or 'µM'

        # Normalize unit
        if value and isinstance(value, str):
            # Parse "5.2 nM" → value=5.2, unit='nM'
            import re
            m = re.match(r'([\d.]+)\s*([a-zA-Z]+)', value)
            if m:
                value = float(m.group(1))
                unit = m.group(2)

        results.append({
            'affinity_type': affinity_type,
            'affinity_value': float(value) if value is not None else None,
            'affinity_unit': unit,
            'target_name': entry.get('target_name') or entry.get('protein_name'),
            'target_uniprot': entry.get('uniprot') or entry.get('uniprot_id'),
            'assay_description': entry.get('assay') or entry.get('assay_description'),
            'reference': entry.get('pmid') or entry.get('reference') or entry.get('doi'),
            'smiles': entry.get('smiles') or query if query_type == 'smiles' else None,
        })

    # Cache results
    with open(cache_key, 'w') as f:
        json.dump(results, f, indent=2)

    return results


def fetch_bindingdb_by_target(uniprot_id: str = None,
                                target_name: str = None,
                                max_results: int = 50) -> list:
    """
    Query BindingDB for all known ligands of a target protein.

    Args:
        uniprot_id: UniProt accession (e.g. 'P00533')
        target_name: Target protein name (fallback)
        max_results: Maximum ligands to return (default 50)

    Returns:
        list of dicts, each with:
          - smiles: compound SMILES
          - name: compound name
          - affinity_type: 'Ki' | 'Kd' | 'IC50'
          - affinity_value: float
          - affinity_unit: str
          - reference: PubMed ID or DOI
    """
    if not (uniprot_id or target_name):
        raise ValueError("Provide uniprot_id or target_name")

    query = uniprot_id or target_name
    query_type = 'uniprot' if uniprot_id else 'target'

    # Check cache
    cache_key = _bindingdb_cache_key('target', f"{query_type}:{query}")
    if cache_key.exists():
        with open(cache_key) as f:
            return json.load(f)

    # BindingDB target API
    if uniprot_id:
        url = f"https://www.bindingdb.org/bind/xmlsearch?uniprot={urllib.parse.quote(uniprot_id)}&format=json"
    else:
        url = f"https://www.bindingdb.org/bind/xmlsearch?target={urllib.parse.quote(target_name)}&format=json"

    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[structure_fetch] BindingDB target query failed: {e}")
        return []

    # Parse results
    results = []
    entries = data if isinstance(data, list) else data.get('results', [])

    for entry in entries[:max_results]:
        value = entry.get('affinity') or entry.get('value')
        unit = entry.get('unit') or 'µM'

        if value and isinstance(value, str):
            import re
            m = re.match(r'([\d.]+)\s*([a-zA-Z]+)', value)
            if m:
                value = float(m.group(1))
                unit = m.group(2)

        results.append({
            'smiles': entry.get('smiles'),
            'name': entry.get('compound_name') or entry.get('name'),
            'affinity_type': entry.get('affinity_type') or 'unknown',
            'affinity_value': float(value) if value is not None else None,
            'affinity_unit': unit,
            'reference': entry.get('pmid') or entry.get('reference'),
        })

    # Cache results
    with open(cache_key, 'w') as f:
        json.dump(results, f, indent=2)

    return results


# ─── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== structure_fetch module ===")
    print(f"  RDKit: {'OK' if _HAVE_RDKIT else 'MISSING'}")
    print()

    # Test protein fetch
    print("[1] Testing PDB fetch (1COV)...")
    try:
        pdb_path = fetch_protein_pdb("1COV")
        print(f"  → {pdb_path}")
    except Exception as e:
        print(f"  FAILED: {e}")

    # Test PubChem fetch
    print("[2] Testing PubChem fetch (aspirin)...")
    try:
        mol = fetch_molecule_pubchem("aspirin")
        print(f"  → {mol['name']}: {mol['smiles']}")
    except Exception as e:
        print(f"  FAILED: {e}")

    print()
    print("Done.")
