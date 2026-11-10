// node capture.cjs <stage> <footage dir> [employee]
// Records the spreadsheet scenario on a booth stack with demo mode off (BOOTH_URL).
// Stages, run in this order:
//   setup           adds the Expense reports project in t3code (not recorded)
//   prep <name>     a chat for one employee, then the feedback from <footage>/feedback-<name>.txt (not recorded)
//   chat <name>     the same, recorded, then the Hone page, Start optimization and the whole real run
//   review <question> <rule>
//                   the finished run page scrolled to a judge question that matches <question>, then the
//                   new version on the Versions page with the line that matches <rule>
//   chat2 <name>    a new chat for another employee, after the commit
// The feedback file is written by hand after looking at the agent's spreadsheet, so the
// complaint is about what this run really got wrong. Its first line is up or down, the rest is the comment.
const fs = require('fs');
const path = require('path');
const { openRig, waitForReply, sleep, now } = require('../../capture/rig.cjs');
const F = require('../../capture/flows.cjs');

const PROJECT_DIR = '/home/node/demo/Expense reports/';
const TEMPLATE = 'Inbox/Expense report template.xlsx';
const receipts = (name) => `Inbox/Receipts October 2026 ${name}.pdf`;
const sheetName = (name) => `Expenses ${name}.xlsx`;
const request = (name) => `Fill in the October expense report for ${name} from these receipts, using the template. Save it as ${sheetName(name)}`;

const [stage, out, employee] = process.argv.slice(2);

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
  await page.getByText('Expense reports').first().click();
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
  const file = path.join(out, `feedback-${name.replace(/ /g, '-')}.txt`);
  console.log('waiting for', file);
  while (!fs.existsSync(file)) await sleep(3);
  const [verdict, ...rest] = fs.readFileSync(file, 'utf8').trim().split('\n');
  return { verdict: verdict.trim(), comment: rest.join(' ').trim() };
}

async function rate(rig, { verdict, comment }) {
  const { page } = rig;
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

// Opens the spreadsheet in the previewer, maximized, and holds on it.
async function showSheet(rig, name) {
  const { page } = rig;
  await rig.click(F.item(page, name), 0.8);
  await sleep(3);
  rig.mark('sheet-open');
  await rig.click(page.getByRole('button', { name: 'Maximize panel' }), 0.7);
  await sleep(2.5);
  rig.mark('sheet-max');
  await rig.moveTo(1500, 900, 0.6);
  await sleep(6);
  rig.mark('sheet-end');
  await rig.click(page.getByRole('button', { name: 'Restore panel size' }), 0.7);
  await sleep(1);
  await rig.click(page.getByRole('button', { name: `Close ${name}` }), 0.6);
  await sleep(1.2);
  rig.mark('sheet-closed');
}

async function newChat(rig, name, { record }) {
  const { page } = rig;
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
  await F.composeRequest(rig, { send: true, files: [receipts(name), TEMPLATE], request: request(name) });
  await rig.moveTo(1180, 700, 0.8);
  rig.hideCursor();
  const reply = await waitForReply(page, 600);
  rig.mark('replied', { tail: reply.replace(/\n+/g, ' | ').slice(-900) });
  rig.showCursor();
  await sleep(2.5);
  rig.mark('reply-read');
  await showSheet(rig, sheetName(name));
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

const box = async (loc) => {
  const b = await loc.boundingBox();
  return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
};

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
  const rig = await openRig(out, employee && stage !== 'review' ? `${stage}-${employee.replace(/ /g, '-')}` : stage);
  if (stage === 'setup') await setup(rig);
  else if (stage === 'prep' || stage === 'chat') {
    const record = stage === 'chat';
    await newChat(rig, employee, { record });
    await rate(rig, await waitForFeedback(rig, employee));
    if (record) {
      await sleep(1);
      await optimize(rig);
      await sleep(1);
      await rig.stopRecording();
    }
  } else if (stage === 'review') {
    await review(rig, employee, process.argv[5]);
  } else if (stage === 'chat2') {
    await newChat(rig, employee, { record: true });
    await rig.stopRecording();
  } else throw new Error('unknown stage ' + stage);
  await rig.close();
})().catch((e) => { console.error(e); process.exit(1); });
