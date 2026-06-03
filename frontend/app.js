/* ── State ── */
const API = '/api';
let curSessionId = null;
let chatAbort = null;

/* ── Helpers ── */
const $ = id => document.getElementById(id);
const qs = (el, sel) => (typeof el === 'string' ? document.querySelector(el) : el.querySelector(sel));
const qsa = (el, sel) => (typeof el === 'string' ? document.querySelectorAll(el) : el.querySelectorAll(sel));

function fmtBytes(n) {
  if (!n || n <= 0) return '\u2014';
  for (const u of ['B', 'KB', 'MB', 'GB', 'TB']) { if (Math.abs(n) < 1024) return `${n.toFixed(1)} ${u}`; n /= 1024; }
  return `${n.toFixed(1)} PB`;
}
function fmtRate(bps) { return fmtBytes(bps) + '/s'; }
function fmtEta(s) {
  if (s == null || s <= 0) return '\u2014';
  const m = Math.floor(s / 60), h = Math.floor(m / 60);
  if (h) return `${h}h ${m % 60}m`;
  if (m) return `${m}m ${Math.floor(s % 60)}s`;
  return `${Math.floor(s)}s`;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

/* ── Tab Switching ── */
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelector('.tab.active')?.classList.remove('active');
    tab.classList.add('active');
    document.querySelector('.tab-content.active')?.classList.remove('active');
    const pane = document.getElementById('tab-' + tab.dataset.tab);
    if (pane) pane.classList.add('active');
    if (tab.dataset.tab === 'downloads') refreshDownloads();
    if (tab.dataset.tab === 'hardware') refreshHardware();
    if (tab.dataset.tab === 'logs') refreshLogs();
  });
});

/* ── API helpers ── */
async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const res = await fetch(API + path, opts);
  if (!res.ok) { const txt = await res.text(); throw new Error(txt); }
  return res.json();
}

/* ── Runtime Indicator ── */
async function refreshRuntime() {
  try {
    const s = await api('GET', '/inference/status');
    const el = $('runtime-indicator');
    if (s.model_id) {
      el.className = 'runtime-badge ' + (s.status === 'loaded' ? 'loaded' : 'loading');
      el.textContent = `\u25CF ${s.model_id.slice(0, 12)}... \u00b7 ${s.status}`;
    } else {
      el.className = 'runtime-badge idle';
      el.textContent = 'Idle';
    }
  } catch { /* ignore */ }
}

/* ════════════════════════════════════════
   CHAT
   ════════════════════════════════════════ */
async function loadSessions() {
  try {
    const sessions = await api('GET', '/chat/sessions');
    const list = $('session-list');
    list.innerHTML = sessions.map(s => `<div class="session-item${s.id === curSessionId ? ' active' : ''}" data-id="${s.id}"><span>${escapeHtml(s.title)}</span>${s.pinned ? '<span class="pin">\uD83D\uDCCC</span>' : ''}</div>`).join('');
    list.querySelectorAll('.session-item').forEach(el => {
      el.addEventListener('click', () => selectSession(el.dataset.id));
    });
  } catch (e) { console.error('loadSessions', e); }
}

async function selectSession(id) {
  curSessionId = id;
  loadSessions();
  try {
    const msgs = await api('GET', `/chat/sessions/${id}/messages`);
    const container = $('chat-messages');
    container.innerHTML = msgs.map(m => renderMsg(m)).join('');
    container.scrollTop = container.scrollHeight;
    const s = await api('GET', `/chat/sessions/${id}`);
    // find session name and set as title
  } catch (e) { console.error('selectSession', e); }
}

function renderMsg(m) {
  const content = escapeHtml(m.content).replace(/\n/g, '<br>');
  return `<div class="msg ${m.role}"><div class="bubble">${content}</div></div>`;
}

$('create-session').addEventListener('click', async () => {
  const title = $('new-session-title').value.trim() || 'New Chat';
  try {
    const s = await api('POST', '/chat/sessions', { title, system_prompt: '', parameters: {} });
    curSessionId = s.id;
    $('new-session-title').value = '';
    $('chat-messages').innerHTML = '';
    loadSessions();
  } catch (e) { console.error(e); }
});

