/* Host supplies the existing authenticated api() helper. No standalone credentials,
   no whole-sheet fallback, no retries after an uncertain POST. */
(() => {
  'use strict';
  const el = id => document.getElementById('ttiCtl' + id);
  if (!el('')) return;
  const tracker = 'master';
  let plan = null, gate = null, busy = false, view = null;
  const text = (node, value) => { node.textContent = String(value == null ? '' : value); };
  const status = value => text(el('Status'), value);
  function invalidate() { plan = null; el('Run').disabled = true; text(el('Selection'), ''); }
  function lock(on) {
    busy = on;
    for (const id of ['Load','Preview','Run','Reviewed','Mode','Count','Start','Reason','Replace']) el(id).disabled = on;
    for (const tick of el('Rows').querySelectorAll('input')) tick.disabled = on;
    el('Count').disabled = on || el('Mode').value === 'rerun';
    el('Start').disabled = on || el('Mode').value === 'rerun';
    el('Run').disabled = on || !plan || !plan.runnable;
  }
  async function post(action, body) {
    if (typeof api !== 'function') throw new Error('Portal API integration is not installed. Nothing submitted.');
    const response = await api('/api/estimate/tti/batches/' + action, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({tracker_id:tracker,...body})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request refused; refresh and inspect the row status.');
    return data;
  }
  function showRows(rows) {
    el('Rows').replaceChildren();
    for (const row of rows) {
      const tr = document.createElement('tr');
      const select = document.createElement('td');
      if (row.rerun_allowed) {
        const tick = document.createElement('input'); tick.type='checkbox'; tick.value=row.row_id;
        tick.setAttribute('aria-label', 'Select row ' + row.row + ' for rerun');
        tick.addEventListener('change', invalidate); select.append(tick);
      }
      tr.append(select);
      for (const value of [row.row,row.drawing,row.quantity,row.state,(row.reasons || []).join('; ')]) {
        const td=document.createElement('td'); text(td,value); tr.append(td);
      }
      el('Rows').append(tr);
    }
  }
  async function refresh() {
    invalidate(); view=await post('rows',{}); gate=view.review_gate;
    showRows(view.rows); el('Review').hidden=!gate;
    el('Outputs').checked=false; el('Costs').checked=false; el('Notes').value='';
    if (view.suggested_start != null) el('Start').value=view.suggested_start;
    const ready=view.rows.filter(x=>x.next_eligible).length;
    status(`${ready} currently eligible rows. Two jobs maximum at once. ` +
      (view.active ? 'Existing batch needs completion or reconciliation.' : gate ? 'Previous batch needs review.' :
       !view.enabled ? 'Preview only: production integration is not enabled.' : 'Preview the next selection.'));
    // Optional link from a spreadsheet: selects by permanent ID and NEVER starts a job.
    const linked=new URLSearchParams(location.hash.replace(/^#/, '')).get('tti-row-id');
    if (linked) {
      const tick=Array.from(el('Rows').querySelectorAll('input')).find(x=>x.value===linked.toLowerCase());
      if (tick) { tick.checked=true; el('Mode').value='rerun'; mode(); el('').scrollIntoView(); }
      else status('Linked row is not currently eligible for rerun. Review its status; nothing was started.');
    }
  }
  function mode() {
    invalidate(); const rerun=el('Mode').value==='rerun';
    el('RerunFields').hidden=!rerun; el('NextHelp').hidden=rerun;
    el('Count').disabled=rerun; el('Start').disabled=rerun;
  }
  el('Mode').addEventListener('change',mode);
  for (const id of ['Count','Start','Reason']) el(id).addEventListener('input',invalidate);
  el('Load').onclick=async()=>{if(busy)return;lock(true);try{await refresh();}catch(e){status(e.message);}finally{lock(false);}};
  el('Preview').onclick=async()=>{
    if(busy)return; invalidate(); lock(true);
    try {
      const rerun=el('Mode').value==='rerun';
      plan=await post('preview',{mode:el('Mode').value,count:Number(el('Count').value),start_row:Number(el('Start').value),
        row_ids:rerun?Array.from(el('Rows').querySelectorAll('input:checked')).map(x=>x.value):[],reason:el('Reason').value.trim()});
      text(el('Selection'),`${plan.selected.length} jobs: `+plan.selected.map(x=>`row ${x.row}, ${x.drawing}, qty ${x.quantity}`).join('; '));
      status(plan.message + (!plan.runnable?' Preview only; integration gates are still closed.':''));
    } catch(e) { invalidate();status(e.message); } finally {lock(false);}
  };
  el('Run').onclick=async()=>{
    if(busy||!plan||!plan.runnable)return;
    if(plan.mode==='rerun'&&!el('Replace').checked){status('Confirm replacement of the selected rows’ previous AI costs first.');return;}
    if(!confirm(`Run exactly ${plan.selected.length} jobs, two at once?\n`+plan.selected.map(x=>`${x.row}: ${x.drawing} × ${x.quantity}`).join('\n')))return;
    const chosen=plan, replace=el('Replace').checked; invalidate();lock(true);
    try {
      const result=await post('run',{plan_id:chosen.plan_id,confirm_replace:replace});
      status(`Batch accepted: ${result.task_id}. Follow it in Grid Control; refresh here for reconciliation and review. Do not submit it again.`);
      document.dispatchEvent(new CustomEvent('tti-batch-started',{detail:result}));
    }catch(e){status(e.message+' Do not retry this submission. Refresh row status and reconcile its outcome.');}
    finally{lock(false);}
  };
  el('Reviewed').onclick=async()=>{
    if(busy||!gate)return;lock(true);
    try{
      await post('review',{plan_id:gate.plan_id,outputs_checked:el('Outputs').checked,costs_reviewed:el('Costs').checked,notes:el('Notes').value.trim()});
      await refresh();
    }catch(e){status(e.message);}finally{lock(false);}
  };
})();
