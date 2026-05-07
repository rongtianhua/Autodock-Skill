"""
Autodock ADMET Module
=====================
ADMET property prediction: Neurosnap API, ADMETlab browser, RDKit fallback.
"""
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors, AllChem

from autodock._core import autodock_logger, _HAVE_RDKIT

# Backward-compat logger alias
logger = autodock_logger

def predict_admet(smiles_list: list[str],
                use_remote: bool = True,
                timeout: int = 120) -> pd.DataFrame | None:
    """
    Predict ADMET properties for a list of compounds.

    Tries three paths in order:
      1. ADMET-AI (Neurosnap) — fast REST API, 99 columns, ~1-5s
      2. ADMETlab 3.0 web via Playwright — 122 columns, ~20-30s
      3. Local RDKit — always works, curated subset, instant

    Args:
        smiles_list: List of SMILES strings
        use_remote: If False, skip remote calls and use RDKit only
        timeout: Total timeout in seconds (default 120)

    Returns:
        DataFrame with ADMET columns. Schema varies by source:
          - ADMET-AI: 99 columns (molecular_weight, logP, hbond_acceptors,
            hbond_donors, Lipinski, QED, CYP1A2_Veith, CYP2C19_Veith,
            CYP2D6_Veith, CYP3A4_Veith, hERG, BBB_Martins, HIA_Hou,
            AMES, DILI, ClinTox, Carcinogens, PAMPA_NCATS, ...)
          - ADMETlab web (Playwright): 122 columns, same endpoints
          - RDKit: SMILES, MW, LogP, TPSA, HBD, HBA, RotatableBonds,
            QED, LipinskiViolations, VeberCompliant, PAINSAlert,
            BBB_penetration, hERG_risk, CYP3A4_inhibitor, source
        Returns None if all methods fail.
    """
    if not _HAVE_RDKIT:
        logger.error("[autodock] RDKit not available for ADMET prediction")
        return None

    if not smiles_list:
        return None

    # ── Path 1: ADMET-AI (Neurosnap) — fast REST API ────────────────
    if use_remote:
        try:
            df = _predict_admet_neurosnap(smiles_list, timeout=min(timeout, 60))
            if df is not None and len(df) > 0:
                logger.info(f"[autodock] ADMET-AI (Neurosnap): {len(df)} compounds, "
                            f"{len(df.columns)} columns")
                return df
        except Exception as e:
            logger.warning(f"[autodock] ADMET-AI failed ({e}), trying Playwright")

    # ── Path 2: ADMETlab via Playwright browser → CSV ───────────────
    if use_remote:
        try:
            csv_path = _run_admetlab_browser(smiles_list, timeout=min(timeout, 60))
            if csv_path:
                df = _parse_admetlab_csv(csv_path)
                if df is not None and len(df) > 0:
                    logger.info(f"[autodock] ADMETlab browser: {len(df)} compounds, "
                                f"{len(df.columns)} columns")
                    return df
        except Exception as e:
            logger.warning(f"[autodock] ADMETlab browser failed ({e}), using RDKit")

    # ── Path 3: Local RDKit ─────────────────────────────────────────
    return _predict_admet_rdkit(smiles_list)


