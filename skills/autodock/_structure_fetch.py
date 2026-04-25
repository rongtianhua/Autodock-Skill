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
    api_url = f"https://swissmodel.expasy.org/api/repository/uniprot/{uniprot_id}"
    model_url = None

    try:
        req = urllib.request.Request(api_url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            data = json.loads(resp.read())
            results = data.get('result', {}).get('structures', [])
            if results:
                # Get the first/best model
                best = results[0]
                model_url = best.get('pdb_url')
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
    # PDBredo re-refined version
    url = f"https://www.pdbredo.central.ebi.ac.uk/c/up/{pdb_id}/full"
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
                  source: str = 'pdb',
                  output_dir: str = "./structures") -> str:
    """
    Unified protein structure fetch.

    Args:
        pdb_id: RCSB PDB ID (4 chars)
        uniprot_id: UniProt accession
        source: 'pdb' | 'alphafold' | 'swissmodel' | 'pdbredo'
        output_dir: Directory to save structure

    Returns:
        Path to downloaded PDB file
    """
    os.makedirs(output_dir, exist_ok=True)

    if source == 'pdb' and pdb_id:
        return fetch_protein_pdb(pdb_id)
    elif source == 'alphafold' and uniprot_id:
        return fetch_protein_alphafold(uniprot_id)
    elif source == 'swissmodel' and uniprot_id:
        return fetch_protein_swissmodel(uniprot_id)
    elif source == 'pdbredo' and pdb_id:
        return fetch_protein_pdb_redo(pdb_id)
    else:
        raise ValueError("Provide pdb_id (for PDB/pdbredo) or uniprot_id (for AlphaFold/swissmodel)")


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


def fetch_molecule_zinc(zinc_id: str, output_smi: str = None) -> dict:
    """
    Fetch compound from ZINC database.

    Args:
        zinc_id: ZINC ID (e.g. 'ZINC00000001')
        output_smi: Optional path to save SMILES file

    Returns:
        dict with keys: zinc_id, smiles, smiles_url
    """
    zinc_id = zinc_id.upper()
    if not zinc_id.startswith('ZINC'):
        zinc_id = f'ZINC{zinc_id:010d}'  # pad to 10 digits

    # ZINC20 API
    url = f"https://zinc20.docking.org/substances/{zinc_id}/"

    try:
        req = urllib.request.Request(url, headers={'Accept': 'text/plain'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            smiles = resp.read().decode().strip()

        if not smiles or len(smiles) > 1000:
            raise ValueError(f"ZINC fetch returned invalid data for: {zinc_id}")

        result = {
            'zinc_id': zinc_id,
            'smiles': smiles,
        }

        if output_smi:
            with open(output_smi, 'w') as f:
                f.write(smiles)
            result['smiles_path'] = output_smi

        print(f"[structure_fetch] ZINC: {zinc_id} — {smiles[:50]}...")
        return result

    except urllib.error.HTTPError as e:
        raise ValueError(f"ZINC entry not found: {zinc_id} (HTTP {e.code})")
    except Exception as e:
        raise ValueError(f"ZINC error: {e}")


def fetch_molecule(identifier: str,
                   source: str = 'pubchem',
                   identifier_type: str = 'name',
                   output_dir: str = "./structures") -> dict:
    """
    Unified small molecule structure fetch.

    Args:
        identifier: Compound name, SMILES, ID, etc.
        source: 'pubchem' | 'chembl' | 'zinc'
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
    elif source == 'zinc':
        smi = os.path.join(output_dir, f"{identifier}.smi")
        return fetch_molecule_zinc(identifier, output_smi=smi)
    else:
        raise ValueError(f"Unknown source: {source}")


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
