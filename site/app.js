import {KS,isNumber,percent,number,escapeHTML as e,compactName,metricName,indexData,lookup,availableModels,csv} from './lib/data.js';

const $ = selector => document.querySelector(selector);
const icons = {
  moon:'<path d="M20 15.5A9 9 0 0 1 8.5 4 9 9 0 1 0 20 15.5Z"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  close:'<path d="M6 6l12 12M18 6 6 18"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||''}</svg>`;
const colors=['#18765c','#5b6eb3','#bc723c','#9b5d91','#3987a0','#788b38','#c25c5c','#726450','#3f827a','#847ab1','#8f7734','#9c6570','#526b91','#677d63'];
// Viridis, fixed to the report's 0–1 score range across every table and selection.
const scoreColors=['440154','472d7b','3b528b','2c728e','21918c','28ae80','5ec962','addc30','fde725'].map(hex=>[0,2,4].map(offset=>parseInt(hex.slice(offset,offset+2),16)));
function heatAttributes(value){
  if(!isNumber(value))return '';
  const position=Math.max(0,Math.min(1,value))*(scoreColors.length-1),i=Math.min(Math.floor(position),scoreColors.length-2),fraction=position-i;
  const rgb=scoreColors[i].map((channel,c)=>Math.round(channel+(scoreColors[i+1][c]-channel)*fraction));
  const linear=rgb.map(channel=>{const s=channel/255;return s<=.04045?s/12.92:((s+.055)/1.055)**2.4;});
  const luminance=linear[0]*.2126+linear[1]*.7152+linear[2]*.0722,color=`rgb(${rgb.join(',')})`;
  return `class="score-heat" style="--score-color-light:${color};--score-color-dark:${color};--score-ink:${luminance>.179?'#000':'#fff'}"`;
}
let data,index,state,toastTimer,dialogRequest=0;
const breakdownCache=new Map();
function readStorage(key){try{return localStorage.getItem(key);}catch{return null;}}
function saveStorage(key,value){try{localStorage.setItem(key,value);}catch{}}
function applyTheme(theme){document.documentElement.dataset.theme=theme;$('#theme-toggle').innerHTML=icon(theme==='dark'?'sun':'moon');$('#theme-toggle').setAttribute('aria-label',`Switch to ${theme==='dark'?'light':'dark'} theme`);}
applyTheme(readStorage('edge-theme')||'light');
function notify(message){$('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),2500);}
function model(id){return index.models.get(id)||{id,name:id,family:'Other'};}
function benchmark(id=state.benchmark){return index.benchmarks.get(id);}
function modelPool(){return availableModels(data,state.run,'all',state.query,state.family);}
function models(){return modelPool().filter(m=>state.modelIds.includes(m.id));}
function benchPool(){return data.benchmarks.filter(b=>state.category==='all'||b.category===state.category);}
function benches(){return benchPool().filter(b=>state.benchIds.includes(b.id));}
function rowFor(id,b=state.benchmark,run=state.run,k=state.k,metric=state.metric){return lookup(index,run,id,b,metric,run==='greedy'?1:k);}
function option(value,label,current){return `<option value="${e(value)}" ${value===current?'selected':''}>${e(label)}</option>`;}
function benchmarkSelect(){return `<select class="benchmark-select" aria-label="Curve benchmark">${benches().map(b=>option(b.id,b.name,state.benchmark)).join('')}</select>`;}
function metricSelect(){return `<select class="metric-select" aria-label="Curve metric">${(benchmark()?.metrics||[]).map(m=>option(m,metricName(m),state.metric)).join('')}</select>`;}
function selectedList(params,key,valid){return params.has(key)?params.get(key).split(',').filter(id=>valid.includes(id)):valid;}
function getState(){
  const p=new URLSearchParams(location.hash.slice(1));
  // Keep previously shared report links usable after the navigation change.
  const oldSample=p.get('view')==='sampling';
  const s={run:oldSample?'sample128':p.get('run')||'greedy',k:Number(p.get('k')||1),metricMode:p.get('metrics')||'primary',query:p.get('q')||'',family:p.get('family')||'all',category:p.get('suite')||'all',benchmark:p.get('benchmark')||'ai2d',metric:p.get('metric')||'accuracy',sortBenchmark:p.get('sortBenchmark')||'',sortMetric:p.get('sortMetric')||'',direction:p.get('direction')||'desc',modelIds:selectedList(p,'models',data.models.map(m=>m.id)),benchIds:selectedList(p,'benches',data.benchmarks.map(b=>b.id))};
  if(!['greedy','sample128'].includes(s.run))s.run='greedy';
  if(!KS.includes(s.k))s.k=1;
  if(!['primary','all'].includes(s.metricMode))s.metricMode='primary';
  if(!['all','text','vision','instruction'].includes(s.category))s.category='all';
  if(!['all',...data.models.map(m=>m.family)].includes(s.family))s.family='all';
  if(!['asc','desc'].includes(s.direction))s.direction='desc';
  if(!index.benchmarks.has(s.sortBenchmark))s.sortBenchmark='';
  return s;
}
function normalize(){
  const bs=benches();
  if(!bs.some(b=>b.id===state.benchmark))state.benchmark=bs[0]?.id||data.benchmarks[0].id;
  if(!benchmark().metrics.includes(state.metric))state.metric=benchmark().primaryMetric;
  if(state.sortBenchmark&&!bs.some(b=>b.id===state.sortBenchmark&&(state.metricMode==='all'?b.metrics:[b.primaryMetric]).includes(state.sortMetric))){state.sortBenchmark='';state.sortMetric='';}
}
function writeURL(){
  const p=new URLSearchParams({run:state.run,k:String(state.k),metrics:state.metricMode,models:state.modelIds.join(','),benches:state.benchIds.join(','),benchmark:state.benchmark,metric:state.metric});
  if(state.query)p.set('q',state.query);if(state.family!=='all')p.set('family',state.family);if(state.category!=='all')p.set('suite',state.category);
  if(state.sortBenchmark){p.set('sortBenchmark',state.sortBenchmark);p.set('sortMetric',state.sortMetric);p.set('direction',state.direction);}
  history.replaceState(null,'',`#${p}`);
}
function update(change){
  const focus=document.activeElement,selection=focus?.id==='model-search'?[focus.selectionStart,focus.selectionEnd]:null;
  const focusAttribute=['data-model','data-benchmark','data-models','data-benches','data-run','data-sort-benchmark'].find(attribute=>focus?.hasAttribute(attribute));
  const focusValue=focusAttribute?focus.getAttribute(focusAttribute):null;
  const focusMetric=focus?.getAttribute('data-sort-metric');
  const scroll=$('#content .table-scroll'),position=scroll?[scroll.scrollLeft,scroll.scrollTop]:null;
  Object.assign(state,change);if(change.benchmark)state.metric=benchmark().primaryMetric;
  normalize();writeURL();render();
  if(selection){$('#model-search')?.focus();$('#model-search')?.setSelectionRange(...selection);}
  else if(focusAttribute)$(`[${focusAttribute}="${CSS.escape(focusValue)}"]${focusMetric?`[data-sort-metric="${CSS.escape(focusMetric)}"]`:''}`)?.focus({preventScroll:true});
  if(position&&$('#content .table-scroll')){$('#content .table-scroll').scrollLeft=position[0];$('#content .table-scroll').scrollTop=position[1];}
}
function selectionPanels(){
  const mp=modelPool(),bp=benchPool();
  return `<section class="selection-panel" aria-label="Models"><div class="selector-head"><span class="selection-label">Models</span><span class="selection-count">${models().length}/${mp.length}</span><button class="text-button" data-models="all">All</button><button class="text-button" data-models="none">None</button><input id="model-search" type="search" placeholder="Search" aria-label="Search models" value="${e(state.query)}"><select id="family-select" aria-label="Model family">${['all',...new Set(data.models.map(m=>m.family))].map(f=>option(f,f==='all'?'All families':f,state.family)).join('')}</select></div><div class="model-chips">${mp.map(m=>`<button class="model-chip ${state.modelIds.includes(m.id)?'active':''}" data-model="${e(m.id)}" aria-pressed="${state.modelIds.includes(m.id)}" title="${e(m.name)}">${e(compactName(m.name))}</button>`).join('')||'<span class="muted">No matches</span>'}</div></section><section class="selection-panel" aria-label="Benchmarks"><div class="selector-head"><span class="selection-label">Benchmarks</span><span class="selection-count">${benches().length}/${bp.length}</span><button class="text-button" data-benches="all">All</button><button class="text-button" data-benches="none">None</button><select id="category-select" aria-label="Benchmark suite">${['all','text','vision','instruction'].map(c=>option(c,({all:'All suites',text:'Text',vision:'Vision',instruction:'Instruction'})[c],state.category)).join('')}</select></div><div class="benchmark-chips">${bp.map(b=>`<button class="benchmark-chip ${state.benchIds.includes(b.id)?'active':''}" data-benchmark="${e(b.id)}" aria-pressed="${state.benchIds.includes(b.id)}">${e(b.name)}</button>`).join('')}</div></section>`;
}
function columns(){return benches().flatMap(b=>(state.metricMode==='all'?b.metrics:[b.primaryMetric]).map(metric=>({benchmark:b,metric})));}
function sortedModels(){
  const list=models();if(!state.sortBenchmark)return list;
  return list.sort((a,b)=>{
    const av=rowFor(a.id,state.sortBenchmark,state.run,state.k,state.sortMetric)?.pass_at_k,bv=rowFor(b.id,state.sortBenchmark,state.run,state.k,state.sortMetric)?.pass_at_k;
    if(!isNumber(av))return isNumber(bv)?1:a.name.localeCompare(b.name);if(!isNumber(bv))return -1;
    return (av-bv)*(state.direction==='asc'?1:-1)||a.name.localeCompare(b.name);
  });
}
function scoreCell(row,id,b,metric){
  if(!isNumber(row?.pass_at_k))return '<span class="missing" title="No reported result">—</span>';
  const interval=isNumber(row.ci_lower)&&isNumber(row.ci_upper)?` · 95% CI ${percent(row.ci_lower)}–${percent(row.ci_upper)}`:'';
  return `<button class="score-cell" data-detail="${e(id)}" data-detail-benchmark="${e(b.id)}" data-detail-metric="${e(metric)}" data-detail-k="${row.k}" data-detail-run="${e(row.run)}" title="${e(metricName(metric))}${interval}" aria-label="${e(model(id).name)}, ${e(b.name)}, ${e(metricName(metric))}, k ${row.k}, ${percent(row.pass_at_k)} percent">${percent(row.pass_at_k)}</button>`;
}
function matrix(){
  const ms=sortedModels(),cols=columns();
  if(!ms.length||!cols.length)return '<div class="empty">Select models and benchmarks.</div>';
  const head=cols.map(c=>{const active=state.sortBenchmark===c.benchmark.id&&state.sortMetric===c.metric;return `<th scope="col" class="metric-heading" aria-sort="${active?(state.direction==='asc'?'ascending':'descending'):'none'}"><button data-sort-benchmark="${e(c.benchmark.id)}" data-sort-metric="${e(c.metric)}" title="${e(c.benchmark.name)} · ${e(metricName(c.metric))}"><span>${e(c.benchmark.name)}</span><small>${e(metricName(c.metric))} ${active?(state.direction==='desc'?'↓':'↑'):''}</small></button></th>`;}).join('');
  return `<div class="table-scroll" tabindex="0" role="region" aria-label="Greedy score matrix"><table class="matrix"><thead><tr><th scope="col" class="model-column"><button data-sort-model>Model</button></th>${head}</tr></thead><tbody>${ms.map(m=>`<tr data-model-row="${e(m.id)}"><th scope="row" class="model-column"><span class="model-name" title="${e(m.name)}">${e(compactName(m.name))}</span></th>${cols.map(c=>{const row=rowFor(m.id,c.benchmark.id,'greedy',1,c.metric);return `<td ${heatAttributes(row?.pass_at_k)}>${scoreCell(row,m.id,c.benchmark,c.metric)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function toolbar(){return `<div class="table-toolbar">${state.run==='sample128'?`<label>k <select id="k-select" aria-label="Sampling budget">${KS.map(k=>option(k,k,state.k)).join('')}</select></label>`:`<label>Metrics <select id="metric-mode" aria-label="Metric display">${option('primary','Primary',state.metricMode)}${option('all','All',state.metricMode)}</select></label>`}<span class="results-count">${models().length} models · ${benches().length} benchmarks</span></div>`;}
function curveData(){return models().map(m=>({id:m.id,color:colors[data.models.findIndex(item=>item.id===m.id)%colors.length],points:KS.map(k=>rowFor(m.id,state.benchmark,'sample128',k)).filter(r=>r&&isNumber(r.pass_at_k))})).filter(s=>s.points.length);}
function curveChart(){
  const narrow=matchMedia('(max-width:700px)').matches,series=curveData(),w=narrow?400:560,h=w,pad=narrow?36:44,p={l:pad,r:pad,t:pad,b:pad},iw=w-p.l-p.r,ih=h-p.t-p.b,x=k=>p.l+Math.log2(k)/7*iw,y=v=>p.t+(1-v)*ih;
  if(!series.length)return '<div class="empty">No sampled results.</div>';
  return `<svg class="curve-svg" viewBox="0 0 ${w} ${h}" role="group" aria-label="${e(benchmark().name)} sampling scores"><title>${e(benchmark().name)} · ${e(metricName(state.metric))}</title>${[0,.25,.5,.75,1].map(v=>`<line class="curve-grid" x1="${p.l}" x2="${w-p.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${p.l-10}" y="${y(v)+3}" text-anchor="end">${v*100}</text>`).join('')}<path class="curve-axes" d="M${p.l},${p.t}V${h-p.b}H${w-p.r}" fill="none" stroke="var(--muted)"/>${KS.map(k=>`<text x="${x(k)}" y="${h-p.b+20}" text-anchor="middle">${k}</text>`).join('')}<line x1="${x(state.k)}" x2="${x(state.k)}" y1="${p.t}" y2="${h-p.b}" stroke="var(--line)" stroke-dasharray="4 4"/>${series.map(s=>`<path d="${s.points.map((r,i)=>`${i?'L':'M'}${x(r.k).toFixed(2)},${y(r.pass_at_k).toFixed(2)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="1.7"/>${s.points.map(r=>`<circle class="chart-point" cx="${x(r.k)}" cy="${y(r.pass_at_k)}" r="3" fill="var(--panel)" stroke="${s.color}" stroke-width="1.5" tabindex="0" data-point="${e(s.id)}" data-point-k="${r.k}" aria-label="${e(model(s.id).name)}, k ${r.k}, ${percent(r.pass_at_k)} percent"/>`).join('')}`).join('')}</svg>`;
}
function curves(){
  if(!models().length||!benches().length)return '<div class="empty">Select models and benchmarks.</div>';
  const series=curveData();
  return `<div class="curve-panel"><div class="curve-controls">${benchmarkSelect()}${metricSelect()}<span class="muted">Score (%) / k</span></div>${curveChart()}<div class="curve-legend">${series.map(s=>`<span class="legend-item"><span class="legend-dot" style="background:${s.color}"></span>${e(compactName(model(s.id).name))}</span>`).join('')}</div></div><div class="table-scroll" tabindex="0" role="region" aria-label="Sampling scores"><table class="curve-table matrix"><thead><tr><th class="model-column" scope="col">Model</th>${KS.map(k=>`<th scope="col">k = ${k}</th>`).join('')}</tr></thead><tbody>${series.map(s=>`<tr data-model-row="${e(s.id)}"><th scope="row" class="model-column"><span class="model-name" title="${e(model(s.id).name)}">${e(compactName(model(s.id).name))}</span></th>${KS.map(k=>{const r=s.points.find(p=>p.k===k);return `<td ${heatAttributes(r?.pass_at_k)}>${scoreCell(r,s.id,benchmark(),state.metric)}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function render(){
  $('#chart-tooltip').hidden=true;
  $('#navigation').innerHTML=[['greedy','Greedy'],['sample128','Sample']].map(([id,label])=>`<button class="nav-item ${state.run===id?'active':''}" data-run="${id}" ${state.run===id?'aria-current="page"':''}>${label}</button>`).join('');
  $('#page-title').textContent=state.run==='greedy'?'Greedy':'Sample';
  const parameters=data.sources.find(s=>s.id===state.run).parameters;
  $('#run-meta').textContent=`n = ${parameters.n} · T = ${parameters.temperature}`;
  $('#content').innerHTML=`${selectionPanels()}<section class="results-panel" aria-label="Results">${toolbar()}${state.run==='sample128'?curves():matrix()}<div class="table-footer"><span class="score-scale" aria-label="Score color scale: 0 to 100 percent"><span>0</span><span class="score-gradient" aria-hidden="true"></span><span>100%</span><span>· — missing</span></span><a href="data/dashboard.json" download="edgeinstant-results.json">JSON ↓</a></div></section>`;
}
function toggleList(key,id){update({[key]:state[key].includes(id)?state[key].filter(item=>item!==id):[...state[key],id]});}
function exportRows(){
  if(state.run==='sample128')return benches().length?curveData().flatMap(s=>s.points):[];
  return models().flatMap(m=>columns().map(c=>rowFor(m.id,c.benchmark.id,state.run,state.k,c.metric)).filter(Boolean));
}
function download(rows){
  if(!rows.length){notify('No results selected.');return;}
  const fields=[...new Set(rows.flatMap(r=>Object.keys(r)))],url=URL.createObjectURL(new Blob(['\ufeff'+csv(rows,fields)],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');
  a.href=url;a.download=`edgeinstant-${state.run}-${state.run==='sample128'?'curves':'k1'}.csv`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notify(`${rows.length} rows exported.`);
}

async function showDetails(id, bId=state.benchmark, metric=state.metric, run=state.run, k=state.k) {
 const row=rowFor(id,bId,run,k,metric),b=index.benchmarks.get(bId),request=++dialogRequest;
 if(!row){notify('No result.');return;}
 const raw=isNumber(row.raw_score)?`<p><b>Raw score:</b> ${number(row.raw_score)}${isNumber(row.score_max)?` / ${number(row.score_max)}`:''}</p>`:'';
 $('#detail-content').innerHTML=`<div class="dialog-header"><div><h2 id="detail-title">${e(b.name)}</h2><p>${e(model(id).name)}</p></div><button class="icon-button" data-close aria-label="Close result details">${icon('close')}</button></div><div class="dialog-body"><span class="badge">${run==='greedy'?'Greedy':`Sample ×128 · k = ${k}`}</span><div class="detail-score" style="margin-top:18px">${percent(row.pass_at_k)}<small>%</small></div><div class="detail-ci">${e(metricName(row.metric))} · ${isNumber(row.ci_lower)&&isNumber(row.ci_upper)?`95% CI: ${percent(row.ci_lower)}–${percent(row.ci_upper)}%`:'95% CI: —'}</div><div class="detail-stats"><div class="detail-stat"><span>Questions</span><strong>${number(row.n_questions)}</strong></div><div class="detail-stat"><span>Invalid answers</span><strong>${percent(row.invalid_answer_rate,2)}${isNumber(row.invalid_answer_rate)?'%':''}</strong></div><div class="detail-stat"><span>Truncated</span><strong>${percent(row.truncation_rate,2)}${isNumber(row.truncation_rate)?'%':''}</strong></div></div><div class="detail-meta">${raw}<p><b>Aggregation:</b> ${e(row.aggregation)} · <b>Units:</b> ${number(row.n_units)} · <b>Samples:</b> ${number(row.n_samples)}</p><p><b>Chance baseline:</b> ${percent(row.chance_at_k)}${isNumber(row.chance_at_k)?'%':''} · <b>Evaluation date:</b> ${e(row.date)}</p>${row.interval_note?`<p>${e(row.interval_note)}</p>`:''}<p><b>Scorer:</b> ${e(row.scorer_version)}<br><b>Parser:</b> ${e(row.parser_version)}<br><b>Prompt:</b> ${e(row.prompt_version)}<br><b>Protocol group:</b> ${e(row.protocol_group)}</p><p><b>Evaluation ID</b><br><code>${e(row.evaluation_id)}</code></p></div><div id="breakdown-content"><div class="loading" style="height:85px"><span class="spinner"></span> Loading…</div></div></div>`;
 const dialog=$('#detail-dialog');if(!dialog.open)dialog.showModal();
 try {
  const path=data.breakdownFiles?.[run]?.[bId];
  if(!path){$('#breakdown-content').innerHTML='<div class="notice">No breakdown.</div>';return;}
  if(!breakdownCache.has(path)){const response=await fetch(new URL(path,document.baseURI));if(!response.ok)throw new Error(`HTTP ${response.status}`);breakdownCache.set(path,await response.json());}
  if(request!==dialogRequest||!dialog.open)return;
  const rows=breakdownCache.get(path).rows.filter(r=>r.model_id===id&&r.metric===metric&&r.k===(run==='greedy'?1:k));
  renderBreakdowns(rows);
 } catch {if(request===dialogRequest&&dialog.open)$('#breakdown-content').innerHTML='<div class="notice">Breakdown unavailable. Reload to retry.</div>';}
}
function renderBreakdowns(rows) {
 const groups=[...new Set(rows.map(r=>r.group_by))];
 if(!groups.length){$('#breakdown-content').innerHTML='<div class="notice">No breakdown.</div>';return;}
 $('#breakdown-content').innerHTML=`<div class="breakdown-controls"><h3>Breakdown</h3><select id="breakdown-group" aria-label="Breakdown grouping">${groups.map(g=>option(g,g.replace(/_/g,' '),groups[0])).join('')}</select></div><div id="breakdown-table" class="breakdown-table"></div><p class="muted" style="font-size:10px;margin-top:9px">Units = group denominator</p>`;
 const draw=()=>{const selected=rows.filter(r=>r.group_by===$('#breakdown-group').value).sort((a,b)=>(b.pass_at_k??-1)-(a.pass_at_k??-1));$('#breakdown-table').innerHTML=`<table aria-label="Subject breakdown scores"><thead><tr><th scope="col">GROUP</th><th scope="col">SCORE %</th><th scope="col">UNITS</th></tr></thead><tbody>${selected.map(r=>`<tr><td>${e(r.group)}</td><td ${heatAttributes(r.pass_at_k)}>${percent(r.pass_at_k)}</td><td>${number(r.n_units)}</td></tr>`).join('')}</tbody></table>`;};draw();$('#breakdown-group').addEventListener('change',draw);
}
function showPoint(element){
  const row=rowFor(element.dataset.point,state.benchmark,'sample128',Number(element.dataset.pointK));if(!row)return;
  const tip=$('#chart-tooltip');tip.innerHTML=`<strong>${e(model(row.model_id).name)}</strong><span>k = ${row.k} · ${percent(row.pass_at_k)}%</span>${isNumber(row.ci_lower)&&isNumber(row.ci_upper)?`<br>95% CI ${percent(row.ci_lower)}–${percent(row.ci_upper)}%`:''}`;tip.hidden=false;
  const rect=element.getBoundingClientRect(),tr=tip.getBoundingClientRect();tip.style.left=`${Math.max(8,Math.min(rect.x-40,innerWidth-tr.width-10))}px`;tip.style.top=`${Math.max(8,rect.y-tr.height-14)}px`;
}
document.addEventListener('click',event=>{
  const t=event.target.closest('button,a');if(!t||!state)return;
  if(t.dataset.run){update({run:t.dataset.run});}
  else if(t.matches('.brand')){event.preventDefault();update({run:'greedy'});}
  else if(t.hasAttribute('data-model'))toggleList('modelIds',t.dataset.model);
  else if(t.hasAttribute('data-benchmark'))toggleList('benchIds',t.dataset.benchmark);
  else if(t.dataset.models)update({modelIds:t.dataset.models==='all'?data.models.map(m=>m.id):[]});
  else if(t.dataset.benches)update({benchIds:t.dataset.benches==='all'?data.benchmarks.map(b=>b.id):[]});
  else if(t.dataset.sortBenchmark)update({sortBenchmark:t.dataset.sortBenchmark,sortMetric:t.dataset.sortMetric,direction:state.sortBenchmark===t.dataset.sortBenchmark&&state.sortMetric===t.dataset.sortMetric&&state.direction==='desc'?'asc':'desc'});
  else if(t.hasAttribute('data-sort-model'))update({sortBenchmark:'',sortMetric:''});
  else if(t.dataset.detail)showDetails(t.dataset.detail,t.dataset.detailBenchmark||state.benchmark,t.dataset.detailMetric||state.metric,t.dataset.detailRun||state.run,t.dataset.detailK?Number(t.dataset.detailK):state.k);
  else if(t.hasAttribute('data-close'))$('#detail-dialog').close();
});
document.addEventListener('change',event=>{
  const t=event.target;
  if(t.id==='family-select')update({family:t.value});
  else if(t.id==='category-select')update({category:t.value});
  else if(t.id==='metric-mode')update({metricMode:t.value});
  else if(t.id==='k-select')update({k:Number(t.value)});
  else if(t.matches('.benchmark-select'))update({benchmark:t.value});
  else if(t.matches('.metric-select'))update({metric:t.value});
});
document.addEventListener('input',event=>{if(event.target.id==='model-search')update({query:event.target.value});});
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)&&!$('#detail-dialog').open&&$('#model-search')){event.preventDefault();$('#model-search').focus();}});
for(const eventName of ['pointerover','focusin'])document.addEventListener(eventName,event=>{if(event.target.matches('.chart-point'))showPoint(event.target);});
for(const eventName of ['pointerout','focusout'])document.addEventListener(eventName,event=>{if(event.target.matches('.chart-point'))$('#chart-tooltip').hidden=true;});
$('#detail-dialog').addEventListener('click',event=>{if(event.target===$('#detail-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close();}});
$('#detail-dialog').addEventListener('close',()=>{dialogRequest++;});
$('#theme-toggle').addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';applyTheme(theme);saveStorage('edge-theme',theme);});
$('#export').addEventListener('click',()=>{if(state)download(exportRows());});
$('#share').addEventListener('click',async()=>{if(!state)return;writeURL();try{await navigator.clipboard.writeText(location.href);notify('Link copied.');}catch{notify('Copy the URL from the address bar.');}});
window.addEventListener('hashchange',()=>{if(data){state=getState();normalize();render();}});
window.addEventListener('scroll',()=>{$('#chart-tooltip').hidden=true;},{passive:true});
matchMedia('(max-width:700px)').addEventListener('change',()=>{if(state)render();});
async function initialize(){
  try{
    const response=await fetch('data/dashboard.json',{cache:'no-cache'});if(!response.ok)throw new Error(`HTTP ${response.status}`);
    data=await response.json();if(data.schemaVersion!==1||!data.rows?.length)throw new Error('Invalid report snapshot');
    index=indexData(data);state=getState();normalize();render();
  }catch(error){$('#content').innerHTML=`<div class="empty"><strong>Data unavailable</strong><p>${e(error.message)}</p><button class="button" id="retry">Retry</button></div>`;$('#retry').addEventListener('click',initialize);}
}
initialize();
