/* Channel Toolkit — front-end logic.
   Talks to the local Python server in web.py. No external dependencies. */

const $  = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

let S = null;            // latest /api/status
let phaseStartedAt = null;
let STATS = null;        // latest /api/stats
let RULES = [];          // rule list being edited
let PREVIEW = null;      // last dry-run result
let VIDEOS = [];         // merged video list
let SHOWN = 100;         // paging
let SELECTED = new Set();
let EDIT_MODE = 'text';
let PREVIEW_REVISION = 0;
let PREVIEW_BUSY = false;
let logSince = 0;

/* ---------------- helpers ---------------- */

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

const nfmt = n => (n === null || n === undefined) ? '—' : Number(n).toLocaleString();

function dur(sec){
  if(!sec) return '—';
  const m = Math.floor(sec/60), s = Math.round(sec%60);
  return `${m}:${String(s).padStart(2,'0')}`;
}

function ago(iso){
  if(!iso) return 'never';
  const d = (Date.now() - new Date(iso).getTime())/1000;
  if(d < 60) return 'just now';
  if(d < 3600) return Math.floor(d/60)+' min ago';
  if(d < 86400) return Math.floor(d/3600)+' h ago';
  return Math.floor(d/86400)+' d ago';
}

function fmtDur(sec){
  const h = Math.floor(sec/3600), m = Math.floor(sec%3600/60);
  return h ? `${h}h ${String(m).padStart(2,'0')}m` : `${m}m`;
}

function hl(text, words){
  let out = esc(text);
  for(const w of (words||[])){
    if(!w) continue;
    const rx = new RegExp(String(w).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi');
    out = out.replace(rx, m => '<mark>'+m+'</mark>');
  }
  return out;
}

async function api(path, opts){
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({error:'server sent a bad response'}));
  if(!r.ok) throw new Error(j.error || ('HTTP '+r.status));
  return j;
}

async function post(path, body){
  return api(path, {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify(body||{})});
}

function toast(msg, kind){
  const n = $('#phaseMsg');
  n.textContent = msg;
  n.style.color = kind === 'bad' ? 'var(--danger)' : '';
}
function notifyError(message){
  if(window.ToolkitUI) window.ToolkitUI.notify(message, 'bad');
  else toast(message, 'bad');
}
async function confirmAction(message){
  return window.ToolkitUI ? window.ToolkitUI.confirmAction(message) : window.confirm(message);
}

/* ---------------- theme ---------------- */

function applyTheme(t){
  if(t === 'system') t = 'dark';
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('theme', t);
  $('#themeLabel').textContent = t === 'system' ? 'System' : (t === 'dark' ? 'Dark' : 'Light');
}
$('#themeBtn').onclick = () => {
  const order = ['light','dark'];
  const cur = localStorage.getItem('theme') || 'dark';
  applyTheme(order[(order.indexOf(cur)+1) % order.length]);
};
applyTheme('dark');

/* ---------------- navigation ---------------- */

