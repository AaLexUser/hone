const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const out=process.argv[2];
(async()=>{const b=await chromium.launch();
for (const [w,u,f] of [[620,'/','d620'],[1440,'/runs/r_1cd0','r1440'],[700,'/runs/r_1cd0','r700'],[760,'/versions','v760']]){
 const c=await b.newContext({viewport:{width:w,height:1600},deviceScaleFactor:4});const p=await c.newPage();await p.goto('http://127.0.0.1:8095'+u);await p.waitForTimeout(3500);
 await p.screenshot({path:out+'/'+f+'@4.png',clip:{x:0,y:0,width:w,height:f==='r1440'?700:(f==='r700'?400:700)}});await c.close()}
await b.close()})()
