// node capture.cjs <stage> <footage dir> [chat]
// Records the workshop name badges scenario on a booth stack with demo mode off (BOOTH_URL).
// Stages, run in this order:
//   setup           adds the Workshop badges project in t3code (not recorded)
//   prep <chat>     one of the CHATS below, then the feedback from <footage>/feedback-<chat>.txt (not recorded)
//   chat <chat>     the same, recorded
//   sheet <file>    opens a delivered badge sheet in the previewer, maximized, recorded
//   run             the Hone page, Start optimization and the whole real run, recorded
//   review <question> <rule>
//                   the finished run page scrolled to the activity line that matches <question>, then the
//                   new version on the Versions page with the line that matches <rule>
//   chat2 <chat>    a new chat for another workshop, after the commit
// The feedback file is written by hand after looking at the delivered sheet, so the complaint is about
// what this chat really produced. Its first line is up, down or none, the rest is the comment.
const fs = require('fs');
const path = require('path');
const { openRig, sleep, now } = require('../../capture/rig.cjs');
const F = require('../../capture/flows.cjs');

const PROJECT_DIR = '/home/node/demo/Workshop badges/';
const PROJECT = 'Workshop badges';
const workshop = (w) => [[`Inbox/Registrations ${w}.pdf`, 'Inbox/Badge sheet template.docx'],
  `Make the name badges for the ${w} from this registration list, using the badge sheet template. Save as DOCX and PDF.`];
const CHATS = {
  graph: workshop('Graph Mining Workshop'),
  streams: workshop('Data Streams Workshop'),
  fairness: workshop('Fairness in ML Workshop'),
  timeseries: workshop('Time Series Workshop'),
  xai: workshop('Explainable AI Workshop'),
};
// Words the reply marks look for: point sizes and page counts the agent reports.
const SPELLINGS = /\b\d+(\.\d+)? ?pt\b|\b\d+ pages?\b|\bone line\b/g;

const [stage, out, chat] = process.argv.slice(2);

async function closeOnboarding(page) {
  const close = page.getByRole('dialog').getByRole('button', { name: 'Close' });
  if (await close.isVisible().catch(() => false)) {
    await close.click();
    await sleep(0.8);
  }
}

async function showFiles(page) {
  await sleep(1);
  if (!(await F.item(page, 'Inbox/').isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Toggle right panel' }).click();
    await sleep(1.5);
    const files = page.getByText('Files', { exact: true });
    if (await files.isVisible().catch(() => false)) {
      await files.click();
      await sleep(1.5);
    }
  }
}

async function openApp(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/');
  await sleep(6);
  await closeOnboarding(page);
  await page.getByText(PROJECT, { exact: true }).first().click();
  await sleep(2);
  await F.closeDetailsCard(page);
  await showFiles(page);
}

async function setup(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/');
  await sleep(6);
  await closeOnboarding(page);
  await page.getByRole('button', { name: 'Add project' }).first().click();
  await sleep(1);
  await page.getByText('Local folder', { exact: true }).click();
  await sleep(1);
  await page.getByRole('dialog').locator('input').first().fill(PROJECT_DIR);
  await sleep(1.5);
  await page.getByText('Add', { exact: true }).first().click();
  await sleep(3);
  rig.mark('project-added');
}

async function waitForFeedback(rig, name) {
  const file = path.join(out, `feedback-${name}.txt`);
  console.log('waiting for', file);
  while (!fs.existsSync(file)) await sleep(3);
  const [verdict, ...rest] = fs.readFileSync(file, 'utf8').trim().split('\n');
  return { verdict: verdict.trim(), comment: rest.join(' ').trim() };
}

async function rate(rig, { verdict, comment }) {
  const { page } = rig;
  if (verdict === 'none') {
    rig.mark('no-feedback');
    return;
  }
  const label = verdict === 'up' ? 'Good reply, tell Hone' : 'Needs work, tell Hone';
  await rig.click(page.getByRole('button', { name: label }).last(), 0.9);
  await sleep(0.8);
  rig.mark('thumb-' + verdict);
  if (comment) {
    const box = page.getByPlaceholder('Hone uses this to improve AGENTS.md');
    await box.evaluate((e) => { e.spellcheck = false; });
    await rig.click(box, 0.4);
    await rig.type(comment, 30);
    rig.mark('feedback-typed');
    await sleep(0.6);
  }
  await rig.click(page.getByRole('button', { name: 'Send to Hone' }), 0.6);
  rig.mark('feedback-sent');
  await sleep(4);
  const header = await page.locator('header, [data-slot="header"]').first().innerText().catch(() => '');
  rig.mark('chip', { header: header.replace(/\n+/g, ' ') });
}

const box = async (loc) => {
  const b = await loc.boundingBox();
  return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
};

// Boxes of the matching words visible in the chat, in CSS pixels.
async function spellingBoxes(page) {
  return page.evaluate((src) => {
    const re = new RegExp(src, 'g');
    const out = [];
    const walker = document.createTreeWalker(document.querySelector('main'), NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      for (const m of n.data.matchAll(re)) {
        const r = document.createRange();
        r.setStart(n, m.index);
        r.setEnd(n, m.index + m[0].length);
        const b = r.getBoundingClientRect();
        if (b.width && b.bottom > 60 && b.top < 940) out.push({ word: m[0], x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) });
      }
    }
    return out;
  }, SPELLINGS.source);
}

