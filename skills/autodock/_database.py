"""
Autodock Database Module
========================
Compound database access: ZINC22 virtual screening library, bioactivity queries.
"""
import os
import re
import gzip
import urllib.request
import json
from pathlib import Path
from typing import Optional

import pandas as pd
from rdkit import Chem

from autodock._core import autodock_logger

# Backward-compat logger alias
logger = autodock_logger

def fetch_bioactivities(
    target_chembl_id: str,
    standard_types: tuple = ("IC50", "Ki", "EC50", "Kd"),
    min_pchembl: float = None,
    cache_file: str = None,
    timeout: int = 10,
) -> dict:
    """
    Fetch bioactivity records for a target from ChEMBL.

    Retrieves published IC50/Ki/EC50/Kd data with SMILES for a given
    ChEMBL target ID. Results are cached to cache_file (JSON) on success.
    """
    import json as _json, os as _os, requests as _requests
    if cache_file and _os.path.exists(cache_file):
        logger.info(f"[autodock] Loading cached bioactivities from {cache_file}")
        with open(cache_file) as f:
            return _json.load(f)
    base_url = "https://www.ebi.ac.uk/chembl/api/data"
    headers = {"Accept": "application/json"}
    try:
        tgt_resp = _requests.get(f"{base_url}/target/{target_chembl_id}.json",
                                headers=headers, timeout=timeout)
        tgt_resp.raise_for_status()
        target_name = tgt_resp.json().get("pref_name", target_chembl_id)
    except Exception as e:
        logger.warning(f"[autodock] Could not fetch target name for {target_chembl_id}: {e}")
        target_name = target_chembl_id
    all_activities, offset, page_size = [], 0, 1000
    while True:
        params = {"target_chembl_id": target_chembl_id, "limit": page_size, "offset": offset}
        if standard_types:
            params["standard_type"] = ",".join(standard_types)
        try:
            resp = _requests.get(f"{base_url}/activity.json", params=params,
                               headers=headers, timeout=timeout)
            resp.raise_for_status()
            page = resp.json().get("activities", [])
        except Exception as e:
            logger.warning(f"[autodock] ChEMBL API error at offset {offset}: {e}")
            break
        if not page:
            break
        all_activities.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    smiles_to_id, smiles_to_pchembl, smiles_to_type = {}, {}, {}
    for rec in all_activities:
        smiles = rec.get("canonical_smiles")
        if not smiles:
            continue
        pchembl = rec.get("pchembl_value")
        stype = rec.get("standard_type", "")
        if standard_types and stype not in standard_types:
            continue
        if min_pchembl is not None:
            if pchembl is None:
                continue
            try:
                if float(pchembl) < min_pchembl:
                    continue
            except (TypeError, ValueError):
                continue
        existing = smiles_to_pchembl.get(smiles)
        if existing is None or (pchembl is not None and float(pchembl) > float(existing)):
            smiles_to_pchembl[smiles] = pchembl
            smiles_to_id[smiles] = rec.get("molecule_chembl_id", "")
            smiles_to_type[smiles] = stype
    result = {"smiles_to_id": smiles_to_id, "smiles_to_pchembl": smiles_to_pchembl,
              "smiles_to_type": smiles_to_type, "target_name": target_name,
              "count": len(smiles_to_pchembl)}
    if cache_file:
        try:
            with open(cache_file, "w") as f:
                _json.dump(result, f)
            logger.info(f"[autodock] Cached {result['count']} activities to {cache_file}")
        except Exception as e:
            logger.warning(f"[autodock] Could not write cache file: {e}")
    logger.info(f"[autodock] fetch_bioactivities: {result['count']} unique active compounds for {target_name}")
    return result

