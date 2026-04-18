---
name: clawbio-wrapper
slug: clawbio-wrapper
version: 1.0.0
description: Unified gateway to all 50 ClawBio bioinformatics skills. Routes requests to the correct skill (GWAS, PharmGx, RNA-seq, scRNA-seq, methylation, etc.) based on user intent.
metadata:
  openclaw:
    emoji: "🧬"
    os: [darwin, linux]
---

## Overview

This skill routes bioinformatics requests to the appropriate ClawBio skill. The ClawBio repo lives at `~/.openclaw/clawbio/` and contains 50 domain-specific skills covering genomics, transcriptomics, proteomics, pharmacogenomics, and more.

## Routing Table

| User asks about... | Skill to invoke | CLI |
|---|---|---|
| Drug interactions, CYP2D6, CYP2C19, warfarin, pharmacogenomics | `pharmgx-reporter` | `pharmgx_reporter.py --input <file> --output <dir>` |
| Gene-drug lookup, ClinPGx, PharmGKB, CPIC | `clinpgx` | `clinpgx.py --gene <GENE> --output <dir>` |
| rsID variant lookup, GWAS associations, PheWAS, eQTL | `gwas-lookup` | `gwas_lookup.py --rsid <rsid> --output <dir>` |
| Polygenic risk score, PGS Catalog, diabetes risk | `gwas-prs` | `gwas_prs.py --input <file> --trait <trait> --output <dir>` |
| GWAS fine-mapping, SuSiE, ABF, credible sets, PIP | `fine-mapping` | `fine_mapping.py --sumstats <file> --ld <ld.npy> --output <dir>` |
| VCF annotation, VEP, ClinVar, gnomAD | `vcf-annotator` | Read SKILL.md, apply methodology |
| ACMG variant classification, clinical report | `clinical-variant-reporter` | `acmg_engine.py --demo` |
| Ancestry PCA, population structure, SGDP | `claw-ancestry-pca` | `ancestry_pca.py --demo` |
| Genome comparison, IBS, Corpasome | `genome-compare` | `genome_compare.py --demo` |
| HEIM equity score, population diversity, FST | `equity-scorer` | `equity_scorer.py --input <vcf/csv> --output <dir>` |
| Bulk RNA-seq differential expression, DESeq2, PyDESeq2 | `rnaseq-de` | `rnaseq_de.py --counts <csv> --metadata <csv> --formula <f> --contrast <c> --output <dir>` |
| scRNA-seq, Scanpy, clustering, doublet removal | `scrna-orchestrator` | `scrna_orchestrator.py --input <h5ad> --output <dir>` |
| Epigenetic age, methylation clock, Horvath, GrimAge | `methylation-clock` | `methylation_clock.py --input <csv> --output <dir>` |
| PubMed search, literature briefing, recent papers | `pubmed-summariser` | `pubmed_summariser.py --query <term> --output <dir>` |
| UK Biobank fields, schema search | `ukb-navigator` | `ukb_navigator.py --query <term> --output <dir>` |
| Galaxy tools, usegalaxy.eu workflow | `galaxy-bridge` | `galaxy_bridge.py --search <term>` |
| Methylation analysis, GEO | `methylation-clock` | `methylation_clock.py --input <file> --output <dir>` |
| Bioconductor packages, R workflow | `bioconductor-bridge` | `bioc_recommender.py --query <task>` |
| Clinical trials, ClinicalTrials.gov | `clinical-trial-finder` | `gwas_bridge.py --demo` |
| Drug photo, medication from image | `drug-photo` | `drug_photo.py --image <img> --output <dir>` |
| Multi-sample QC report, FastQC summary | `multiqc-reporter` | `multiqc_reporter.py --input <dir> --output <dir>` |
| Cell segmentation, Cellpose, fluorescence microscopy | `cell-detection` | `cell_detection.py --input <image> --output <dir>` |
| Soul to DNA, compile genome | `soul2dna` | `soul2dna.py --demo` |
| Protocol search, protocols.io | `protocols-io` | `protocols_io.py --search <term>` |
| Lab notebook, Labstep | `labstep` | `labstep.py --experiments` |
| Uncertain what skill to use | `bio-orchestrator` | `orchestrator.py --input <query> --list-skills` |

## Python Environment

ClawBio requires:
- Python 3.10+
- User site-packages: `/Users/allenrong/Library/Python/3.14/lib/python/site-packages`

Always prepend to `sys.path` before running any ClawBio script:
```python
import sys
sys.path.insert(0, '/Users/allenrong/Library/Python/3.14/lib/python/site-packages')
sys.path.insert(0, '/Users/allenrong/.openclaw/clawbio')
```

Run scripts using `python3` (not `python`).

## Demo Mode

Every skill supports `--demo` when the user has no input data. Always offer demo first:
```bash
python3 skills/<skill>/<script>.py --demo --output /tmp/<skill>_demo
```

## Key Skills for Spine Surgery × Neuroscience Research

For your research focus, these are highest priority:

1. **GWAS Lookup** — Find genetic variants associated with disc degeneration, spinal arthritis, neuropathic pain
2. **RNA-seq DE** — Differential expression in spinal cord / dorsal root ganglion / herniated disc tissue
3. **scRNA-seq Orchestrator** — Single-cell analysis of microglia, astrocytes, neurons in spinal cord injury
4. **methylation-clock** — Epigenetic age of intervertebral disc tissue
5. **fine-mapping** — Identify causal variants in spine disease GWAS loci
6. **vcf-annotator** — Annotate variants from WES/WGS of spine surgery patients
7. **clinpgx** — Drug metabolism genes relevant to analgesic response (CYP2D6, OPRM1)
8. **Allen Brain Atlas** (via `ukb-navigator` concept search) — Gene expression in spinal cord regions

## Reference Genomes

Default: **GRCh38** (preferred) or GRCh37. Track which is used per project and store in memory.

## Output Structure

Every skill produces:
```
<output_dir>/
├── report.md              # Full analysis
├── figures/               # PNG plots
├── tables/                # CSV data
├── commands.sh            # Exact commands
├── environment.yml        # Conda env
└── checksums.sha256       # File checksums
```

## Safety

- All processing is local — no genomic data leaves the machine
- Always include disclaimer: *"ClawBio is a research tool, not a medical device. Consult a healthcare professional before clinical decisions."*
- Never improvise bioinformatics parameters — follow SKILL.md methodology exactly

## Skills Directory

`~/.openclaw/clawbio/skills/` — 50 skills total. See `~/.openclaw/clawbio/CLAUDE.md` for full routing table and CLI reference.
