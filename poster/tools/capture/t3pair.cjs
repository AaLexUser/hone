const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async()=>{const b=await chromium.launch();const c=await b.newContext({viewport:{width:1100,height:760},deviceScaleFactor:1});const p=await c.newPage();
await p.goto('http://localhost:3773/pair#token='+process.argv[3]);await p.waitForTimeout(6000);
await c.storageState({path:process.argv[2]+'/t3state.json'});
await p.screenshot({path:process.argv[2]+'/t3-1.png'});
const items=await p.$$eval('[href], button',as=>as.map(a=>(a.textContent||'').trim().slice(0,50)+' | '+(a.getAttribute('href')||'')).filter(x=>x.length>3).slice(0,40));console.log(items.join('\n'));
await b.close()})()
