"""The three cards the connector shows inside ChatGPT / the Claude app:
Records, Read-back (with Yes / No, then what was saved) and Recent activity.

Each is one self-contained HTML page (no outside files) that the app shows in
a sandboxed frame under the reply. It gets the tool's result from the app and,
for Yes / No, asks the app to call confirm_changes on our server. Two apps,
two ways of talking to the frame: ChatGPT's window.openai, and the MCP Apps
standard's postMessage messages (Claude). The page speaks both.
"""

_STYLE = """
:root{--bg:#fff;--card:#f7f7f8;--line:#e3e3e8;--ink:#17171b;--dim:#5d5d66;--faint:#8a8a93;
  --accent:#b38600;--accent-bg:#fff6d6;--ok:#17803d;--ok-bg:#e5f5ea;--bad:#b42318;--bad-bg:#fdecea;}
:root[data-theme=dark]{--bg:#17171b;--card:#1f1f24;--line:#30303a;--ink:#f3f2ee;--dim:#b4b4ba;--faint:#7c7c84;
  --accent:#ffd400;--accent-bg:#3a3210;--ok:#5fd38a;--ok-bg:#16301f;--bad:#ff8a80;--bad-bg:#3a1a18;}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#17171b;--card:#1f1f24;--line:#30303a;
  --ink:#f3f2ee;--dim:#b4b4ba;--faint:#7c7c84;--accent:#ffd400;--accent-bg:#3a3210;--ok:#5fd38a;--ok-bg:#16301f;
  --bad:#ff8a80;--bad-bg:#3a1a18;}}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,'Segoe UI',Roboto,Arial,sans-serif;
  padding:12px;overflow-wrap:anywhere}
.head{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:8px}
.title{font-weight:650;font-size:15px}
.kicker{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
.stats{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 10px}
.chip{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;background:var(--card);
  border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.chip.bad{background:var(--bad-bg);border-color:transparent;color:var(--bad)}
.chip.warn{background:var(--accent-bg);border-color:transparent;color:var(--accent)}
.chip.ok{background:var(--ok-bg);border-color:transparent;color:var(--ok)}
.row{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin-top:6px}
.row .top{display:flex;justify-content:space-between;gap:8px;align-items:baseline}
.name{font-weight:600}
.money{font-variant-numeric:tabular-nums;color:var(--dim);white-space:nowrap}
.sub{color:var(--dim);font-size:13px;margin-top:3px}
.flags{margin-top:5px;display:flex;gap:5px;flex-wrap:wrap}
.more,.note{color:var(--faint);font-size:12.5px;margin-top:8px}
.change{display:grid;grid-template-columns:1fr;gap:2px}
.field{font-size:12px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em;margin-top:4px}
.fromto{font-size:14px}.fromto s{color:var(--faint)}.fromto b{color:var(--ink)}
.btns{display:flex;gap:8px;margin-top:12px}
button{flex:1;font:inherit;font-weight:600;padding:11px 12px;border-radius:8px;border:1px solid var(--line);
  background:var(--card);color:var(--ink);cursor:pointer}
button.yes{background:var(--accent);border-color:var(--accent);color:#17171b}
button:disabled{opacity:.5;cursor:default}
.outcome{margin-top:10px;padding:10px 11px;border-radius:8px;font-weight:600}
.outcome.ok{background:var(--ok-bg);color:var(--ok)}.outcome.bad{background:var(--bad-bg);color:var(--bad)}
.outcome ul{font-weight:400;margin:6px 0 0 18px;color:var(--ink)}
.empty{color:var(--dim)}
"""

