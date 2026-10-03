const {chromium}=require('playwright');
const {spawn}=require('child_process');
const path=require('path'),assert=require('assert');
const root=process.cwd();
const app=spawn(path.join(root,'.venv','Scripts','python.exe'),['-u','tqdmboard.py','--no-browser'],{cwd:root,windowsHide:true});
let output='',url,browser;
app.stdout.on('data',b=>output+=b);app.stderr.on('data',b=>output+=b);
const wait=async(fn)=>{const end=Date.now()+15000;while(!await fn()){if(Date.now()>end)throw Error('Timeout '+fn+'\n'+output);await new Promise(r=>setTimeout(r,50));}};
(async()=>{try{
 await wait(()=>{url=output.match(/tqdmboard: (http:\/\/127\.0\.0\.1:\d+\/)/)?.[1];return url;});
 const original=await (await fetch(url+'state')).json();
 const allPoints=Array.from({length:20000},(_,i)=>[i/100,(i%199)*8,i+1,i+1]);
 const points=allPoints.slice(-300);
 const small=points.map(p=>[p[0],0.000010001+(p[2]-19701)*1e-10,p[2],p[3]]);
 const data={history_updates:20000,description:'Chart display test',state:'finished',started:20000,completed:20000,total:20000,elapsed:200,rate:100,remaining:0,metrics:{score:'1588'},
  control:{finished:true,capabilities:{save_checkpoint:false,learning_rate:false},save_at_step:null},
  charts:{score:{overview:points},loss:{overview:small}}};
 browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
 const context=await browser.newContext({deviceScaleFactor:2,viewport:{width:1280,height:900}});
 const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  window.chartText=new WeakMap();
  const clear=CanvasRenderingContext2D.prototype.clearRect,fill=CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.clearRect=function(...args){window.chartText.set(this.canvas,[]);return clear.apply(this,args);};
  CanvasRenderingContext2D.prototype.fillText=function(text,...args){window.chartText.get(this.canvas)?.push(String(text));return fill.call(this,text,...args);};
 });
 await page.route('**/state',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...original,job_id:1,running:true,training:{data,connected:true}})}));
 await page.route('**/training-history?*',route=>{
  const after=Number(new URL(route.request().url()).searchParams.get('after'));
  const end=Math.min(allPoints.length,after+2000);
  const score=allPoints.slice(after,end);
  const loss=score.map(p=>[p[0],0.000010001+(p[2]-19701)*1e-10,p[2],p[3]]);
  route.fulfill({contentType:'application/json',body:JSON.stringify({charts:{score,loss},next_update:end,has_more:end<allPoints.length})});
 });
 await page.goto(url);
 await wait(async()=>await page.locator('#training-chart-overview canvas').isVisible());
 assert.strictEqual(await page.locator('#tab-monitor').getAttribute('aria-selected'),'true');
 await page.locator('#tab-run').click();
 assert(await page.locator('#arguments').isVisible());
 assert.strictEqual(await page.locator('#arguments').evaluate(el=>el.closest('#run-panel')!=null),true);
 await page.locator('#tab-monitor').click();
 const checkResolution=async id=>{
  await wait(async()=>page.locator(id).evaluate(c=>c.width===Math.round(c.clientWidth*devicePixelRatio)&&c.height===Math.round(c.clientHeight*devicePixelRatio)));
  const size=await page.locator(id).evaluate(c=>({bitmap:c.width,css:c.clientWidth,dpr:devicePixelRatio}));
  assert(size.bitmap>640);return size;
 };
 const basic=await checkResolution('#training-chart-overview canvas');
 await page.locator('#full-history-section > summary').click();
 const recent=await checkResolution('#training-chart-recent canvas');
 const form=page.locator('#training-chart-recent form');
 await form.locator('select[name=y]').selectOption('score');
 await form.locator('input[name=xmin]').fill('0');await form.locator('input[name=ymin]').fill('0');
 await form.locator('button[type=submit]').click();
 await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).includes('Samples: 1 – 20,000 (20000 points)'));
 assert((await page.locator('#training-chart-recent .chart-caption').innerText()).startsWith('X: 0 – 20,000; Y: 0'));
 await page.screenshot({path:path.join(root,'runs','chart-manual-range.png'),fullPage:true});
 await form.locator('input[name=xmin]').fill('');await form.locator('button[type=submit]').click();
 await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).startsWith('X: 1 – 20,000'));
 const labels=await page.locator('#training-chart-recent canvas').evaluate(c=>window.chartText.get(c));
 assert(labels.includes('1'));assert(labels.includes('20,000'));assert(!labels.some(label=>/^19,\d{3}\./.test(label)),JSON.stringify(labels));
 await form.locator('select[name=y]').selectOption('loss');
 await form.locator('input[name=ymin]').fill('');await form.locator('button[type=submit]').click();
 await form.locator('input[name=xmin]').fill('19701');await form.locator('button[type=submit]').click();
 const tiny=await page.locator('#training-chart-recent canvas').evaluate(c=>window.chartText.get(c));
 const ylabels=tiny.filter(t=>t.includes('e-'));
 assert.strictEqual(new Set(ylabels).size,5,JSON.stringify(tiny));
 // More updates must extend the full series, retaining the very first point.
 for(let i=20000;i<20500;i++)allPoints.push([i/100,(i%199)*8,i+1,i+1]);
 data.history_updates=20500;
 await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).includes('(20500 points)'));
 await form.locator('input[name=xmin]').fill('');await form.locator('button[type=submit]').click();
 await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).includes('Samples: 1 – 20,500 (20500 points)'));
 await page.reload();
 await page.locator('#full-history-section > summary').click();
 await wait(async()=> (await page.locator('#training-chart-recent .chart-caption').innerText()).includes('Samples: 1 – 20,500 (20500 points)'));
 await page.setViewportSize({width:390,height:844});
 await wait(async()=>page.locator('#training-chart-recent canvas').evaluate(c=>c.width===Math.round(c.clientWidth*devicePixelRatio)));
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.setViewportSize({width:1280,height:900});await checkResolution('#training-chart-recent canvas');
 await form.locator('select[name=y]').selectOption('score');
 await page.screenshot({path:path.join(root,'runs','chart-auto-range.png'),fullPage:true});
 await page.locator('#training-chart-recent canvas').screenshot({path:path.join(root,'runs','chart-recent.png')});
 assert.strictEqual(errors.length,0,errors.join('\n'));
 console.log(JSON.stringify({result:'PASS',basic,recent,checks:['Arguments in Run','DPR 2 bitmap','Monitor details open resize','accurate large Step labels','distinct tiny value labels','full 20000-point history','updates retain first point','reload restores 20500 points','manual bounds and sample range','mobile resize and no overflow']}));
}finally{
 if(url&&app.exitCode===null){await fetch(url+'shutdown',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).catch(()=>{});await wait(()=>app.exitCode!==null);}
 if(browser)await browser.close();
}})().catch(e=>{console.error(e);process.exitCode=1;});
