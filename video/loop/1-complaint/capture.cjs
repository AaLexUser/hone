// node capture.cjs <stage> <footage dir>
// Records "A complaint becomes a rule" on the booth stack in demo mode (BOOTH_URL), with the shipped
// recordings: the visitor's first turn replays from clients/t3code/turn-cache and the optimization
// replays the approved run r_89a9 from packages/hone/demo/run-cache. A fresh browser context has
// guide mode off. Stages, run in this order:
//   reset      Reset demo from the sidebar (not recorded)
//   check      composes the request without sending and prints the composer text (not recorded)
//   pastchat   a prepared chat and the feedback under its reply
//   chat       the request with the two Inbox files, the agent at work, the letter, thumbs down
//   run        the Hone page, Start optimization and the whole run
//   review     the judge's question on the run page, then the new rule on the Versions page
//   chat2      the same request in a new chat, live on the new AGENTS.md, and its letter
// The request and the feedback are word for word what the recorded visit sent, or nothing replays.
const fs = require('fs');
const path = require('path');
const { openRig, resetDemo, sleep, now } = require('../../capture/rig.cjs');
const F = require('../../capture/flows.cjs');

const FILES = ['Inbox/Hiring approval Amara Osei.pdf', 'Inbox/Offer letter template.docx'];
const REQUEST = "New hire today. Please prepare Amara Osei's offer letter from her approval and the template. Keep your reply short.";
const FEEDBACK = "There's a '£0' sign-on bonus and '0 shares' of equity again. If the approval has none, leave the line out.";
// What the composer shows when it holds exactly the recorded request.
const COMPOSER = `Hiring approval Amara Osei.pdf\n \nOffer letter template.docx\n ${REQUEST}`;
const LETTER = 'Offer_Osei_Amara.pdf';

const [stage, out] = process.argv.slice(2);

async function openProject(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/');
  await sleep(6);
  await F.closeDetailsCard(page);
}

async function newThread(rig) {
  const { page } = rig;
  await rig.click(page.getByRole('button', { name: 'New thread', exact: true }), 0.8);
  await sleep(2.5);
  await F.closeDetailsCard(page);
  rig.mark('new-thread');
}

async function compose(rig) {
  const { page } = rig;
  const inbox = F.item(page, 'Inbox/');
  if ((await inbox.getAttribute('aria-expanded')) !== 'true') {
    await rig.click(inbox, 0.8);
    await sleep(0.8);
  }
  rig.mark('inbox-open');
  const editor = page.locator('[contenteditable="true"]').first();
  for (const [i, f] of FILES.entries()) {
    await rig.drag(F.item(page, f), editor);
    rig.mark(`dragged-${i}`);
  }
  await editor.evaluate((e) => { e.spellcheck = false; });
  await editor.click();
  await page.keyboard.press('End');
  await rig.type(REQUEST);
  rig.mark('typed');
  await sleep(0.8);
  const text = await editor.innerText();
  rig.mark('composer', { text, exact: text === COMPOSER });
  return text === COMPOSER;
}

// The reply is done when nothing says Working and its thumbs are there, twice in a row.
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

async function sendAndWait(rig) {
  const { page } = rig;
  await rig.click(page.getByRole('button', { name: 'Submit message' }), 0.5);
  rig.mark('sent');
  await rig.moveTo(1180, 700, 0.8);
  rig.hideCursor();
  const reply = await waitForReply(page, 900);
  rig.mark('replied', { tail: reply.replace(/\n+/g, ' | ').slice(-800) });
  rig.showCursor();
  await sleep(2);
}

async function showLetter(rig) {
  const { page } = rig;
  await page.screenshot({ path: path.join(out, `${stage}-before-letter.png`) });
  await F.showLetter(rig, LETTER, Number(process.env.LETTER_WHEEL || 260));
}

async function thumbsDown(rig) {
  const { page } = rig;
  await rig.click(page.getByRole('button', { name: 'Needs work, tell Hone' }).last(), 0.9);
  await sleep(0.8);
  rig.mark('thumb-down');
  const box = page.getByPlaceholder('Hone uses this to improve AGENTS.md');
  await box.evaluate((e) => { e.spellcheck = false; });
  await rig.click(box, 0.4);
  await rig.type(FEEDBACK, 30);
  rig.mark('feedback-typed');
  await sleep(0.6);
  await rig.click(page.getByRole('button', { name: 'Send to Hone' }), 0.6);
  rig.mark('feedback-sent');
  await sleep(4);
  const chip = await page.getByRole('link', { name: 'Open the Hone dashboard' }).innerText().catch(() => '');
  rig.mark('chip', { chip: chip.replace(/\n+/g, ' ') });
  await sleep(2);
}