def _predict_admet_neurosnap(smiles_list: list[str], timeout: int = 60) -> pd.DataFrame | None:
    """
    Predict ADMET via ADMET-AI on Neurosnap (https://neurosnap.ai).

    Workflow:
      1. Submit job via POST /api/job/submit/ADMET-AI (multipart, JSON molecules)
      2. Poll /api/job/status/<job_id> until 'completed'
      3. Download /api/job/file/<job_id>/out/results.csv

    API key is read from the ADMETLAB_API_KEY environment variable,
    or ~/.openclaw/keys/neurosnap_api_key.

    Returns DataFrame with 99 columns (molecular_weight, logP, CYP, hERG, etc.)
    or None if the call fails.
    """
    import json, time, os, urllib.request, urllib.error

    # Resolve API key
    api_key = os.environ.get('ADMETLAB_API_KEY') or _load_neurosnap_key()
    if not api_key:
        logger.debug("[autodock] No Neurosnap API key found")
        return None

    endpoint = 'https://neurosnap.ai'

    # Build multipart body — "Input Molecules" field with JSON array of SMILES
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    molecules = [{'data': smi.strip(), 'type': 'smiles'} for smi in smiles_list if smi.strip()]
    body = (f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="Input Molecules"\r\n\r\n'
            f'{json.dumps(molecules)}\r\n'
            f'--{boundary}--\r\n').encode()

    # Submit job
    try:
        req = urllib.request.Request(
            f'{endpoint}/api/job/submit/ADMET-AI',
            data=body,
            headers={
                'X-API-KEY': api_key,
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'User-Agent': 'curl/7.70+',
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            job_id = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[autodock] Neurosnap job submit failed: {e}")
        return None

    # Poll until done
    status_url = f'{endpoint}/api/job/status/{job_id}'
    poll_req = urllib.request.Request(status_url, headers={'X-API-KEY': api_key, 'User-Agent': 'curl/7.70+'})
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(poll_req, timeout=10) as r:
                status = json.loads(r.read())
            if status == 'completed':
                break
            elif status in ('failed', 'deleted', 'cancelled'):
                logger.warning(f"[autodock] Neurosnap job {status}: {job_id}")
                return None
        except Exception as e:
            logger.warning(f"[autodock] Neurosnap status poll error: {e}")
            return None
        time.sleep(2)
    else:
        logger.warning(f"[autodock] Neurosnap job timed out after {timeout}s")
        return None

    # Download results CSV
    csv_url = f'{endpoint}/api/job/file/{job_id}/out/results.csv'
    try:
        csv_req = urllib.request.Request(csv_url, headers={'X-API-KEY': api_key, 'User-Agent': 'curl/7.70+'})
        with urllib.request.urlopen(csv_req, timeout=30) as r:
            csv_data = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        logger.warning(f"[autodock] Neurosnap CSV download failed: {e}")
        return None

    # Parse CSV
    import io as _io
    try:
        df = pd.read_csv(_io.StringIO(csv_data))
    except Exception as e:
        logger.warning(f"[autodock] Failed to parse Neurosnap CSV: {e}")
        return None

    if df.empty:
        return None

    # Normalise: lowercase column names, add source tag
    df.columns = [str(c).strip().lower() for c in df.columns]
    # 'molecule' column holds SMILES
    if 'molecule' in df.columns:
        df = df.rename(columns={'molecule': 'smiles'})
    df['source'] = 'admet_ai'

    return df


def _load_neurosnap_key() -> str | None:
    """Load Neurosnap API key from ~/.openclaw/keys/neurosnap_api_key."""
    key_file = os.path.expanduser('~/.openclaw/keys/neurosnap_api_key')
    try:
        with open(key_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _run_admetlab_browser(smiles_list: list[str], timeout: int = 60) -> str | None:
    """
    Run ADMETlab 3.0 via Playwright browser automation.
    Submits the SMILES list through the web form, waits for the result page,
    parses the CSV URL from the HTML, and returns the CSV file path.

    Returns path to the downloaded CSV file ( caller must delete it ), or None.
    """
    import subprocess, tempfile, os

    node_script = os.path.join(os.path.dirname(__file__), 'tools', 'admetlab_web.js')
    if not os.path.exists(node_script):
        logger.warning(f"[autodock] admetlab_web.js not found at {node_script}")
        return None

    # Write SMILES to a temp file (one per line)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.smi', delete=False) as f:
        f.write('\n'.join(smiles_list))
        smiles_file = f.name

    tmp_csv = tempfile.mktemp(suffix='.csv')

    try:
        result = subprocess.run(
            ['node', node_script, '--csv', tmp_csv, '--smiles-file', smiles_file],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
            cwd=os.path.dirname(node_script)
        )
        if result.returncode != 0:
            logger.warning(f"[autodock] admetlab_web.js failed: {result.stderr[:200]}")
            return None

        if os.path.exists(tmp_csv) and os.path.getsize(tmp_csv) > 100:
            return tmp_csv
        else:
            logger.warning(f"[autodock] admetlab_web.js returned empty or no file")
            return None
    except subprocess.TimeoutExpired:
        logger.warning(f"[autodock] admetlab_web.js timed out after {timeout}s")
        return None
    finally:
        try: os.unlink(smiles_file)
        except: pass


def _parse_admetlab_csv(csv_path: str) -> pd.DataFrame | None:
    """Parse ADMETlab CSV into a normalised DataFrame."""
    try:
        # ADMETlab CSV may use comma or tab as separator; try comma first
        try:
            df = pd.read_csv(csv_path, sep=',')
        except Exception:
            df = pd.read_csv(csv_path, sep='\t')
        os.unlink(csv_path)
    except Exception:
        return None

    if df.empty:
        return None

    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]

    # Normalise: if there's a 'smiles' col and also 'raw_smiles', keep only 'smiles'
    if 'raw_smiles' in df.columns and 'smiles' in df.columns:
        df = df.drop(columns=['raw_smiles'])

    # Lower-case the source column
    if 'source' in df.columns:
        df['source'] = df['source'].astype(str).str.lower().str.strip()

    return df


def _predict_admet_rdkit(smiles_list: list[str]) -> pd.DataFrame:
    """Local RDKit ADMET calculation — always available fallback."""
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors
    from rdkit.Chem.QED import qed
    from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams

    results = []
    for smi in smiles_list:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            results.append({'SMILES': smi, 'source': 'error', 'error': 'Invalid SMILES',
                            'MW': None, 'LogP': None, 'TPSA': None})
            continue

        params = FilterCatalogParams()
        params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        catalog = FilterCatalog(params)
        entry = catalog.GetFirstMatch(mol)

        mw   = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        hbd  = Lipinski.NumHDonors(mol)
        hba  = Lipinski.NumHAcceptors(mol)
        tpsa = Descriptors.TPSA(mol)
        rot  = Lipinski.NumRotatableBonds(mol)
        violations = sum([mw > 500, logp > 5, hbd > 5, hba > 10])
        veber = rot <= 10 and tpsa <= 140
        herg_risk = (logp > 4 and tpsa < 75)  # conservative proxy

        results.append({
            'SMILES': smi,
            'MW': round(mw, 2),
            'LogP': round(logp, 2),
            'TPSA': round(tpsa, 1),
            'HBD': hbd,
            'HBA': hba,
            'RotatableBonds': rot,
            'QED': round(qed(mol), 3),
            'LipinskiViolations': violations,
            'VeberCompliant': veber,
            'PAINSAlert': entry.GetDescription() if entry else None,
            'BBB_penetration': 'High' if (logp > 0 and tpsa < 90) else 'Low',
            'hERG_risk': herg_risk,
            'CYP3A4_inhibitor': None,
            'FractionCSP3': round(rdMolDescriptors.CalcFractionCSP3(mol), 3),
            'NumRings': rdMolDescriptors.CalcNumRings(mol),
            'NumAromaticRings': rdMolDescriptors.CalcNumAromaticRings(mol),
            'NumAliphaticRings': rdMolDescriptors.CalcNumAliphaticRings(mol),
            'NumHeteroatoms': rdMolDescriptors.CalcNumHeteroatoms(mol),
            'FormalCharge': Chem.GetFormalCharge(mol),
            'HeavyAtomCount': mol.GetNumHeavyAtoms(),
            'SlogP_VSA': round(Descriptors.SlogP_VSA1(mol) + Descriptors.SlogP_VSA2(mol) + Descriptors.SlogP_VSA3(mol), 2),
            'RuleOf3_compliant': (mw <= 300 and logp <= 3 and hbd <= 3 and hba <= 3 and rot <= 3),
            'Pfizer_3_75_alert': (logp > 3 and tpsa < 75),
            'source': 'local_rdkit',
        })

    df = pd.DataFrame(results)
    logger.info(f"[autodock] Local RDKit ADMET: {len(df)} compounds calculated")
    return df


def filter_admet(df: pd.DataFrame,
                 max_lipinski_violations: int = 1,
                 min_qed: float = 0.5,
                 max_herg_risk: bool = False,
                 filter_pains: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Apply ADMET drug-likeness filters to a DataFrame from predict_admet().

    Args:
        df: DataFrame from predict_admet() with SMILES column
        max_lipinski_violations: Max allowed Lipinski violations (default 1)
        min_qed: Minimum QED score (default 0.5)
        max_herg_risk: If True, reject compounds flagged as hERG risk
        filter_pains: If True, reject PAINS-flagged compounds

    Returns:
        (passed_df, failed_df) — both retain all original columns plus 'filter_reason'
    """
    if 'SMILES' not in df.columns:
        raise ValueError("DataFrame must have 'SMILES' column")

    df = df.copy()
    df['filter_reason'] = None

    # Lipinski
    mask_lipinski = df['LipinskiViolations'] <= max_lipinski_violations
    df.loc[~mask_lipinski, 'filter_reason'] = \
        df.loc[~mask_lipinski, 'filter_reason'].apply(
            lambda x: f"Lipinski violations: {x['LipinskiViolations']}" if x else f"Lipinski violations: {df.loc[~mask_lipinski, 'LipinskiViolations'].values[0]}")
    # QED
    mask_qed = df['QED'] >= min_qed
    df.loc[~mask_qed, 'filter_reason'] = df.loc[~mask_qed, 'filter_reason'].apply(
        lambda x: f"QED {x['QED']:.2f} < {min_qed}" if x and x else f"QED below threshold")
    # Veber
    mask_veber = df.get('VeberCompliant', pd.Series([True]*len(df)))
    # hERG: safe bool conversion to avoid ~ on bool deprecation warning
    herg_series = df.get('hERG_risk', pd.Series([False]*len(df)))
    herg_is_true = herg_series.astype(int).astype(bool)
    mask_herg = ~herg_is_true if max_herg_risk else pd.Series([True]*len(df), index=df.index)
    # PAINS: only filter if filter_pains=True
    mask_pains = df['PAINSAlert'].isna() if filter_pains else pd.Series([True]*len(df), index=df.index)

    mask_pass = mask_lipinski & mask_qed & mask_veber & mask_herg & mask_pains

    df.loc[~mask_lipinski, 'filter_reason'] = \
        'Lipinski violations: ' + df.loc[~mask_lipinski, 'LipinskiViolations'].astype(str)
    df.loc[~mask_qed, 'filter_reason'] = \
        'QED=' + df.loc[~mask_qed, 'QED'].round(2).astype(str) + f' < {min_qed}'
    if filter_pains:
        df.loc[~mask_pains, 'filter_reason'] = \
            'PAINS alert: ' + df.loc[~mask_pains, 'PAINSAlert'].fillna('').astype(str)
    if max_herg_risk:
        df.loc[~mask_herg, 'filter_reason'] = 'hERG risk'

    passed = df[mask_pass].copy()
    failed = df[~mask_pass].copy()

    logger.info(f"[autodock] ADMET filter: {len(passed)}/{len(df)} passed "
                f"(Lipinski≤{max_lipinski_violations}, QED≥{min_qed}, "
                f"hERG_risk={max_herg_risk}, PAINS={filter_pains})")
    return passed, failed


# ─────────────────────────────────────────────────────────────────────────────
# P1-5: VIRTUAL SCREENING STATISTICS — Enrichment Metrics
# ─────────────────────────────────────────────────────────────────────────────