# Talks to whichever app is showing the card. ChatGPT: window.openai (the
# tool's result in toolOutput, callTool to run a tool). MCP Apps standard
# (Claude and others): JSON-RPC over postMessage - ui/initialize, then the
# tool result arrives as ui/notifications/tool-result, and tools/call runs a
# tool. Results are unwrapped from structuredContent (and a lone "result" key).
_BRIDGE = """
const Card = (() => {
  let data = null, render = () => {}, nextId = 1;
  const pending = {}, oa = () => window.openai;
  const unwrap = r => { if (!r) return r; let d = r.structuredContent || r;
    if (d && typeof d === 'object' && Object.keys(d).length === 1 && d.result) d = d.result; return d; };
  const post = m => window.parent.postMessage(m, '*');
  const rpc = (method, params) => new Promise((res, rej) => {
    const id = nextId++; pending[id] = {res, rej}; post({jsonrpc: '2.0', id, method, params});
    setTimeout(() => { if (pending[id]) { delete pending[id]; rej(new Error('no reply')); } }, 15000); });
  function show(d) { d = unwrap(d); if (d && typeof d === 'object') { data = d; render(d); resize(); } }
  function resize() {
    const h = document.documentElement.scrollHeight;
    try { if (oa() && oa().notifyIntrinsicHeight) oa().notifyIntrinsicHeight(h); } catch (e) {}
    if (!oa()) post({jsonrpc: '2.0', method: 'ui/notifications/size-changed', params: {height: h}});
  }
  window.addEventListener('message', e => {
    const m = e.data; if (!m || m.jsonrpc !== '2.0') return;
    if (m.id && pending[m.id] && !m.method) { const p = pending[m.id]; delete pending[m.id];
      return m.error ? p.rej(m.error) : p.res(m.result); }
    if (m.method === 'ui/notifications/tool-result') show(m.params);
    if (m.method === 'ui/notifications/host-context-changed' && m.params && m.params.theme)
      document.documentElement.dataset.theme = m.params.theme;
  });
  function fromOpenai() {
    if (oa().theme) document.documentElement.dataset.theme = oa().theme;
    show(oa().toolOutput);
  }
  async function start(fn) {
    render = fn;
    // ChatGPT may hand over the result after the page has started.
    window.addEventListener('openai:set_globals', () => { if (oa()) fromOpenai(); });
    if (oa()) return fromOpenai();
    for (let i = 0; i < 10 && !oa(); i++) await new Promise(r => setTimeout(r, 50));
    if (oa()) return fromOpenai();
    try {
      const r = await rpc('ui/initialize', {protocolVersion: '2026-01-26',
        appInfo: {name: 'SDI Tracker', version: '1'}, appCapabilities: {}});
      const theme = r && r.hostContext && r.hostContext.theme;
      if (theme) document.documentElement.dataset.theme = theme;
      post({jsonrpc: '2.0', method: 'ui/notifications/initialized', params: {}});
    } catch (e) {}
  }
  async function callTool(name, args) {
    if (oa() && oa().callTool) return unwrap(await oa().callTool(name, args));
    return unwrap(await rpc('tools/call', {name, arguments: args}));
  }
  return {start, callTool, resize, get data() { return data; }};
})();
const el = (tag, cls, text) => { const n = document.createElement(tag);
  if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const money = v => { const n = Number(v); return isFinite(n) && v !== '' ? '£' + n.toLocaleString('en-GB') : ''; };
"""


def _page(title: str, script: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{title}</title><style>{_STYLE}</style></head>"
            f"<body><div id='root'></div><script>{_BRIDGE}\n{script}</script></body></html>")


RECORDS_HTML = _page("Records", """
Card.start(d => {
  const root = document.getElementById('root'); root.replaceChildren();
  const recs = d.records || [], today = d.today_iso || '';
  const due = r => r['KEY DATES FOR NEXT STEPS'] || '';
  const overdue = r => due(r) && today && due(r) < today;
  const risk = r => /at risk/i.test(r['Commercial Status'] || '');
  const head = el('div', 'head'); head.append(el('div', 'title', recs.length + (recs.length === 1 ? ' record' : ' records')),
    el('div', 'kicker', 'SDI Tracker')); root.append(head);
  const stats = el('div', 'stats');
  const nOver = recs.filter(overdue).length, nRisk = recs.filter(risk).length;
  const total = recs.reduce((s, r) => s + (Number(r['BUDGET COST']) || 0), 0);
  if (nOver) stats.append(el('span', 'chip bad', nOver + ' overdue'));
  if (nRisk) stats.append(el('span', 'chip warn', nRisk + ' at risk'));
  if (total) stats.append(el('span', 'chip', money(total) + ' in total'));
  if (stats.childElementCount) root.append(stats);
  // Most urgent first: overdue, then soonest next step, then the rest by value.
  const order = [...recs].sort((a, b) => (overdue(b) - overdue(a)) || ((due(a) || '9') < (due(b) || '9') ? -1 :
    (due(a) || '9') > (due(b) || '9') ? 1 : (Number(b['BUDGET COST']) || 0) - (Number(a['BUDGET COST']) || 0)));
  order.slice(0, 8).forEach(r => {
    const row = el('div', 'row'), top = el('div', 'top');
    top.append(el('div', 'name', r.name || r.id), el('div', 'money', money(r['BUDGET COST'])));
    row.append(top);
    const next = r['NEXT STEPS'] ? r['NEXT STEPS'] + (r['KEY DATES FOR NEXT STEPS (spoken)'] ? ' · ' + r['KEY DATES FOR NEXT STEPS (spoken)'] : '') : '';
    if (next) row.append(el('div', 'sub', next));
    const flags = el('div', 'flags');
    const same = (r.Status || '').toLowerCase() === (r['Commercial Status'] || '').toLowerCase();
    if (r.Status && !same) flags.append(el('span', 'chip', r.Status));
    if (r['Commercial Status']) flags.append(el('span', risk(r) ? 'chip warn' : 'chip', r['Commercial Status']));
    if (r['Confidence to Order']) flags.append(el('span', 'chip', r['Confidence to Order'] + ' confidence'));
    if (overdue(r)) flags.append(el('span', 'chip bad', 'Overdue'));
    row.append(flags); root.append(row);
  });
  if (order.length > 8) root.append(el('div', 'more', 'and ' + (order.length - 8) + ' more'));
  if (!recs.length) root.append(el('div', 'empty', 'No records.'));
  if (d.note) root.append(el('div', 'note', d.note));
});
""")


