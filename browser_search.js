/**
 * Fast, 100% headless multiplatform video search engine for ShortBot.
 * Runs completely silent in the background (headless: true).
 * Never opens or displays any window on the user's screen.
 */

const fs = require('fs');
const path = require('path');

function findPlaywright() {
  const candidates = [
    'playwright-core',
    path.join(__dirname, 'node_modules', 'playwright-core'),
    path.join(process.env.APPDATA || '', 'npm', 'node_modules', '@agentrhq', 'webcmd', 'node_modules', 'playwright-core'),
    path.join(process.env.APPDATA || '', 'npm', 'node_modules', 'playwright-core'),
  ];
  for (const c of candidates) {
    try {
      if (fs.existsSync(c) || !path.isAbsolute(c)) {
        const pw = require(c);
        if (pw && pw.chromium) return pw.chromium;
      }
    } catch (e) {}
  }
  return null;
}

function findBrowserExecutable() {
  // 1. Cloak browser profile if installed
  const cloakBase = path.join(process.env.USERPROFILE || '', '.cloakbrowser');
  if (fs.existsSync(cloakBase)) {
    try {
      const entries = fs.readdirSync(cloakBase);
      for (const entry of entries) {
        const exePath = path.join(cloakBase, entry, 'chrome.exe');
        if (fs.existsSync(exePath)) return exePath;
      }
    } catch (e) {}
  }

  // 2. Microsoft Edge (Installed on 100% of Windows 10 & 11)
  const edgePath = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
  if (fs.existsSync(edgePath)) return edgePath;

  // 3. Google Chrome
  const chromePaths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Google', 'Chrome', 'Application', 'chrome.exe')
  ];
  for (const cp of chromePaths) {
    if (fs.existsSync(cp)) return cp;
  }

  return null;
}

async function search(platform, query, maxResults = 20) {
  const chromium = findPlaywright();
  if (!chromium) {
    return { ok: false, error: 'playwright-core not found', results: [] };
  }

  const exePath = findBrowserExecutable();
  if (!exePath) {
    return { ok: false, error: 'Browser executable not found', results: [] };
  }

  let browser = null;
  try {
    browser = await chromium.launch({
      executablePath: exePath,
      headless: true, // 100% HEADLESS - NEVER OPENS ANY WINDOW ON USER SCREEN
      args: ['--no-sandbox']
    });

    const page = await browser.newPage();

    let prefix = '';
    const plat = String(platform).toLowerCase();
    if (plat === 'instagram') {
      prefix = 'site:instagram.com/reel ';
    } else if (plat === 'x' || plat === 'twitter') {
      prefix = 'site:x.com ';
    } else if (plat === 'reddit') {
      prefix = 'site:reddit.com ';
    }

    const hasVideoKeyword = /\b(video|clip|clips|reel|reels|shorts?|footage|moments)\b/i.test(query);
    const fullQuery = prefix + query + ((plat === 'x' || plat === 'twitter' || plat === 'reddit') && !hasVideoKeyword ? ' video' : '');
    const searchUrl = 'https://duckduckgo.com/?q=' + encodeURIComponent(fullQuery);

    await page.goto(searchUrl, { waitUntil: 'domcontentloaded', timeout: 12000 });

    try {
      await page.waitForSelector('article, [data-testid="result"]', { timeout: 8000 });
    } catch (e) {
      await page.waitForTimeout(2500);
    }

    const items = await page.evaluate((targetPlat) => {
      const list = [];
      const seen = new Set();
      const articles = document.querySelectorAll('article, [data-testid="result"], li');

      for (const art of articles) {
        let a = null;
        if (targetPlat === 'instagram') {
          a = art.querySelector('a[href*="instagram.com/reel/"], a[href*="instagram.com/reels/"], a[href*="instagram.com/p/"]');
        } else if (targetPlat === 'x' || targetPlat === 'twitter') {
          a = art.querySelector('a[href*="x.com/"][href*="/status/"], a[href*="twitter.com/"][href*="/status/"]');
        } else if (targetPlat === 'reddit') {
          a = art.querySelector('a[href*="reddit.com/r/"][href*="/comments/"], a[href*="v.redd.it/"]');
        }

        if (!a) continue;

        let rawUrl = a.href || '';
        if (rawUrl.includes('duckduckgo.com/l/?uddg=')) {
          try {
            const u = new URL(rawUrl);
            rawUrl = decodeURIComponent(u.searchParams.get('uddg') || '');
          } catch (e) {}
        }

        const isX = (targetPlat === 'x' || targetPlat === 'twitter');
        const clean = rawUrl.split('?')[0].replace(/\/$/, '') + (isX ? '' : '/');

        if (seen.has(clean)) continue;
        seen.add(clean);

        const h2 = art.querySelector('h2, [data-testid="result-title-a"]');
        let title = h2 ? h2.innerText.trim() : a.innerText.trim();
        const snip = art.querySelector('[data-result="snippet"], [data-testid="result-snippet"], .result__snippet');
        let snippet = snip ? snip.innerText.trim() : '';

        title = title.replace(/\s+/g, ' ').trim();
        snippet = snippet.replace(/\s+/g, ' ').trim();

        // If title is generic breadcrumb or placeholder, build a rich title from snippet
        const isGeneric = !title ||
          title.toLowerCase().includes('instagram.com') ||
          title.toLowerCase().includes('x.com') ||
          title.toLowerCase().includes('twitter.com') ||
          title.toLowerCase().includes('reddit.com') ||
          title.toLowerCase().includes('video post') ||
          title.length < 5;

        if (isGeneric && snippet) {
          const firstSentence = snippet.split(/[.!?\n]/)[0].trim();
          title = firstSentence.length > 10 ? firstSentence : snippet.slice(0, 70).trim();
        }

        list.push({
          title: title || `${targetPlat.toUpperCase()} Video`,
          snippet,
          url: clean,
          platform: targetPlat
        });
      }
      return list;
    }, plat);

    return { ok: true, results: items.slice(0, maxResults) };
  } catch (err) {
    return { ok: false, error: err.message, results: [] };
  } finally {
    if (browser) {
      try { await browser.close(); } catch (e) {}
    }
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    process.stdout.write(JSON.stringify({ ok: true, results: [] }));
    return;
  }
  const platform = args[0] || 'instagram';
  let query = '';
  let maxResults = 20;

  const lastArg = args[args.length - 1];
  if (args.length > 2 && /^\d+$/.test(lastArg)) {
    maxResults = parseInt(lastArg, 10);
    query = args.slice(1, -1).join(' ');
  } else {
    query = args.slice(1).join(' ');
  }

  const res = await search(platform, query, maxResults);
  process.stdout.write(JSON.stringify(res));
}

if (require.main === module) {
  main().catch(err => {
    process.stdout.write(JSON.stringify({ ok: false, error: err.message, results: [] }));
  });
}

module.exports = { search };
