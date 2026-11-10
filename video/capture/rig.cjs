// Records the booth stack in a headful Chromium on an Xvfb display.
// The page is 1920 by 1080 CSS pixels at device scale 1.5, so the raw capture is 2880 by 1620.
// Every recording keeps wall clock timestamps (ffmpeg -copyts), and every mark and cursor
// event is logged in wall clock seconds, so the composer can line them up exactly.
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { chromium } = require(process.env.PLAYWRIGHT || '/opt/node-tools/node_modules/playwright');

const BASE = process.env.BOOTH_URL || 'http://127.0.0.1:8443';
const CREDS = { username: process.env.BOOTH_USER || 'icdm', password: process.env.BOOTH_PASS || 'booth-pass-1' };
const DISPLAY = process.env.DISPLAY || ':99';
const SCALE = 1.5;
const W = 1920;
const H = 1080;

const now = () => Date.now() / 1000;
const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));
const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);

async function openRig(outDir, stage) {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({
    headless: false,
    args: [`--force-device-scale-factor=${SCALE}`, '--window-position=0,0', `--window-size=${W},${H}`, '--hide-scrollbars'],
    ignoreDefaultArgs: ['--enable-automation'],
    env: { ...process.env, DISPLAY },
  });
  const context = await browser.newContext({ viewport: null, httpCredentials: CREDS });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  const { windowId } = await cdp.send('Browser.getWindowForTarget');
  await cdp.send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'fullscreen' } });

  const log = { stage, marks: {}, cursor: [], data: {} };
  let pos = { x: W / 2, y: H / 2 };
  let ff = null;
  const save = () => fs.writeFileSync(path.join(outDir, `${stage}.json`), JSON.stringify(log, null, 1));

  const rig = {
    page,
    browser,
    BASE,
    log,
    mark(name, data) {
      log.marks[name] = now();
      if (data !== undefined) log.data[name] = data;
      console.log(new Date().toISOString().slice(11, 19), stage, name, data === undefined ? '' : JSON.stringify(data).slice(0, 300));
      save();
    },
    async startRecording() {
      const file = path.join(outDir, `${stage}.mkv`);
      ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '30',
        '-video_size', `${W * SCALE}x${H * SCALE}`, '-i', DISPLAY, '-copyts',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '12', '-pix_fmt', 'yuv444p', file], { stdio: ['pipe', 'inherit', 'inherit'] });
      await sleep(1.5);
      log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'move' });
      rig.mark('rec-start');
    },
    async stopRecording() {
      rig.mark('rec-stop');
      ff.stdin.write('q');
      await new Promise((r) => ff.on('close', r));
      save();
    },
    async moveTo(x, y, dur = 0.6) {
      const from = { ...pos };
      const n = Math.max(2, Math.round(dur * 60));
      for (let i = 1; i <= n; i++) {
        const u = ease(i / n);
        pos = { x: from.x + (x - from.x) * u, y: from.y + (y - from.y) * u };
        await page.mouse.move(pos.x, pos.y);
        log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'move' });
        await sleep(dur / n);
      }
    },
    async center(locator) {
      await locator.scrollIntoViewIfNeeded().catch(() => {});
      const b = await locator.boundingBox();
      if (!b) throw new Error('no box for ' + locator);
      return { x: b.x + b.width / 2, y: b.y + b.height / 2, box: b };
    },
    async hover(locator, dur) {
      const c = await rig.center(locator);
      await rig.moveTo(c.x, c.y, dur);
      return c;
    },
    async click(locator, dur = 0.6) {
      await rig.hover(locator, dur);
      await sleep(0.15);
      log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'down' });
      await page.mouse.down();
      await sleep(0.08);
      await page.mouse.up();
      log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'up' });
    },
    async drag(fromLocator, toLocator) {
      const a = await rig.center(fromLocator);
      const b = await rig.center(toLocator);
      const ax = a.box.x + Math.min(90, a.box.width / 2);
      await rig.moveTo(ax, a.y, 0.6);
      await sleep(0.15);
      log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'down' });
      await page.mouse.down();
      await rig.moveTo(ax + 20, a.y + 6, 0.15);
      await rig.moveTo(b.x, b.y, 0.9);
      await sleep(0.3);
      await page.mouse.up();
      log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'up' });
      await sleep(0.6);
    },
    async type(text, cps = 28) {
      await page.keyboard.type(text, { delay: 1000 / cps });
    },
    async wheel(dy, steps = 10, dur = 1) {
      for (let i = 0; i < steps; i++) {
        await page.mouse.wheel(0, dy / steps);
        await sleep(dur / steps);
      }
    },
    hideCursor() { log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'hide' }); },
    showCursor() { log.cursor.push({ t: now(), x: pos.x, y: pos.y, e: 'show' }); },
    async api(p) {
      return page.evaluate(async (u) => (await fetch(u)).json(), BASE + p);
    },
    async close() {
      save();
      await browser.close();
    },
  };
  return rig;
}

async function resetDemo(rig) {
  const { page } = rig;
  await page.goto(BASE + '/');
  await sleep(6);
  await page.getByRole('button', { name: 'Reset demo' }).first().click();
  await sleep(1.5);
  await page.getByRole('button', { name: 'Confirm' }).click();
  await sleep(15);
  const st = await rig.api('/hone/api/state');
  return { current: st.currentId, traces: st.traces.length, versions: st.versions.length };
}

async function waitForReply(page, maxSec = 360) {
  const t0 = now();
  for (;;) {
    await sleep(3);
    const text = await page.locator('main').innerText().catch(() => '');
    if (/Worked for/.test(text) && !/Working/.test(text)) return text;
    if (now() - t0 > maxSec) throw new Error('agent reply timed out');
  }
}

module.exports = { openRig, resetDemo, waitForReply, sleep, now, BASE };
