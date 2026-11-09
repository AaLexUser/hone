const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async()=>{const b=await chromium.launch();const c=await b.newContext({viewport:{width:1100,height:760},deviceScaleFactor:3,storageState:process.argv[2]+'/t3state.json'});const p=await c.newPage();
await p.goto('http://localhost:3773/');await p.waitForTimeout(4000);
await p.getByText('Settled',{exact:true}).click();await p.waitForTimeout(1200);
await p.getByText('Prepare New Hire',{exact:false}).first().click({force:true});await p.waitForTimeout(3500);
await p.getByRole('button',{name:'Needs work, tell Hone'}).click();await p.waitForTimeout(800);
await p.keyboard.type("There's a '£0' sign-on bonus line. If there's no bonus, just leave the line out.");await p.waitForTimeout(500);
await p.mouse.move(900,600);await p.waitForTimeout(300);
await p.screenshot({path:process.argv[2]+'/t3-fb-full.png'});
await b.close()})()