def compute_enrichment(screened_smiles: list, bioactivity_data: dict,
                       decoy_smiles: list = None, threshold_pchembl: float = 6.0) -> dict:
    """
    Compute enrichment statistics (AUC, BEDROC, EF) for virtual screening results.
    """
    import numpy as np
    from scipy import stats as scipy_stats
    n_total = len(screened_smiles)
    if n_total == 0:
        return {"error": "No screened compounds provided"}
    active_smiles = set(bioactivity_data["smiles_to_pchembl"].keys())
    smiles_to_id = bioactivity_data["smiles_to_id"]
    is_active = np.array([s in active_smiles for s in screened_smiles], dtype=bool)
    n_active = int(is_active.sum())
    n_decoys = len(decoy_smiles) if decoy_smiles else (n_total - n_active)
    if n_active == 0:
        return {"n_screened": n_total, "n_active": 0, "n_decoys": n_decoys,
                "enrichment_factors": {}, "auc": 0.5, "bedroc": 0.0, "ef_1pct": 0.0,
                "ef_5pct": 0.0, "ef_10pct": 0.0, "n_hits_top50": 0, "n_hits_top1pct": 0,
                "active_names": {}, "recall_top10pct": 0.0,
                "note": "No active compounds found in screened library"}
    active_names = {s: smiles_to_id.get(s, "") for s in screened_smiles if s in active_smiles}
    y_true = is_active.astype(int)
    y_score = np.arange(n_total, 0, -1, dtype=float)
    auc = float(scipy_stats.roc_auc_score(y_true, y_score))
    alpha, m = 20.0, n_active
    r_i = np.where(is_active)[0] + 1
    def _bedroc(ranks, n, m, alpha):
        if m == 0 or n == 0:
            return 0.0
        s = sum(np.exp(-alpha * ri / n) for ri in ranks)
        random_sum = (1 - np.exp(-alpha)) / (n * (1 - np.exp(-alpha / n)))
        return s / (m * random_sum) if random_sum else 0.0
    bedroc = _bedroc(r_i, n_total, m, alpha)
    def ef_at_fraction(frac):
        k = max(1, int(np.ceil(n_total * frac)))
        hits_topk = int(is_active[:k].sum())
        return float((hits_topk / m) / frac) if m > 0 else 0.0
    enrichment_factors = {frac: ef_at_fraction(frac) for frac in [0.005, 0.01, 0.02, 0.05, 0.10]}
    k_50 = min(50, n_total)
    top1pct_k = max(1, int(np.ceil(n_total * 0.01)))
    top10pct_k = max(1, int(np.ceil(n_total * 0.10)))
    recall_top10pct = float(is_active[:top10pct_k].sum()) / m if m > 0 else 0.0
    return {"n_screened": n_total, "n_active": n_active, "n_decoys": n_decoys,
            "enrichment_factors": enrichment_factors, "auc": auc, "bedroc": bedroc,
            "ef_1pct": enrichment_factors[0.01], "ef_5pct": enrichment_factors[0.05],
            "ef_10pct": enrichment_factors[0.10],
            "n_hits_top50": int(is_active[:k_50].sum()),
            "n_hits_top1pct": int(is_active[:top1pct_k].sum()),
            "active_names": active_names, "recall_top10pct": recall_top10pct}

def print_enrichment_report(stats: dict, target_name: str = None):
    """Print a formatted enrichment statistics report."""
    if "error" in stats:
        autodock_logger.error(f"Enrichment error: {stats['error']}")
        return
    sep = "=" * 55
    hdr = "Enrichment Statistics"
    if target_name:
        hdr = f"Enrichment Statistics — {target_name}"
    auc_val = stats["auc"]
    auc_label = "Excellent" if auc_val > 0.9 else "Good" if auc_val > 0.8 else "Fair" if auc_val > 0.7 else "Poor"
    print(f"\n{sep}\n  {hdr}\n{sep}")
    print(f"  Screened compounds : {stats['n_screened']}")
    print(f"  Confirmed actives  : {stats['n_active']} ({100*stats['n_active']/max(stats['n_screened'],1):.1f}%)")
    print(f"  Decoys / inactives : {stats['n_decoys']}")
    print(f"\n  -- Global Ranking ----------------------------------------")
    print(f"  AUC               : {stats['auc']:.4f}  ({auc_label})")
    print(f"  BEDROC (alpha=20)  : {stats['bedroc']:.4f}")
    print(f"\n  -- Enrichment Factors ------------------------------------")
    for frac, ef in stats["enrichment_factors"].items():
        label = f"EF@{int(frac*100)}%"
        bar = "#" * min(int(ef), 20) if ef > 0 else ""
        print(f"  {label:<10} : {ef:6.2f}x  {bar}")
    print(f"\n  -- Early Enrichment --------------------------------------")
    print(f"  Top 50 hits        : {stats['n_hits_top50']} active compounds")
    print(f"  Top 1% hits        : {stats['n_hits_top1pct']} active compounds")
    print(f"  Recall @ top 10%   : {100*stats['recall_top10pct']:.1f}% of all actives found")
    print(f"{sep}\n")


