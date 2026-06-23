// Headless screenshot of a URL. Usage: node shot.js <url> [outfile]
const { chromium } = require('playwright-core');
(async () => {
  const url = process.argv[2];
  const out = process.argv[3] || '/tmp/shot.png';
  if (!url) { console.error('usage: node shot.js <url> [outfile]'); process.exit(1); }
  const b = await chromium.launch({
    executablePath: '/usr/bin/chromium',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const ctx = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 900, height: 1200 } });
  const p = await ctx.newPage();
  await p.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  await p.waitForTimeout(1500);
  await p.screenshot({ path: out, fullPage: true });
  await b.close();
  console.log('OK ' + out);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
