#!/usr/bin/env node
/**
 * ADMETlab 3.0 browser automation via Playwright.
 *
 * CLI usage:
 *   node admetlab_web.js [--csv <out.csv>] [--smiles-file <file>] [SMILES...]
 *
 * Python wrapper calls:
 *   node admetlab_web.js --csv /tmp/out.csv --smiles-file /tmp/smiles.smi
 *
 * Exit codes: 0 = success, 1 = error
 */
const { chromium } = require('/opt/homebrew/lib/node_modules/playwright');
const https = require('https');
const fs = require('fs');
const path = require('path');

// ── Argument parsing ──────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let csvOut = null;
let smilesFile = null;
const positionalSmiles = [];

for (let i = 0; i < args.length; i++) {
    if (args[i] === '--csv' && i + 1 < args.length) {
        csvOut = args[++i];
    } else if (args[i] === '--smiles-file' && i + 1 < args.length) {
        smilesFile = args[++i];
    } else if (!args[i].startsWith('--')) {
        positionalSmiles.push(args[i]);
    }
}

// Load SMILES from file or positional args
let smilesList = [];
if (smilesFile) {
    try {
        smilesList = fs.readFileSync(smilesFile, 'utf8')
            .split('\n')
            .map(l => l.trim())
            .filter(l => l && !l.startsWith('#'));
    } catch (e) {
        console.error(`Cannot read smiles file: ${smilesFile}`);

        process.exit(1);
    }
} else {
    smilesList = positionalSmiles;
}

if (smilesList.length === 0) {
    console.error('No SMILES provided. Use positional args or --smiles-file');
    process.exit(1);
}

// ── HTTP download helper ─────────────────────────────────────────────────────
function download(url, dest) {
    return new Promise((resolve, reject) => {
        const file = fs.createWriteStream(dest);
        const req = https.get(url, {
            headers: { 'User-Agent': 'curl/7.70+' },
            timeout: 20000
        }, (res) => {
            if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
                file.close();
                download(res.headers.location, dest).then(resolve).catch(reject);
                return;
            }
            if (res.statusCode !== 200) {
                file.close();
                reject(new Error(`HTTP ${res.statusCode}`));
                return;
            }
            res.pipe(file);
            file.on('finish', () => { file.close(); resolve(dest); });
        });
        req.on('error', reject);
    });
}

// ── Main prediction function ───────────────────────────────────────────────────
async function predictAdmetWeb(smilesList, timeoutSec = 60) {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    // 1. Load screening page
    // 1. Load screening page — use 'load' (not networkidle) so we don't wait
    //    for external resources (fonts, analytics) that may be slow/unavailable
    await page.goto('https://admetlab3.scbdd.com/server/screening', {
        waitUntil: 'load',
        timeout: 30000
    });

    // 2. Extract CSRF token
    const csrfToken = await page.evaluate(() => {
        const el = document.querySelector('input[name="csrfmiddlewaretoken"]');
        return el ? el.value : null;
    });
    if (!csrfToken) throw new Error('CSRF token not found');

    // 3. Switch to SMILES tab
    await page.click('#profile-tab');
    await page.waitForTimeout(400);

    // 4. Fill textarea
    await page.fill('#exampleFormControlTextarea1', smilesList.join('\n'));

    // 5. Set up navigation wait BEFORE triggering submit (critical ordering)
    const navPromise = page.waitForURL('**/server/result/**', {
        timeout: timeoutSec * 1000
    });

    // 6. Fill all form fields and submit — in one evaluate to avoid race
    await page.evaluate((csrf) => {
        const form = document.getElementById('form2');
        const inp = (name, val) => {
            let el = form.querySelector(`input[name="${name}"]`);
            if (!el) { el = document.createElement('input'); el.type = 'hidden'; el.name = name; form.appendChild(el); }
            el.value = val;
        };
        inp('csrfmiddlewaretoken', csrf);
        inp('method', '2');
        inp('is_example', '0');
        form.submit();
    }, { csrf: csrfToken });

    // 7. Wait for result page navigation
    await navPromise;

    // 8. Parse CSV URL from result page HTML
    const csvUrl = await page.evaluate(() => {
        // window.open("/static/results/csv/xxx.csv") is embedded in the page JS
        const m = document.body.innerHTML.match(/window\.open\("(\/static\/results\/csv\/[^"]+)"\)/);
        return m ? m[1] : null;
    });

    await browser.close();

    if (!csvUrl) throw new Error('CSV URL not found in result page');

    // 9. Download CSV
    const tmpCsv = csvOut || `/tmp/admetlab_${Date.now()}.csv`;
    await download('https://admetlab3.scbdd.com' + csvUrl, tmpCsv);

    // 10. Parse TSV
    const content = fs.readFileSync(tmpCsv, 'utf-8').trim();
    if (!csvOut) fs.unlinkSync(tmpCsv);  // only clean up if we created a temp file

    const lines = content.split('\n').map(l => l.split('\t'));

    return {
        headers: lines[0],
        data: lines.slice(1),
        source: 'admetlab3',
        csvPath: csvOut || tmpCsv
    };
}

// ── Run ───────────────────────────────────────────────────────────────────────
const TIMEOUT_SEC = 120;

predictAdmetWeb(smilesList, TIMEOUT_SEC).then(r => {
    if (csvOut) {
        // Just write the CSV as-is; Python handles it
        console.error(`OK:${r.csvPath}`);
    } else {
        console.log(`SUCCESS: ${r.data.length} rows × ${r.headers.length} cols`);
        console.log('Columns:', r.headers.slice(0, 12).join(', '), '...');
    }
    process.exit(0);
}).catch(e => {
    console.error(`ERROR: ${e.message}`);
    process.exit(1);
});