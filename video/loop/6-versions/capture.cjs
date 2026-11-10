// node capture.cjs <stage> <footage dir>
// Records the Versions scenario on the demo stack (BOOTH_URL, demo mode on).
// Stages:
//   versions  from a prepared chat to the Versions page, Diff vs parent, Branch from here on the older
//             version, Set as current, then back to the chat, where the Hone chip shows that version
//   reset     Reset demo, so the stack is back in the prepared state (not recorded)
const { openRig, resetDemo, sleep } = require('../../capture/rig.cjs');
const F = require('../../capture/flows.cjs');

const [stage, out] = process.argv.slice(2);
const CHAT = 'Offer letter for Chloé Martin';
const BRANCH = 'earlier-rules';

const box = async (loc) => {
  const b = await loc.boundingBox();
  return b && { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) };
};

async function openChat(rig) {
  const { page } = rig;
  const thread = page.locator('[data-thread-item]').filter({ hasText: CHAT }).first();
  await rig.click(thread, 0.8);
  await sleep(2.5);
  await F.closeDetailsCard(page);
}

async function versions(rig) {
  const { page } = rig;
  await page.goto(rig.BASE + '/');
  await sleep(6);
  const st = await rig.api('/hone/api/state');
  if (st.versions.length !== 3) throw new Error('expected the prepared state, press Reset demo first');
  await F.closeDetailsCard(page);
  await openChat(rig);
  await rig.startRecording();
  await sleep(2);
  const chip = page.getByText('AGENTS.md', { exact: false }).first();
  rig.mark('chat', { header: (await page.locator('header').first().innerText()).replace(/\n+/g, ' '), chip: await box(chip) });
  await sleep(2);

  await rig.click(page.getByRole('button', { name: 'Hone', exact: true }), 1);
  await sleep(3.5);
  const ui = page.frameLocator('iframe');
  await rig.click(ui.getByRole('link', { name: 'Versions' }).or(ui.getByRole('button', { name: 'Versions' })).first(), 0.8);
  await sleep(2.5);
  rig.mark('versions', { history: await box(ui.getByText('History', { exact: true }).locator('xpath=../..')) });
  await sleep(3);

  const diffTab = ui.getByText('Diff vs parent', { exact: true });
  await rig.hover(diffTab, 0.8);
  await sleep(0.4);
  const added = ui.getByText(/Fill placeholders run by run/).first();
  rig.mark('diff', { tab: await box(diffTab), added: await box(added), removed: await box(ui.getByText(/Save every letter as both/).first()) });
  await sleep(4);

  const older = ui.getByText('cc5cedc', { exact: true }).first();
  await rig.click(older, 0.9);
  await sleep(2.5);
  rig.mark('older', { row: await box(older.locator('xpath=ancestor::button[1]')) });
  await sleep(3);

  const branchBtn = ui.getByRole('button', { name: 'Branch from here' });
  await rig.click(branchBtn, 0.8);
  await sleep(1);
  rig.mark('branch-form', { button: await box(branchBtn) });
  await rig.type(BRANCH, 14);
  await sleep(0.6);
  const create = ui.getByRole('button', { name: 'Create branch' });
  rig.mark('branch-typed', { create: await box(create) });
  await rig.click(create, 0.6);
  await sleep(2.5);
  rig.mark('branch-created', { tag: await box(ui.getByText(BRANCH, { exact: true }).first()) });
  await sleep(2.5);

  const setBtn = ui.getByRole('button', { name: 'Set as current' });
  rig.mark('set-before', { button: await box(setBtn) });
  await rig.click(setBtn, 0.8);
  await sleep(1.2);
  const confirm = ui.getByRole('button', { name: /set as current/ });
  rig.mark('set-confirm', { button: await box(confirm) });
  await rig.click(confirm, 0.5);
  await sleep(3);
  const pill = ui.getByText(/· earlier-rules/).first();
  rig.mark('set-done', { serving: await box(ui.getByText('serving at /agents.md')), pill: await box(pill).catch(() => null) });
  await sleep(4);

  await openChat(rig);
  await sleep(4);
  rig.mark('chat-after', { header: (await page.locator('header').first().innerText()).replace(/\n+/g, ' '), chip: await box(page.getByText('AGENTS.md', { exact: false }).first()) });
  await sleep(5);
  rig.mark('end');
  await rig.stopRecording();
}

(async () => {
  const rig = await openRig(out, stage);
  if (stage === 'versions') await versions(rig);
  else if (stage === 'reset') rig.mark('reset', await resetDemo(rig));
  else throw new Error('unknown stage ' + stage);
  await rig.close();
})().catch((e) => { console.error(e); process.exit(1); });
