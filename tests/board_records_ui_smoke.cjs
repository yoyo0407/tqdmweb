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
progress.wait()
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
  assert.strictEqual(record.exit_code,0);
  await wait(async()=> (await (await fetch(url+'state')).json()).training.data?.state==='finished');
  await post('shutdown',{});await wait(()=>app.exitCode!==null);
  await start();await page.goto(url);
  await page.locator('#tab-history').click();
  await page.locator('#record-list').selectOption(first.id);
  await page.locator('#view-record').click();
  await page.locator('#tab-record-charts').click();
  await wait(async()=> (await page.locator('#record-chart-full .chart-caption').innerText()).includes('(3501 points)'));
  assert.strictEqual(await page.locator('#history-panel button').filter({hasText:'Stop'}).count(),0);
  assert((await page.locator('#record-config').innerText()).includes(script));
  await page.locator('#tab-record-console').click();
  assert((await page.locator('#record-console-output').innerText()).includes('result=finished'));
  await page.locator('#tab-record-charts').click();
  const smoothing=page.locator('#record-chart-full select[name=smoothing]');
  await smoothing.selectOption('0.9');
  await wait(async()=> (await page.locator('#record-chart-full .chart-caption').innerText()).includes('EMA 0.9'));
  const values=await page.evaluate(()=> {
    const raw=[[0,0,1,1],[1,10,2,2],[2,0,3,3]];
    const smooth=smoothChartPoints(raw,0.6);
    return {raw,smooth};
  });
  assert.deepStrictEqual(values.raw.map(p=>p[1]),[0,10,0]);
  assert.deepStrictEqual(values.smooth.map(p=>p[1]),[0,4,2.4]);
  await smoothing.selectOption('0');
  assert((await page.locator('#record-chart-full .chart-caption').innerText()).includes('Raw data.'));
  await page.locator('#tab-record-overview').click();
  await page.locator('#record-name').fill('Experiment seed 42');
  await page.locator('#rename-record').click();
  await wait(async()=> (await page.locator(`#record-list option[value="${first.id}"]`).innerText()).includes('Experiment seed 42'));
  await page.locator('#record-search').fill('Experiment seed 42');
  assert.strictEqual(await page.locator('#record-list option').count(),2);
  await page.locator('#record-search').fill('no-matching-experiment');
  assert.strictEqual(await page.locator('#record-list option').count(),1);
  await page.locator('#record-search').fill('');
  const downloadPromise=page.waitForEvent('download');
  await page.locator('#export-record').click();
  const download=await downloadPromise;
  await download.saveAs(path.join(folder,'export.zip'));
  assert(fs.statSync(path.join(folder,'export.zip')).size>0);
  await post('run',config('--steps 100000 --delay 0.005'));
  await wait(async()=> (await (await fetch(url+'state')).json()).training.connected);
  const initialState = await (await fetch(url+'state')).json();
  const currentJob = initialState.job_id;
  const protectedDelete=await fetch(url+'record-delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:initialState.record_id})});
  assert.strictEqual(protectedDelete.status,400);
  const startStep = initialState.training.data.completed;
  const commands = [];
  page.on('request', r => {
    if (r.method()==='POST' && /\/(training-control|run|restart|stop|force-stop|shutdown)$/.test(new URL(r.url()).pathname)) commands.push(r.url());
  });
  await page.locator('#tab-monitor').click();
  await page.locator('#full-history-section > summary').click();
  await page.locator('#training-chart-recent select[name=smoothing]').selectOption('0.6');
  await page.locator('#tab-history').click();
  await page.locator('#view-record').click();
  await wait(async()=> (await page.locator('#record-chart-full .chart-caption').innerText()).includes('(3501 points)'));
  await wait(async()=> Number(await page.locator('#training-completed').innerText())>=startStep+50);
  const during = await (await fetch(url+'state')).json();
  assert.strictEqual(during.job_id,currentJob);
  assert.strictEqual(during.running,true);
  assert.strictEqual(during.training.data.control.pause_requested,false);
  assert.strictEqual(during.training.data.control.stop_requested,false);
  assert(during.training.data.completed>startStep);
  // A delayed earlier record cannot replace a more recent selection.
  await page.locator('#refresh-records').click();
  const currentRecord=during.record_id;
  await wait(async()=> await page.locator(`#record-list option[value="${currentRecord}"]`).count()===1);
  await page.route('**/record?id='+first.id,async route=>{await sleep(800);await route.continue();});
  await page.locator('#record-list').selectOption(first.id);
  await page.locator('#view-record').click();
  await page.locator('#record-list').selectOption(currentRecord);
  await page.locator('#view-record').click();
  await page.locator('#tab-record-overview').click();
  await wait(async()=> (await page.locator('#record-config').innerText()).includes('--steps 100000'));
  await sleep(1000);
  assert((await page.locator('#record-config').innerText()).includes('--steps 100000'));
  // Refresh must reload the displayed run even if its process/training state is unchanged.
  const completed = async()=> Number((await page.locator('#record-summary div').filter({has:page.locator('dt', {hasText:'Completed'})}).locator('dd').innerText()).split(' / ')[0]);
  const captured=await completed();
  await page.locator('#tab-record-charts').click();
  await page.locator('#record-chart-full select[name=smoothing]').selectOption('0.9');
  await page.locator('#record-chart-full input[name=xmin]').fill('0');
  await page.locator('#record-chart-full button[type=submit]').click();
  await wait(async()=> (await (await fetch(url+'state')).json()).training.data.completed>captured+25);
  await page.locator('#refresh-records').click();
  await wait(async()=> (await completed())>captured);
  assert.strictEqual(await page.locator('#record-chart-full select[name=smoothing]').inputValue(),'0.9');
  assert.strictEqual(await page.locator('#record-chart-full input[name=xmin]').inputValue(),'0');
  assert.strictEqual(commands.length,0,'History and tab switching must not issue training/process commands');
  await page.screenshot({path:path.join(folder,'tabs-history.png'),fullPage:true});
  await page.locator('#tab-monitor').click();
  assert.strictEqual(await page.locator('#training-chart-recent select[name=smoothing]').inputValue(),'0.6');
  await wait(async()=> !(await page.locator('#training-stop').isDisabled()));
  await page.locator('#tab-console').click();
  assert(!(await page.locator('#console-output').innerText()).includes('result=finished'));
  await page.locator('#tab-monitor').click();
  await page.screenshot({path:path.join(folder,'tabs-monitor.png'),fullPage:true});
  // Once a displayed running process exits, its terminal state and exit code update automatically.
  await page.locator('#tab-history').click();
  await page.locator('#tab-record-overview').click();
  await post('stop',{});
  await wait(async()=> (await (await fetch(url+'state')).json()).state==='exited');
  await wait(async()=> (await page.locator('#record-summary').innerText()).includes('exited'));
  const code=await page.locator('#record-summary div').filter({has:page.locator('dt', {hasText:'Exit Code'})}).locator('dd').innerText();
  assert.strictEqual(code,'0');
  assert((await page.locator('#record-summary').innerText()).includes('stopped'));
  // Force Stop has no final flush; distinguish the captured training state from process exit.
  await post('run',config('--steps 100000 --delay 0.005'));
  await wait(async()=> (await (await fetch(url+'state')).json()).training.connected);
  const forcedId=(await (await fetch(url+'state')).json()).record_id;
  await post('force-stop',{});
  await wait(async()=> (await (await fetch(url+'state')).json()).state==='failed');
  await page.locator('#tab-monitor').click();
  await wait(async()=> (await page.locator('#training-state').innerText()).startsWith('Last captured:'));
  const forcedState=await (await fetch(url+'state')).json();
  assert.notStrictEqual(forcedState.exit_code,0);
  await page.locator('#tab-history').click();
  await page.locator('#refresh-records').click();
  await wait(async()=> await page.locator(`#record-list option[value="${forcedId}"]`).count()===1);
  await page.locator('#record-list').selectOption(forcedId);
  await page.locator('#view-record').click();
  await wait(async()=> (await page.locator('#record-summary').innerText()).includes('failed'));
  const forcedCode=await page.locator('#record-summary div').filter({has:page.locator('dt', {hasText:'Exit Code'})}).locator('dd').innerText();
  assert.strictEqual(forcedCode,String(forcedState.exit_code));
  assert(await page.locator('#record-error').isVisible());
  assert((await page.locator('#record-error [data-error-summary]').innerText()).includes('Process exited'));
  const logPath=(await (await fetch(url+'record?id='+forcedId)).json()).log_path;
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#delete-record').click();
  await wait(async()=> (await page.locator(`#record-list option[value="${forcedId}"]`).count())===0);
  assert(fs.existsSync(logPath),'Deleting a record must preserve its original log');
  const failingScript=path.join(folder,'fail.py');
  fs.writeFileSync(failingScript,"raise RuntimeError('visible error-panel regression')\n");
  await post('run',{...config(''),script:failingScript});
  await wait(async()=> (await (await fetch(url+'state')).json()).state==='failed');
  await page.locator('#tab-monitor').click();
  await wait(async()=> (await page.locator('#run-error [data-error-summary]').innerText()).includes('visible error-panel regression'));
  await page.locator('#run-error details > summary').click();
  assert((await page.locator('#run-error [data-error-traceback]').innerText()).includes('RuntimeError'));
  assert((await page.locator('#run-error [data-error-log]').innerText()).includes('.log'));
  // Start a fresh execution for the Quit App regression.
  await post('run',config('--steps 100000 --delay 0.005'));
  await wait(async()=> (await (await fetch(url+'state')).json()).training.connected);
  // Keyboard navigation changes panels without navigating or sending commands.
  await page.locator('#tab-monitor').focus();await page.keyboard.press('ArrowRight');
  assert.strictEqual(await page.locator('#tab-console').getAttribute('aria-selected'),'true');
  await page.keyboard.press('Home');
  assert.strictEqual(await page.locator('#tab-run').getAttribute('aria-selected'),'true');
  await page.locator('#tab-monitor').click();
  await page.reload();
  await post('shutdown',{});await wait(()=>app.exitCode!==null);
  assert.strictEqual(app.exitCode,0,output);
  await start();
  const recent=(await (await fetch(url+'records')).json())[0];
  assert(recent.ended!==null,'Quit App must stop and finalize the training process');
  assert.strictEqual(recent.exit_code,0);
  record=await (await fetch(url+'record?id='+recent.id)).json();
  assert.strictEqual(record.training.data.state,'stopped');
  assert(record.training.data.completed>0);
  assert.strictEqual(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({result:'PASS',checks:['3501-point fast run final flush','app reopen persists full results and console','independent read-only archive while live steps keep increasing','live chart settings retained','out-of-order record selection','no commands from History or tab switching','manual refresh updates displayed results and preserves axes/EMA','running record automatically shows terminal state and exit 0','Force Stop shows actual failure code and labels last captured state','keyboard tab navigation','EMA and raw-data preservation','rename and search','ZIP export','delete preserves logs and blocks active runs','central error summary','Quit App stops process and app']}));
} finally {
  if(url&&app?.exitCode===null){await post('shutdown',{}).catch(()=>{});await wait(()=>app.exitCode!==null);}
  if(browser)await browser.close();
}})().catch(e=>{console.error(e);process.exitCode=1;});