// Scrolls the finished reply from its top to its end slowly, logging where the spelling words sit.
async function showReply(rig) {
  const { page } = rig;
  await rig.moveTo(1000, 600, 0.6);
  const top = page.locator('main').getByText(/Worked for/).last();
  for (let i = 0; i < 4; i++) {
    const b = await top.boundingBox().catch(() => null);
    if (!b) break;
    const dy = b.y - 120;
    if (Math.abs(dy) < 8) break;
    await rig.wheel(dy, 12, 1.2);
    await sleep(0.8);
  }
  rig.mark('reply-top', { words: await spellingBoxes(page) });
  await sleep(5);
  for (let i = 1; i <= 4; i++) {
    await rig.wheel(560, 14, 1.6);
    await sleep(1);
    rig.mark(`reply-${i}`, { words: await spellingBoxes(page) });
    await sleep(3.5);
  }
  await rig.wheel(6000, 14, 1.6);
  await sleep(1);
  rig.mark('reply-end', { words: await spellingBoxes(page) });
}

// t3code renders a long thread lazily, so "Worked for" can be out of the page. The reply is done
// when nothing says Working and its thumbs are there, twice in a row.
async function waitForReply(page, maxSec) {
  const t0 = now();
  let done = 0;
  for (;;) {
    await sleep(3);
    const text = await page.locator('main').innerText().catch(() => '');
    const thumbs = await page.getByRole('button', { name: 'Needs work, tell Hone' }).count();
    done = !/Working/.test(text) && thumbs > 0 ? done + 1 : 0;
    if (done >= 2) return text;
    if (now() - t0 > maxSec) throw new Error('agent reply timed out');
  }
}

async function newChat(rig, name, { record }) {
  const { page } = rig;
  const [files, request] = CHATS[name];
  await openApp(rig);
  if (record) await rig.startRecording();
  await sleep(1.5);
  const fresh = page.getByRole('button', { name: 'New thread', exact: true });
  if (await fresh.isVisible().catch(() => false)) {
    await rig.click(fresh, 0.8);
    await sleep(2);
    await F.closeDetailsCard(page);
    await showFiles(page);
  }
  rig.mark('new-thread');
  await F.composeRequest(rig, { send: true, files, request });
  await rig.moveTo(1180, 700, 0.8);
  rig.hideCursor();
  const reply = await waitForReply(page, 900).catch(async (e) => {
    await page.screenshot({ path: path.join(out, `timeout-${name}.png`) });
    throw e;
  });
  rig.mark('replied', { tail: reply.replace(/\n+/g, ' | ').slice(-1500) });
  rig.showCursor();
  await sleep(1);
  await showReply(rig);
}

