// node render_overlay.cjs <states.json> <out dir>
// Renders each distinct overlay state through overlay.html to a transparent 1920 by 1080 PNG.
// Writes <out dir>/index.json, which maps every output frame to its PNG.
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT || '/opt/node-tools/node_modules/playwright');

(async () => {
  const [statesFile, outDir] = process.argv.slice(2);
  const states = JSON.parse(fs.readFileSync(statesFile, 'utf8'));
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'overlay.html'));
  await page.evaluate(() => window.fontsReady);
  const seen = new Map();
  const index = [];
  for (let i = 0; i < states.length; i++) {
    const key = JSON.stringify(states[i]);
    if (!seen.has(key)) {
      const file = `ov${String(seen.size).padStart(5, '0')}.png`;
      seen.set(key, file);
      if (key === '{}') {
        await page.evaluate(() => window.render({}));
      } else {
        await page.evaluate((s) => window.render(s), states[i]);
      }
      await page.screenshot({ path: path.join(outDir, file), omitBackground: true });
    }
    index.push(seen.get(key));
    if (i % 300 === 0) console.log('overlay frame', i, 'of', states.length, 'unique', seen.size);
  }
  fs.writeFileSync(path.join(outDir, 'index.json'), JSON.stringify(index));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
