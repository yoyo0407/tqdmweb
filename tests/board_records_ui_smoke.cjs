const {chromium} = require('playwright');
const {spawn} = require('child_process');
const fs = require('fs'), path = require('path'), assert = require('assert');
const root = process.cwd();
const folder = fs.mkdtempSync(path.join(root, 'runs', 'records-smoke-'));
const db = path.join(folder, 'records.sqlite3');
const script = path.join(folder, 'train.py');
fs.writeFileSync(script, `import argparse,time
from qtqdm import Qtqdm
p=argparse.ArgumentParser()
p.add_argument('--steps',type=int,default=3501)
p.add_argument('--delay',type=float,default=0)
a=p.parse_args()
with Qtqdm(range(a.steps),open_browser=False) as progress:
    for i in progress:
        progress.set_postfix(score=i,loss=(i%3)*10)
        if a.delay: time.sleep(a.delay)
print('result='+progress.state,flush=True)
progress.close()
`);
let app, url, browser, output = '';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const wait = async fn => { const end = Date.now()+20000; while (!await fn()) { if(Date.now()>end) throw Error('Timeout '+fn+'\n'+output); await sleep(50); } };
const post = async (route, data) => {
  const response = await fetch(url+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json(); assert(response.ok,JSON.stringify(result)); return result;
};
const start = async () => {
  output = ''; url = null;
  app = spawn(path.join(root,'.venv','Scripts','python.exe'),['-u','tqdmboard.py','--no-browser','--records-path',db],{cwd:root,windowsHide:true});
  app.stdout.on('data',b=>output+=b); app.stderr.on('data',b=>output+=b);
  await wait(()=>{url=output.match(/tqdmboard: (http:\/\/127\.0\.0\.1:\d+\/)/)?.[1];return url;});
};
const config = arguments => ({script,python:path.join(root,'.venv','Scripts','python.exe'),working_directory:root,arguments});
(async()=>{try {
  browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
  const context=await browser.newContext();
  const errors=[];context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));
  await start();
  let page=await context.newPage();await page.goto(url);
  await post('run',config(''));
  await wait(async()=> (await (await fetch(url+'state')).json()).state==='exited');
  const first=(await (await fetch(url+'records')).json())[0];
  let record=await (await fetch(url+'record?id='+first.id)).json();
  assert.strictEqual(record.training.data.completed,3501);
  assert.strictEqual(record.training.data.state,'finished');
  assert.strictEqual(record.training.data.history_updates,3501);
  await post('shutdown',{});await wait(()=>app.exitCode!==null);
  await start();await page.goto(url);
  await page.locator('#record-list').selectOption(first.id);
  await page.locator('#view-record').click();
  await page.locator('#advanced-section > summary').click();
  await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).includes('(3501 points)'));
  assert(await page.locator('#training-pause').isDisabled());
  assert((await page.locator('#record-config').innerText()).includes(script));
  assert((await page.locator('#console-output').innerText()).includes('result=finished'));
  const smoothing=page.locator('#training-chart-recent select[name=smoothing]');
  await smoothing.selectOption('0.9');
  await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).includes('EMA 0.9'));
  const values=await page.evaluate(()=> {
    const raw=[[0,0,1,1],[1,10,2,2],[2,0,3,3]];
    const smooth=smoothChartPoints(raw,0.6);
    return {raw,smooth};
  });
  assert.deepStrictEqual(values.raw.map(p=>p[1]),[0,10,0]);
  assert.deepStrictEqual(values.smooth.map(p=>p[1]),[0,4,2.4]);
  await smoothing.selectOption('0');
  assert((await page.locator('#training-chart-recent .chart-caption').innerText()).includes('Raw data.'));
  await post('run',config('--steps 100000 --delay 0.005'));
  await wait(async()=> (await (await fetch(url+'state')).json()).training.connected);
  assert(await page.locator('#training-stop').isDisabled());
  assert(await page.locator('#stop-process').isDisabled());
  await page.locator('#live-view').click();
  await wait(async()=> !(await page.locator('#training-stop').isDisabled()));
  await page.reload();await sleep(3500);assert.strictEqual(app.exitCode,null);
  const second=await context.newPage();await second.goto(url);
  await page.close({runBeforeUnload:true});await sleep(3500);assert.strictEqual(app.exitCode,null);
  await second.close({runBeforeUnload:true});await wait(()=>app.exitCode!==null);
  assert.strictEqual(app.exitCode,0,output);
  await start();
  const recent=(await (await fetch(url+'records')).json())[0];
  assert(recent.ended!==null,'Last-tab shutdown must stop and finalize the training process');
  assert.strictEqual(recent.exit_code,0);
  record=await (await fetch(url+'record?id='+recent.id)).json();
  assert.strictEqual(record.training.data.state,'stopped');
  assert(record.training.data.completed>0);
  assert.strictEqual(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({result:'PASS',checks:['3501-point fast run final flush','app reopen persists full results and console','read-only archive during live training','EMA and raw-data preservation','reload grace','multiple tabs','last-tab process and app shutdown']}));
} finally {
  if(url&&app?.exitCode===null){await post('shutdown',{}).catch(()=>{});await wait(()=>app.exitCode!==null);}
  if(browser)await browser.close();
}})().catch(e=>{console.error(e);process.exitCode=1;});