function show(view){
  if(!view || view === 'overview') view = 'edit';
  // Video selection now belongs to Bulk Edit; there is no standalone Videos page.
  if(view === 'videos') view = 'edit';
  const previous = $('section[id^="view-"]:not([hidden])')?.id;
  $$('#nav button').forEach(b =>
    b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false'));
  $$('section[id^="view-"]').forEach(s => s.hidden = (s.id !== 'view-'+view));
  location.hash = view;
  if(previous !== 'view-'+view) window.scrollTo({top:0,behavior:'instant'});
  if(view === 'links')    loadLinks();
  if(view === 'edit')     renderRules();
  if(view === 'download') loadDownloadEnv().then(syncModeFields);
}
$('#nav').addEventListener('click', e => {
  const b = e.target.closest('button[data-view]');
  if(b) show(b.dataset.view);
});
window.addEventListener('hashchange', () => {
  const v = location.hash.slice(1);
  show(v && $('#view-'+v) ? v : 'edit');
});

/* ---------------- status polling ---------------- */

async function poll(){
  try{
    S = await api('/api/status');
  }catch(e){
    $('#phaseBadge').textContent = 'offline';
    $('#phaseBadge').className = 'badge dot bad';
    toast('Cannot reach the local server. Is web.py still running?', 'bad');
    return;
  }

  const busy = ['scanning','updating','syncing','downloading'].includes(S.phase);
  renderDownloadProgress(downloadStatus(S));
  const b = $('#phaseBadge');
  b.textContent = ({ready:'Ready to edit',idle:'Not scanned',scanning:'Scanning channel',syncing:'Refreshing metadata',updating:'Applying changes',downloading:'Downloading',error:'Needs attention'})[S.phase] || S.phase;
  b.className = 'badge dot ' + (busy ? 'live' : S.phase === 'error' ? 'bad'
                : S.phase === 'ready' ? 'ok' : '');

  let msg = S.message || '';
  if(S.phase === 'ready' && /^API scan complete/i.test(msg)) msg = `${S.counts.api_videos} video descriptions loaded. Open Bulk Edit to preview your replacements.`;
  if(busy){
    if(phaseStartedAt === null) phaseStartedAt = Date.now();
    const elapsed = Math.floor((Date.now() - phaseStartedAt) / 1000);
    if(S.phase === 'scanning') msg += (msg.startsWith('Signing in') ? ' Check your browser for Google sign-in.' : '') + ` (${elapsed < 60 ? elapsed+'s' : fmtDur(elapsed)} elapsed)` + (elapsed >= 120 ? ' If nothing progresses, check Activity on Overview.' : '');
  }else phaseStartedAt = null;
  if(S.job && S.job.total){
    const p = S.job;
    msg = `${p.label}: ${p.done}/${p.total}` +
          (p.eta_seconds != null ? ` · about ${fmtDur(p.eta_seconds)} left` : '') +
          (p.current ? ` · ${p.current}` : '');
  }
  toast(msg + (S.error ? ` ${S.error} See How to use for help.` : ''), S.error ? 'bad' : '');

  $('#brandChannel').textContent = S.channel ? S.channel.title : 'not connected';
  $('#btnStop').disabled  = !busy;
  $('#btnStop').hidden = !busy;
  $('#btnScanApi').disabled = busy;
  $('#btnSyncFree').disabled = busy;
  $('#editScan').disabled = busy;
  $('#editConnectionTitle').textContent = S.counts.api_videos ? `${S.counts.api_videos} videos ready` : 'Connect & scan';
  $('#editConnectionHelp').textContent = S.counts.api_videos ? 'Your descriptions are loaded. Choose a replacement and preview the result.' : 'Sign in with the account that owns your channel, then load your descriptions.';
  updateApplyState();
  updateScope();

  $('#cVideos').textContent = S.counts.videos || '—';
  $('#cEdit').textContent   = S.counts.pending_edits ?? '—';
  $('#cLinks').textContent  = S.counts.links ?? '—';

  renderOverview();
}

async function pollLog(){
  try{
    const j = await api('/api/log?since=' + logSince);
    if(!j.lines.length) return;
    const el = $('#log');
    const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
    for(const l of j.lines) el.appendChild(document.createTextNode(l.text + '\n'));
    logSince = j.lines[j.lines.length-1].n;
    if(stick) el.scrollTop = el.scrollHeight;
    $('#logCount').textContent = j.total + ' lines';
  }catch(e){}
}

/* ---------------- overview ---------------- */

function statCard(label, value, note, cls){
  return `<div class="card stat">
    <div class="label">${esc(label)}</div>
    <div class="value ${cls||''}">${value}</div>
    <div class="note">${esc(note||'')}</div></div>`;
}

function renderOverview(){
  if(!S) return;
  const st = STATS || {};
  const q  = S.quota;

  $('#ovStats').innerHTML =
    statCard('Videos', nfmt(S.counts.videos || st.count || 0),
             S.counts.api_videos ? `${S.counts.api_videos} visible to the API` : 'run a sync') +
    statCard('Total views', nfmt(st.total_views), st.count ? `${nfmt(st.avg_views)} average` : 'sync for stats') +
    statCard('Total likes', nfmt(st.total_likes), st.engagement_pct ? st.engagement_pct + '% like rate' : '') +
    statCard('Watch time', st.total_duration_hours ? st.total_duration_hours + ' h' : '—', 'combined runtime') +
    statCard('Median views', nfmt(st.median_views), st.max_views ? `best ${nfmt(st.max_views)}` : '');

  // data sources
  const yt = S.ytdlp;
  $('#ovSources').innerHTML = `
    <div class="row" style="justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--border)">
      <div><b>yt-dlp</b><div class="small muted">Free reads · ${esc(yt.version || 'not found')}</div></div>
      <span class="badge ${yt.available ? 'ok' : 'bad'} dot">${yt.available ? 'ready' : 'missing'}</span>
    </div>
    <div class="row" style="justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--border)">
      <div><b>Cache</b><div class="small muted">${nfmt(yt.cached)} videos · updated ${esc(ago(yt.updated_at))}</div></div>
      <span class="badge ${yt.cached ? 'ok' : 'warn'} dot">${yt.cached ? 'populated' : 'empty'}</span>
    </div>
    <div class="row" style="justify-content:space-between;padding:9px 0">
      <div><b>YouTube API</b><div class="small muted">Writes and private videos${S.counts.api_videos ? ' · '+S.counts.api_videos+' scanned' : ''}</div></div>
      <span class="badge ${S.counts.api_videos ? 'ok' : ''} dot">${S.counts.api_videos ? 'scanned' : 'not scanned'}</span>
    </div>`;

  // quota
  const pct = Math.min(100, Math.round(q.spent / q.limit * 100));
  $('#ovQuotaBar').style.width = pct + '%';
  $('#ovQuotaTxt').textContent = `${nfmt(q.spent)} / ${nfmt(q.limit)} units used`;
  $('#ovQuotaReset').textContent = `resets ${S.reset.reset_local}`;
  $('#headerQuotaBar').style.width = pct + '%';
  $('#headerQuotaText').textContent = `${nfmt(q.spent)} / ${nfmt(q.limit)}`;
  $('#headerQuotaReset').textContent = `Resets ${S.reset.reset_local}`;
  $('#ovQuotaSub').textContent =
    `${q.affordable_updates} description writes available right now (${q.update_cost} units each).`;
  $('#ovQuotaNote').innerHTML = q.affordable_updates <= 0
    ? `<div class="note warn">Quota spent for today. Reads through yt-dlp still work —
       only writing is blocked until <b>${esc(S.reset.reset_local)}</b>.</div>` : '';

  const list = (arr, empty) => !arr || !arr.length
    ? `<div class="small muted">${empty}</div>`
    : arr.map(v => `<div class="row" style="padding:7px 0;border-bottom:1px solid var(--border);gap:10px">
        <a href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener"
           style="flex:1;min-width:0;color:inherit;text-decoration:none">
          <div class="small" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(v.title)}</div>
        </a>
        <span class="mono small" style="color:var(--primary)">${nfmt(v.view_count)}</span>
      </div>`).join('');

  $('#ovTop').innerHTML    = list(st.top, 'Run a free sync to see view counts.');
  $('#ovBottom').innerHTML = list(st.bottom, 'Run a free sync to see view counts.');
}

/* ---------------- videos ---------------- */

async function loadVideos(){
  try{
    const j = await api('/api/videos');
    VIDEOS = j.videos;
    renderVideos();
  }catch(e){ /* not scanned yet */ }
}

function filtered(){
  const q = $('#vSearch').value.trim().toLowerCase();
  const f = $('#vFilter').value;
  const sort = $('#vSort').value;

  let rows = VIDEOS.filter(v => {
    if(q && !((v.title||'').toLowerCase().includes(q) ||
              (v.description||'').toLowerCase().includes(q))) return false;
    if(f === 'public'   && v.privacy !== 'public') return false;
    if(f === 'unlisted' && v.privacy !== 'unlisted') return false;
    if(f === 'private'  && v.privacy !== 'private') return false;
    if(f === 'nodesc'   && (v.desc_len||0) >= 500) return false;
    if(f === 'long'     && (v.desc_len||0) < 4500) return false;
    if(f === 'nostats'  && v.views != null) return false;
    return true;
  });

  const cmp = {
    date:  (a,b) => String(b.upload_date||'').localeCompare(String(a.upload_date||'')),
    views: (a,b) => (b.views||0) - (a.views||0),
    likes: (a,b) => (b.likes||0) - (a.likes||0),
    ratio: (a,b) => ((b.likes||0)/(b.views||1)) - ((a.likes||0)/(a.views||1)),
    length:(a,b) => (b.desc_len||0) - (a.desc_len||0),
    title: (a,b) => String(a.title||'').localeCompare(String(b.title||'')),
  }[sort];
  return rows.sort(cmp);
}

function renderVideos(){
  const rows = filtered();
  const page = rows.slice(0, SHOWN);
  const q = $('#vSearch').value.trim();

  if(!VIDEOS.length){
    $('#vBody').innerHTML = `<tr><td colspan="7"><div class="empty">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="m10 9 5 3-5 3z"/></svg>
      <div><b>No videos loaded yet</b></div>
      <div class="small">Use <b>Sync (free)</b> for stats and descriptions, or
        <b>API scan</b> to include private videos.</div>
      </div></td></tr>`;
    $('#vCount').textContent = '';
    $('#vMore').hidden = true;
    return;
  }

  $('#vBody').innerHTML = page.map(v => {
    const ratio = v.views ? ((v.likes||0)/v.views*100).toFixed(1)+'%' : '';
    const pv = v.privacy || 'unknown';
    const pcls = pv === 'private' ? 'warn' : pv === 'unlisted' ? '' : 'ok';
    const near = (v.desc_len||0) > 4800;
    return `<tr>
      <td><input type="checkbox" data-id="${esc(v.id)}" ${SELECTED.has(v.id)?'checked':''}
                 aria-label="Select ${esc(v.title)}"></td>
      <td>${v.has_thumb
            ? `<img class="thumb" loading="lazy" width="76" height="43"
                 src="/thumb?id=${esc(v.id)}" alt="">`
            : `<span class="thumb"></span>`}</td>
      <td><span class="title">${hl(v.title, q?[q]:[])}</span>
          <a class="small mono" href="https://www.youtube.com/watch?v=${esc(v.id)}"
             target="_blank" rel="noopener">${esc(v.id)}</a>
          <span class="small muted"> · ${dur(v.duration)}</span></td>
      <td class="num">${nfmt(v.views)}</td>
      <td class="num">${nfmt(v.likes)}<div class="small muted">${ratio}</div></td>
      <td class="num ${near?'':''}" ${near?'style="color:var(--warn)"':''}>${nfmt(v.desc_len)}</td>
      <td><span class="badge ${pcls}">${esc(pv)}</span></td>
    </tr>`;
  }).join('');

  $('#vCount').textContent =
    `showing ${page.length} of ${rows.length}` +
    (rows.length !== VIDEOS.length ? ` (filtered from ${VIDEOS.length})` : '');
  $('#vMore').hidden = page.length >= rows.length;
  updateSelBar();
}

$('#vBody').addEventListener('change', e => {
  const cb = e.target.closest('input[type=checkbox][data-id]');
  if(!cb) return;
  cb.checked ? SELECTED.add(cb.dataset.id) : SELECTED.delete(cb.dataset.id);
  invalidatePreview();
  updateSelBar();
});
$('#vAll').addEventListener('change', e => {
  const rows = filtered().slice(0, SHOWN);
  rows.forEach(v => e.target.checked ? SELECTED.add(v.id) : SELECTED.delete(v.id));
  invalidatePreview();
  renderVideos();
});
$('#vSelClear').onclick = () => { SELECTED.clear(); invalidatePreview(); renderVideos(); };
$('#vSelEdit').onclick  = () => { show('edit'); };
function updateSelBar(){
  $('#vSelBar').hidden = SELECTED.size === 0;
  $('#vSelCount').textContent = `${SELECTED.size} selected`;
  const shown = $$('#vBody input[data-id]');
  $('#vAll').checked = shown.length > 0 && shown.every(el => el.checked);
  $('#vAll').indeterminate = shown.some(el => el.checked) && !$('#vAll').checked;
}
$('#vMore').onclick = () => { SHOWN += 100; renderVideos(); };
['input','change'].forEach(ev => {
  $('#vSearch').addEventListener(ev, () => { SHOWN = 100; renderVideos(); });
});
$('#vFilter').onchange = () => { SHOWN = 100; renderVideos(); };
$('#vSort').onchange   = () => { SHOWN = 100; renderVideos(); };

/* ---------------- rules ---------------- */

async function loadRules(){
  try{ RULES = (await api('/api/rules')).rules; renderRules(); }catch(e){}
}

function renderRules(){
  updateScope();
  updateApplyState();
  if(!RULES.length){
    $('#rList').innerHTML = `<div class="empty small">No rules yet. Add one to get started.</div>`;
    return;
  }
  $('#rList').innerHTML = RULES.map((r,i) => `
    <div class="card rule-card" data-i="${i}">
      <div class="row" style="margin-bottom:10px">
        <input type="checkbox" data-f="enabled" ${r.enabled?'checked':''}
               aria-label="Enable rule" style="flex:0 0 auto">
        <input type="text" data-f="name" value="${esc(r.name||'')}"
               aria-label="Replacement name" placeholder="Replacement name" style="flex:1 1 180px;font-weight:600">
        <button class="sm ghost icon" data-act="del" title="Delete rule" aria-label="Delete rule">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>
        </button>
      </div>
      <div class="field-pair">
        <div><label for="find-${i}">${r.type==='regex'?'Pattern to find (advanced)':'Text to find'}</label>
          <input id="find-${i}" type="text" data-f="find" value="${esc(r.find||'')}" placeholder="e.g. @prod.crmdrm" class="mono"></div>
        <div><label for="replace-${i}">Replace with</label>
          <input id="replace-${i}" type="text" data-f="replace" value="${esc(r.replace||'')}" placeholder="e.g. @prod_crmdrm" class="mono"></div>
      </div>
      <details class="advanced"><summary>More options${r.type==='regex' ? ' (regex is enabled)' : ''}</summary>
      <div class="row" style="margin-top:10px"><label for="type-${i}" style="margin:0">Match type</label><select id="type-${i}" data-f="type" style="flex:0 0 150px"><option value="text" ${r.type!=='regex'?'selected':''}>Plain text</option><option value="regex" ${r.type==='regex'?'selected':''}>Regex (advanced)</option></select></div>
      <div><label for="protect-${i}" style="margin-top:10px">Protected text (optional, separated by commas)</label>
        <input id="protect-${i}" type="text" data-f="protect" class="mono"
               value="${esc((r.protect||[]).join(', '))}"
               placeholder="business.crmdrm@gmail.com, Prod. CRMDRM"></div>
      <div class="row small muted" style="margin-top:10px;gap:16px">
        <label style="margin:0;display:flex;align-items:center;gap:7px;cursor:pointer">
          <input type="checkbox" data-f="case_sensitive" ${r.case_sensitive?'checked':''}> Case sensitive</label>
        <label style="margin:0;display:flex;align-items:center;gap:7px;cursor:pointer">
          <input type="checkbox" data-f="word_boundary" ${r.word_boundary?'checked':''}> Whole word only</label>
      </div>
      <div class="hint">Protected text must stay unchanged. A rule that would alter it is skipped for that video.</div></details>
    </div>`).join('');
}

$('#rList').addEventListener('input', e => {
  const card = e.target.closest('[data-i]'); if(!card) return;
  const r = RULES[+card.dataset.i], f = e.target.dataset.f;
  if(!f) return;
  if(f === 'protect') r[f] = e.target.value.split(',').map(s=>s.trim()).filter(Boolean);
  else if(e.target.type === 'checkbox') r[f] = e.target.checked;
  else r[f] = e.target.value;
  invalidatePreview();
});
$('#rList').addEventListener('change', e => {
  const card = e.target.closest('[data-i]'); if(!card) return;
  const r = RULES[+card.dataset.i], f = e.target.dataset.f;
  if(f === 'type') r.type = e.target.value;
  invalidatePreview();
});
$('#rList').addEventListener('click', async e => {
  const btn = e.target.closest('[data-act="del"]'); if(!btn) return;
  const rule = RULES[+btn.closest('[data-i]').dataset.i];
  if(!await confirmAction('Remove this replacement rule from the editor? Saved rules stay unchanged until you save or preview.')) return;
  const index = RULES.indexOf(rule);
  if(index < 0) return;
  RULES.splice(index, 1);
  invalidatePreview();
  renderRules();
});
$('#rAdd').onclick = () => {
  let number=1;
  while(RULES.some(r=>r.name===`Replacement ${number}`)) number++;
  RULES.push({name:`Replacement ${number}`, enabled:true, type:'text', find:'', replace:'',
              case_sensitive:false, protect:[]});
  invalidatePreview(); renderRules();
  $('#rList').lastElementChild?.scrollIntoView({block:'nearest'});
};
function updateApplyState(){
  let help = $('#applyHelp');
  if(!help){
    help = document.createElement('span'); help.id = 'applyHelp'; help.className = 'small muted';
    $('#rApply').before(help);
  }
  const hasScan = S && S.counts && S.counts.api_videos;
  const working = S && ['scanning','syncing','updating','downloading'].includes(S.phase);
  const canApply = !!(PREVIEW && PREVIEW.changes.length && !PREVIEW.errors.length && PREVIEW.affordable > 0 && hasScan && !working && !PREVIEW_BUSY);
  $('#rApply').disabled = !canApply;
  $('#rPreview').disabled = !!working || PREVIEW_BUSY;
  help.textContent = working ? 'Wait for the current task to finish.' : !hasScan ? 'Scan for editing first.' : !PREVIEW ? 'Preview your changes before applying.' : PREVIEW.errors.length ? 'Fix the replacement errors and preview again.' : !PREVIEW.changes.length ? 'There are no changes to apply.' : PREVIEW.affordable <= 0 ? 'Daily update budget used. Preview again after the reset.' : `Ready to review ${PREVIEW.changes.length} changed videos.`;
  $$('.steps .step').forEach((el,i) => { const active = PREVIEW ? i===3 : hasScan ? i===1 : i===0; el.classList.toggle('active',active); if(active) el.setAttribute('aria-current','step'); else el.removeAttribute('aria-current'); });
}
function invalidatePreview(){ PREVIEW_REVISION++; PREVIEW = null; updateApplyState(); $('#editResult').innerHTML = '<div class="empty-preview"><h3>Preview before you publish</h3><p class="small">Your settings have changed. Preview again to review the latest replacements.</p></div>'; }
function selectedScope(){ return false; }
function updateScope(){
  const count = S?.counts?.api_videos || 0;
  $('#allScopeCount').textContent = `${count} scanned videos`;
  $('#editScope').textContent = selectedScope() ? `${SELECTED.size} selected videos. Only these will be reviewed.` : `${count} scanned videos. Replacements apply only where text matches.`;
}
$$('[name="editScopeMode"]').forEach(el => el.onchange = () => { invalidatePreview(); updateScope(); });
$('#chooseVideos').onclick = () => notify('All scanned videos are included. Add replacements, then preview your changes.');
$('#editScan').onclick = () => $('#btnScanApi').click();
function setEditMode(mode){ EDIT_MODE=mode; $('#instagramFields').hidden=mode!=='instagram'; $('#rList').hidden=mode==='instagram'; $('#rAdd').hidden=mode==='instagram'; $('#rTextMode').setAttribute('aria-pressed',mode==='text'); $('#rInstagram').setAttribute('aria-pressed',mode==='instagram'); invalidatePreview(); renderRules(); }
$('#rInstagram').onclick = () => setEditMode('instagram');
$('#rTextMode').onclick = () => setEditMode('text');
$('#instagramFields').addEventListener('input',invalidatePreview);
function currentRules(){
  if(EDIT_MODE==='text') return RULES;
  const oldName=$('#igOldName').value.trim().replace(/^@/,''), newName=$('#igNewName').value.trim().replace(/^@/,'');
  if(!/^[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*$/.test(oldName)||!/^[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*$/.test(newName)) throw Error('Enter valid Instagram usernames using letters, numbers, dots, or underscores.');
  const oldUrl=new URL($('#igOldUrl').value.trim()), newUrl=new URL($('#igNewUrl').value.trim());
  for(const u of [oldUrl,newUrl]) if(!['www.instagram.com','instagram.com'].includes(u.hostname)||!['https:','http:'].includes(u.protocol)||u.search||u.hash||u.username||u.password||u.port) throw Error('Use a complete Instagram profile URL, without a query or fragment.');
  const oldProfile=oldUrl.pathname.replace(/^\/|\/$/g,''), newProfile=newUrl.pathname.replace(/^\/|\/$/g,'');
  if(oldProfile!==oldName||newProfile!==newName) throw Error('The profile URLs must use the usernames entered above.');
  const rx=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const protect=[...new Set(RULES.flatMap(r=>r.protect||[]))];
  return [
    {name:'Instagram profile URL',enabled:true,type:'regex',find:'(?<![\\w./])https?://(?:www\\.)?instagram\\.com/'+rx(oldName)+'(?![\\w.@-]|/[^\\s<>"\'\\)\\]]+)/?',replace:'https://www.instagram.com/'+newName+'/',protect},
    {name:'Instagram username',enabled:true,type:'regex',find:'(?<![\\w@./+\\-])(@?)'+rx(oldName)+'(?![\\w@./+\\-])',replace:'\\1'+newName,protect}
  ];
}
$('#rSave').onclick = async () => {
  try{
    const rules=currentRules();
    const j = await post('/api/rules', {rules});
    RULES=rules;
    $('#rErrors').innerHTML = j.errors.length
      ? `<div class="note bad"><b>Problems:</b><br>${j.errors.map(esc).join('<br>')}</div>`
      : `<div class="note ok">Saved. ${j.enabled} rule(s) enabled.</div>`;
    invalidatePreview();
  }catch(e){ $('#rErrors').innerHTML = `<div class="note bad">${esc(e.message)}</div>`; }
};

$('#rPreview').onclick = async () => {
  invalidatePreview(); PREVIEW_BUSY=true; updateApplyState();
  const revision=PREVIEW_REVISION;
  $('#editResult').innerHTML = `<div class="card"><div class="row">
    <span class="spin"></span> Running dry run…</div></div>`;
  try{
    const rules=currentRules();
    const saved=await post('/api/rules', {rules});
    if(saved.errors.length) throw Error(saved.errors.join(' '));
    RULES=rules;
    const result = await post('/api/bulk/preview',
      {video_ids: selectedScope() ? [...SELECTED] : null});
    if(revision!==PREVIEW_REVISION) return;
    PREVIEW = result;
    renderPreview();
  }catch(e){
    $('#editResult').innerHTML = `<div class="card"><div class="note bad">${esc(e.message)}</div></div>`;
  }finally{PREVIEW_BUSY=false;updateApplyState();}
};

function renderPreview(){
  const p = PREVIEW;
  updateApplyState();
  if(!p) return;
  const marked = parts => parts.map(part => part.changed ? `<mark>${esc(part.text)}</mark>` : esc(part.text)).join('');

  const words = [];
  RULES.filter(r=>r.enabled).forEach(r => { if(r.type!=='regex'){ words.push(r.find); words.push(r.replace);} });

  let html = `<div class="card" style="margin-top:14px">
    <h2>Review your changes</h2>
    <p class="sub">Nothing has been modified. This exact preview is the only set that can be applied.</p>
    <div class="grid g-stats" style="margin-top:14px">
      ${statCard('Scanned', nfmt(p.scanned), p.scope)}
      ${statCard('Would change', nfmt(p.changes.length), 'videos')}
      ${statCard('No matches', nfmt((p.unchanged||[]).length), 'descriptions stay the same')}
      ${statCard('Skipped', nfmt(new Set(p.rejected.map(r=>r.video_id)).size), 'videos with skipped replacements')}
      ${statCard('Quota needed', nfmt(p.changes.length*50), `${p.affordable} affordable now`)}
    </div>`;

  if(p.errors.length)
    html += `<div class="note bad"><b>Rule problems:</b><br>${p.errors.map(esc).join('<br>')}</div>`;

  if(p.rejected.length){
    html += `<div class="note warn"><b>${p.rejected.length} video(s) had a rule skipped
      for safety:</b><br>` +
      p.rejected.map(r =>
        `<code>${esc(r.rule)}</code> on ${esc(r.title.slice(0,44))} — ${esc(r.reason)}`).join('<br>') +
      `<p class="small">Adjust the replacement or protected text, shorten an over-length result, or scan for editing if a video is not loaded. Then preview again.</p></div>`;
  }
  if(p.unchanged?.length) html += `<details class="advanced no-match-results"><summary><span><b>${p.unchanged.length} videos without matches</b><small>These descriptions will stay unchanged.</small></span></summary><p class="no-match-help">The text to find was not present in these descriptions. Check your spelling or use a different replacement if you expected a match.</p><ul class="no-match-list" aria-label="Videos without matching text">${p.unchanged.map(v=>`<li>${esc(v.title)}</li>`).join('')}</ul></details>`;

  if(!p.changes.length){
    html += `<div class="empty"><b>No changes</b><div class="small">
      No descriptions are ready to update. Check the skipped results above or confirm that the old text matches your descriptions.</div></div></div>`;
    $('#editResult').innerHTML = html;
    return;
  }

  html += `<div style="margin-top:16px">` + p.changes.map(c => `
    <div class="card" style="box-shadow:none;margin-bottom:10px">
      <div class="row" style="gap:10px">
        <b style="flex:1;min-width:0">${esc(c.title)}</b>
        <span class="badge">${esc(c.privacy)}</span>
        <span class="badge ${c.new_len>4900?'warn':''}">${c.old_len} → ${c.new_len} chars</span>
      </div>
      <a class="small mono" href="https://www.youtube.com/watch?v=${esc(c.video_id)}"
         target="_blank" rel="noopener">${esc(c.video_id)}</a>
      ${c.edits ? c.edits.map(d=>`<div class="diff before"><span class="tag">BEFORE</span>${marked(d.before)}</div><div class="diff after"><span class="tag">AFTER</span>${marked(d.after)}</div>`).join('') : c.diffs.map(d => `
        <div class="diff before"><span class="tag">BEFORE</span>${hl(d.before, words)}</div>
        <div class="diff after"><span class="tag">AFTER </span>${hl(d.after, words)}</div>`).join('')}
      <details class="advanced"><summary>Read full descriptions${c.replacement_count ? ` · ${c.replacement_count} replacements` : ''}</summary><h3>Before</h3><p class="full-description">${esc(c.before||'')}</p><h3>After</h3><p class="full-description">${esc(c.after||'')}</p></details>
    </div>`).join('');
  html += `</div></div>`;
  $('#editResult').innerHTML = html;
}

/* ---------------- confirm dialog ---------------- */

let dlgAction = null;
function confirmDialog({title, sub, body, go}){
  $('#dlgTitle').textContent = title;
  $('#dlgSub').textContent = sub || '';
  $('#dlgBody').innerHTML = body || '';
  $('#dlgWord').value = '';
  $('#dlgGo').disabled = true;
  dlgAction = go;
  if(window.ToolkitUI) window.ToolkitUI.openConfirm();
  else { $('#dlg').showModal(); $('#dlgWord').focus(); }
}
function closeConfirmation(){
  if(window.ToolkitUI) window.ToolkitUI.closeConfirm();
  else $('#dlg').close();
}
$('#dlgWord').addEventListener('input', e => {
  $('#dlgGo').disabled = e.target.value !== 'UPDATE';
});
$('#dlgCancel').onclick = closeConfirmation;
$('#dlgGo').onclick = async () => {
  $('#dlgGo').disabled = true;
  $('#dlgGo').setAttribute('aria-busy', 'true');
  try{ await dlgAction($('#dlgWord').value); closeConfirmation(); }
  catch(e){ notifyError(e.message); }
  finally { $('#dlgGo').removeAttribute('aria-busy'); $('#dlgGo').disabled = $('#dlgWord').value !== 'UPDATE'; }
};

$('#rApply').onclick = () => {
  if(!PREVIEW || $('#rApply').disabled) return;
  const reviewed=PREVIEW;
  const n = PREVIEW.changes.length, afford = PREVIEW.affordable;
  const planned = Math.min(n, afford);
  confirmDialog({
    title: `Modify ${planned} reviewed description${planned===1?'':'s'}?`,
    sub: S.channel ? S.channel.title : '',
    body: `<div class="note"><b>Scope: ${esc(PREVIEW.scope)}.</b> Only the exact videos shown in the preview will be changed. Only the description field is sent. Titles, tags, category,
      privacy, thumbnails and every other setting are copied through unchanged.</div>
      ${afford < n ? `<div class="note warn">Quota allows ${afford} today;
      scan and preview the remaining ${n-afford} after the reset.</div>` : ''}`,
    go: async word => {
      if(PREVIEW!==reviewed) throw Error('Settings changed. Close this dialog and preview again.');
      await post('/api/bulk/apply', {confirm: word, preview_id: reviewed.preview_id});
      invalidatePreview();
      show('overview');
    }
  });
};

/* ---------------- links ---------------- */

async function loadLinks(){
  $('#linkList').innerHTML = `<div class="card"><div class="row">
    <span class="spin"></span> Scanning descriptions…</div></div>`;
  try{
    const j = await api('/api/links');
    if(!j.links.length){
      $('#linkList').innerHTML = `<div class="card"><div class="empty">
        <b>No links found</b><div class="small">Sync your channel metadata to find the links in your descriptions.</div><button class="primary" style="margin-top:16px" onclick="document.getElementById('btnSyncFree').click()">Sync metadata</button></div></div>`;
      return;
    }
    const groups = {};
    for(const l of j.links) (groups[l.domain] ||= []).push(l);
    const summary = `<div class="links-summary"><div><strong>${nfmt(j.links.length)}</strong><span>Unique links</span></div><div><strong>${nfmt(Object.keys(groups).length)}</strong><span>Websites</span></div><div><strong>${nfmt(j.links.reduce((s,l)=>s+l.count,0))}</strong><span>Total mentions</span></div></div><p class="links-help">Open a link to check it. To replace an outdated URL, return to Bulk Edit and preview a text replacement.</p>`;
    $('#linkList').innerHTML = summary + '<div class="links-domain-grid">' + Object.entries(groups)
      .sort((a,b) => b[1].reduce((s,x)=>s+x.count,0) - a[1].reduce((s,x)=>s+x.count,0))
      .map(([dom, list]) => `
        <div class="card link-domain-card">
          <div class="row"><h3>${esc(dom)}</h3>
            <span class="badge">${list.length} URL${list.length===1?'':'s'}</span>
            <span class="spacer"></span>
            <span class="small muted">${nfmt(list.reduce((s,x)=>s+x.count,0))} mentions</span></div>
          <div style="margin-top:10px">
            ${list.map(l => `
              <div class="link-url-row">
                <a href="${esc(l.url)}" target="_blank" rel="noopener noreferrer"
                   class="link-url">${esc(l.url)}</a>
                <span class="link-mentions">${nfmt(l.count)} mentions</span>
              </div>`).join('')}
          </div>
        </div>`).join('') + '</div>';
  }catch(e){
    $('#linkList').innerHTML = `<div class="card"><div class="note bad">${esc(e.message)}</div></div>`;
  }
}

/* ---------------- download page ---------------- */

let DLENV = null;

async function loadDownloadEnv(){
  if(DLENV) return DLENV;
  try{ DLENV = await api('/api/download/env'); }catch(e){
    $('#dlPresets').innerHTML = `<div class="note bad">Could not load download presets. ${esc(e.message)} Reopen this page to retry.</div>`;
    return null;
  }

  const e = DLENV;
  const badge = (ok, yes, no) =>
    `<span class="badge ${ok?'ok':'bad'} dot">${ok?yes:no}</span>`;

  let html = `<div class="card" style="margin-top:14px">
    <h2>Toolchain</h2>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));margin-top:12px">
      <div class="row" style="justify-content:space-between">
        <div><b>yt-dlp</b><div class="small muted">${esc(e.ytdlp_version||'not found')}</div></div>
        ${badge(!!e.ytdlp_version && !e.stale, 'ready', e.ytdlp_version ? 'outdated' : 'missing')}
      </div>
      <div class="row" style="justify-content:space-between">
        <div><b>FFmpeg</b><div class="small muted">${e.ffmpeg?'merging &amp; conversion available':'required for merging'}</div></div>
        ${badge(e.ffmpeg,'ready','missing')}
      </div>
      <div class="row" style="justify-content:space-between">
        <div><b>JS runtime</b><div class="small muted">${esc(e.js_runtime||'none — some formats hidden')}</div></div>
        ${badge(!!e.js_runtime, esc(e.js_runtime||''), 'none')}
      </div>
    </div>`;

  if(e.stale)
    html += `<div class="note bad"><b>yt-dlp is out of date (${esc(e.ytdlp_version)}).</b>
      YouTube rejects media streams from old builds with <code>HTTP 403</code>, so
      video and audio downloads will fail. Metadata, captions and thumbnails still work.
      Update it in PowerShell:<br><br>
      <code>.\\yt-dlp.exe -U</code><br><br>
      then restart this app.</div>`;
  if(!e.ffmpeg)
    html += `<div class="note warn">FFmpeg was not found. Without it, yt-dlp cannot merge
      separate video and audio streams or convert audio formats. Install it with
      <code>winget install Gyan.FFmpeg</code> and restart this app.</div>`;
  html += `</div>`;
  $('#dlEnv').innerHTML = html;
  $('#dlOutHint').textContent = 'Currently: ' + e.default_outdir;
  if(window.ToolkitDesktop && $('#dlOutDir').value==='downloads') $('#dlOutDir').value=localStorage.getItem('download-output-dir')||e.default_outdir;
  $('#dlOutDir').onchange=()=>localStorage.setItem('download-output-dir',$('#dlOutDir').value);

  $('#dlPresets').innerHTML = e.presets.map(p => `
    <button class="ghost" data-preset="${esc(p.key)}"
      style="flex-direction:column;align-items:flex-start;gap:3px;padding:12px 14px;height:auto;text-align:left">
      <b style="font-size:13.5px">${esc(p.label)}</b>
      <span class="small muted" style="font-weight:400;line-height:1.4">${esc(p.hint)}</span>
    </button>`).join('');
  return e;
}

function applyPreset(key){
  const p = (DLENV.presets || []).find(x => x.key === key);
  if(!p) return;
  const o = p.opts;
  const set = (id, val) => { const el = $(id); if(el && val !== undefined) el.value = val; };
  const chk = (id, val) => { const el = $(id); if(el) el.checked = !!val; };
  set('#dlMode', o.mode); set('#dlQuality', o.quality || 'best');
  set('#dlContainer', o.container || 'mp4'); set('#dlAudioFmt', o.audio_format || 'mp3');
  set('#dlTemplate', o.template || 'date');
  set('#dlSubLangs', o.sub_langs || 'en.*'); set('#dlSubConv', o.convert_subs || 'srt');
  chk('#dlSubs', o.subs); chk('#dlAutoSubs', o.auto_subs); chk('#dlEmbedSubs', o.embed_subs);
  chk('#dlThumb', o.thumbnail); chk('#dlEmbedThumb', o.embed_thumbnail);
  chk('#dlInfoJson', o.info_json); chk('#dlDesc', o.write_description);
  chk('#dlComments', o.write_comments); chk('#dlMeta', o.embed_metadata);
  chk('#dlChapters', o.embed_chapters); chk('#dlArchive', o.archive !== false);
  set('#dlDateAfter', o.date_after || '');
  $$('#dlPresets button').forEach(b => {
    b.classList.toggle('selected', b.dataset.preset === key);
    b.setAttribute('aria-pressed', b.dataset.preset === key);
  });
  syncModeFields();
  $('#dlPreview').innerHTML = '';
}

function syncModeFields(){
  const mode = $('#dlMode').value;
  $$('[data-when]').forEach(el => {
    el.style.display = el.dataset.when === mode ? '' : 'none';
  });
}

function downloadOpts(){
  const v = id => $(id) ? $(id).value.trim() : '';
  const c = id => $(id) ? $(id).checked : false;
  return {
    urls: $('#dlUrls').value,
    mode: v('#dlMode'),
    quality: v('#dlQuality'),
    container: v('#dlContainer'),
    audio_format: v('#dlAudioFmt'),
    template: v('#dlTemplate'),
    output_dir: v('#dlOutDir') || 'downloads',
    subs: c('#dlSubs'), auto_subs: c('#dlAutoSubs'), embed_subs: c('#dlEmbedSubs'),
    sub_langs: v('#dlSubLangs') || 'en.*', convert_subs: v('#dlSubConv'),
    thumbnail: c('#dlThumb'), embed_thumbnail: c('#dlEmbedThumb'),
    info_json: c('#dlInfoJson'), write_description: c('#dlDesc'),
    write_comments: c('#dlComments'), embed_metadata: c('#dlMeta'),
    embed_chapters: c('#dlChapters'), archive: c('#dlArchive'),
    live_from_start: c('#dlLive'),
    sponsorblock: v('#dlSponsor') || 'off',
    match_filter: v('#dlFilter'), date_after: v('#dlDateAfter'),
    date_before: v('#dlDateBefore'), playlist_items: v('#dlItems'),
    section: v('#dlSection'), limit_rate: v('#dlRate'),
    cookies_browser: v('#dlCookies') || null,
  };
}

$('#dlPresets').addEventListener('click', e => {
  const b = e.target.closest('[data-preset]');
  if(b) applyPreset(b.dataset.preset);
});
$('#dlMode').addEventListener('change', syncModeFields);

$('#dlMyChannel').onclick = () => {
  if(!S || !S.channel){ notifyError('Scan for editing or sync metadata first to identify your channel.'); return; }
  $('#dlUrls').value = `https://www.youtube.com/channel/${S.channel.id}/videos`;
};
$('#dlSelected').onclick = () => {
  if(!SELECTED.size){ notifyError('Select videos on the Videos page first.'); return; }
  $('#dlUrls').value = [...SELECTED]
    .map(id => 'https://www.youtube.com/watch?v=' + id).join('\n');
};

$('#dlPreviewBtn').onclick = async () => {
  $('#dlPreview').innerHTML = '<div class="row" style="margin-top:12px"><span class="spin"></span> Building…</div>';
  try{
    const j = await post('/api/download/preview', downloadOpts());
    $('#dlPreview').innerHTML = `
      <div class="note ok" style="margin-top:12px">Valid. Files go to
        <code>${esc(j.outdir)}</code></div>
      <div class="diff after" style="margin-top:10px"><span class="tag">COMMAND</span>${esc(j.command)}</div>
      <div class="hint">You can paste that straight into PowerShell if you prefer.</div>`;
  }catch(e){
    $('#dlPreview').innerHTML = `<div class="note bad" style="margin-top:12px">${esc(e.message)}</div>`;
  }
};

$('#dlFormats').onclick = async () => {
  const urls = $('#dlUrls').value.split('\n').map(s=>s.trim()).filter(Boolean);
  if(!urls.length){ notifyError('Put a video URL in the box first.'); return; }
  $('#dlPreview').innerHTML = '<div class="row" style="margin-top:12px"><span class="spin"></span> Asking yt-dlp…</div>';
  try{
    const j = await post('/api/download/formats',
      {url: urls[0], cookies_browser: $('#dlCookies').value || null});
    $('#dlPreview').innerHTML = `<div class="log" style="margin-top:12px;height:340px">${esc(j.text)}</div>`;
  }catch(e){
    $('#dlPreview').innerHTML = `<div class="note bad" style="margin-top:12px">${esc(e.message)}</div>`;
  }
};

let completedDownloadId = null;
let legacyDownload = null;
function downloadStatus(status){
  if(status.download) return status.download;
  // Older server processes expose download progress through the shared job.
  if(status.phase==='downloading'){
    const job=status.job||{};
    const current=job.current||'';
    const match=current.match(/(\d+(?:\.\d+)?)%/);
    legacyDownload={...(legacyDownload||{id:'legacy-'+Date.now(),folder:$('#dlOutDir').value||DLENV?.default_outdir||''}),status:'running',percent:match ? match[1] : null,title:current||status.message,item:job.done,items:job.total,legacy:true};
  }else if(legacyDownload?.status==='running'){
    const message=status.message||'';
    legacyDownload={...legacyDownload,status:/Download finished\./i.test(message)?'complete':/stop/i.test(message)?'stopped':'errors',folder:message.match(/Files are in (.+)$/i)?.[1]||legacyDownload.folder};
  }
  return legacyDownload;
}
async function openDownloadFolder(d, target){
  if(window.ToolkitDesktop){
    try{await window.ToolkitDesktop.openDownloadFolder();}catch(e){target.textContent=e.message;}
    return;
  }
  if(d.legacy){
    target.textContent='Restart the toolkit server after this download finishes to enable Open folder. You can also paste the folder path above into File Explorer.';
    return;
  }
  try{await post('/api/download/open-folder',{});}catch(e){target.textContent=e.message;}
}
function renderDownloadProgress(d){
  if(!d) return;
  let host = $('#downloadProgress');
  if(!host){ host=document.createElement('div'); host.id='downloadProgress'; $('#dlPreview').before(host); }
  const running=d.status==='running';
  const raw=parseFloat(String(d.percent??'').replace('%',''));
  const known=Number.isFinite(raw);
  host.innerHTML=running ? `<div class="download-progress"><div class="row"><b>Downloading${d.items ? ` · item ${esc(d.item)} of ${esc(d.items)}` : ''}</b><span>${known ? Math.max(0,Math.min(100,raw)).toFixed(1)+'% of current file' : 'Preparing files…'}</span></div><progress ${known ? `value="${Math.max(0,Math.min(100,raw))}"` : ''} max="100" aria-label="Current file download progress"></progress><p class="small muted">${esc(d.title||'Starting download…')} ${esc(d.speed||'')}</p></div>` : '';
  if(!running){
    const label=d.status==='complete' ? 'Download complete' : d.status==='stopped' ? 'Download stopped' : 'Finished with errors';
    host.innerHTML=`<div class="download-finished"><h3>${label}</h3><p class="small muted">${d.status==='complete' ? 'Your saved files are available below.' : 'Check Activity for details about incomplete files.'}</p><p class="download-folder">${esc(d.folder)}</p><button class="primary" id="downloadPanelOpenFolder">Open folder</button><p id="downloadPanelError" role="status"></p></div>`;
    $('#downloadPanelOpenFolder').onclick=()=>openDownloadFolder(d,$('#downloadPanelError'));
  }
  if(!running && completedDownloadId!==d.id){
    completedDownloadId=d.id;
    let dlg=$('#downloadComplete');
    if(!dlg){dlg=document.createElement('dialog');dlg.id='downloadComplete';document.body.append(dlg);}
    const title=d.status==='complete' ? 'Download complete' : d.status==='stopped' ? 'Download stopped' : 'Download finished with errors';
    dlg.innerHTML=`<h2>${title}</h2><p class="sub">${d.status==='complete' ? 'Your files are ready in the folder below.' : 'Some files may have been saved. Check the Activity log for details.'}</p><p class="download-folder">${esc(d.folder)}</p><p id="folderError" role="status"></p><div class="row"><button id="downloadDismiss">Close</button><button class="primary" id="downloadOpenFolder">Open folder</button></div>`;
    $('#downloadDismiss').onclick=()=>dlg.close();
    $('#downloadOpenFolder').onclick=()=>openDownloadFolder(d,$('#folderError'));
    dlg.showModal();
  }
}
$('#dlStart').onclick = async () => {
  const opts = downloadOpts();
  const n = opts.urls.split('\n').filter(s=>s.trim()).length;
  if(!n){ notifyError('Add at least one URL.'); return; }
  if(DLENV && DLENV.stale && (opts.mode === 'video' || opts.mode === 'audio')){
    if(!await confirmAction('yt-dlp is out of date, so media downloads will likely fail with '
              + 'HTTP 403.\n\nUpdate it with  .\\yt-dlp.exe -U  first.\n\nTry anyway?')) return;
  }
  try{
    await post('/api/download/start', opts);
    renderDownloadProgress({id:'starting-'+Date.now(),status:'running',percent:null,title:'Waiting for download information…',folder:opts.output_dir||DLENV?.default_outdir||''});
    await poll();
    $('#dlPreview').innerHTML =
      '<div class="note ok" style="margin-top:12px">Download started. Progress will appear here as files are received.</div>';
  }catch(e){ notifyError(e.message); }
};

/* ---------------- top bar actions ---------------- */

$('#btnScanApi').onclick = async () => {
  invalidatePreview();
  try{ await post('/api/scan'); await poll(); }catch(e){ notifyError(e.message); }
};
$('#btnSyncFree').onclick = async () => {
  try{
    await post('/api/ytdlp/sync', {cookies_browser: $('#tCookies').value || null});
  }catch(e){ notifyError(e.message); }
};
$('#btnStop').onclick = async () => {
  try { await post('/api/stop'); window.ToolkitUI?.notify('Stop requested. The current item may finish first.'); }
  catch(e) { notifyError(e.message); }
};

$('#tCsv').onclick    = () => runTool('/api/export', {format:'csv'});
$('#tJson').onclick   = () => runTool('/api/export', {format:'json'});
$('#tThumbs').onclick = () => runTool('/api/ytdlp/thumbnails',
                                      {cookies_browser: $('#tCookies').value || null});
async function runTool(path, body){
  try{ const j = await post(path, body); toast(j.message || 'Done.'); window.ToolkitUI?.notify(j.message || 'Done.'); }
  catch(e){ notifyError(e.message); }
}

/* ---------------- boot ---------------- */

// Presentation-only feedback: reuse the existing handlers and request payloads.
for(const id of ['rSave','btnScanApi','btnSyncFree','btnStop','tCsv','tJson','tThumbs','dlPreviewBtn','dlFormats','dlStart']){
  const button = $('#'+id), action = button.onclick;
  button.onclick = async event => {
    if(button.getAttribute('aria-busy') === 'true') return;
    const content = button.innerHTML;
    button.setAttribute('aria-busy','true'); button.disabled = true;
    button.innerHTML = '<span class="spin" aria-hidden="true"></span> Working…';
    try { await action.call(button,event); }
    finally {
      button.innerHTML = content; button.removeAttribute('aria-busy');
      button.disabled = false;
      if(['btnScanApi','btnSyncFree','btnStop'].includes(id)) await poll();
      updateApplyState();
    }
  };
}

async function refreshData(){
  try{ STATS = await api('/api/stats'); }catch(e){}
  await loadVideos();
  renderOverview();
}

let lastPhase = null;
setInterval(async () => {
  await poll();
  if(S && S.phase !== lastPhase){
    if(lastPhase && (lastPhase === 'syncing' || lastPhase === 'scanning'
                     || lastPhase === 'updating')) refreshData();
    lastPhase = S.phase;
  }
}, 1500);
setInterval(pollLog, 1200);

(async () => {
  const loadingTimer = setTimeout(()=>{
    $('#startup-status').textContent = 'Still loading. Check that the local server is running, or try again.';
    $('#startup-retry').hidden = false;
  },15000);
  try{
    await poll();
    lastPhase = S ? S.phase : null;
    await loadRules();
    await refreshData();
    const v = location.hash.slice(1);
    show(v && $('#view-'+v) ? v : 'edit');
    if(!S) throw Error('Cannot connect to the local server. Start python web.py, then try again.');
    $('#startup-screen').hidden = true;
  }catch(e){
    $('#startup-status').textContent = e.message || 'Could not load the workspace. Try again.';
    $('#startup-retry').hidden = false;
  }finally{clearTimeout(loadingTimer);}
})();
