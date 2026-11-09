// Screenshots each band of the poster at a close-inspection scale.
const { chromium } = require('playwright')
const path = require('path')
const MM = 96 / 25.4
;(async () => {
  const [src, outDir, dsf] = process.argv.slice(2)
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: Math.round(900 * MM), height: Math.round(1200 * MM) }, deviceScaleFactor: Number(dsf || 0.9) })
  await p.goto('file://' + path.resolve(src)); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(500)
  const els = await p.$$('.poster > *')
  for (let i = 0; i < els.length; i++) await els[i].screenshot({ path: `${outDir}/band-${i}.png` })
  await b.close()
})()