$('send-btn').addEventListener('click', sendMessage);
$('chat-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });

async function sendMessage() {
  const input = $('chat-input');
  const msg = input.value.trim();
  if (!msg) return;
  input.value = '';

  if (!curSessionId) {
    try {
      const s = await api('POST', '/chat/sessions', { title: msg.slice(0, 60), system_prompt: '', parameters: {} });
      curSessionId = s.id;
      loadSessions();
    } catch (e) { return console.error(e); }
  }

  const container = $('chat-messages');
  container.insertAdjacentHTML('beforeend', `<div class="msg user"><div class="bubble">${escapeHtml(msg)}</div></div>`);
  const assistantIdx = container.children.length;
  container.insertAdjacentHTML('beforeend', `<div class="msg assistant" id="stream-msg"><div class="bubble"></div></div>`);
  container.scrollTop = container.scrollHeight;

  const sp = $('sp').value;
  const params = {
    temperature: parseFloat($('temp').value),
    top_p: parseFloat($('top-p').value),
    top_k: parseInt($('top-k').value),
    max_tokens: parseInt($('max-tok').value),
    repetition_penalty: parseFloat($('rep-pen').value),
  };

  if (chatAbort) { chatAbort.abort(); }
  chatAbort = new AbortController();

  try {
    const resp = await fetch(API + `/chat/sessions/${curSessionId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: msg, attachments: [], parameters: params }),
      signal: chatAbort.signal,
    });
    if (!resp.ok) throw new Error(await resp.text());
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';
    const bubble = document.querySelector('#stream-msg .bubble');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.token) {
            fullText += data.token;
            bubble.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>');
            container.scrollTop = container.scrollHeight;
          }
          if (data.done) break;
        } catch { /* skip parse errors */ }
      }
    }
    // final
    if (fullText) {
      bubble.innerHTML = escapeHtml(fullText).replace(/\n/g, '<br>');
      container.scrollTop = container.scrollHeight;
    }
  } catch (e) {
    if (e.name !== 'AbortError') console.error('sendMessage', e);
  }
  chatAbort = null;
}

/* ════════════════════════════════════════
   MODELS
   ════════════════════════════════════════ */
$('hf-search').addEventListener('click', searchHF);
$('hf-query').addEventListener('keydown', e => { if (e.key === 'Enter') searchHF(); });
$('hf-files-close').addEventListener('click', () => { $('hf-files-panel').style.display = 'none'; });

let hfResults = [];

async function searchHF() {
  const q = $('hf-query').value.trim();
  const task = $('hf-task').value;
  const sort = $('hf-sort').value;
  try {
    const res = await api('GET', `/models/huggingface?query=${encodeURIComponent(q)}&task=${encodeURIComponent(task)}&sort=${sort}&limit=25`);
    hfResults = res.items;
    const tbody = $('hf-table').querySelector('tbody');
    tbody.innerHTML = res.items.map((r, i) =>
      `<tr class="hf-row" data-idx="${i}">
        <td>${escapeHtml(r.id)}</td><td>${escapeHtml(r.pipeline_tag || '\u2014')}</td>
        <td>${fmtBytes(r.total_size_bytes)}</td><td>${r.downloads}</td><td>${r.likes}</td>
        <td>${r.last_modified || ''}</td>
        <td style="color:var(--accent);font-size:11px">click to view</td>
      </tr>`
    ).join('');
    tbody.querySelectorAll('.hf-row').forEach(el => {
      el.addEventListener('click', () => showFiles(hfResults[parseInt(el.dataset.idx)]));
    });
  } catch (e) { console.error(e); }
}

function isModelFile(name) {
  const ext = name.split('.').pop().toLowerCase();
  return ['gguf', 'safetensors', 'bin', 'pt', 'pth'].includes(ext);
}

async function showFiles(model) {
  $('hf-files-repo').textContent = model.id;
  const tbody = $('hf-files-table').querySelector('tbody');
  tbody.innerHTML = '<tr><td colspan="3">Loading files...</td></tr>';
  $('hf-files-panel').style.display = 'block';

  try {
    const info = await api('GET', '/models/huggingface/' + encodeURIComponent(model.id) + '/size');
    const files = (info.files || []).filter(s => isModelFile(s.path));
    if (!files.length) {
      tbody.innerHTML = '<tr><td colspan="3">No model files found.</td></tr>';
      return;
    }
    tbody.innerHTML = files.map(f =>
      `<tr>
        <td>${escapeHtml(f.path)}</td>
        <td>${fmtBytes(f.size_bytes)}</td>
        <td><button class="btn file-dl-btn" data-repo="${escapeHtml(model.id)}" data-file="${escapeHtml(f.path)}">Download</button></td>
      </tr>`
    ).join('');
    tbody.querySelectorAll('.file-dl-btn').forEach(btn => {
      btn.addEventListener('click', () => downloadFile(btn.dataset.repo, btn.dataset.file));
    });
    const foot = tbody.parentElement.createTFoot();
    foot.innerHTML = `<tr><td colspan="3" style="text-align:center;padding:6px"><button class="btn primary" id="dl-all-files">Download All (${fmtBytes(info.total_size_bytes)})</button></td></tr>`;
    foot.querySelector('#dl-all-files').addEventListener('click', () => downloadAll(model.id));
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="3">Error loading files: ' + escapeHtml(e.message) + '</td></tr>';
  }
}

async function downloadFile(repo, file) {
  $('dl-status').textContent = `Queuing ${file}...`;
  try {
    await api('POST', '/downloads', { repo_id: repo, files: [file] });
    $('dl-status').textContent = `Queued: ${repo}/${file}`;
  } catch (e) { $('dl-status').textContent = `Error: ${e.message}`; }
}

async function downloadAll(repo) {
  $('dl-status').textContent = `Queuing all files from ${repo}...`;
  try {
    await api('POST', '/downloads', { repo_id: repo });
    $('dl-status').textContent = `Queued: ${repo}`;
  } catch (e) { $('dl-status').textContent = `Error: ${e.message}`; }
}

$('dl-btn').addEventListener('click', async () => {
  const repo = $('dl-repo').value.trim();
  if (!repo) return;
  await downloadAll(repo);
});

async function loadLocalModels() {
  try {
    const models = await api('GET', '/models');
    const tbody = $('local-table').querySelector('tbody');
    tbody.innerHTML = models.map(m =>
      `<tr class="local-row" data-id="${escapeHtml(m.id)}" data-name="${escapeHtml(m.name)}">
        <td>${escapeHtml(m.name)}</td>
        <td>${escapeHtml(m.architecture || '\u2014')}</td>
        <td>${escapeHtml(m.parameter_count || '\u2014')}</td>
        <td>${escapeHtml(m.quantization || '\u2014')}</td>
        <td>${fmtBytes(m.size_bytes)}</td>
        <td>${escapeHtml((m.compatibility && m.compatibility.badge) || '\u2014')}</td>
        <td>${escapeHtml(m.id)}</td>
      </tr>`
    ).join('');
    tbody.querySelectorAll('.local-row').forEach(el => {
      el.addEventListener('click', () => {
        $('load-id').value = el.dataset.id;
        $('load-btn').click();
      });
      el.style.cursor = 'pointer';
    });
  } catch (e) { console.error(e); }
}

$('scan-btn').addEventListener('click', async () => {
  try {
    await api('POST', '/models/scan');
    loadLocalModels();
  } catch (e) { console.error(e); }
});

$('load-btn').addEventListener('click', async () => {
  const mid = $('load-id').value.trim();
  if (!mid) return;
  try {
    const res = await fetch(API + '/inference/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: mid, backend: 'auto' }),
    });
    const data = await res.json();
    if (data.status === 'error') {
      $('load-status').textContent = `Error: ${data.error || 'Failed to load model'}`;
    } else {
      $('load-status').textContent = 'Model loaded successfully.';
    }
    refreshRuntime();
  } catch (e) { $('load-status').textContent = `Error: ${e.message}`; }
});

$('unload-btn').addEventListener('click', async () => {
  try {
    await api('POST', '/inference/unload');
    $('load-status').textContent = 'Model unloaded.';
    refreshRuntime();
  } catch (e) { $('load-status').textContent = `Error: ${e.message}`; }
});

/* ════════════════════════════════════════
   DOWNLOADS
   ════════════════════════════════════════ */
async function refreshDownloads() {
  try {
    const jobs = await api('GET', '/downloads');
    const tbody = $('dl-table').querySelector('tbody');
    tbody.innerHTML = jobs.map(j => {
      const pct = j.total_bytes > 0 ? (j.downloaded_bytes / j.total_bytes * 100).toFixed(1) + '%' : '0%';
      return `<tr><td>${escapeHtml(j.repo_id)}</td><td>${escapeHtml(j.status)}</td><td>${pct}</td><td>${fmtBytes(j.downloaded_bytes)}</td><td>${fmtBytes(j.total_bytes)}</td><td>${fmtRate(j.speed_bps)}</td><td>${fmtEta(j.eta_seconds)}</td><td>${escapeHtml(j.id)}</td></tr>`;
    }).join('');
  } catch { /* ignore */ }
}

async function dlAction(action) {
  const jid = $('dl-jid').value.trim();
  if (!jid) return;
  try {
    await api('POST', `/downloads/${jid}/${action}`);
    $('dl-action-status').textContent = `${action} ${jid.slice(0, 8)}`;
    refreshDownloads();
  } catch (e) { $('dl-action-status').textContent = `Error: ${e.message}`; }
}

$('pause-btn').addEventListener('click', () => dlAction('pause'));
$('resume-btn').addEventListener('click', () => dlAction('resume'));
$('cancel-btn').addEventListener('click', () => dlAction('cancel'));
$('retry-btn').addEventListener('click', () => dlAction('retry'));

/* ════════════════════════════════════════
   HARDWARE
   ════════════════════════════════════════ */
async function refreshHardware() {
  try {
    const hw = await api('GET', '/hardware');
    $('hw-cpu').textContent = `${hw.cpu_model} | ${hw.physical_cores}C/${hw.logical_threads}T`;
    $('hw-cpu-usage').textContent = `${hw.cpu_usage_percent.toFixed(1)}%`;
    $('hw-ram-total').textContent = fmtBytes(hw.ram_total_bytes);
    $('hw-ram-avail').textContent = fmtBytes(hw.ram_available_bytes);
    $('hw-ram-usage').textContent = `${hw.ram_usage_percent.toFixed(1)}%`;
    $('hw-gpu-count').textContent = `${hw.gpus.length} GPU(s)`;
    $('hw-vram-total').textContent = fmtBytes(hw.total_vram_bytes);
    $('hw-vram-avail').textContent = fmtBytes(hw.available_vram_bytes);
    const tbody = $('hw-gpu-table').querySelector('tbody');
    tbody.innerHTML = hw.gpus.map(g =>
      `<tr><td>${escapeHtml(g.name)}</td><td>${g.utilization_percent.toFixed(0)}%</td><td>${fmtBytes(g.total_vram_bytes)}</td><td>${fmtBytes(g.available_vram_bytes)}</td><td>${escapeHtml(g.vendor)}</td><td>${escapeHtml(g.cuda_capability || '\u2014')}</td></tr>`
    ).join('');
  } catch { /* ignore */ }
}

$('hw-refresh').addEventListener('click', refreshHardware);

/* ════════════════════════════════════════
   SETTINGS
   ════════════════════════════════════════ */
async function loadSettings() {
  try {
    const s = await api('GET', '/settings');
    const v = s.values;
    if (v.download_location) $('s-loc').value = v.download_location;
    if (v.cache_size_gb != null) $('s-cache').value = v.cache_size_gb;
    if (v.default_backend) $('s-backend').value = v.default_backend;
    if (v.temperature != null) $('s-temp').value = v.temperature;
    if (v.top_p != null) $('s-top-p').value = v.top_p;
    if (v.top_k != null) $('s-top-k').value = v.top_k;
    if (v.max_tokens != null) $('s-max-tok').value = v.max_tokens;
    if (v.repetition_penalty != null) $('s-rep-pen').value = v.repetition_penalty;
    // sync chat defaults too
    $('temp').value = v.temperature ?? 0.7;
    $('top-p').value = v.top_p ?? 0.9;
    $('top-k').value = v.top_k ?? 40;
    $('max-tok').value = v.max_tokens ?? 1024;
    $('rep-pen').value = v.repetition_penalty ?? 1.05;
  } catch { /* ignore */ }
}

$('s-save').addEventListener('click', async () => {
  const vals = {
    download_location: $('s-loc').value,
    cache_size_gb: parseFloat($('s-cache').value),
    default_backend: $('s-backend').value,
    temperature: parseFloat($('s-temp').value),
    top_p: parseFloat($('s-top-p').value),
    top_k: parseInt($('s-top-k').value),
    max_tokens: parseInt($('s-max-tok').value),
    repetition_penalty: parseFloat($('s-rep-pen').value),
  };
  try {
    await api('PUT', '/settings', { values: vals });
    $('s-status').textContent = 'Settings saved.';
  } catch (e) { $('s-status').textContent = `Error: ${e.message}`; }
});

/* ════════════════════════════════════════
   LOGS
   ════════════════════════════════════════ */
async function refreshLogs() {
  const level = $('log-level').value;
  try {
    const entries = await api('GET', `/logs?limit=150${level ? '&level=' + level : ''}`);
    const tbody = $('log-table').querySelector('tbody');
    tbody.innerHTML = entries.map(e =>
      `<tr><td>${escapeHtml(e.level)}</td><td>${escapeHtml(e.source)}</td><td>${escapeHtml(e.message.slice(0, 120))}</td><td>${escapeHtml(e.created_at)}</td></tr>`
    ).join('');
  } catch { /* ignore */ }
}

$('log-refresh').addEventListener('click', refreshLogs);
$('log-level').addEventListener('change', refreshLogs);

/* ════════════════════════════════════════
   Auto-refresh
   ════════════════════════════════════════ */
function autoRefresh() {
  refreshRuntime();
  refreshDownloads();
  loadLocalModels();
}

loadSessions();
loadLocalModels();
loadSettings();
refreshHardware();
refreshLogs();
refreshRuntime();
setInterval(autoRefresh, 5000);