// Opens a delivered file in the previewer, maximized, holds, then scrolls it once.
async function page_sheet(rig, file) {
  const { page } = rig;
  await page.locator('[data-thread-item]').first().click();
  await sleep(3);
  await rig.startRecording();
  await sleep(1.5);
  await rig.click(F.item(page, file), 0.8);
  await sleep(3);
  rig.mark('sheet-open');
  await rig.click(page.getByRole('button', { name: 'Maximize panel' }), 0.7);
  await sleep(2.5);
  rig.mark('sheet-max');
  await sleep(6);
  await rig.moveTo(960, 640, 0.6);
  await rig.wheel(500, 12, 1.4);
  await sleep(4);
  rig.mark('sheet-end');
  await rig.stopRecording();
}

async function optimize(rig) {
  const { page } = rig;
  await rig.click(page.getByRole('button', { name: 'Hone', exact: true }), 1);
  await sleep(4);
  rig.mark('hone-dashboard');
  const frame = page.frameLocator('iframe');
  await rig.click(frame.getByRole('button', { name: 'Start optimization' }), 0.9);
  rig.mark('start-clicked');
  let run = null;
  for (let i = 0; i < 30 && !run; i++) {
    await sleep(1);
    const st = await rig.api('/hone/api/state');
    if (st.run && st.run.id) run = st.run;
  }
  rig.mark('run-started', { id: run.id });
  await rig.moveTo(1880, 1040, 1);
  rig.hideCursor();
  const t0 = now();
  for (;;) {
    await sleep(10);
    const r = await rig.api('/hone/api/runs/' + run.id);
    if (!['running', 'validating'].includes(r.status)) {
      rig.mark('run-ended', r);
      break;
    }
    if (now() - t0 > 45 * 60) throw new Error('run still going after 45 minutes');
  }
  await sleep(8);
  rig.showCursor();
  rig.mark('run-settled');
}

async function review(rig, question, rule) {
  const { page } = rig;
  await page.goto(rig.BASE + '/hone');
  await sleep(5);
  const runs = await rig.api('/hone/api/runs');
  const run = (Array.isArray(runs) ? runs : runs.runs)[0];
  const frame = page.frames().find((f) => f.url().includes('/hone/'));
  await frame.goto(rig.BASE + '/hone/runs/' + run.id);
  await sleep(5);
  const ui = page.frameLocator('iframe');
  await rig.startRecording();
  await sleep(2.5);
  rig.mark('run-page', { run: run.id, durationMs: run.durationMs });
  const q = ui.getByText(new RegExp(question)).first();
  await rig.moveTo(700, 640, 0.6);
  for (let i = 0; i < 3; i++) {
    const b = await q.boundingBox();
    const dy = b.y - 430;
    if (Math.abs(dy) < 8) break;
    await rig.wheel(dy, 14, 1.2);
    await sleep(0.8);
  }
  await sleep(0.6);
  rig.mark('question', { question: await box(q) });
  await sleep(5);
  await rig.wheel(-6000, 12, 1.2);
  await sleep(1.2);
  await rig.click(ui.getByRole('link', { name: /View version/ }).or(ui.getByRole('button', { name: /View version/ })).first(), 1);
  await sleep(3);
  rig.mark('versions', { rule: await box(ui.getByText(new RegExp(rule)).first()).catch(() => null) });
  await sleep(7);
  rig.mark('versions-end');
  await rig.stopRecording();
}

(async () => {
  const rig = await openRig(out, chat && stage !== 'review' ? `${stage}-${chat}` : stage);
  if (stage === 'setup') await setup(rig);
  else if (stage === 'prep' || stage === 'chat') {
    const record = stage === 'chat';
    await newChat(rig, chat, { record });
    await rate(rig, await waitForFeedback(rig, chat));
    if (record) {
      await sleep(2);
      await rig.stopRecording();
    }
  } else if (stage === 'sheet') {
    await openApp(rig);
    await page_sheet(rig, chat);
  } else if (stage === 'run') {
    await openApp(rig);
    await rig.startRecording();
    await sleep(2);
    await optimize(rig);
    await sleep(1);
    await rig.stopRecording();
  } else if (stage === 'review') {
    await review(rig, chat, process.argv[5]);
  } else if (stage === 'chat2') {
    await newChat(rig, chat, { record: true });
    await sleep(2);
    await rig.stopRecording();
  } else throw new Error('unknown stage ' + stage);
  await rig.close();
})().catch((e) => { console.error(e); process.exit(1); });
