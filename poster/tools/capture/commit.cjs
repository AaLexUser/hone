const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async()=>{const b=await chromium.launch();const c=await b.newContext({viewport:{width:480,height:900},deviceScaleFactor:4});const p=await c.newPage();await p.goto('http://127.0.0.1:8095/runs/r_1cd0');await p.waitForTimeout(3500);
await p.screenshot({path:process.argv[2]+'/r480@4.png',clip:{x:0,y:0,width:480,height:520}});await b.close()})()