# ─────────────────────────────────────────────────────────────────────────────
# ZINC22 Compound Database Access
# ─────────────────────────────────────────────────────────────────────────────

_ZINC22_BASE = "https://files.docking.org/zinc22"
_ZINC_GENERATIONS = ["a","b","c","d","e","f","g"]   # g = ZINC20 in stock (newest)

def parse_zinc_tranche(tranche_code: str) -> dict | None:
    """
    Parse a ZINC tranche code into physicochemical properties.

    Tranche format: H##P###M###-phase
      H##   = H-bond donor count (0–29)
      P###  = LogP × 10 (integer, e.g. P035 = 3.5)
      M###  = molecular weight in Da
      phase = reactivity classification (0=stable, 1=reactive, ...)

    Example: H05P035M400-0
      → h_donors=5, logp=3.5, mw=400, phase=0

    Returns None if the tranche code cannot be parsed.
    """
    import re
    m = re.match(r"H(\d+)P(\d+)M(\d+)-(\d+)", str(tranche_code))
    if not m:
        return None
    return {
        "h_donors": int(m.group(1)),
        "logp": int(m.group(2)) / 10.0,
        "mw": int(m.group(3)),
        "phase": int(m.group(4)),
    }


def _zinc_tranche_url(generation: str, h_donors: int, logp: float, mw: int,
                      suffix: str = "N.g.smi.gz") -> str:
    """
    Build a ZINC22 tranche URL for a specific property combination.

    Args:
        generation: ZINC22 generation letter (e.g. "g" for ZINC20 in stock)
        h_donors:   H-bond donor count (0–29)
        logp:       Partition coefficient (used to find P### subdir)
        mw:         Molecular weight in Da (used for MW branch)
        suffix:     File suffix: "N.g.smi.gz" (neutral), "L.g.smi.gz" (acid),
                   "M.g.smi.gz" (base), "O.g.smi.gz" (other)
                   NOTE: Only .smi.gz exists; .txt.gz does NOT exist.
    Returns:
        Full HTTPS URL to the tranche file
    """
    h_str = f"H{h_donors:02d}"
    # LogP branch: H##/H##P###/H##P###-N.g.smi.gz (primary, dense coverage)
    p_str = f"P{int(round(logp * 10)):03d}"
    url_logp = (
        f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{h_str}{p_str}/"
        f"{h_str}{p_str}-{suffix}"
    )
    return url_logp


