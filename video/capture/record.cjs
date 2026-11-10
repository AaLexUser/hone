// node record.cjs <stage> <footage dir>
// Stages, run in this order:
//   chat     reset, live chat with the Amara Osei approval, thumbs down, Start optimization, the whole real run
//   review   the finished run page, its Activity feed, then the new version on the Versions page
//   chat2    a new chat with the same approval, after the commit
//   reset    Reset demo, so the stack is back in the prepared state (not recorded)
const { openRig, resetDemo, waitForReply, sleep, now } = require('./rig.cjs');
const F = require('./flows.cjs');

const [stage, out] = process.argv.slice(2);
const PDF_WHEEL = 700;

async function chat(rig) {
  const { page } = rig;
  rig.mark('reset', await resetDemo(rig));
  await page.goto(rig.BASE + '/');
  await sleep(6);
  await F.closeDetailsCard(page);
  await rig.startRecording();
  await sleep(1.5);
  await F.composeRequest(rig, { send: true });
  await rig.moveTo(1180, 700, 0.8);
  rig.hideCursor();
  const reply = await waitForReply(page);
  rig.mark('replied', { tail: reply.replace(/\n+/g, ' | ').slice(-700) });
  rig.showCursor();
  await sleep(2.5);
  rig.mark('reply-read');
  await F.showLetter(rig, F.LETTER, PDF_WHEEL);

  const down = page.getByRole('button', { name: 'Needs work, tell Hone' }).last();
  await rig.click(down, 0.9);
  await sleep(0.8);
  rig.mark('thumb-down');
  const box = page.getByPlaceholder('Hone uses this to improve AGENTS.md');
  await box.evaluate((e) => { e.spellcheck = false; });
  await rig.click(box, 0.4);
  await rig.type(F.FEEDBACK, 30);
  rig.mark('feedback-typed');
  await sleep(0.6);
  await rig.click(page.getByRole('button', { name: 'Send to Hone' }), 0.6);
  rig.mark('feedback-sent');
  await sleep(4);
  const header = await page.locator('header, [data-slot="header"]').first().innerText().catch(() => '');
  rig.mark('chip', { header: header.replace(/\n+/g, ' ') });
  await sleep(1);

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
  await sleep(1);
  await rig.stopRecording();
}

async function review(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/hone');
  await sleep(5);
  const runs = await rig.api('/hone/api/runs');
  const run = (Array.isArray(runs) ? runs : runs.runs)[0];
  const frame = page.frames().find((f) => f.url().includes('/hone/'));
  await frame.goto(rig.BASE + '/hone/runs/' + run.id);
  await sleep(5);
  const ui = page.frameLocator('iframe');
  const box = async (loc) => {
    const b = await loc.boundingBox();
    return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
  };
  // Scrolls the run page until the locator's top sits at y, in a few smooth wheel steps.
  const bring = async (loc, y) => {
    await rig.moveTo(700, 640, 0.6);
    for (let i = 0; i < 3; i++) {
      const b = await loc.boundingBox();
      const dy = b.y - y;
      if (Math.abs(dy) < 8) break;
      await rig.wheel(dy, 14, 1.2);
      await sleep(0.8);
    }
  };
  await rig.startRecording();
  await sleep(2.5);
  rig.mark('run-page', { run: run.id, durationMs: run.durationMs });
  const reviewQ = ui.getByText(/Two falsification checks/).first();
  await bring(reviewQ, 430);
  await sleep(0.6);
  const judgeRow = ui.getByText(/Two falsification checks/).first();
  const lastQ = ui.getByText(/review-2 explicitly reports/).first();
  const r1 = ui.getByText('cd (shell)', { exact: true }).nth(4);
  rig.mark('judge-questions', { first: await box(judgeRow), last: await box(lastQ), answer: await box(r1) });
  await sleep(4);
  const proposeQ = ui.getByText(/Your first edit adds/).first();
  await bring(proposeQ, 420);
  await sleep(0.6);
  const answer = ui.getByText(/^Proposal submitted: two edits/).first();
  rig.mark('propose-questions', { question: await box(proposeQ), answer: await box(answer), judge: await box(ui.getByText(/^Anchors verified unique/).first()) });
  await sleep(4);
  await rig.wheel(-6000, 12, 1.2);
  await sleep(1.2);
  await rig.click(ui.getByRole('link', { name: /View version/ }).or(ui.getByRole('button', { name: /View version/ })).first(), 1);
  await sleep(3);
  rig.mark('versions');
  const added = ui.getByText(/leave that row and its label out/).first();
  rig.mark('versions-line', { added: await box(added).catch(() => null) });
  await sleep(6);
  rig.mark('versions-end');
  await rig.stopRecording();
}

async function chat2(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/');
  await sleep(6);
  await F.closeDetailsCard(page);
  await rig.startRecording();
  await sleep(1.5);
  await rig.click(page.getByRole('button', { name: 'New thread', exact: true }), 0.8);
  await sleep(2);
  await F.closeDetailsCard(page);
  rig.mark('new-thread');
  await F.composeRequest(rig, { send: true });
  await rig.moveTo(1180, 700, 0.8);
  rig.hideCursor();
  const reply = await waitForReply(page);
  rig.mark('replied', { tail: reply.replace(/\n+/g, ' | ').slice(-700) });
  rig.showCursor();
  await sleep(2.5);
  await F.showLetter(rig, F.LETTER, PDF_WHEEL);
  await rig.stopRecording();
}

(async () => {
  const rig = await openRig(out, stage);
  if (stage === 'chat') await chat(rig);
  else if (stage === 'review') await review(rig);
  else if (stage === 'chat2') await chat2(rig);
  else if (stage === 'reset') rig.mark('reset', await resetDemo(rig));
  else throw new Error('unknown stage ' + stage);
  await rig.close();
})().catch((e) => { console.error(e); process.exit(1); });
