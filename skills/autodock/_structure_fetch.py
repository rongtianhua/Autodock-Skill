"""
Structure Fetching Module
=========================
Fetch protein structures and small molecule structures for docking.
No external software required — pure HTTP + RDKit.

Author: PrimeClaw (OpenClaw)
"""

import os
import warnings
import urllib.request
import urllib.error
import urllib.parse

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem, Draw
    _HAVE_RDKIT = True
except ImportError:
    _HAVE_RDKIT = False


# ─── Protein Structure Sources ─────────────────────────────────────────────────

def fetch_protein_pdb(pdb_id: str, output_path: str = None) -> str:
    """
    Download protein structure from RCSB PDB.

    Args:
        pdb_id: 4-character PDB ID (e.g. '1ABC', '6LU7')
        output_path: Optional output path (default: ./structures/{pdb_id}.pdb)

    Returns:
        Path to downloaded PDB file

    Raises:
        ValueError: If PDB ID invalid or download fails
    """
    pdb_id = pdb_id.upper()
    if len(pdb_id) != 4:
        raise ValueError(f"Invalid PDB ID: {pdb_id} (must be 4 characters)")

    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    dest = output_path or f"./structures/{pdb_id}.pdb"

    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)

    try:
        urllib.request.urlretrieve(url, dest)
        # Verify it's a real PDB file
        with open(dest) as f:
            content = f.read()
        if 'HEADER' not in content and 'ATOM' not in content:
            raise ValueError(f"Downloaded file is not a valid PDB: {pdb_id}")
        print(f"[structure_fetch] PDB downloaded: {dest}")
        return dest
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
        if 'ATOM' not in content:
            raise ValueError(f"AlphaFold structure not found: {uniprot_id}")
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
                           output_sdf: str = None) -> dict:
    """
    Fetch small molecule from PubChem.

    Args:
        identifier: Compound name, SMILES, InChI, or CID
        identifier_type: 'name' | 'smiles' | 'inchi' | 'cid'
        output_sdf: Optional path to save SDF file

    Returns:
        dict with keys: name, smiles, inchi, cid, sdf_path
    """
    import json

    # Map identifier type to PUG REST endpoint (URL-encode identifiers to handle spaces/special chars)
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

    try:
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        props = data['PropertyTable']['Properties'][0]
        smiles = props.get('IsomericSMILES') or props.get('CanonicalSMILES') or props.get('SMILES') or ''
        inchi = props.get('InChI', '')
        name = props.get('Title', identifier)
        cid = props.get('CID', '')

        result = {
            'name': name,
            'smiles': smiles,
            'inchi': inchi,
            'cid': str(cid),
            'sdf_path': None
        }

        # Optionally download SDF
        if output_sdf:
            sdf_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/SDF"
            urllib.request.urlretrieve(sdf_url, output_sdf)
            result['sdf_path'] = output_sdf

        print(f"[structure_fetch] PubChem: {name} (CID: {cid})")
        return result

    except urllib.error.HTTPError as e:
        raise ValueError(f"PubChem lookup failed for '{identifier}': HTTP {e.code}")
    except Exception as e:
        raise ValueError(f"PubChem error: {e}")


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

    Args:
        drugbank_id: DrugBank ID (e.g. 'DB00102')
        drug_name: Or search by name

    Returns:
        dict with keys: drugbank_id, name, smiles, description
    """
    import json

    if drugbank_id:
        url = f"https://go.drugbank.com/api/regna/similar_by_name/{drugbank_id}"  # just search
        # Actually use the public DrugBank structure API
        url = f"https://www.drugbank.ca/structures/bulk_xml/{drugbank_id}"
        raise NotImplementedError("DrugBank bulk download requires API key — use PubChem instead")
    elif drug_name:
        # Use PubChem as DrugBank proxy
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
    IUPAC Nomenclature). Best for IUPAC names; common names (caffeine, ibuprofen,
    glucose) also accepted.

    Args:
        identifier: Chemical name (IUPAC or common, e.g. 'caffeine', 'glucose')

    Returns:
        dict with keys: name, smiles, source

    Raises:
        ValueError: if the name cannot be parsed
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
        raise ValueError(f"OPSIN lookup failed for '{identifier}' (HTTP {e.code})")
    except Exception as e:
        raise ValueError(f"OPSIN error: {e}")


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