async function pastChat(rig) {
  const { page } = rig;
  await rig.click(page.locator('[role="treeitem"][aria-label^="Offer letter for Olivia Grant"]'), 0.9);
  await sleep(3);
  await F.closeDetailsCard(page);
  await sleep(1);
  rig.mark('pastchat-open');
  await rig.moveTo(1000, 600, 0.6);
  await rig.wheel(6000, 14, 1.4);
  await sleep(1.5);
  await rig.click(page.getByRole('button', { name: 'Show the full feedback' }).last(), 0.8);
  await sleep(1);
  rig.mark('feedback-shown', { text: await page.getByRole('button', { name: 'Show less of the feedback' }).last().innerText().catch(() => '') });
  await sleep(5);
  rig.mark('pastchat-end');
}

async function optimize(rig) {
  const { page } = rig;
  await rig.click(page.getByRole('link', { name: 'Open the Hone dashboard' }), 1);
  await sleep(5);
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
  for (;;) {
    await sleep(5);
    const r = await rig.api('/hone/api/runs/' + run.id);
    if (!['running', 'validating'].includes(r.status)) {
      rig.mark('run-ended', { status: r.status, durationMs: r.durationMs, commit: r.commitTitle, replayOf: r.replayOf && r.replayOf.entryId });
      break;
    }
  }
  await sleep(8);
  rig.showCursor();
  rig.mark('run-settled');
}

const box = async (loc) => {
  const b = await loc.boundingBox();
  return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
};

async function review(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/hone');
  await sleep(5);
  const st = await rig.api('/hone/api/state');
  const runs = await rig.api('/hone/api/runs');
  const run = (Array.isArray(runs) ? runs : runs.runs).find((r) => r.resultVersionId === st.currentId);
  const frame = page.frames().find((f) => f.url().includes('/hone/'));
  await frame.goto(rig.BASE + '/hone/runs/' + run.id);
  await sleep(5);
  const ui = page.frameLocator('iframe');
  await rig.startRecording();
  await sleep(2.5);
  rig.mark('run-page', { run: run.id });
  const q = ui.getByText(/blank lines/).first();
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
  await sleep(6);
  await rig.wheel(-6000, 12, 1.2);
  await sleep(1.2);
  await rig.click(ui.getByRole('link', { name: /View version/ }).or(ui.getByRole('button', { name: /View version/ })).first(), 1);
  await sleep(3);
  rig.mark('versions', { rule: await box(ui.getByText(/leave that line out of the letter entirely/).first()).catch(() => null) });
  await sleep(8);
  rig.mark('versions-end');
  await rig.stopRecording();
}

(async () => {
  const rig = await openRig(out, stage);
  if (stage === 'reset') {
    rig.mark('reset', await resetDemo(rig));
  } else if (stage === 'check') {
    await openProject(rig);
    await newThread(rig);
    const exact = await compose(rig);
    console.log('composer matches the recorded request:', exact);
  } else if (stage === 'pastchat') {
    await openProject(rig);
    await rig.startRecording();
    await sleep(1.5);
    await pastChat(rig);
    await rig.stopRecording();
  } else if (stage === 'chat' || stage === 'chat2') {
    await openProject(rig);
    await rig.startRecording();
    await sleep(1.5);
    await newThread(rig);
    const exact = await compose(rig);
    if (!exact && stage === 'chat') throw new Error('the composer does not hold the recorded request, not sending');
    await sendAndWait(rig);
    await showLetter(rig);
    if (stage === 'chat') await thumbsDown(rig);
    await sleep(1);
    await rig.stopRecording();
  } else if (stage === 'run') {
    await openVisitorChat(rig);
    await rig.startRecording();
    await sleep(2);
    await optimize(rig);
    await sleep(1);
    await rig.stopRecording();
  } else if (stage === 'review') {
    await review(rig);
  } else throw new Error('unknown stage ' + stage);
  await rig.close();
})().catch((e) => { console.error(e); process.exit(1); });

// The run starts from the visitor's chat, where the header chip opens the Hone page.
async function openVisitorChat(rig) {
  const { page } = rig;
  await openProject(rig);
  const rows = page.locator('[data-thread-item] > [role="treeitem"]');
  await rows.first().click();
  await sleep(4);
  await F.closeDetailsCard(page);
  fs.writeFileSync(path.join(out, 'run-start-thread.txt'), (await rows.first().getAttribute('aria-label')) || '');
}
