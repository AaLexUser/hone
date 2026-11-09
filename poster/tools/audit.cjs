// Poster audit: natural band heights, overflow, clipped text, min text size (mm on paper),
// WCAG contrast of HTML text against its nearest opaque background, and banned wording.
const { chromium } = require('playwright')
const fs = require('fs')
const path = require('path')
const MM = 96 / 25.4
const src = path.resolve(process.argv[2] || 'index.html')
const BANNED = [/\bMei\b/, /real run/i, /real log/i, /verbatim from/i, /\blive\b(?!\s+demo\s+at\s+this\s+booth)/i, /one week/i, /must agree/i, /until it agrees/i,
  /\br_[0-9a-f]{4}\b/, /\bses_/, /\b[0-9a-f]{7}\b(?![-\w])/, /1 m 06/, /batch 0\/4/, /ask_panel/, /deepseek-v4|glm-5\.2|mimo-v2|minimax-m3|gpt-5\.4-mini@/,
  /held.out/i, /generaliz/i, /significan/i, /\benough\b/i, /unsupervised/i, /best AGENTS/i, /best baseline/i, /≈ paraphrased/, /only recurring/i, /demo link/i, /scan to open/i, /\bTry it\b/i, /\bsynced\b/i, /\brunning\b/i]
;(async () => {
  const b = await chromium.launch()
  const p = await b.newPage({ viewport: { width: Math.round(900 * MM), height: Math.round(1200 * MM) } })
  await p.goto('file://' + src); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(500)
  const res = await p.evaluate((MM) => {
    const lum = (c) => { const m = c.match(/[\d.]+/g).map(Number); const [r, g, bb] = m.slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }); return 0.2126 * r + 0.7152 * g + 0.0722 * bb }
    const alpha = (c) => { const m = c.match(/[\d.]+/g); return m.length > 3 ? +m[3] : 1 }
    const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const s = getComputedStyle(e); if (s.backgroundImage !== 'none' && !/gradient/.test(s.backgroundImage)) return null; if (alpha(s.backgroundColor) > 0.9) return s.backgroundColor } return 'rgb(255,255,255)' }
    const poster = document.querySelector('.poster')
    const out = { small: [], contrast: [], clipped: [], overflowX: [], stills: [], logo: [] }
    const walker = document.createTreeWalker(poster, NodeFilter.SHOW_TEXT)
    const seen = new Set()
    while (walker.nextNode()) {
      const t = walker.currentNode; if (!t.textContent.trim()) continue
      const el = t.parentElement; if (seen.has(el)) continue; seen.add(el)
      const s = getComputedStyle(el); if (s.display === 'none' || s.visibility === 'hidden') continue
      let mm
      if (el.closest('svg')) { const svg = el.closest('svg'); const vb = svg.viewBox.baseVal; const k = vb && vb.width ? svg.getBoundingClientRect().width / vb.width : 1; mm = parseFloat(s.fontSize) * k / MM }
      else mm = parseFloat(s.fontSize) / MM
      if (el.classList && el.classList.contains('num')) continue
      const label = (el.className && el.className.baseVal !== undefined ? el.tagName : el.tagName + '.' + el.className) + ': ' + t.textContent.trim().slice(0, 40)
      if (mm < 8.49) out.small.push([+mm.toFixed(2), label])
      if (!el.closest('svg')) {
        const bg = bgOf(el); if (!bg) continue
        const fg = s.color; const a = lum(fg), c = lum(bg); const cr = (Math.max(a, c) + 0.05) / (Math.min(a, c) + 0.05)
        if (cr < 4.5 || (cr < 7 && /\b(17, 19, 24|53, 64, 166|70, 83, 201)\b/.test(bg))) out.contrast.push([+cr.toFixed(2), fg, bg, label])
      }
    }
    for (const e of poster.querySelectorAll('*')) {
      const r = e.getBoundingClientRect(); if (r.right > 900 * MM + 1 || r.left < -1) out.overflowX.push(e.tagName + '.' + e.className)
      const s = getComputedStyle(e); if ((s.overflow === 'hidden' || s.textOverflow === 'ellipsis') && e.scrollWidth > e.clientWidth + 2 && !e.classList.contains('poster')) out.clipped.push(e.className)
    }
    out.overflowX = out.overflowX.slice(0, 10)
    // Type inside a still: its smallest stage-px string scaled by the placed width
    out.stills = [...poster.querySelectorAll('img[data-stage-w]')].map((i) => { const k = i.getBoundingClientRect().width / MM / +i.dataset.stageW; return { src: i.getAttribute('src'), widthMm: +(i.getBoundingClientRect().width / MM).toFixed(1), heightMm: +(i.getBoundingClientRect().height / MM).toFixed(1), minMm: +(k * +i.dataset.minPx).toFixed(2) } })
    out.stills.filter((t) => t.minMm < 8.5).forEach((t) => out.small.push([t.minMm, 'still: ' + t.src]))
    // No Hone logo mark and no demo QR: the only QR is the Code QR
    out.logo = [...poster.querySelectorAll('img')].map((i) => i.getAttribute('src')).filter((s) => /hone\.svg|qr-demo|mark/i.test(s))
    if (poster.querySelectorAll('.mark').length) out.logo.push('.mark element')
    return out
  }, MM)
  await p.addStyleTag({ content: '.band{flex:none!important}.poster{height:auto!important}' })
  res.heights = await p.evaluate((MM) => [...document.querySelector('.poster').children].map((c) => [c.id || c.className.split(' ')[0], +(c.getBoundingClientRect().height / MM).toFixed(1)]), MM)
  res.natural = +res.heights.reduce((a, k) => a + k[1], 0).toFixed(1)
  res.slackOk = res.natural <= 1195
  const text = await p.evaluate(() => document.querySelector('.poster').innerText + ' ' + [...document.querySelectorAll('svg text')].map((t) => t.textContent).join(' '))
  res.banned = BANNED.filter((re) => re.test(text)).map((re) => re.source + ' -> ' + text.match(re)[0])
  console.log(JSON.stringify(res, null, 1)); await b.close()
})()
