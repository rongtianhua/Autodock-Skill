#!/usr/bin/env python3
"""
PMC PDF Downloader using Playwright — handles Cloudflare POW challenge
that blocks plain curl/wget requests to PMC /pdf/ endpoints.

Strategy:
1. Navigate to the PMC article HTML page (no challenge there)
2. Extract the DOI
3. Follow PDF link from DOI publisher site (Springer/Elsevier/Wiley etc.)
   which typically has direct PDF without Cloudflare challenge
4. If publisher PDF also has challenge, use Playwright to wait for
   the PDF URL to become available after JS challenge completes
"""

import subprocess
import sys
import os
import re
import json


def get_pmc_article_page(pmcid: str) -> str:
    """Fetch the PMC article page and return HTML."""
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    result = subprocess.run(
        ["curl", "-sL", url, "--max-time", "30",
         "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
         "-H", "Accept: text/html"],
        capture_output=True,
        text=True,
        timeout=35,
    )
    return result.stdout


def extract_doi_from_pmc_html(html: str) -> str | None:
    """Extract DOI from PMC article page HTML."""
    patterns = [
        r'"doi":\s*"([^"]+)"',
        r'"DOI"\s*:\s*"([^"]+)"',
        r'href="https?://doi\.org/([^"]+)"',
        r'href="https?://dx\.doi\.org/([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            doi = m.group(1).strip()
            if not doi.startswith("10."):
                continue
            return doi
    return None


def extract_pdf_url_from_doi(doi: str) -> str | None:
    """
    Given a DOI, return the direct PDF URL if the publisher provides one.
    This avoids Cloudflare entirely by going direct to publisher PDF.
    """
    # Try CrossRef API for full-text links
    result = subprocess.run(
        ["curl", "-sL", f"https://api.crossref.org/works/{doi}",
         "--max-time", "20", "-A", "Mozilla/5.0"],
        capture_output=True,
        text=True,
        timeout=25,
    )
    try:
        data = json.loads(result.stdout)
        links = data.get("message", {}).get("link", [])
        for link in links:
            if link.get("content-type", "").startswith("application/pdf"):
                url = link.get("URL", "")
                if url:
                    return url
        # Also check 'alternative' link
        alinks = data.get("message", {}).get("alternative-id", [])
    except Exception:
        pass
    return None


def download_with_playwright(pdf_url: str, output_path: str) -> str:
    """
    Use Playwright to handle any JS challenge (Cloudflare POW),
    then download the PDF once the page is ready.
    """
    script = f"""
const {{ chromium }} = require('playwright');

(async () =G>
  const browser = await chromium.launch();
  const page = await browser.newPage();

  // Set a real user agent
  await page.setExtraHTTPHeaders({{
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
  }});

  // Navigate and wait for PDF to load
  await page.goto('{pdf_url}', {{ waitUntil: 'networkidle', timeout: 45000 }});

  // Check final URL after any JS redirects
  const finalUrl = page.url();
  console.log('FINAL_URL:' + finalUrl);

  // If it's still a PDF URL, trigger download via page.goto won't work for PDF
  // Instead, use curl on the final URL with cookies from the browser session
  const cookies = await page.context().cookies();
  const cookieStr = cookies.map(c =G> c.name + '=' + c.value).join('; ');
  console.log('COOKIES:' + cookieStr);
  console.log('READY');

  await browser.close();
}})();
"""
    result = subprocess.run(
        ["node", "-e", script.replace("=G>", ">")],
        capture_output=True, text=True, timeout=60
    )
    return result.stdout


def download_pdf_curl_with_cookies(pdf_url: str, cookies: str, output_path: str) -> bool:
    """Download PDF using curl with browser-collected cookies."""
    result = subprocess.run(
        ["curl", "-sL", "-o", output_path, "--max-time", "60",
         "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
         "-H", f"Cookie: {cookies}",
         pdf_url],
        capture_output=True, timeout=65
    )
    if os.path.exists(output_path):
        with open(output_path, "rb") as f:
            return f.read(4) == b"%PDF"
    return False


def download_pmc_pdf(pmcid: str, output_dir: str = "/tmp/") -> str:
    """
    Main entry point. Attempts:
    1. Extract DOI from PMC → publisher direct PDF (avoids Cloudflare)
    2. CrossRef API for PDF link
    3. Playwright as fallback
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{pmcid}.pdf")

    print(f"[{pmcid}] Fetching article page...", file=sys.stderr)
    html = get_pmc_article_page(pmcid)

    doi = extract_doi_from_pmc_html(html)
    if doi:
        print(f"[{pmcid}] Found DOI: {doi}", file=sys.stderr)
        pdf_url = extract_pdf_url_from_doi(doi)
        if pdf_url:
            print(f"[{pmcid}] Publisher PDF URL: {pdf_url}", file=sys.stderr)
            # Try direct curl download first (no Cloudflare on publisher sites)
            result = subprocess.run(
                ["curl", "-sL", "-o", output_path, "--max-time", "60",
                 "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                 pdf_url],
                capture_output=True, timeout=65
            )
            if os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    if f.read(4) == b"%PDF":
                        print(f"[{pmcid}] SUCCESS (publisher direct): {output_path}", file=sys.stderr)
                        return output_path

    # Fallback: Playwright to handle Cloudflare
    print(f"[{pmcid}] Attempting Playwright fallback...", file=sys.stderr)
    pdf_page_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"
    playwright_output = download_with_playwright(pdf_page_url, output_path)

    # Parse cookies from Playwright output
    cookies_match = re.search(r"COOKIES:(.+)", playwright_output)
    final_url_match = re.search(r"FINAL_URL:(.+)", playwright_output)

    if cookies_match and final_url_match:
        cookies = cookies_match.group(1).strip()
        final_url = final_url_match.group(1).strip()
        # Check if Cloudflare redirected to a different URL
        if "cloudflare" not in final_url.lower() and final_url != pdf_page_url:
            print(f"[{pmcid}] Playwright resolved URL: {final_url}", file=sys.stderr)
            ok = download_pdf_curl_with_cookies(final_url, cookies, output_path)
            if ok:
                print(f"[{pmcid}] SUCCESS (Playwright+curl): {output_path}", file=sys.stderr)
                return output_path
        elif "cloudflare" in final_url.lower():
            print(f"[{pmcid}] WARNING: Cloudflare challenge still active", file=sys.stderr)

    # Last resort: use Playwright to save PDF directly via CDP
    print(f"[{pmcid}] Final attempt: Playwright direct CDP download...", file=sys.stderr)
    script = f"""
const {{ chromium }} = require('playwright');
const fs = require('fs');

(async () =G>
  const browser = await chromium.launch({{
    args: ['--disable-web-security', '--enable-features=MsixPackage']
  }});
  const context = await browser.newContext({{
    acceptDownloads: true
  }});
  const page = await context.newPage();
  await page.setExtraHTTPHeaders({{
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
  }});

  const [download] = await Promise.all([
    page.waitForEvent('download', {{ timeout: 45000 }}),
    page.goto('{pmcid}', {{ waitUntil: 'domcontentloaded', timeout: 30000 }})
  ]);

  await download.saveAs('{output_path}');
  console.log('DONE');
  await browser.close();
}})();
"""
    result = subprocess.run(
        ["node", "-e", script.replace("=G>", ">")],
        capture_output=True, text=True, timeout=90
    )
    if result.returncode == 0 and os.path.exists(output_path):
        with open(output_path, "rb") as f:
            if f.read(4) == b"%PDF":
                print(f"[{pmcid}] SUCCESS (CDP download): {output_path}", file=sys.stderr)
                return output_path

    raise ValueError(f"All download strategies failed for {pmcid}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pmc_pdf_download.py PMC12345678 [output_dir]")
        sys.exit(1)

    pmcid = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "/tmp/"

    try:
        path = download_pmc_pdf(pmcid, output_dir)
        print(path)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
