import {KS,isNumber,percent,number,escapeHTML as e,compactName,metricName,indexData,lookup,availableModels,benchmarkRows,delta,csv} from './lib/data.js';

const $ = selector => document.querySelector(selector);
const icons = {
 overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 benchmarks:'<path d="M4 20V11m5 9V4m6 16v-7m5 7V8"/>',
 sampling:'<path d="M3 17l6-7 5 3 7-9M17 4h4v4M3 21h18"/>',
 health:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 methodology:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h4"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="M16 16l5 5"/>',
 model:'<path d="M12 3l9 5v8l-9 5-9-5V8l9-5Z"/><path d="M3 8l9 5 9-5m-9 5v8M7.5 5.5l9 5"/>',
 layers:'<path d="M3 8l9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 18l9 5 9-5"/>',
 moon:'<path d="M20 15.5A9 9 0 0 1 8.5 4 9 9 0 1 0 20 15.5Z"/>',
 sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 close:'<path d="M6 6l12 12M18 6 6 18"/>'
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.overview}</svg>`;
const views = {
 overview:{name:'Overview', title:'Evaluation overview', description:'Every model. Every benchmark. A clearer perspective.'},
 benchmarks:{name:'Benchmarks', title:'Benchmark explorer', description:'Look closer. Compare scores, inspect uncertainty, and explore subjects.'},
 sampling:{name:'Sampling analysis', title:'The value of another try', description:'Explore how model capability changes with the sampling budget.'},
 health:{name:'Run health', title:'Behind the results', description:'Coverage, answer validity, and the details that shape a score.'},
 methodology:{name:'Methodology', title:'Know what you’re measuring', description:'Transparent sources. Preserved metrics. Reproducible updates.'}
};
const colors = ['#258362','#9294cb','#4b90ba','#c79c50','#cc817d','#75965b'];
let data, index, state, toastTimer, dialogRequest = 0;
const breakdownCache = new Map();
function readStorage(key) { try { return localStorage.getItem(key); } catch { return null; } }
function saveStorage(key,value) { try { localStorage.setItem(key,value); } catch { /* Private browsing can disable storage. */ } }
function applyTheme(theme) { document.documentElement.dataset.theme=theme; for(const id of ['theme-toggle','mobile-theme']){$(`#${id}`).innerHTML=icon(theme==='dark'?'sun':'moon');$(`#${id}`).setAttribute('aria-label',`Switch to ${theme==='dark'?'light':'dark'} theme`);} }
applyTheme(readStorage('edge-theme') || 'light');
function notify(message) { $('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),3000); }
function model(id) { return index.models.get(id) || {id,name:id,family:'Other'}; }
function benchmark(id = state.benchmark) { return index.benchmarks.get(id); }
function benches() { return data.benchmarks.filter(b=>state.category==='all'||b.category===state.category); }
function models(run = state.run) { return availableModels(data,run,state.category,state.query,state.family); }
function rowFor(id, b = state.benchmark, run = state.run, k = state.k, metric = state.metric) { return lookup(index,run,id,b,metric,run==='greedy'?1:k); }
function chosenRows() { return benchmarkRows(data,state); }
function filteredRows(allK = false, run = state.run) {
 const ids=new Set(models(run).map(m=>m.id)), bs=new Set(benches().map(b=>b.id));
 return data.rows.filter(r=>r.run===run&&ids.has(r.model_id)&&bs.has(r.benchmark)&&(allK||r.k===(run==='greedy'?1:state.k)));
}
function filteredGaps() {
 const bs=new Set(benches().map(b=>b.id));
 return data.coverage.filter(r=>r.run===state.run&&bs.has(r.benchmark)&&(state.family==='all'||model(r.model_id).family===state.family)&&`${model(r.model_id).name} ${r.model_id}`.toLowerCase().includes(state.query.toLowerCase()));
}
function option(value,label,current) { return `<option value="${e(value)}" ${value===current?'selected':''}>${e(label)}</option>`; }
function benchmarkSelect() { return `<select class="benchmark-select" aria-label="Benchmark">${benches().map(b=>option(b.id,b.name,state.benchmark)).join('')}</select>`; }
function metricSelect() { return `<select class="metric-select" aria-label="Metric">${benchmark().metrics.map(m=>option(m,metricName(m),state.metric)).join('')}</select>`; }
function deltaLabel(value) { return isNumber(value)?`<span class="${value>0?'positive':value<0?'negative':'muted'}">${value>0?'+':''}${value.toFixed(1)} <small>pp</small></span>`:'<span class="muted">—</span>'; }
function modelLabel(m, clickable = true) {return `<div class="model-label"><span class="model-mark ${e(m.family.toLowerCase())}">${e(({EdgeInstant:'EI',Qwen:'Q',MiniCPM:'M',Other:'S'})[m.family]||'M')}</span><div>${clickable?`<button data-model-detail="${e(m.id)}" title="${e(m.name)}">${e(compactName(m.name))}</button>`:e(compactName(m.name))}<span class="model-sub">${e(m.family)}</span></div></div>`;}
function getState() {
 const p=new URLSearchParams(location.hash.slice(1).replace(/^overview$/,''));
 const s={view:p.get('view')||'overview',run:p.get('run')||'greedy',k:Number(p.get('k')||1),category:p.get('suite')||'all',benchmark:p.get('benchmark')||'ai2d',metric:p.get('metric')||'accuracy',query:p.get('q')||'',family:p.get('family')||'all',table:p.get('table')||'ranking',sort:p.get('sort')||'score',direction:p.get('direction')||'desc',pins:(p.get('models')||'edgeinstant-v2m_formal,qwen3.5-2b,qwen3-omni-30b-a3b,minicpm-o-4_5').split(',').filter(id=>index.models.has(id)).slice(0,6)};
 if(!views[s.view])s.view='overview';if(!data.sources.some(r=>r.id===s.run))s.run=data.sources[0].id;
 if(!KS.includes(s.k))s.k=1;if(!['all','text','vision','instruction'].includes(s.category))s.category='all';
 const bs=data.benchmarks.filter(b=>s.category==='all'||b.category===s.category);
 if(!bs.some(b=>b.id===s.benchmark))s.benchmark=bs[0].id;
 if(!index.benchmarks.get(s.benchmark).metrics.includes(s.metric))s.metric=index.benchmarks.get(s.benchmark).primaryMetric;
 if(!['all',...data.models.map(m=>m.family)].includes(s.family))s.family='all';
 if(!['ranking','matrix'].includes(s.table))s.table='ranking';if(!['score','model','invalid','questions'].includes(s.sort))s.sort='score';
 if(!['asc','desc'].includes(s.direction))s.direction='desc';
 return s;
}
function writeURL() {
 const p=new URLSearchParams({view:state.view,run:state.run,k:String(state.k),benchmark:state.benchmark,metric:state.metric});
 if(state.category!=='all')p.set('suite',state.category);if(state.query)p.set('q',state.query);if(state.family!=='all')p.set('family',state.family);
 if(state.table!=='ranking')p.set('table',state.table);if(state.sort!=='score')p.set('sort',state.sort);if(state.direction!=='desc')p.set('direction',state.direction);
 p.set('models',state.pins.join(','));history.replaceState(null,'',`#${p}`);
}
function update(change) {
 const focus=document.activeElement, selection=focus?.tagName==='INPUT'&&focus.type==='search'?[focus.selectionStart,focus.selectionEnd]:null;
 Object.assign(state,change);
 if(!benches().some(b=>b.id===state.benchmark))state.benchmark=benches()[0].id;
 if(change.benchmark||!benchmark().metrics.includes(state.metric))state.metric=benchmark().primaryMetric;
 writeURL();render();
 if(selection){const input=$('#model-search');input?.focus();input?.setSelectionRange(...selection);}
}
function stat(label,value,description,iconName) {return `<div class="stat-card"><div class="stat-label">${label}<span class="stat-icon">${icon(iconName)}</span></div><div class="stat-number">${value}</div><div class="stat-description">${description}</div></div>`;}
function stats() {
 const rows=filteredRows(), modelCount=new Set(rows.map(r=>r.model_id)).size,bCount=new Set(rows.map(r=>r.benchmark)).size,gaps=filteredGaps();
 return `<section class="stat-grid" aria-label="Report summary">${stat('Evaluated models',modelCount,`${new Set(rows.map(r=>model(r.model_id).family)).size} model families represented`,'model')}${stat('Benchmarks',bCount,'Reported benchmark views','layers')}${stat('Score observations',number(rows.length),state.run==='greedy'?'Deterministic decoding · temperature 0':`128 completions / question · k = ${state.k}`,'sampling')}${stat('Coverage gaps',gaps.length,gaps.length?'Missing results are shown as <strong>—</strong>':'<span class="positive">All expected results available</span>','health')}</section>`;
}
function rankingChart() {
 const rows=chosenRows().filter(r=>isNumber(r.pass_at_k)).sort((a,b)=>b.pass_at_k-a.pass_at_k).slice(0,6);
 return `<section class="panel"><div class="panel-header"><div><h2>Benchmark leaders</h2><p>${e(metricName(state.metric))} · ${state.run==='greedy'?'greedy decoding':`sampled at k = ${state.k}`}</p></div>${benchmarkSelect()}</div><div class="bar-chart">${rows.length?rows.map(r=>`<div class="bar-row" tabindex="0" role="button" data-detail="${e(r.model_id)}" aria-label="Inspect ${e(model(r.model_id).name)}, ${percent(r.pass_at_k)} percent"><div class="bar-label" title="${e(model(r.model_id).name)}">${e(compactName(model(r.model_id).name))}</div><div class="bar-track"><div class="bar-fill" style="width:${r.pass_at_k*100}%"></div></div><div class="bar-score">${percent(r.pass_at_k)}</div></div>`).join(''):'<div class="empty">No results for this selection.</div>'}</div><div class="chart-footnote"><span>TOP ${rows.length} MODELS <span aria-hidden="true">·</span> SCORE / 100</span><button data-view="benchmarks">Explore all results →</button></div></section>`;
}
function curveData() {
 const allowed=new Set(models('sample128').map(m=>m.id));
 return state.pins.filter(id=>allowed.has(id)).map((id,i)=>({id,color:colors[i],points:KS.map(k=>rowFor(id,state.benchmark,'sample128',k)).filter(r=>r&&isNumber(r.pass_at_k))})).filter(s=>s.points.length);
}
function curveChart(wide = false) {
 const narrow=matchMedia('(max-width:700px)').matches;
 const series=curveData(), w=wide&&!narrow?1000:520,h=wide?(narrow?270:335):215,p={l:42,r:18,t:17,b:35},iw=w-p.l-p.r,ih=h-p.t-p.b;
 const x=k=>p.l+Math.log2(k)/7*iw,y=v=>p.t+(1-v)*ih;
 if(!series.length)return '<div class="empty"><strong>No sampling curves selected</strong><p>Select models with sampled results for this benchmark. Model search and family filters also apply.</p><button class="button" data-reset-pins>Restore model selection</button></div>';
 return `<svg class="curve-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${e(benchmark().name)} sampled scores from k 1 to 128. Each point is keyboard accessible."><title>Sampling curves for ${e(benchmark().name)}</title>${[0,.25,.5,.75,1].map(v=>`<line class="curve-grid" x1="${p.l}" x2="${w-p.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${p.l-10}" y="${y(v)+3}" text-anchor="end">${v*100}</text>`).join('')}${KS.map(k=>`<text x="${x(k)}" y="${h-11}" text-anchor="middle">${k}</text>`).join('')}${state.run==='sample128'?`<line x1="${x(state.k)}" x2="${x(state.k)}" y1="${p.t}" y2="${h-p.b}" stroke="var(--line)" stroke-dasharray="4 4"/>`:''}${series.map(s=>`<path d="${s.points.map((r,i)=>`${i?'L':'M'}${x(r.k).toFixed(2)},${y(r.pass_at_k).toFixed(2)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/>${s.points.map(r=>`<circle class="chart-point" cx="${x(r.k)}" cy="${y(r.pass_at_k)}" r="3" fill="var(--panel)" stroke="${s.color}" stroke-width="1.6" tabindex="0" data-point="${e(s.id)}" data-point-k="${r.k}" aria-label="${e(model(s.id).name)}, k ${r.k}, ${percent(r.pass_at_k)} percent"><title>${e(model(s.id).name)} · k = ${r.k}: ${percent(r.pass_at_k)}%</title></circle>`).join('')}`).join('')}</svg>`;
}
function curveLegend() {return `<div class="curve-legend">${curveData().map(s=>`<div class="legend-item"><span class="legend-dot" style="background:${s.color}"></span><button data-model-detail="${e(s.id)}" data-detail-run="sample128" title="${e(model(s.id).name)}">${e(compactName(model(s.id).name))}</button></div>`).join('')}</div>`;}
function curvePanel() {return `<section class="panel"><div class="panel-header"><div><h2>More samples, more possibility</h2><p>${e(benchmark().name)} · ${e(metricName(state.metric))}</p></div><span class="badge">Sample ×128</span></div><div class="curve-wrap">${curveChart()}</div>${curveLegend()}<div class="chart-footnote"><span>SAMPLING BUDGET (k) · LOG₂ SPACING</span><button data-view="sampling">Explore scaling →</button></div></section>`;}
function filters(includeMetrics = true) {return `<div class="filter-row"><label class="search-box">${icon('search')}<input id="model-search" type="search" placeholder="Search models…" aria-label="Search models" value="${e(state.query)}" autocomplete="off"></label><select id="family-select" aria-label="Model family">${['all',...new Set(data.models.map(m=>m.family))].map(f=>option(f,f==='all'?'All families':f,state.family)).join('')}</select>${includeMetrics?benchmarkSelect()+metricSelect():''}<button class="text-button" data-reset>Reset</button><span class="results-count">${models().length} models</span></div>`;}
function sortedModels() {
 const list=models();
 return list.sort((a,b)=>{
   const ar=rowFor(a.id),br=rowFor(b.id),key={score:'pass_at_k',invalid:'invalid_answer_rate',questions:'n_questions'}[state.sort];
   if(state.sort==='model')return a.name.localeCompare(b.name)*(state.direction==='asc'?1:-1);
   const av=ar?.[key],bv=br?.[key];if(!isNumber(av))return isNumber(bv)?1:a.name.localeCompare(b.name);if(!isNumber(bv))return -1;
   return (av-bv)*(state.direction==='asc'?1:-1)||a.name.localeCompare(b.name);
 });
}
function sortHeader(key,label) {return `<button data-sort="${key}">${label} <span aria-hidden="true">${state.sort===key?(state.direction==='desc'?'↓':'↑'):'↕'}</span></button>`;}
function rankingTable() {
 const sorted=sortedModels(), scored=chosenRows().filter(r=>isNumber(r.pass_at_k)).sort((a,b)=>b.pass_at_k-a.pass_at_k), ranks=new Map();
 let rank=0;scored.forEach((r,i)=>{if(i===0||r.pass_at_k!==scored[i-1].pass_at_k)rank=i+1;ranks.set(r.model_id,rank);});
 if(!sorted.length)return emptySearch();
 return `<div class="table-scroll"><table aria-label="${e(benchmark().name)} model results"><thead><tr><th scope="col">PIN</th><th scope="col">#</th><th scope="col">${sortHeader('model','MODEL')}</th><th scope="col">${sortHeader('score','SCORE %')}</th><th scope="col">95% INTERVAL</th>${state.run==='sample128'?'<th scope="col">Δ VS GREEDY</th>':''}<th scope="col">${sortHeader('questions','QUESTIONS')}</th><th scope="col">${sortHeader('invalid','INVALID %')}</th><th scope="col">DETAILS</th></tr></thead><tbody>${sorted.map(m=>{const r=rowFor(m.id);return `<tr><td><input type="checkbox" data-pin="${e(m.id)}" ${state.pins.includes(m.id)?'checked':''} aria-label="Pin ${e(m.name)} to sampling chart"></td><td class="rank">${ranks.get(m.id)||'—'}</td><td class="model-cell">${modelLabel(m)}</td><td><div class="score-cell"><span class="score-value">${percent(r?.pass_at_k)}</span>${isNumber(r?.pass_at_k)?`<span class="tiny-track"><i style="width:${r.pass_at_k*100}%"></i></span>`:''}</div></td><td class="muted">${isNumber(r?.ci_lower)&&isNumber(r?.ci_upper)?`${percent(r.ci_lower)} – ${percent(r.ci_upper)}`:'—'}</td>${state.run==='sample128'?`<td>${deltaLabel(delta(r,rowFor(m.id,state.benchmark,'greedy')))}</td>`:''}<td>${number(r?.n_questions)}</td><td>${percent(r?.invalid_answer_rate,2)}</td><td>${r?`<button class="text-button" data-detail="${e(m.id)}" aria-label="Inspect ${e(m.name)}">Inspect <span>↗</span></button>`:'<span class="muted" title="No compatible complete evaluation">Missing</span>'}</td></tr>`;}).join('')}</tbody></table></div>`;
}
function matrixTable() {
 const ms=models(),bs=benches();if(!ms.length)return emptySearch();
 return `<div class="table-scroll"><table class="heatmap" aria-label="Benchmark score matrix"><thead><tr><th scope="col">MODEL / BENCHMARK</th>${bs.map(b=>`<th scope="col"><button data-benchmark="${e(b.id)}" title="${e(metricName(b.primaryMetric))}">${e(b.name)}</button></th>`).join('')}</tr></thead><tbody>${ms.map(m=>`<tr><td>${modelLabel(m)}</td>${bs.map(b=>{const r=rowFor(m.id,b.id,state.run,state.k,b.primaryMetric),v=r?.pass_at_k;return `<td>${isNumber(v)?`<button class="heat-cell" style="background:color-mix(in srgb, var(--green) ${Math.round(5+v*30)}%, var(--panel))" data-detail="${e(m.id)}" data-detail-benchmark="${e(b.id)}" data-detail-metric="${e(b.primaryMetric)}" aria-label="${e(m.name)}, ${e(b.name)}, ${percent(v)} percent">${percent(v)}</button>`:'<span class="heat-cell heat-missing" title="No compatible complete evaluation">—</span>'}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function emptySearch() {return '<div class="empty"><strong>No models match these filters</strong><p>Try a different model name or family.</p><button class="button" data-reset>Clear filters</button></div>';}
function explorer() {return `<section class="panel section-panel"><div class="panel-header explorer-header"><div><h2>Results explorer</h2><p>${state.table==='matrix'?'One primary metric per benchmark. Select a cell to inspect the result.':`${e(benchmark().name)} · ${e(metricName(state.metric))} · select a model for the full picture.`}</p></div><div class="segmented" aria-label="Results display"><button data-table="ranking" class="${state.table==='ranking'?'active':''}" aria-pressed="${state.table==='ranking'}">Ranking</button><button data-table="matrix" class="${state.table==='matrix'?'active':''}" aria-pressed="${state.table==='matrix'}">Matrix</button></div></div>${filters(state.table==='ranking')}${state.table==='ranking'?rankingTable():matrixTable()}<div class="table-footer"><span>${state.table==='ranking'?'Pin up to 6 models to compare sampling curves.':'Primary metrics: IFEval prompt strict · HallusionBench Avg · OCRBench normalized score.'}<br><strong>Missing results are gaps, never zero scores.</strong>${state.run==='sample128'&&state.table==='ranking'?' Δ is descriptive; decoding settings and seeds differ.':''}</span>${state.table==='matrix'?'<span class="heat-scale">0 <i></i> 100</span>':`<span>${state.run==='greedy'?'GREEDY · N = 1':`SAMPLE · N = 128 · K = ${state.k}`}</span>`}</div></section>`;}
function samplingView() {
 const ms=models('sample128'),series=curveData();
 return `<div class="notice"><strong>Sampling analysis always uses the Sample ×128 run.</strong> Scores estimate success within k attempts. Grouped metrics retain their own semantics. Hover or focus a point for its reported interval.</div><section class="panel section-panel"><div class="panel-header"><div><h2>Capability across sampling budgets</h2><p>Select up to six models. All curves use the same benchmark and metric.</p></div><div class="panel-tools">${benchmarkSelect()}${metricSelect()}</div></div><div class="model-chips">${ms.map(m=>`<button class="model-chip ${state.pins.includes(m.id)?'active':''}" data-toggle-pin="${e(m.id)}" aria-pressed="${state.pins.includes(m.id)}">${state.pins.includes(m.id)?'<span aria-hidden="true">✓</span>':''}${e(compactName(m.name))}</button>`).join('')}</div><div class="wide-chart">${curveChart(true)}</div>${curveLegend()}<div class="chart-footnote"><span>k = 1, 2, 4, 8, 16, 32, 64, 128 · LOG₂ SPACING</span><span>Temperature 1.0 · 128 completions per question</span></div></section><section class="panel section-panel"><div class="panel-header"><div><h2>Sampling, by the numbers</h2><p>Normalized scores (%) and descriptive gain from k = 1 to k = 128.</p></div><button class="button compact" data-export-curves>↓ Export curves</button></div><div style="height:20px"></div><div class="table-scroll"><table aria-label="Sampling scores by budget"><thead><tr><th scope="col">MODEL</th>${KS.map(k=>`<th scope="col">k = ${k}</th>`).join('')}<th scope="col">GAIN</th></tr></thead><tbody>${series.map(s=>`<tr><td>${modelLabel(model(s.id))}</td>${KS.map(k=>`<td>${percent(s.points.find(p=>p.k===k)?.pass_at_k)}</td>`).join('')}<td>${deltaLabel(delta(s.points.find(p=>p.k===128),s.points.find(p=>p.k===1)))}</td></tr>`).join('')}</tbody></table></div>${series.length?'':'<div class="empty">Select models to see their scores.</div>'}<div class="table-footer"><span>These are estimates from the reported completions, not additional evaluation runs.</span></div></section>`;
}
function healthView() {
 const gaps=filteredGaps(),rows=filteredRows().filter(r=>r.metric===index.benchmarks.get(r.benchmark).primaryMetric),issueRows=rows.filter(r=>isNumber(r.invalid_answer_rate)||isNumber(r.truncation_rate)).sort((a,b)=>(b.invalid_answer_rate||0)-(a.invalid_answer_rate||0));
 const exclusions=data.excluded.filter(r=>r.run===state.run), reasons=new Map();for(const r of exclusions){const reason=r.reason||r.exclusion_reason||'Excluded by source selection';reasons.set(reason,(reasons.get(reason)||0)+1);}
 return `${stats()}<div class="health-grid"><section class="panel"><div class="panel-header"><div><h2>Coverage gaps</h2><p>Expected results without a compatible completed evaluation.</p></div><span class="badge neutral-badge">${gaps.length}</span></div><div class="health-list">${gaps.length?gaps.map(g=>`<div class="health-item"><div><strong>${e(compactName(model(g.model_id).name))}</strong><small>${e(index.benchmarks.get(g.benchmark)?.name||g.benchmark)}</small></div><span class="badge neutral-badge">Missing</span></div>`).join(''):'<div class="empty">No gaps in this selection.</div>'}</div></section><section class="panel"><div class="panel-header"><div><h2>Report selection</h2><p>Source-reported exclusions for the full selected run.</p></div><span class="badge neutral-badge">${exclusions.length}</span></div><div class="health-list">${[...reasons].map(([reason,count])=>`<div class="health-item"><div><strong>${e(reason.replace(/_/g,' '))}</strong><small>Preserved from the evaluation report</small></div><span class="badge neutral-badge">${count}</span></div>`).join('')||'<div class="empty">No exclusions reported.</div>'}</div></section></div><section class="panel section-panel"><div class="panel-header"><div><h2>Answer diagnostics</h2><p>Highest invalid-answer rates first. Rates describe the full completion pool, independently of k.</p></div></div>${filters(false)}<div class="table-scroll"><table aria-label="Answer diagnostics"><thead><tr><th scope="col">MODEL</th><th scope="col">BENCHMARK</th><th scope="col">INVALID %</th><th scope="col">TRUNCATED %</th><th scope="col">SAMPLES</th><th scope="col">GENERATED TOKENS</th><th scope="col">DETAILS</th></tr></thead><tbody>${issueRows.slice(0,40).map(r=>`<tr><td>${modelLabel(model(r.model_id))}</td><td>${e(index.benchmarks.get(r.benchmark).name)}</td><td class="${r.invalid_answer_rate>.1?'negative':''}">${percent(r.invalid_answer_rate,2)}</td><td>${percent(r.truncation_rate,2)}</td><td>${number(r.n_samples)}</td><td>${number(r.generated_tokens)}</td><td><button class="text-button" data-detail="${e(r.model_id)}" data-detail-benchmark="${e(r.benchmark)}" data-detail-metric="${e(r.metric)}">Inspect ↗</button></td></tr>`).join('')}</tbody></table></div>${!issueRows.length?emptySearch():''}<div class="table-footer"><span>Showing ${Math.min(40,issueRows.length)} of ${issueRows.length} model–benchmark results. Benchmark views can overlap; counts must not be summed as unique work.</span><button class="text-button" data-export-health>Export all diagnostics ↓</button></div></section>`;
}
function methodologyView() {return `<div class="method-grid"><section class="panel section-panel"><div class="panel-header"><h2>Reading the results</h2><span class="badge">Source-faithful</span></div><div class="prose"><h3>Two decoding settings</h3><p><b>Greedy</b> uses one deterministic completion with temperature 0. <b>Sample ×128</b> uses 128 completions per question with temperature 1. Results at k = 1 are the sampled success estimate, not greedy accuracy. Seeds differ between the runs, so displayed differences are descriptive.</p><h3>What does pass@k mean?</h3><p>For n completions and c correct answers, the estimator is <code>1 − C(n − c, k) / C(n, k)</code>. Scores and confidence intervals here come directly from the evaluator. The dashboard does not rescore answers or pool attempts.</p><h3>Metrics retain their meaning</h3><p>CMMLU uses subject-macro aggregation. MMBench uses circular accuracy. HallusionBench exposes Avg, aAcc, fAcc, and qAcc. IFEval exposes prompt and instruction scores in strict and loose variants. OCRBench preserves its raw score and maximum in the result details while displaying its normalized score.</p><p>The matrix uses one primary metric per benchmark: prompt strict for IFEval, Avg for HallusionBench, score for OCRBench, and the report’s accuracy metric elsewhere. No overall average is calculated across these different metrics.</p><h3>Uncertainty and missing data</h3><p>Reported 95% intervals use question-cluster bootstrap, with subject stratification for CMMLU, conditional on the sampled completions. Some grouped metrics have no interval; those are displayed as —. Missing results also stay empty, with their coverage gaps retained.</p><h3>Selection and provenance</h3><p>The source reports select compatible completed evaluations, prefer flexible scores in auto mode, and keep attempts separate. Each result retains its evaluation ID, date, scorer, parser, prompt, and aggregation. Benchmark views may overlap; their question and token counts are not additive.</p></div></section><div><section class="panel section-panel"><div class="panel-header"><h2>Connected report snapshots</h2></div><div class="prose">${data.sources.map(s=>`<h3>${e(s.label)}</h3><code class="source-path">${e(s.settingId)}</code><div class="source-row"><span>Score observations</span><strong>${number(s.rowCount)}</strong></div><div class="source-row"><span>Source updated</span><strong>${formatDate(s.updatedAt)}</strong></div><div class="source-row"><span>Completions / temperature</span><strong>${s.parameters.n} / ${s.parameters.temperature}</strong></div><div class="source-row"><span>Seed</span><strong>${e(s.parameters.seed)}</strong></div>`).join('')}<div class="source-row"><span>Dashboard imported</span><strong>${formatDate(data.generatedAt)}</strong></div><p style="margin-top:17px"><a class="text-button positive" href="data/dashboard.json" download="edgeinstant-dashboard.json">Download the imported data ↓</a></p></div></section><section class="panel section-panel"><div class="panel-header"><h2>A repeatable update</h2></div><div class="prose"><p>Refresh the reports in EdgeInstant-Eval, then run the dashboard importer. New models, benchmarks, scores, and coverage gaps are discovered from the configured CSV reports.</p><code class="source-path">python scripts/import_reports.py</code><p>Report locations live in <code>reports.config.json</code>. The dashboard is a static website; the imported snapshot can be hosted independently of the evaluation machine. Subject breakdowns load only when you inspect a result.</p><p>See the repository README for configuration, preview, and verification commands.</p></div></section></div></div>`;}
function formatDate(value) {if(!value)return 'Not reported';const d=new Date(value);return Number.isNaN(d.getTime())?e(value):d.toLocaleDateString('en-GB',{timeZone:'Asia/Shanghai',day:'2-digit',month:'short',year:'numeric'});}
function render() {
 $('#chart-tooltip').hidden=true;
 $('#navigation').innerHTML=Object.entries(views).map(([key,v])=>`<button class="nav-item ${state.view===key?'active':''}" data-view="${key}" ${state.view===key?'aria-current="page"':''}>${icon(key)}${v.name}${key==='benchmarks'?`<span class="nav-count">${data.benchmarks.length}</span>`:''}</button>`).join('');
 $('#page-title').textContent=views[state.view].title;$('#page-description').textContent=views[state.view].description;$('#breadcrumb').textContent=views[state.view].name;
 $('#run-switch').innerHTML=data.sources.map(s=>`<button data-run="${e(s.id)}" class="${s.id===state.run?'active':''}" aria-pressed="${s.id===state.run}">${s.id==='greedy'?'Greedy <small>Deterministic</small>':'Sample ×128 <small>Stochastic</small>'}</button>`).join('');
 $('#k-select').innerHTML=KS.map(k=>option(k,`k = ${k}`,state.k)).join('');$('#k-control').hidden=state.run==='greedy';$('#category-select').value=state.category;
 $('.control-bar').hidden=state.view==='methodology';$('#export').hidden=state.view==='methodology';
 $('#content').innerHTML=state.view==='overview'?`${stats()}<div class="panels">${rankingChart()}${curvePanel()}</div>${explorer()}`:state.view==='benchmarks'?`${stats()}${explorer()}`:state.view==='sampling'?samplingView():state.view==='health'?healthView():methodologyView();
}
function togglePin(id) {
 if(state.pins.includes(id))update({pins:state.pins.filter(v=>v!==id)});
 else if(state.pins.length<6)update({pins:[...state.pins,id]});
 else{notify('Select up to 6 models. Unpin a model to add another.');render();}
}
function download(rows,name) {
 if(!rows.length){notify('There are no results to export.');return;}
 const fields=[...new Set(rows.flatMap(r=>Object.keys(r)))],blob=new Blob(['\ufeff'+csv(rows,fields)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notify(`Exported ${rows.length} observations.`);
}
function exportCurrent() {
 const rows=state.view==='sampling'?curveData().flatMap(s=>s.points):state.view==='health'?filteredRows().filter(r=>r.metric===index.benchmarks.get(r.benchmark).primaryMetric):state.table==='matrix'?filteredRows().filter(r=>r.metric===index.benchmarks.get(r.benchmark).primaryMetric):chosenRows();
 download(rows,`edgeinstant-${state.view}-${state.view==='sampling'?'sample128':state.run}-${state.benchmark}.csv`);
}
async function showDetails(id, bId=state.benchmark, metric=state.metric, run=state.run, k=state.k) {
 const row=rowFor(id,bId,run,k,metric),b=index.benchmarks.get(bId),request=++dialogRequest;
 if(!row){notify('No reported result for this model and selection.');return;}
 const raw=isNumber(row.raw_score)?`<p><b>Original score:</b> ${number(row.raw_score)}${isNumber(row.score_max)?` / ${number(row.score_max)}`:''}</p>`:'';
 $('#detail-content').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">RESULT DETAIL</div><h2 id="detail-title">${e(b.name)}</h2><p>${e(model(id).name)}</p></div><button class="icon-button" data-close aria-label="Close result details">${icon('close')}</button></div><div class="dialog-body"><span class="badge">${run==='greedy'?'Greedy':`Sample ×128 · k = ${k}`}</span><div class="detail-score" style="margin-top:18px">${percent(row.pass_at_k)}<small>%</small></div><div class="detail-ci">${e(metricName(row.metric))} · ${isNumber(row.ci_lower)&&isNumber(row.ci_upper)?`95% interval: ${percent(row.ci_lower)}–${percent(row.ci_upper)}%`:'Confidence interval not reported'}</div><div class="detail-stats"><div class="detail-stat"><span>Questions</span><strong>${number(row.n_questions)}</strong></div><div class="detail-stat"><span>Invalid answers</span><strong>${percent(row.invalid_answer_rate,2)}${isNumber(row.invalid_answer_rate)?'%':''}</strong></div><div class="detail-stat"><span>Truncated</span><strong>${percent(row.truncation_rate,2)}${isNumber(row.truncation_rate)?'%':''}</strong></div></div><div class="detail-meta">${raw}<p><b>Aggregation:</b> ${e(row.aggregation)} · <b>Units:</b> ${number(row.n_units)} · <b>Samples:</b> ${number(row.n_samples)}</p><p><b>Chance baseline:</b> ${percent(row.chance_at_k)}${isNumber(row.chance_at_k)?'%':''} · <b>Evaluation date:</b> ${e(row.date)}</p>${row.interval_note?`<p>${e(row.interval_note)}</p>`:''}<p><b>Scorer:</b> ${e(row.scorer_version)}<br><b>Parser:</b> ${e(row.parser_version)}<br><b>Prompt:</b> ${e(row.prompt_version)}<br><b>Protocol group:</b> ${e(row.protocol_group)}</p><p><b>Evaluation ID</b><br><code>${e(row.evaluation_id)}</code></p></div><div id="breakdown-content"><div class="loading" style="height:85px"><span class="spinner"></span> Loading subject breakdowns…</div></div></div>`;
 const dialog=$('#detail-dialog');if(!dialog.open)dialog.showModal();
 try {
  const path=data.breakdownFiles?.[run]?.[bId];
  if(!path){$('#breakdown-content').innerHTML='<div class="notice">No subject breakdown is available for this benchmark.</div>';return;}
  if(!breakdownCache.has(path)){const response=await fetch(new URL(path,document.baseURI));if(!response.ok)throw new Error(`HTTP ${response.status}`);breakdownCache.set(path,await response.json());}
  if(request!==dialogRequest||!dialog.open)return;
  const rows=breakdownCache.get(path).rows.filter(r=>r.model_id===id&&r.metric===metric&&r.k===(run==='greedy'?1:k));
  renderBreakdowns(rows);
 } catch {if(request===dialogRequest&&dialog.open)$('#breakdown-content').innerHTML='<div class="notice">Subject breakdowns could not be loaded. Refresh the page to use the latest imported snapshot.</div>';}
}
function renderBreakdowns(rows) {
 const groups=[...new Set(rows.map(r=>r.group_by))];
 if(!groups.length){$('#breakdown-content').innerHTML='<div class="notice">No subject breakdown is reported for this metric.</div>';return;}
 $('#breakdown-content').innerHTML=`<div class="breakdown-controls"><h3>Look inside the score</h3><select id="breakdown-group" aria-label="Breakdown grouping">${groups.map(g=>option(g,g.replace(/_/g,' '),groups[0])).join('')}</select></div><div id="breakdown-table" class="breakdown-table"></div><p class="muted" style="font-size:10px;margin-top:9px">Units are the group denominator; benchmark question counts may repeat across groups.</p>`;
 const draw=()=>{const selected=rows.filter(r=>r.group_by===$('#breakdown-group').value).sort((a,b)=>(b.pass_at_k??-1)-(a.pass_at_k??-1));$('#breakdown-table').innerHTML=`<table aria-label="Subject breakdown scores"><thead><tr><th scope="col">GROUP</th><th scope="col">SCORE %</th><th scope="col">UNITS</th></tr></thead><tbody>${selected.map(r=>`<tr><td>${e(r.group)}</td><td>${percent(r.pass_at_k)}</td><td>${number(r.n_units)}</td></tr>`).join('')}</tbody></table>`;};draw();$('#breakdown-group').addEventListener('change',draw);
}
function showPoint(element) {
 const row=rowFor(element.dataset.point,state.benchmark,'sample128',Number(element.dataset.pointK));if(!row)return;
 const tip=$('#chart-tooltip');tip.innerHTML=`<strong>${e(model(row.model_id).name)}</strong><span>k = ${row.k} <span aria-hidden="true">·</span> ${percent(row.pass_at_k)}%</span>${isNumber(row.ci_lower)&&isNumber(row.ci_upper)?`<br>95% interval ${percent(row.ci_lower)}–${percent(row.ci_upper)}%`:''}`;tip.hidden=false;
 const rect=element.getBoundingClientRect(),tr=tip.getBoundingClientRect();tip.style.left=`${Math.max(8,Math.min(rect.x-40,innerWidth-tr.width-10))}px`;tip.style.top=`${Math.max(8,rect.y-tr.height-14)}px`;
}
document.addEventListener('click',event=>{
 const t=event.target.closest('button,a,[data-detail]');if(!t)return;
 if(t.dataset.view){event.preventDefault();update({view:t.dataset.view});window.scrollTo({top:0,behavior:'instant'});}
 else if(t.matches('.brand')){event.preventDefault();update({view:'overview'});}
 else if(t.dataset.run)update({run:t.dataset.run});
 else if(t.dataset.table)update({table:t.dataset.table});
 else if(t.dataset.sort)update({sort:t.dataset.sort,direction:state.sort===t.dataset.sort&&state.direction==='desc'?'asc':'desc'});
 else if(t.dataset.benchmark)update({benchmark:t.dataset.benchmark,table:'ranking'});
 else if(t.hasAttribute('data-reset'))update({query:'',family:'all',category:'all'});
 else if(t.hasAttribute('data-reset-pins'))update({query:'',family:'all',pins:data.models.filter(m=>data.rows.some(r=>r.model_id===m.id&&r.run==='sample128'&&r.benchmark===state.benchmark)).slice(0,4).map(m=>m.id)});
 else if(t.dataset.togglePin)togglePin(t.dataset.togglePin);
 else if(t.dataset.detail)showDetails(t.dataset.detail,t.dataset.detailBenchmark||state.benchmark,t.dataset.detailMetric||state.metric);
 else if(t.dataset.modelDetail)showDetails(t.dataset.modelDetail,state.benchmark,state.metric,t.dataset.detailRun||(state.view==='sampling'?'sample128':state.run));
 else if(t.hasAttribute('data-close')){$('#detail-dialog').close();dialogRequest++;}
 else if(t.hasAttribute('data-export-curves'))download(curveData().flatMap(s=>s.points),`edgeinstant-sampling-${state.benchmark}.csv`);
 else if(t.hasAttribute('data-export-health'))download(filteredRows().filter(r=>r.metric===index.benchmarks.get(r.benchmark).primaryMetric),`edgeinstant-diagnostics-${state.run}.csv`);
});
document.addEventListener('change',event=>{
 const t=event.target;if(t.matches('.benchmark-select'))update({benchmark:t.value});
 else if(t.matches('.metric-select'))update({metric:t.value});
 else if(t.id==='family-select')update({family:t.value});
 else if(t.id==='category-select')update({category:t.value});
 else if(t.id==='k-select')update({k:Number(t.value)});
 else if(t.dataset.pin)togglePin(t.dataset.pin);
});
document.addEventListener('input',event=>{if(event.target.id==='model-search')update({query:event.target.value});});
document.addEventListener('keydown',event=>{
 if((event.key==='Enter'||event.key===' ')&&event.target.matches('.bar-row')){event.preventDefault();event.target.click();}
 if(event.key==='/'&&!['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName)&&!$('#detail-dialog').open&&$('#model-search')){event.preventDefault();$('#model-search').focus();}
});
document.addEventListener('pointerover',event=>{if(event.target.matches('.chart-point'))showPoint(event.target);});
document.addEventListener('pointerout',event=>{if(event.target.matches('.chart-point'))$('#chart-tooltip').hidden=true;});
document.addEventListener('focusin',event=>{if(event.target.matches('.chart-point'))showPoint(event.target);});
document.addEventListener('focusout',event=>{if(event.target.matches('.chart-point'))$('#chart-tooltip').hidden=true;});
$('#detail-dialog').addEventListener('click',event=>{if(event.target===$('#detail-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom){event.target.close();dialogRequest++;}}});
$('#detail-dialog').addEventListener('close',()=>{dialogRequest++;});
for(const id of ['theme-toggle','mobile-theme'])$(`#${id}`).addEventListener('click',()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';applyTheme(theme);saveStorage('edge-theme',theme);});
$('#export').addEventListener('click',()=>{if(data)exportCurrent();});
$('#share').addEventListener('click',async()=>{if(!data)return;writeURL();try{await navigator.clipboard.writeText(location.href);notify('Link copied. Filters and model selections are included.');}catch{notify('This view is saved in the address bar. Copy the URL to share it.');}});
window.addEventListener('hashchange',()=>{if(data){state=getState();render();}});
window.addEventListener('scroll',()=>{$('#chart-tooltip').hidden=true;},{passive:true});
matchMedia('(max-width:700px)').addEventListener('change',()=>{if(data&&state)render();});
async function initialize() {
 try {
  const response=await fetch('data/dashboard.json',{cache:'no-cache'});if(!response.ok)throw new Error(`Data request failed (${response.status})`);
  data=await response.json();if(data.schemaVersion!==1||!data.rows?.length)throw new Error('Unsupported or empty report snapshot');index=indexData(data);state=getState();
  $('#snapshot-date').textContent=formatDate(data.generatedAt);render();
 } catch(error){$('#content').innerHTML=`<div class="panel empty"><strong>The report snapshot is unavailable</strong><p>Run <code>python scripts/import_reports.py</code> in the dashboard repository, then serve the <code>site</code> directory over HTTP and reload this page.</p><p>${e(error.message)}</p><button class="button" id="retry">Retry loading</button></div>`;$('#retry').addEventListener('click',initialize);}
}
initialize();