CHANGE_HTML = _page("Read-back", """
let busy = false;
function outcome(root, o) {
  const good = o.state === 'saved' || o.state === 'partly_saved';
  const box = el('div', 'outcome ' + (good ? 'ok' : 'bad'),
    o.state === 'saved' ? 'Saved' : o.state === 'partly_saved' ? 'Partly saved' :
    o.state === 'declined' ? 'Not saved — cancelled' : o.state === 'conflict' ? 'Not saved — the record changed' :
    o.state === 'expired' ? 'Not saved — the read-back expired' : 'Not saved');
  const lines = [...(o.saved_lines || []), ...(o.not_saved || [])];
  if (lines.length) { const ul = el('ul'); lines.forEach(t => ul.append(el('li', null, t))); box.append(ul); }
  else if (o.detail && !good) box.append(el('div', 'sub', o.detail));
  root.append(box);
}
Card.start(d => {
  const root = document.getElementById('root'); root.replaceChildren();
  const head = el('div', 'head');
  const isOutcome = d.state && d.state !== 'awaiting_yes' && d.state !== 'nothing_to_save';
  head.append(el('div', 'title', isOutcome ? 'Your changes' : 'Check before saving'), el('div', 'kicker', 'SDI Tracker'));
  root.append(head);
  if (isOutcome) return outcome(root, d);
  (d.items || []).forEach(c => {
    const row = el('div', 'row change');
    row.append(el('div', 'name', c.name), el('div', 'field', c.field));
    const ft = el('div', 'fromto'); ft.append(el('s', null, c.old_spoken), document.createTextNode(' → '), el('b', null, c.new_spoken));
    row.append(ft); root.append(row);
  });
  (d.not_included || d.problems || []).forEach(t => root.append(el('div', 'note', 'Not included: ' + t)));
  if (d.state !== 'awaiting_yes') return;
  const btns = el('div', 'btns'), yes = el('button', 'yes', 'Yes — save'), no = el('button', 'no', 'No');
  btns.append(yes, no); root.append(btns);
  const answer = async reply => {
    if (busy) return; busy = true; yes.disabled = no.disabled = true;
    yes.textContent = reply === 'yes' ? 'Saving…' : 'Yes — save';
    try { const o = await Card.callTool('confirm_changes', {proposal_id: d.proposal_id, user_reply: reply});
          btns.remove(); outcome(root, o || {state: 'error'}); }
    catch (e) { busy = false; yes.disabled = no.disabled = false; yes.textContent = 'Yes — save';
                root.append(el('div', 'note', 'That didn\\'t reach the tracker. Try again, or say yes.')); }
    Card.resize();
  };
  yes.onclick = () => answer('yes'); no.onclick = () => answer('no');
});
""")


RECENT_HTML = _page("Recent activity", """
const LABEL = {proposed: ['Waiting for yes', 'chip warn'], saved: ['Saved', 'chip ok'], partly_saved: ['Partly saved', 'chip warn'],
  declined: ['Cancelled', 'chip'], conflict: ['Not saved', 'chip bad'], expired: ['Expired', 'chip']};
Card.start(d => {
  const root = document.getElementById('root'); root.replaceChildren();
  const list = d.entries || [];
  const head = el('div', 'head'); head.append(el('div', 'title', 'Recent activity'), el('div', 'kicker', 'SDI Tracker'));
  root.append(head);
  if (!list.length) return root.append(el('div', 'empty', 'Nothing yet.'));
  list.forEach(e => {
    const row = el('div', 'row'), top = el('div', 'top'), [txt, cls] = LABEL[e.state] || [e.state, 'chip'];
    top.append(el('span', cls, txt), el('div', 'money', e.when)); row.append(top);
    // Saved: what it is now. Otherwise: what was proposed.
    const lines = e.saved_lines && e.saved_lines.length ? e.saved_lines : (e.lines || []);
    lines.forEach(t => row.append(el('div', 'sub', t)));
    if (e.reply && e.state !== 'proposed') row.append(el('div', 'note', 'Reply: “' + e.reply + '”'));
    root.append(row);
  });
});
""")
