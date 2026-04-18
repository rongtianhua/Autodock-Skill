---
name: pmc-pdf-downloader
description: Download PDF full-texts from PubMed Central (PMC) articles and other open-access sources. Activated when user asks to download, send, or attach a research paper PDF.
---

# PMC PDF Downloader

Downloads PDF files from PMC articles via DOI → CrossRef → publisher direct link, falling back to Playwright for Cloudflare-protected pages.

## Quick Start

```bash
python3 ~/.openclaw/workspace/skills/pmc-pdf-downloader/scripts/pmc_pdf_download.py PMC12975808 /tmp/
```

## Download Strategy (in order)

1. **PMC article page → extract DOI**
2. **DOI → CrossRef API → publisher PDF URL** (avoids Cloudflare entirely)
3. **Publisher direct download** via curl
4. **Fallback: Playwright** handles Cloudflare JS proof-of-work challenge, then curl with session cookies
5. **Last resort: Playwright CDP** intercepts download directly

## Usage

```bash
python3 scripts/pmc_pdf_download.py <pmcid_or_doi> [output_dir]
```

- `pmcid`: e.g. `PMC12975808`
- `doi`: e.g. `10.1007/s00701-026-06819-1` (auto-detected)
- `output_dir`: defaults to `/tmp/`

## Sending to User

After download, send to user via:
```
filePath: ~/.openclaw/workspace/Documents/<pmcid>.pdf
```

**Always use workspace absolute path, NOT /tmp/** — feishu file sending is unreliable with /tmp/ files.

## Common Publishers & PDF Patterns

| Publisher | PDF URL Pattern |
|---|---|
| Springer | `link.springer.com/content/pdf/{doi}.pdf` |
| Elsevier | `www.sciencedirect.com/science/article/pii/{pii}/pdfft` |
| Wiley | `onlinelibrary.wiley.com/doi/pdfdirect/{doi}` |
| Nature | `www.nature.com/articles/{article_id}.pdf` |
| Oxford | `academic.oup.com/{journal}/article-pdf/{doi}/{id}.pdf` |

## Notes

- PMC HTML free ≠ PMC PDF free — PMC's /pdf/ endpoint is Cloudflare-protected
- Always try DOI publisher link FIRST before reaching for Playwright
- CrossRef API: `https://api.crossref.org/works/{doi}` → check `message.link[].URL` for `application/pdf`
