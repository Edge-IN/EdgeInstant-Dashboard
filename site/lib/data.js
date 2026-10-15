export const KS = [1, 2, 4, 8, 16, 32, 64, 128];
export const isNumber = value => typeof value === 'number' && Number.isFinite(value);
export const percent = (value, digits = 1) => isNumber(value) ? (value * 100).toFixed(digits) : '—';
export const number = value => isNumber(value) ? new Intl.NumberFormat('en-US').format(value) : '—';
export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const compactName = name => name.replace(/\s*\(\d{8}\)/g, '').replace(' (Instruct)', '').replace(/_/g, ' ');
export const metricName = metric => ({accuracy:'Accuracy', circular_accuracy:'Circular accuracy', score:'Normalized score', Avg:'Average', aAcc:'Answer accuracy', fAcc:'Figure accuracy', qAcc:'Question accuracy', prompt_strict:'Prompt · strict', prompt_loose:'Prompt · loose', instruction_strict:'Instruction · strict', instruction_loose:'Instruction · loose'}[metric] || metric);
export const rowKey = row => [row.run, row.model_id, row.benchmark, row.metric, row.k].join('|');
export function indexData(data) {
  return {rows:new Map(data.rows.map(row=>[rowKey(row),row])), models:new Map(data.models.map(model=>[model.id,model])), benchmarks:new Map(data.benchmarks.map(benchmark=>[benchmark.id,benchmark]))};
}
export function lookup(index, run, model, benchmark, metric, k) { return index.rows.get([run,model,benchmark,metric,k].join('|')); }
export function availableModels(data, run, category = 'all', query = '', family = 'all') {
  const ids = new Set(data.rows.filter(row => row.run === run && (category === 'all' || data.benchmarks.find(b=>b.id===row.benchmark)?.category === category)).map(row=>row.model_id));
  return data.models.filter(model=>ids.has(model.id) && (family === 'all' || model.family === family) && `${model.name} ${model.id}`.toLowerCase().includes(query.toLowerCase()));
}
export function benchmarkRows(data, state) {
  const ids = new Set(availableModels(data,state.run,state.category,state.query,state.family).map(m=>m.id));
  const k = state.run === 'greedy' ? 1 : state.k;
  return data.rows.filter(row=>row.run===state.run && row.benchmark===state.benchmark && row.metric===state.metric && row.k===k && ids.has(row.model_id));
}
export function delta(row, baseline) {
  return row && baseline && isNumber(row.pass_at_k) && isNumber(baseline.pass_at_k) ? (row.pass_at_k-baseline.pass_at_k)*100 : null;
}
export function csv(rows, fields) {
  const cell = value => {
    let text = value == null ? '' : String(value);
    // Text labels must not turn into spreadsheet formulas on export.
    if (typeof value === 'string' && /^[=+@\-\t\r]/.test(text)) text = `'${text}`;
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g,'""')}"` : text;
  };
  return [fields.join(','), ...rows.map(row=>fields.map(field=>cell(row[field])).join(','))].join('\r\n');
}
