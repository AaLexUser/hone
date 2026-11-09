const { chromium } = require('playwright')
const path = require('path')

const [src, outDir] = process.argv.slice(2)
const MM = 96 / 25.4

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({
    viewport: { width: Math.round(900 * MM), height: Math.round(1200 * MM) },
    deviceScaleFactor: Number(process.env.DSF || 0.6),
  })
  await page.goto('file://' + path.resolve(src))
  await page.waitForLoadState('networkidle')
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(800)
  const fit = await page.evaluate(() => {
    const p = document.querySelector('.poster')
    const over = [...p.children].map((c) => {
      const r = c.getBoundingClientRect()
      return { tag: c.tagName + (c.className ? '.' + c.className.split(' ')[0] : ''), top: Math.round(r.top / (96 / 25.4)), bottom: Math.round(r.bottom / (96 / 25.4)) }
    })
    const clipped = [...document.querySelectorAll('*')].filter((e) => e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflow === 'hidden').map((e) => e.className)
    return { pageScroll: document.documentElement.scrollHeight, client: document.documentElement.clientHeight, sections: over, clipped, fonts: [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family).filter((v, i, a) => a.indexOf(v) === i) }
  })
  console.log(JSON.stringify(fit, null, 1))
  await page.screenshot({ path: `${outDir}/preview.png` })
  await page.pdf({ path: `${outDir}/hone-poster.pdf`, width: '900mm', height: '1200mm', printBackground: true, pageRanges: '1' })
  await browser.close()
})()
