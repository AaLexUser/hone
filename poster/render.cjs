// Render index.html to out/preview.png and out/hone-poster.pdf, and report
// text smaller than 8.5 mm on paper plus any element that overflows the page.
// Usage: node render.cjs   (from any directory; needs global playwright)
const { chromium } = require('playwright')
const path = require('path')

const dir = __dirname
const MM = 96 / 25.4

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage({
    viewport: { width: Math.round(900 * MM), height: Math.round(1200 * MM) },
    deviceScaleFactor: Number(process.env.DSF || 0.6),
  })
  await page.goto('file://' + path.join(dir, 'index.html'))
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(500)
  const report = await page.evaluate((MM) => {
    const small = []
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    const seen = new Set()
    while (walker.nextNode()) {
      const t = walker.currentNode
      if (!t.textContent.trim()) continue
      const el = t.parentElement
      if (seen.has(el)) continue
      seen.add(el)
      const s = getComputedStyle(el)
      let px = parseFloat(s.fontSize)
      const svg = el.closest('svg')
      if (svg) {
        const vb = svg.viewBox.baseVal
        if (vb && vb.width) px *= svg.getBoundingClientRect().width / vb.width
      }
      const mm = px / MM
      if (mm < 8.49) small.push(mm.toFixed(2) + ' ' + t.textContent.trim().slice(0, 50))
    }
    const poster = document.querySelector('.poster').getBoundingClientRect()
    const sections = [...document.querySelectorAll('.poster > *')].map((c) => {
      const r = c.getBoundingClientRect()
      return `${c.className.split(' ')[0]}: ${Math.round(r.top / MM)}-${Math.round(r.bottom / MM)} mm`
    })
    const overflow = [...document.querySelectorAll('.poster *')].filter((e) => {
      const r = e.getBoundingClientRect()
      return r.right > poster.right + 1 || r.bottom > poster.bottom + 1
    }).map((e) => e.tagName + '.' + (e.className.baseVal ?? e.className))
    const clipped = [...document.querySelectorAll('.poster *')].filter((e) => e.scrollHeight > e.clientHeight + 2 && getComputedStyle(e).overflow === 'hidden').map((e) => e.className)
    return { small, sections, overflow: overflow.slice(0, 20), clipped, docHeight: document.documentElement.scrollHeight / MM }
  }, MM)
  // Natural content height: let the poster and the demo band size to their content.
  report.naturalHeight = await page.evaluate((MM) => {
    const poster = document.querySelector('.poster'), demo = document.querySelector('.demo')
    const keep = [poster.style.cssText, demo.style.cssText]
    poster.style.height = 'auto'; poster.style.overflow = 'visible'; demo.style.flex = 'none'
    const h = poster.getBoundingClientRect().height / MM
    poster.style.cssText = keep[0]; demo.style.cssText = keep[1]
    return Math.round(h * 10) / 10
  }, MM)
  report.minFont = await page.evaluate((MM) => {
    let min = 1e9, who = ''
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    while (walker.nextNode()) {
      const t = walker.currentNode; if (!t.textContent.trim()) continue
      const el = t.parentElement; let px = parseFloat(getComputedStyle(el).fontSize)
      const svg = el.closest('svg'); if (svg) { const vb = svg.viewBox.baseVal; if (vb && vb.width) px *= svg.getBoundingClientRect().width / vb.width }
      if (px / MM < min) { min = px / MM; who = t.textContent.trim().slice(0, 30) }
    }
    return min.toFixed(2) + ' mm: ' + who
  }, MM)
  console.log(JSON.stringify(report, null, 1))
  await page.screenshot({ path: path.join(dir, 'out/preview.png') })
  if (!process.env.NOPDF) {
    await page.pdf({ path: path.join(dir, 'out/hone-poster.pdf'), width: '900mm', height: '1200mm', printBackground: true, pageRanges: '1' })
  }
  await browser.close()
})()
