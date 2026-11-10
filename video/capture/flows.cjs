const { sleep } = require('./rig.cjs');

const REQUEST = 'Write the offer letter for Amara Osei from this approval, using the template. Save it as DOCX and PDF.';
const FEEDBACK = 'Drop the Sign-on Bonus £0 and Equity Grant 0 shares rows, the approval grants neither.';
const LETTER = 'Offer_Osei_Amara.pdf';

const item = (page, p) => page.locator(`[data-item-path="${p}"]`).first();

async function closeDetailsCard(page) {
  if (await page.getByRole('button', { name: 'Add project script' }).isVisible().catch(() => false)) {
    await page.getByRole('button', { name: 'Toggle thread details panel' }).click();
    await sleep(0.5);
  }
}

const OFFER_FILES = ['Inbox/Hiring approval Amara Osei.pdf', 'Inbox/Offer letter template.docx'];

// Inbox open, the files dragged into the composer, the request typed. Sends only when send is true.
async function composeRequest(rig, { send, files = OFFER_FILES, request = REQUEST }) {
  const { page } = rig;
  const inbox = item(page, 'Inbox/');
  if ((await inbox.getAttribute('aria-expanded')) !== 'true') {
    await rig.click(inbox, 0.8);
    await sleep(0.8);
  }
  rig.mark('inbox-open');
  const editor = page.locator('[contenteditable="true"]').first();
  for (const [i, f] of files.entries()) {
    await rig.drag(item(page, f), editor);
    rig.mark(`dragged-${i}`);
  }
  await editor.evaluate((e) => { e.spellcheck = false; });
  await editor.click();
  await page.keyboard.press('End');
  await rig.type(' ' + request);
  rig.mark('typed');
  await sleep(0.8);
  if (!send) return;
  await rig.click(page.getByRole('button', { name: 'Submit message' }), 0.5);
  rig.mark('sent');
}

// Opens the letter in the previewer, maximized, scrolled to the compensation rows.
async function showLetter(rig, name, wheelPx) {
  const { page } = rig;
  await rig.click(item(page, name), 0.8);
  await sleep(2.5);
  rig.mark('letter-open');
  await rig.click(page.getByRole('button', { name: 'Maximize panel' }), 0.7);
  await sleep(2);
  rig.mark('letter-max');
  await rig.moveTo(900, 640, 0.6);
  await rig.wheel(wheelPx, 12, 1.2);
  await sleep(1.2);
  rig.mark('letter-table');
  await sleep(5);
  rig.mark('letter-table-end');
  await rig.click(page.getByRole('button', { name: 'Restore panel size' }), 0.7);
  await sleep(1);
  await rig.click(page.getByRole('button', { name: `Close ${name}` }), 0.6);
  await sleep(1.2);
  rig.mark('letter-closed');
}

module.exports = { REQUEST, FEEDBACK, LETTER, item, closeDetailsCard, composeRequest, showLetter };