def sample_zinc_compounds(n: int = 100,
                          h_donors_range: tuple[int, int] = (0, 5),
                          logp_range: tuple[float, float] = (-2, 5),
                          mw_range: tuple[int, int] = (150, 500),
                          generation: str = "g",
                          output_csv: str = None,
                          verbose: bool = True,
                          n_workers: int = 4) -> pd.DataFrame:
    """
    Sample purchasable drug-like compounds from ZINC22 by property criteria.

    ZINC22 tranche files are at:
      https://files.docking.org/zinc22/zinc-22{gen}/{H##}/{H##M###}/{H##M###}-{suffix}.smi.gz
      (MW branch — also available via LogP branch at {H##P###}/{H##P###}-{suffix})

    Each .smi.gz file contains SMILES and ZINC IDs (tab-separated, one per line).
    Property-filtered sampling is performed by scanning tranche directories and
    randomly drawing compounds.  Network I/O is parallelized (default 4 workers).

    Args:
        n:               Target number of sampled compounds.
        h_donors_range:  (min, max) H-bond donor count (inclusive, 0–29).
        logp_range:      (min, max) LogP (inclusive).
        mw_range:        (min, max) molecular weight in Da (inclusive).
        generation:      ZINC22 generation: "g" = ZINC20 in stock (default, ~130M
                         purchasable). Use older letters for historical tranches.
        output_csv:      Optional CSV save path.
        verbose:         Print progress messages.
        n_workers:       Number of concurrent HTTP workers (default 4).

    Returns:
        DataFrame with columns: zinc_id, smiles, h_donors, logp, mw, tranche_url.

    Note:
        ZINC22 contains 230M+ purchasable compounds.  With n_workers=4 and
        ~2.5s per HTTP request, 60 tranche files complete in ~15s.

    Example:
        >>> df = sample_zinc_compounds(n=50, mw_range=(250, 400), logp_range=(2, 4))
        >>> print(df.head())
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import gzip
    import re
    import urllib.request
    import random

    def fetch(url: str, timeout: int = 12) -> str | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.70+"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return gzip.decompress(resp.read()).decode("utf-8", "ignore") if resp.status == 200 else None
        except Exception:
            return None

    h_min, h_max = h_donors_range
    p_min = int(round(logp_range[0] * 10))
    p_max = int(round(logp_range[1] * 10))
    mw_min, mw_max = mw_range

    if verbose:
        logger.info(f"[autodock] ZINC22 sampling: gen={generation}, H={h_min}-{h_max}, "
                    f"LogP={logp_range[0]:.1f}–{logp_range[1]:.1f}, MW={mw_min}–{mw_max}, "
                    f"target={n}, workers={n_workers}")

    url_pool = []

    # Build targeted URL pool
    # zinc-22g has H04–H29; clamp h loop to that intersection
    h_start = max(h_min, 4)
    h_end = max(h_max + 1, h_start + 1, 4)
    for h in range(h_start, min(h_end, 30)):
        for p in range(p_min, min(p_max + 1, 60), 10):
            for mw_b in range((mw_min // 100) * 100,
                              min((mw_max // 100 + 1) * 100 + 100, 1000), 100):
                h_str = f"H{h:02d}"
                p_str = f"H{h:02d}P{p:03d}"
                mw_str = f"M{mw_b:03d}"
                for suffix in ["N.g.smi.gz", "L.g.smi.gz", "M.g.smi.gz", "O.g.smi.gz"]:
                    # LogP branch: H##/H##P###/H##P###-N.g.smi.gz
                    # (ZINC22 main index; .txt.gz does NOT exist, must use .smi.gz)
                    url_logp = (
                        f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{p_str}/"
                        f"{p_str}-{suffix}"
                    )
                    url_pool.append(url_logp)
                    # MW branch: H##/H##M###/H##M###-N.g.smi.gz
                    # (coarser bucketing by MW; only M000/M100 exist at H05 level)
                    url_mw = (
                        f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{h_str}{mw_str}/"
                        f"{h_str}{mw_str}-{suffix}"
                    )
                    url_pool.append(url_mw)

    random.shuffle(url_pool)
    if verbose:
        logger.info(f"[autodock] ZINC22: built {len(url_pool)} candidate URLs (LogP + MW branches)")

    collected = []

    def parse_tranche_props(url: str):
        """Extract (h_donors, logp, mw) from ZINC22 tranche URL.
        
        URL patterns:
          .../H{h}P{p}/H{h}P{p}-{suffix}  → LogP branch: h_donors=h, logp=p/10, mw=None
          .../H{h}/H{h}M{m}/H{h}M{m}-{suffix}  → MW branch: h_donors=h, mw=m*100, logp=None
        """
        logp_m = re.search(r"/H(\d+)P(\d+)/", url)   # LogP branch: /H{h}P{p}/
        mw_m   = re.search(r"/H(\d+)M(\d+)/", url)   # MW branch: /H{h}M{m}/
        if logp_m:
            h, p = int(logp_m.group(1)), int(logp_m.group(2))
            return h, p / 10.0, None   # MW not encoded in LogP branch URL
        if mw_m:
            h, m_val = int(mw_m.group(1)), int(mw_m.group(2))
            return h, None, m_val * 100   # LogP not encoded in MW branch URL
        return 4, None, None   # zinc-22g default, unknown properties

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(fetch, url, 12): url for url in url_pool[:48]}
        for fut in as_completed(futures):
            if len(collected) >= n:
                for f in futures:
                    f.cancel()
                break
            url = futures[fut]
            txt = fut.result()
            if not txt:
                continue
            valid_lines = [l.strip() for l in txt.splitlines() if l.strip() and "	" in l]
            if not valid_lines:
                continue
            td_h, td_p, td_m = parse_tranche_props(url)
            sample_n = min(len(valid_lines), max(1, n - len(collected)))
            for line in random.sample(valid_lines, min(sample_n, len(valid_lines))):
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                collected.append({
                    "zinc_id": parts[1].strip(),
                    "smiles": parts[0].strip(),
                    "h_donors": td_h,
                    "logp": td_p,
                    "mw": td_m,
                    "tranche_url": url,
                })

    df = pd.DataFrame(collected[:n])
    if output_csv and len(df):
        df.to_csv(output_csv, index=False)
        if verbose:
            logger.info(f"[autodock] ZINC22: saved {len(df)} compounds to {output_csv}")
    if verbose:
        logger.info(f"[autodock] ZINC22 sampling done: {len(df)}/{n}, scanned {min(48, len(url_pool))} tranche files")
    return df

def lookup_zinc_id(zinc_id: str, generation: str = "g") -> dict | None:
    """
    Look up a single ZINC ID and return its SMILES and properties.

    Searches the ZINC22 tranche index files to locate the compound.

    Args:
        zinc_id: ZINC identifier (e.g. "ZINC000000000001")
        generation: ZINC22 generation ("a"–"g"), default "g" (ZINC20 in stock).

    Returns:
        dict with keys: zinc_id, smiles, h_donors, logp, mw, tranche or None if not found.

    Note:
        ZINC IDs are distributed across tranche files.  This function scans
        the relevant tranche directories to locate the ID, which may take
        5–30 seconds depending on the tranche structure.

    Example:
        >>> result = lookup_zinc_id("ZINC000000000001")
        >>> print(result["smiles"])
    """
    import gzip, urllib.request, re

    def fetch_gz(url: str, timeout: int = 15) -> str | None:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.70+"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return gzip.decompress(resp.read()).decode("utf-8", errors="ignore")
        except Exception:
            return None

    # Tranche files are: {H_str}/{H_str}P{logp_bucket}/{H_str}P{logp_bucket}M{mw_bucket}-{suffix}.txt.gz
    # We scan the index .txt.gz files (not .smi.gz) to find the zinc_id.
    # Strategy: scan a curated set of tranche index files that cover most compounds.
    # H_donors ranges 0-29, MW 0-900, LogP 0.0-6.0

    # Extract numeric suffix from ZINC ID (e.g. ZINC000000000001 → 1)
    try:
        num = int(zinc_id.replace("ZINC", ""))
    except ValueError:
        return None

    # For efficiency: search tranches most likely to contain low ZINC IDs
    # Low ZINC IDs are typically in lower MW/LogP tranches
    candidates = []
    for h in range(0, 10):       # H-donors 0-9
        for p in range(0, 60, 10):  # LogP buckets 0-5.9
            for mw in range(0, 900, 100):
                h_str = f"H{h:02d}"
                p_str = f"H{h:02d}P{p:03d}"
                mw_str = f"{mw:03d}"
                for suffix in ["N.g.txt.gz", "L.g.txt.gz", "M.g.txt.gz", "O.g.txt.gz"]:
                    url = f"{_ZINC22_BASE}/zinc-22{generation}/{h_str}/{p_str}/{h_str}{p_str}{mw_str}-{suffix}"
                    candidates.append(url)

    # Search first 200 candidates as a reasonable scope
    for url in candidates[:200]:
        txt = fetch_gz(url, timeout=10)
        if not txt:
            continue
        lines = txt.splitlines()
        # Index files are one ZINC ID per line (sorted)
        for line in lines:
            if line.strip() == zinc_id:
                # Found — parse tranche path to get properties
                tranche_m = re.search(r"H(\d+)P(\d+)M(\d+)", url)
                if tranche_m:
                    props = {
                        "h_donors": int(tranche_m.group(1)),
                        "logp": int(tranche_m.group(2)) / 10.0,
                        "mw": int(tranche_m.group(3)),
                    }
                else:
                    props = {}
                return {
                    "zinc_id": zinc_id,
                    "smiles": None,   # SMILES not in .txt index, only in .smi.gz
                    **props,
                    "tranche": url.split("/")[-1].replace("-N.g.txt.gz","").replace("-L.g.txt.gz","").replace("-M.g.txt.gz","").replace("-O.g.txt.gz",""),
                    "note": "SMILES available via sample_zinc_compounds() with tranche filter"
                }

    return None



# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== autodock module ===")
    print(f"  PyMOL: {'OK' if _HAVE_PYMOL else 'MISSING'}")
    print(f"  Vina:  {'OK' if _HAVE_VINA else 'MISSING'}")
    print(f"  RDKit: {'OK' if _HAVE_RDKIT else 'MISSING'}")
    print(f"  Meeko: {'OK' if _HAVE_MEEKO else 'MISSING'}")
    if all([_HAVE_PYMOL, _HAVE_VINA, _HAVE_RDKIT, _HAVE_MEEKO]):
        print("\nAll dependencies available — ready for docking!")
    else:
        print("\nSome dependencies missing — run: conda activate autodock313")
