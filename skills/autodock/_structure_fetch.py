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
        autodock_logger.info(f"Cache is already empty: {cache}")
        return {'cleared': [], 'size_mb': 0.0}

    total_mb = sum(f.stat().st_size for f in files) / (1024 * 1024)
    autodock_logger.info(f"Cache: {len(files)} files, {total_mb:.1f} MB")
    autodock_logger.info(f"  Location: {cache}")
    for f in sorted(files):
        autodock_logger.info(f"    {f.name} ({f.stat().st_size / 1024:.0f} KB)")

    if confirm:
        response = input("\n  Delete all cached files? [y/N]: ").strip().lower()
        if response != 'y':
            autodock_logger.info("  Aborted — cache not modified.")
            return {'cleared': [], 'size_mb': 0.0}

    cleared = []
    for f in files:
        f.unlink()
        cleared.append(str(f))

    freed_mb = total_mb
    autodock_logger.info(f"Cleared {len(cleared)} files, freed {freed_mb:.1f} MB")
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
            raise StructureFetchError("OpenBabel not available")
    except Exception as e:
        raise StructureFetchError(f"OpenBabel check failed: {e}") from e

    # Run conversion: obabel -icif input.cif -opdb -O output.pdb
    cmd = ['obabel', '-icif', cif_path, '-opdb', '-O', pdb_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        raise StructureFetchError(f"OpenBabel conversion failed: {result.stderr}")

    # Validate output
    if not os.path.exists(pdb_path) or os.path.getsize(pdb_path) == 0:
        raise StructureFetchError("OpenBabel produced empty output")

    with open(pdb_path) as f:
        content = f.read()
    if 'ATOM' not in content:
        raise StructureFetchError("Converted file has no ATOM records")

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
        autodock_logger.warning(f"OpenBabel not available, falling back to .pdb for {pdb_id}")
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
        autodock_logger.info(f"PDB cached: {pdb_cache} → {working}")
        return working

    # ── Download .cif, convert to .pdb ──────────────────────────────────
    if format == 'cif':
        os.makedirs(working_dir, exist_ok=True)
        try:
            # Download .cif
            urllib.request.urlretrieve(cif_url, str(cif_cache))
            autodock_logger.info(f"CIF downloaded: {cif_url} → {cif_cache}")

            # Convert to .pdb
            _cif_to_pdb(str(cif_cache), str(pdb_cache))
            autodock_logger.info(f"CIF→PDB converted: {cif_cache} → {pdb_cache}")

            # Copy to working path
            if working != str(pdb_cache):
                import shutil
                shutil.copy2(pdb_cache, working)
            return working

        except (urllib.error.HTTPError, RuntimeError) as e:
            # .cif failed — try .pdb fallback (only for legacy 4-char IDs)
            if is_legacy:
                autodock_logger.warning(f".cif failed ({e}), falling back to .pdb...")
                # Continue to .pdb download below
            else:
                raise StructureFetchError(f"Extended PDB ID {pdb_id} only available in .cif: {e}")

    # ── Download .pdb (legacy format or fallback) ─────────────────────────
    os.makedirs(working_dir, exist_ok=True)
    try:
        urllib.request.urlretrieve(pdb_url, working)
        with open(working) as f:
            content = f.read()
        if 'HEADER' not in content and 'ATOM' not in content:
            raise StructureFetchError(f"Downloaded file is not a valid PDB: {pdb_id}")
        # Populate cache
        import shutil
        shutil.copy2(working, pdb_cache)
        autodock_logger.info(f"PDB downloaded: {pdb_id} → {working} (cached at {pdb_cache})")
        return working
    except urllib.error.HTTPError as e:
        raise StructureFetchError(f"PDB not found: {pdb_id} (HTTP {e.code})")


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
            raise StructureFetchError(f"AlphaFold structure has no ATOM records: {uniprot_id}")
        autodock_logger.info(f"AlphaFold downloaded: {dest}")
        return dest
    except urllib.error.HTTPError as e:
        raise StructureFetchError(f"AlphaFold entry not found: {uniprot_id} (HTTP {e.code})")


def fetch_protein_swissmodel(uniprot_id: str, output_path: str = None,
                             provider_filter: str = 'any',
                             min_coverage: float = 0.3,
                             min_identity: float = 0.0,
                             return_all: bool = False) -> str | list:
    """
    Download protein structure from SWISS-MODEL Repository (homology modeling).

    Enhanced with quality scoring (GMQE, QMEAN, identity, coverage) and
    intelligent model selection.

    Args:
        uniprot_id: UniProt accession (e.g. 'P00533')
        output_path: Output path (default: ./structures/{uniprot_id}_swissmodel.pdb)
                     If return_all=True, output_path is used as basename prefix.
        provider_filter: 'any' | 'swissmodel' | 'pdb'
                         'any': best available (default)
                         'swissmodel': homology models only
                         'pdb': experimental structures only
        min_coverage: Minimum sequence coverage (default: 0.3)
        min_identity: Minimum sequence identity (default: 0.0)
        return_all: If True, return all matching models with quality report

    Returns:
        str: Path to downloaded PDB file (default)
        list: [{'path': str, 'provider': str, 'template': str,
                'gmqe': float|None, 'qmean': float|None,
                'identity': float, 'coverage': float,
                'from': int, 'to': int}] (if return_all=True)

    Raises:
        ValueError: If no model meets criteria
    """
    uniprot_id = uniprot_id.upper()
    api_url = f"https://swissmodel.expasy.org/repository/uniprot/{uniprot_id}.json"

    try:
        req = urllib.request.Request(api_url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            all_structures = data.get('result', {}).get('structures', [])
    except Exception as e:
        raise StructureFetchError(f"SWISS-MODEL lookup failed: {e}")

    if not all_structures:
        raise StructureFetchError(f"No SWISS-MODEL structures available for: {uniprot_id}")

    # ── Extract quality scores and filter ───────────────────────────
    candidates = []
    for s in all_structures:
        provider = s.get('provider', 'unknown')
        coverage = s.get('coverage', 0.0)
        identity = s.get('identity', 0.0)
        coords_url = s.get('coordinates')

        # Provider filter
        if provider_filter != 'any' and provider.lower() != provider_filter.lower():
            continue

        # Coverage/identity thresholds
        if coverage < min_coverage or identity < min_identity:
            continue

        # Quality scores (SWISSMODEL entries have gmqe/qmean; PDB entries don't)
        gmqe = s.get('gmqe') if provider == 'SWISSMODEL' else None
        qmean = s.get('qmean') if provider == 'SWISSMODEL' else None

        # Scoring: prefer SWISSMODEL with high GMQE/QMEAN, then PDB with high coverage
        if provider == 'SWISSMODEL' and gmqe is not None:
            score = gmqe * coverage * (1 + identity)
        else:
            score = coverage * (1 + identity)

        candidates.append({
            'structure': s,
            'provider': provider,
            'template': s.get('template', ''),
            'gmqe': gmqe,
            'qmean': qmean,
            'identity': identity,
            'coverage': coverage,
            'from': s.get('from', 0),
            'to': s.get('to', 0),
            'score': score,
            'url': coords_url,
        })

    if not candidates:
        raise StructureFetchError(
            f"No SWISS-MODEL structures meet criteria for {uniprot_id} "
            f"(provider={provider_filter}, min_coverage={min_coverage}, "
            f"min_identity={min_identity})"
        )

    # Sort by score descending
    candidates.sort(key=lambda x: x['score'], reverse=True)

    # ── Download ────────────────────────────────────────────────────
    if return_all:
        results = []
        base_dir = os.path.dirname(output_path) or './structures'
        os.makedirs(base_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(output_path or f"{uniprot_id}_swissmodel.pdb"))[0]

        for i, c in enumerate(candidates):
            suffix = f"_{i}" if i > 0 else ""
            dest = os.path.join(base_dir, f"{base_name}{suffix}.pdb")
            try:
                urllib.request.urlretrieve(c['url'], dest)
                results.append({
                    'path': dest,
                    'provider': c['provider'],
                    'template': c['template'],
                    'gmqe': c['gmqe'],
                    'qmean': c['qmean'],
                    'identity': c['identity'],
                    'coverage': c['coverage'],
                    'from': c['from'],
                    'to': c['to'],
                })
                logger.info(f"[structure_fetch] SWISS-MODEL #{i+1}: {dest} "
                           f"({c['provider']}, GMQE={c['gmqe']}, QMEAN={c['qmean']}, "
                           f"cov={c['coverage']:.2f}, id={c['identity']:.2f})")
            except Exception as e:
                logger.warning(f"[structure_fetch] Download failed for model #{i+1}: {e}")

        if not results:
            raise StructureFetchError(f"All downloads failed for {uniprot_id}")
        return results

    # Single best model
    best = candidates[0]
    dest = output_path or f"./structures/{uniprot_id}_swissmodel.pdb"
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)

    try:
        urllib.request.urlretrieve(best['url'], dest)
        logger.info(
            f"[structure_fetch] SWISS-MODEL best model: {dest} "
            f"(provider={best['provider']}, template={best['template']}, "
            f"GMQE={best['gmqe']}, QMEAN={best['qmean']}, "
            f"coverage={best['coverage']:.2f}, identity={best['identity']:.2f})"
        )
        return dest
    except urllib.error.HTTPError as e:
        raise StructureFetchError(f"SWISS-MODEL download failed: {uniprot_id} (HTTP {e.code})")


def fetch_protein_swissmodel_advanced(uniprot_id: str,
                                      output_dir: str = "./structures",
                                      min_gmqe: float = 0.0,
                                      min_qmean: float = None,
                                      require_full_coverage: bool = False,
                                      fallback_alphafold: bool = True) -> dict:
    """
    Fully automated homology modeling with quality-based selection.

    Workflow:
      1. Query SwissModel Repository for all models
      2. Filter by quality thresholds (GMQE, QMEAN, coverage)
      3. Select best model
      4. If no good model, fallback to AlphaFold DB
      5. Return model + quality report

    Args:
        uniprot_id: UniProt accession (e.g. 'Q9H825')
        output_dir: Directory to save models
        min_gmqe: Minimum GMQE score (0-1, default: 0.0 = no filter)
        min_qmean: Minimum QMEAN Z-score (default: None = no filter)
        require_full_coverage: If True, require coverage >= 0.9
        fallback_alphafold: If True, fallback to AlphaFold when no good model

    Returns:
        dict with keys:
          - path: str (PDB file path)
          - source: 'swissmodel' | 'alphafold' | 'none'
          - provider: str (PDB or SWISSMODEL)
          - template: str
          - gmqe: float | None
          - qmean: float | None
          - identity: float
          - coverage: float
          - quality_grade: 'excellent' | 'good' | 'moderate' | 'poor'
          - all_candidates: list (all models found, sorted by quality)

    Raises:
        ValueError: If no model found and fallback disabled
    """
    uniprot_id = uniprot_id.upper()
    os.makedirs(output_dir, exist_ok=True)

    # ── Step 1: Query all models ────────────────────────────────────
    try:
        all_models = fetch_protein_swissmodel(
            uniprot_id,
            output_path=os.path.join(output_dir, f"{uniprot_id}_swissmodel.pdb"),
            provider_filter='any',
            min_coverage=0.3,
            return_all=True,
        )
    except ValueError:
        all_models = []

    # ── Step 2: Filter by thresholds ────────────────────────────────
    qualified = []
    for m in all_models:
        # GMQE filter
        if min_gmqe > 0 and (m.get('gmqe') is None or m['gmqe'] < min_gmqe):
            continue
        # QMEAN filter
        if min_qmean is not None and (m.get('qmean') is None or m['qmean'] < min_qmean):
            continue
        # Full coverage filter
        if require_full_coverage and m.get('coverage', 0) < 0.9:
            continue
        qualified.append(m)

    # ── Step 3: Select best ─────────────────────────────────────────
    if qualified:
        best = qualified[0]

        # Quality grading
        gmqe = best.get('gmqe')
        qmean = best.get('qmean')
        identity = best.get('identity', 0)
        coverage = best.get('coverage', 0)

        if gmqe is not None and gmqe >= 0.7 and identity >= 0.5:
            grade = 'excellent'
        elif gmqe is not None and gmqe >= 0.5 and identity >= 0.3:
            grade = 'good'
        elif coverage >= 0.5:
            grade = 'moderate'
        else:
            grade = 'poor'

        return {
            'path': best['path'],
            'source': 'swissmodel',
            'provider': best['provider'],
            'template': best.get('template', ''),
            'gmqe': gmqe,
            'qmean': qmean,
            'identity': identity,
            'coverage': coverage,
            'quality_grade': grade,
            'all_candidates': all_models,
        }

    # ── Step 4: Fallback to AlphaFold ─────────────────────────────────
    if fallback_alphafold:
        logger.warning(
            f"[structure_fetch] No qualified SwissModel for {uniprot_id}, "
            f"falling back to AlphaFold"
        )
        try:
            af_path = fetch_protein_alphafold(uniprot_id,
                os.path.join(output_dir, f"AF-{uniprot_id}.pdb"))
            return {
                'path': af_path,
                'source': 'alphafold',
                'provider': 'AlphaFold DB',
                'template': None,
                'gmqe': None,
                'qmean': None,
                'identity': 1.0,  # Self-prediction
                'coverage': 1.0,
                'quality_grade': 'moderate',  # AlphaFold ~ moderate for docking
                'all_candidates': all_models,
            }
        except Exception as e:
            logger.error(f"[structure_fetch] AlphaFold fallback failed: {e}")

    # ── Step 5: Nothing available ───────────────────────────────────
    raise ValueError(
        f"No suitable model for {uniprot_id}. "
        f"Tried SwissModel ({len(all_models)} found, 0 qualified) "
        f"and AlphaFold fallback."
    )


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
        autodock_logger.info(f"PDBreado downloaded: {dest}")
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
            autodock_logger.warning(f"PDB failed ({e}), trying PDB-REDO...")
            try:
                return fetch_protein_pdb_redo(pdb_id, out_path(f"{pdb_id}_redo"))
            except Exception:
                pass
        # Fall through to AlphaFold if PDB both fail
        if uniprot_id:
            autodock_logger.warning(f"PDB/PDBREDO failed, falling back to AlphaFold...")
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
                autodock_logger.warning(f"{src_name} failed ({e})")
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
        autodock_logger.info(f"PubChem: {name} (CID: {cid})")
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
        autodock_logger.info(f"PubChem SDF cached: {cache_sdf} → {output_sdf}")
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
        autodock_logger.info(f"PubChem: {name} (CID: {cid}) → {output_sdf} (cached at {cache_sdf})")
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
                autodock_logger.warning(f"PubChem SDF truncated; RDKit ETKDGv3 generated 3D: {output_sdf}")
                return result
        # RDKit not available: keep output_sdf as-is (degraded but usable)
        result['sdf_path'] = output_sdf
        autodock_logger.warning(f"PubChem: {name} (CID: {cid}) → {output_sdf} (SDF may be incomplete, SMILES OK)")
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
        autodock_logger.info(f"ChEMBL: {result['name']} ({result['chembl_id']})")
        return result

    except urllib.error.HTTPError as e:
        raise DataSourceError(f"ChEMBL not found: HTTP {e.code}")
    except Exception as e:
        raise DataSourceError(f"ChEMBL error: {e}")


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
        source: 'pubchem' | 'chembl' | 'opsin' | 'cactus'
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
    elif source == 'opsin':
        return fetch_molecule_opsin(identifier)
    elif source == 'cactus':
        return fetch_molecule_cactus(identifier)
    else:
        raise ValueError(f"Unknown source: {source} (valid: pubchem, chembl, opsin, cactus)")


def fetch_molecule_opsin(identifier: str) -> dict:
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

        autodock_logger.info(f"OPSIN: {identifier} → {smiles[:50]}...")
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
        autodock_logger.info(f"PubChem fallback: {identifier} → {result['smiles'][:50]}...")
        return result
    except Exception as e2:
        raise ValueError(
            f"Neither OPSIN nor PubChem could resolve '{identifier}'. "
            f"OPSIN requires IUPAC names; PubChem name search also failed ({e2}). "
            f"Try providing a SMILES string directly."
        )


def fetch_molecule_cactus(identifier: str) -> dict:
    """
    Resolve a chemical identifier via NIH CACTUS Chemical Identifier Resolver.

    Supports: name ↔ SMILES ↔ InChI ↔ InChIKey ↔ CAS conversions.
    More robust than OPSIN for common names and generic identifiers.

    Args:
        identifier: Chemical name, SMILES, InChI, InChIKey, or CAS number

    Returns:
        dict with keys: name, smiles, source

    Raises:
        ValueError: if the identifier cannot be resolved
    """
    encoded = urllib.parse.quote(identifier, safe='')
    url = f"https://cactus.nci.nih.gov/chemical/structure/{encoded}/smiles"

    try:
        req = urllib.request.Request(url, headers={'Accept': 'text/plain'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            smiles = resp.read().decode().strip()

        if not smiles or smiles.startswith('Error'):
            raise ValueError(f"CACTUS could not resolve: {identifier}")
        if len(smiles) > 2000:
            raise ValueError(f"CACTUS returned invalid SMILES for: {identifier}")

        autodock_logger.info(f"CACTUS: {identifier} → {smiles[:50]}...")
        return {
            'name': identifier,
            'smiles': smiles,
            'source': 'NIH CACTUS',
        }
    except urllib.error.HTTPError as e:
        # HTTP error from CACTUS — try PubChem fallback
        logger.warning(f"[structure_fetch] CACTUS lookup failed for '{identifier}' (HTTP {e.code}), trying PubChem...")
    except Exception as e:
        logger.warning(f"[structure_fetch] CACTUS error for '{identifier}': {e}, trying PubChem...")

    # ── PubChem fallback ────────────────────────────────────────────────
    try:
        result = fetch_molecule_pubchem(identifier, identifier_type='name')
        result['source'] = f"PubChem (CACTUS fallback for '{identifier}')"
        autodock_logger.info(f"PubChem fallback: {identifier} → {result['smiles'][:50]}...")
        return result
    except Exception as e2:
        raise ValueError(
            f"Neither CACTUS nor PubChem could resolve '{identifier}'. "
            f"CACTUS supports: name, SMILES, InChI, InChIKey, CAS. "
            f"Try providing a SMILES string directly."
        )


# ─── RCSB Chemical Component Dictionary (CCD) ──────────────────────────────────
# PDB Ligand Expo has been retired (2026-02-13); CCD is the official replacement.

def _ccd_cache_dir() -> Path:
    """Get or create the CCD cache directory."""
    cache = Path.home() / ".openclaw" / "structures_cache" / "ccd"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _ccd_cache_key(ligand_id: str) -> Path:
    """Build a cache file path for a CCD query."""
    cache = _ccd_cache_dir()
    return cache / f"{ligand_id.upper()}.json"


def fetch_ligand_ccd(ligand_id: str) -> dict:
    """
    Query RCSB Chemical Component Dictionary (CCD) for ligand information.

    PDB Ligand Expo has been retired (2026-02-13); CCD is the official replacement.
    Provides: name, formula, molecular weight, SMILES, InChI, stereochemistry.

    Args:
        ligand_id: 3-character CCD ID (e.g., 'ATP', 'HEM', 'GOL')

    Returns:
        dict with keys:
          - id, name, formula, formula_weight
          - smiles, inchi, inchi_key
          - stereochemistry (if available)
          - synonyms (list)

    Raises:
        ValueError: if ligand_id invalid or not found
    """
    ligand_id = ligand_id.upper()
    if len(ligand_id) != 3:
        raise ValueError(f"CCD ID must be 3 characters, got: {ligand_id}")

    # Check cache
    cache_key = _ccd_cache_key(ligand_id)
    if cache_key.exists():
        with open(cache_key) as f:
            return json.load(f)

    # RCSB CCD REST API
    url = f"https://data.rcsb.org/rest/v1/core/chemcomp/{ligand_id}"

    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"CCD entry not found: {ligand_id} (HTTP {e.code})")
    except Exception as e:
        raise ValueError(f"CCD query failed: {e}")

    # Extract relevant fields
    chem_comp = data.get('chem_comp', {})
    rcsb = data.get('rcsb_chem_comp_info', {})

    result = {
        'id': chem_comp.get('id', ligand_id),
        'name': chem_comp.get('name', ''),
        'formula': chem_comp.get('formula', ''),
        'formula_weight': chem_comp.get('formula_weight', None),
        'smiles': rcsb.get('smiles', ''),
        'inchi': rcsb.get('inchi', ''),
        'inchi_key': rcsb.get('inchi_key', ''),
        'stereochemistry': rcsb.get('stereochemistry', ''),
        'synonyms': rcsb.get(' synonyms', []),
        'source': 'RCSB CCD',
    }

    # Cache result
    with open(cache_key, 'w') as f:
        json.dump(result, f, indent=2)

    return result


def fetch_ligand_smiles(ligand_id: str) -> str:
    """
    Quick lookup: get SMILES for a CCD ligand.

    Args:
        ligand_id: 3-character CCD ID

    Returns:
        SMILES string, or empty string if not found
    """
    info = fetch_ligand_ccd(ligand_id)
    return info.get('smiles', '')


def fetch_ligand_from_pdb(pdb_id: str, ligand_id: str,
                          output_path: str = None) -> str:
    """
    Download ligand coordinates from a specific PDB entry.

    Uses RCSB ModelServer API to extract the ligand in mmCIF/SDF/MOL format.
    Useful for: redocking validation with native crystal pose.

    Args:
        pdb_id: PDB entry ID (e.g., '1ATP')
        ligand_id: CCD ligand ID (e.g., 'ATP')
        output_path: Where to save the file (default: structures_cache/{pdb_id}_{ligand_id}.sdf)

    Returns:
        Path to downloaded ligand file
    """
    pdb_id = pdb_id.upper()
    ligand_id = ligand_id.upper()

    if output_path is None:
        cache = _ccd_cache_dir()
        output_path = str(cache / f"{pdb_id}_{ligand_id}.sdf")

    # RCSB ModelServer: ligand coordinates in SDF format
    url = f"https://models.rcsb.org/v1/{pdb_id}/ligand?auth_asym_id={ligand_id}&encoding=sdf"

    try:
        urllib.request.urlretrieve(url, output_path)
        if os.path.getsize(output_path) == 0:
            raise ValueError(f"Empty ligand file returned for {pdb_id}/{ligand_id}")
    except Exception as e:
        raise ValueError(f"Ligand download failed for {pdb_id}/{ligand_id}: {e}")

    autodock_logger.info(f"Ligand {ligand_id} from {pdb_id}: {output_path}")
    return output_path


# ─── SwissModel REST API Token Management ────────────────────────────────────

import json as _json  # Avoid conflict with json module import below

_SWISSMODEL_TOKEN_FILE = Path.home() / ".openclaw" / "swissmodel_token.json"


def swissmodel_get_token(username: str = None, password: str = None) -> str:
    """
    Get or refresh SwissModel REST API Token.

    If username/password provided, fetches new token from SwissModel.
    Otherwise, tries to load cached token from ~/.openclaw/swissmodel_token.json

    Args:
        username: SwissModel/Expasy username (optional)
        password: SwissModel/Expasy password (optional)

    Returns:
        API token string

    Raises:
        ValueError: If no cached token and no credentials provided
        RuntimeError: If token fetch fails
    """
    # Check cache
    if _SWISSMODEL_TOKEN_FILE.exists() and not (username and password):
        with open(_SWISSMODEL_TOKEN_FILE) as f:
            cached = _json.load(f)
            token = cached.get('token')
            if token:
                return token

    # Need credentials
    if not (username and password):
        raise ValueError(
            "No cached SwissModel token found. "
            "Please provide username and password, or register at "
            "https://swissmodel.expasy.org and get API credentials."
        )

    # Fetch new token
    url = "https://swissmodel.expasy.org/api-token-auth/"
    payload = {"username": username, "password": password}
    headers = {"Content-Type": "application/json"}

    try:
        req = urllib.request.Request(
            url,
            data=_json.dumps(payload).encode(),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
            token = data.get("token")
            if not token:
                raise RuntimeError(f"Token response missing 'token' field: {data}")
    except Exception as e:
        raise RuntimeError(f"SwissModel token fetch failed: {e}")

    # Cache token
    _SWISSMODEL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_SWISSMODEL_TOKEN_FILE, 'w') as f:
        _json.dump({"token": token}, f)

    autodock_logger.info(f"SwissModel token cached: {_SWISSMODEL_TOKEN_FILE}")
    return token


def swissmodel_clear_token() -> None:
    """Clear cached SwissModel token."""
    if _SWISSMODEL_TOKEN_FILE.exists():
        _SWISSMODEL_TOKEN_FILE.unlink()
        autodock_logger.info("SwissModel token cleared")


def swissmodel_submit_alignment(token: str,
                                 target_sequence: str,
                                 template_pdb: str,
                                 template_chain: str,
                                 template_sequence: str = None,
                                 template_offset: int = 0,
                                 project_title: str = None) -> dict:
    """
    Submit a homology modeling job to SwissModel REST API.

    Note: This requires a valid API token (get via swissmodel_get_token).
    The alignment API requires PRE-DETERMINED template information —
    use fetch_protein_swissmodel_advanced() for automatic template search.

    Args:
        token: SwissModel API token
        target_sequence: Target protein sequence (FASTA string)
        template_pdb: Template PDB ID
        template_chain: Template chain name
        template_sequence: Template sequence (optional, fetched if None)
        template_offset: Offset of template sequence in seqres
        project_title: Project name (optional)

    Returns:
        dict with job_id, status_url, etc.

    Raises:
        RuntimeError: If submission fails
    """
    import base64

    # Fetch template sequence if not provided
    if template_sequence is None:
        try:
            # Get sequence from RCSB
            seq_url = f"https://data.rcsb.org/rest/v1/core/polymer_entity/{template_pdb}/{template_chain}"
            req = urllib.request.Request(seq_url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
                template_sequence = data.get('entity_poly', {}).get('pdbx_seq_one_letter_code', '')
        except Exception as e:
            raise RuntimeError(f"Could not fetch template sequence for {template_pdb}.{template_chain}: {e}")

    # Build alignment data
    alignment_data = {
        "target_sequences": target_sequence,
        "template_sequence": template_sequence,
        "template_seqres_offset": template_offset,
        "pdb_id": template_pdb,
        "auth_asym_id": template_chain,
    }
    if project_title:
        alignment_data["project_title"] = project_title

    # Submit
    url = "https://swissmodel.expasy.org/alignment/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {token}"
    }

    try:
        req = urllib.request.Request(
            url,
            data=_json.dumps(alignment_data).encode(),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f"SwissModel alignment submission failed: {e}")

    autodock_logger.info(f"SwissModel alignment submitted: {result.get('project_id', 'N/A')}")
    return result


def swissmodel_check_status(token: str, project_id: str) -> dict:
    """
    Check status of a SwissModel alignment job.

    Args:
        token: SwissModel API token
        project_id: Project ID from submission

    Returns:
        dict with status, models, etc.
    """
    url = f"https://swissmodel.expasy.org/project/{project_id}/models/"
    headers = {"Authorization": f"Token {token}"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return _json.loads(resp.read())
    except Exception as e:
        raise RuntimeError(f"Status check failed: {e}")


def swissmodel_download_result(token: str, project_id: str, model_id: str,
                               output_path: str) -> str:
    """
    Download a completed SwissModel result.

    Args:
        token: SwissModel API token
        project_id: Project ID
        model_id: Model ID (from status check)
        output_path: Where to save the PDB file

    Returns:
        Path to downloaded PDB file
    """
    url = f"https://swissmodel.expasy.org/project/{project_id}/models/{model_id}/"
    headers = {"Authorization": f"Token {token}"}

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
            download_url = data.get('coordinates')
            if not download_url:
                raise ValueError("No download URL in response")

        urllib.request.urlretrieve(download_url, output_path)
        autodock_logger.info(f"SwissModel result: {output_path}")
        return output_path
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}")


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
