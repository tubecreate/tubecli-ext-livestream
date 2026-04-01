/**
 * Livestream Extension — Client-side Logic
 * YouTube Livestream Manager with FFmpeg RTMP push
 */
const API = '/api/v1/livestream';
let _currentCredId = '';
let _currentLogSession = '';

// ═══ API Helpers ═══
async function apiGet(path) {
    try {
        const r = await fetch(API + path + (path.includes('?') ? `&_t=${Date.now()}` : `?_t=${Date.now()}`));
        if (!r.ok) {
            const text = await r.text();
            try { return JSON.parse(text); } catch { return { error: text }; }
        }
        return await r.json();
    } catch (e) { return { error: e.message }; }
}
async function apiPost(path, data) {
    try {
        const r = await fetch(API + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        const json = await r.json();
        if (!r.ok) json._httpError = r.status;
        return json;
    } catch (e) { return { error: e.message }; }
}
async function apiDelete(path) {
    try {
        const r = await fetch(API + path, { method: 'DELETE' });
        return await r.json();
    } catch (e) { return { error: e.message }; }
}

function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

// ═══ Toast ═══
function toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `ls-toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 4000);
}

// ═══ Modal ═══
function openModal(id) { document.getElementById(id).classList.remove('hidden'); }
function closeModal(id) { document.getElementById(id).classList.add('hidden'); }

// ═══ Panel Navigation ═══
function switchPanel(panelId, btn) {
    document.querySelectorAll('.ls-panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.ls-nav-btn').forEach(b => b.classList.remove('active'));
    const panel = document.getElementById('panel-' + panelId);
    if (panel) panel.classList.add('active');
    if (btn) btn.classList.add('active');

    // Load data on panel switch
    if (panelId === 'active') loadActiveStreams();
    else if (panelId === 'history') loadBroadcasts();
    else if (panelId === 'schedule') loadSchedules();
    else if (panelId === 'ffmpeg') loadFFmpegSessions();
    else if (panelId === 'settings') loadSettings();
}

// ═══ Credentials ═══
async function loadCredentials() {
    try {
        const res = await fetch(`${API}/credentials`);
        const json = await res.json();
        const creds = json?.credentials || [];
        const sel = document.getElementById('cred-select');

        if (creds.length === 0) {
            sel.innerHTML = '<option value="">⚠️ No YouTube accounts — Authorize in Auth Manager</option>';
            return;
        }

        sel.innerHTML = creds.map(c =>
            `<option value="${esc(c.token_id)}">${esc(c.authorized_email || c.credential_name)} (${esc(c.provider)})</option>`
        ).join('');

        _currentCredId = creds[0].token_id;
    } catch (e) {
        document.getElementById('cred-select').innerHTML =
            '<option value="">⚠️ Failed to load credentials</option>';
    }
}

function onCredChange() {
    _currentCredId = document.getElementById('cred-select').value;
    loadActiveStreams();
}

// ═══ FFmpeg Status ═══
async function checkFFmpeg() {
    const data = await apiGet('/ffmpeg-check');
    const badge = document.getElementById('ffmpeg-status');
    const text = document.getElementById('ffmpeg-status-text');

    if (data?.available) {
        badge.classList.remove('error');
        text.textContent = 'FFmpeg OK';
    } else {
        badge.classList.add('error');
        text.textContent = 'FFmpeg Missing!';
    }
}

// ═══ Active Streams ═══
async function loadActiveStreams() {
    const container = document.getElementById('active-streams');
    const data = await apiGet('/broadcasts');
    const broadcasts = data?.broadcasts || [];
    const sessions = (await apiGet('/ffmpeg/sessions'))?.sessions || [];

    // Filter active (running FFmpeg or recent)
    const activeSessionIds = new Set(sessions.filter(s => s.status === 'running').map(s => s.broadcast_id));
    const active = broadcasts.filter(b =>
        activeSessionIds.has(b.broadcast_id) || b.status === 'streaming' || b.status === 'ready'
    );

    if (active.length === 0) {
        container.innerHTML = `
            <div class="ls-empty">
                <div class="ls-empty-icon">📡</div>
                <p>No active streams. Create one to get started!</p>
                <button class="ls-btn ls-btn-primary" onclick="switchPanel('create', document.querySelector('[data-panel=create]'))">➕ Create Stream</button>
            </div>`;
        return;
    }

    container.innerHTML = active.map(b => {
        const isLive = b.status === 'streaming' || activeSessionIds.has(b.broadcast_id);
        const statusClass = isLive ? 'live' : (b.status === 'ready' ? 'ready' : 'stopped');
        const statusLabel = isLive ? 'STREAMING' : b.status?.toUpperCase() || 'UNKNOWN';
        const ytUrl = `https://youtu.be/${b.broadcast_id}`;
        const ytStudioUrl = `https://studio.youtube.com/video/${b.broadcast_id}/livestreaming`;

        return `
        <div class="ls-stream-card ${isLive ? 'live' : ''}">
            <div class="ls-stream-title">
                ${isLive ? '<span class="ls-live-dot"></span>' : ''}
                ${esc(b.title || 'Untitled')}
            </div>
            <div class="ls-stream-meta">
                <span class="ls-tag ${statusClass}">${statusLabel}</span>
                <span>${esc(b.resolution || '1080p')} / ${esc(b.frame_rate || '30fps')}</span>
                <span>🔒 ${esc(b.privacy || 'unlisted')}</span>
            </div>
            <div class="ls-stream-meta">
                <span>📅 ${esc((b.created_at || '').slice(0, 16))}</span>
                <a href="${ytUrl}" target="_blank" class="ls-yt-link" title="Watch on YouTube">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.5 12 3.5 12 3.5s-7.5 0-9.4.6A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.6 9.4.6 9.4.6s7.5 0 9.4-.6a3 3 0 0 0 2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8zM9.75 15.5v-7l6.5 3.5-6.5 3.5z"/></svg>
                    youtu.be/${esc(b.broadcast_id)}
                </a>
                <a href="${ytStudioUrl}" target="_blank" class="ls-yt-link ls-studio-link" title="Open in YouTube Studio">🎬 Studio</a>
            </div>
            <div class="ls-stream-actions">
                <button class="ls-btn ls-btn-sm" onclick="showStreamKey('${esc(b.broadcast_id)}')">🔑 Key</button>
                ${isLive
                    ? `<button class="ls-btn ls-btn-sm ls-btn-danger" onclick="stopStream('${esc(b.broadcast_id)}')">⏹ Stop</button>`
                    : `<button class="ls-btn ls-btn-sm ls-btn-primary" onclick="startStreamFFmpeg('${esc(b.broadcast_id)}')">▶ Start</button>`
                }
                <button class="ls-btn ls-btn-sm" onclick="navigator.clipboard.writeText('${ytUrl}').then(()=>toast('Copied!','success'))" title="Copy YouTube link">🔗</button>
                <button class="ls-btn ls-btn-sm ls-btn-danger" onclick="deleteBroadcast('${esc(b.broadcast_id)}')">🗑</button>
            </div>
        </div>`;
    }).join('');
}

// ═══ Show Stream Key ═══
function showStreamKey(broadcastId) {
    apiGet('/broadcasts/' + broadcastId).then(data => {
        const b = data?.broadcast;
        if (!b) { toast('Broadcast not found', 'error'); return; }
        document.getElementById('modal-rtmp-url').value = b.ingestion_url || 'rtmp://a.rtmp.youtube.com/live2';
        document.getElementById('modal-stream-key-val').value = b.stream_key || '';
        document.getElementById('modal-full-rtmp').value = b.rtmp_url || '';
        openModal('modal-stream-key');
    });
}

function copyField(inputId) {
    const input = document.getElementById(inputId);
    navigator.clipboard.writeText(input.value).then(() => toast('Copied!', 'success'));
}

// ═══ Start/Stop Stream ═══
async function startStreamFFmpeg(broadcastId) {
    const data = await apiGet('/broadcasts/' + broadcastId);
    const b = data?.broadcast;
    if (!b) { toast('Broadcast not found', 'error'); return; }

    const input = prompt('Enter input source (file path or device):', '');
    if (!input) return;

    const preset = prompt('Preset (file, file_loop, camera_win, screen_win):', 'file');
    const result = await apiPost('/ffmpeg/start', {
        stream_key: b.stream_key,
        preset: preset || 'file',
        input_source: input,
        broadcast_id: broadcastId,
    });

    if (result?.status === 'success') {
        toast('🔴 FFmpeg started! Streaming...', 'success');
        loadActiveStreams();
    } else {
        toast(result?.message || result?.detail || 'Failed to start', 'error');
    }
}

async function stopStream(broadcastId) {
    // Find FFmpeg session for this broadcast
    const sessions = (await apiGet('/ffmpeg/sessions'))?.sessions || [];
    const sess = sessions.find(s => s.broadcast_id === broadcastId && s.status === 'running');

    if (sess) {
        await apiPost('/ffmpeg/stop/' + sess.session_id, {});
        toast('⏹ Stream stopped', 'success');
    } else {
        toast('No running FFmpeg session found', 'info');
    }
    loadActiveStreams();
}

// ═══ Create Stream ═══
function onPresetChange() {
    const preset = document.getElementById('create-preset').value;
    const inputGroup = document.getElementById('input-source-group');
    const optionsRow = document.getElementById('ffmpeg-options-row');
    const customGroup = document.getElementById('custom-cmd-group');

    if (preset === 'custom') {
        inputGroup.style.display = 'none';
        optionsRow.style.display = 'none';
        customGroup.style.display = 'block';
    } else if (preset === 'camera_win' || preset === 'screen_win' || preset === 'screen_linux') {
        inputGroup.style.display = 'none';
        optionsRow.style.display = 'flex';
        customGroup.style.display = 'none';
    } else {
        inputGroup.style.display = 'block';
        optionsRow.style.display = 'flex';
        customGroup.style.display = 'none';
    }
}

async function createAndGoLive() {
    const btn = document.getElementById('btn-go-live');
    btn.disabled = true;
    btn.textContent = '⏳ Creating...';

    const title = document.getElementById('create-title').value.trim();
    if (!title) { toast('Title is required', 'error'); btn.disabled = false; btn.textContent = '🚀 Create & Go Live'; return; }

    const preset = document.getElementById('create-preset').value;
    const input_source = document.getElementById('create-input')?.value?.trim() || '';

    if (['file', 'file_loop'].includes(preset) && !input_source) {
        toast('Input source (file path) is required for this preset', 'error');
        btn.disabled = false; btn.textContent = '🚀 Create & Go Live';
        return;
    }

    const body = {
        token_id: _currentCredId,
        title: title,
        description: document.getElementById('create-desc').value.trim(),
        privacy: document.getElementById('create-privacy').value,
        resolution: document.getElementById('create-resolution').value,
        frame_rate: document.getElementById('create-fps').value,
        input_source: input_source,
        preset: preset,
        ffmpeg_args: {
            bitrate: document.getElementById('create-bitrate').value,
            bufsize: document.getElementById('create-bufsize').value,
        },
    };

    if (preset === 'custom') {
        body.ffmpeg_args.custom_cmd = document.getElementById('create-custom-cmd')?.value || '';
    }

    const result = await apiPost('/auto-live', body);

    if (result?.status === 'success') {
        toast('🔴 LIVE! ' + title, 'success');
        switchPanel('active', document.querySelector('[data-panel=active]'));
    } else if (result?.status === 'partial') {
        toast('⚠️ Broadcast created but FFmpeg failed: ' + (result.ffmpeg_error || ''), 'error');
        switchPanel('active', document.querySelector('[data-panel=active]'));
    } else {
        toast(result?.message || result?.detail || 'Failed', 'error');
    }

    btn.disabled = false;
    btn.textContent = '🚀 Create & Go Live';
}

async function createOnly() {
    const title = document.getElementById('create-title').value.trim();
    if (!title) { toast('Title is required', 'error'); return; }

    const body = {
        token_id: _currentCredId,
        title: title,
        description: document.getElementById('create-desc').value.trim(),
        privacy: document.getElementById('create-privacy').value,
        resolution: document.getElementById('create-resolution').value,
        frame_rate: document.getElementById('create-fps').value,
    };

    const result = await apiPost('/broadcasts', body);

    if (result?.status === 'success') {
        toast('✅ Broadcast created! Copy the stream key.', 'success');
        showStreamKey(result.broadcast.broadcast_id);
    } else {
        toast(result?.message || result?.detail || 'Failed', 'error');
    }
}

// ═══ All Broadcasts ═══
async function loadBroadcasts() {
    const container = document.getElementById('broadcast-list');
    const data = await apiGet('/broadcasts');
    const broadcasts = data?.broadcasts || [];

    if (broadcasts.length === 0) {
        container.innerHTML = '<div class="ls-empty"><div class="ls-empty-icon">📋</div><p>No broadcasts yet.</p></div>';
        return;
    }

    container.innerHTML = broadcasts.map(b => {
        const ytUrl = `https://youtu.be/${b.broadcast_id}`;
        return `
        <div class="ls-broadcast-row">
            <div class="ls-broadcast-info">
                <h4>${esc(b.title || 'Untitled')}</h4>
                <p>${esc(b.resolution || '')} · ${esc(b.privacy || '')} · ${esc((b.created_at || '').slice(0, 16))}</p>
            </div>
            <a href="${ytUrl}" target="_blank" class="ls-yt-link">▶ youtu.be/${esc(b.broadcast_id)}</a>
            <span class="ls-tag ${b.status === 'streaming' ? 'streaming' : (b.status === 'ready' ? 'ready' : 'stopped')}">${esc(b.status || 'unknown')}</span>
            <button class="ls-btn ls-btn-sm" onclick="showStreamKey('${esc(b.broadcast_id)}')">🔑</button>
            <button class="ls-btn ls-btn-sm ls-btn-danger" onclick="deleteBroadcast('${esc(b.broadcast_id)}')">🗑</button>
        </div>`;
    }).join('');
}

async function deleteBroadcast(id) {
    if (!confirm('Delete this broadcast?')) return;
    await apiDelete('/broadcasts/' + id + '?token_id=' + encodeURIComponent(_currentCredId));
    toast('Broadcast deleted', 'success');
    loadActiveStreams();
    loadBroadcasts();
}

// ═══ FFmpeg Sessions ═══
async function loadFFmpegSessions() {
    const container = document.getElementById('ffmpeg-sessions');
    const data = await apiGet('/ffmpeg/sessions');
    const sessions = data?.sessions || [];

    if (sessions.length === 0) {
        container.innerHTML = '<div class="ls-empty"><div class="ls-empty-icon">⚡</div><p>No FFmpeg sessions.</p></div>';
        return;
    }

    container.innerHTML = sessions.map(s => `
        <div class="ls-ffmpeg-row">
            ${s.status === 'running' ? '<span class="ls-live-dot"></span>' : '<span style="width:8px;height:8px;border-radius:50%;background:var(--text-muted)"></span>'}
            <div class="ls-ffmpeg-info">
                <h4>${esc(s.session_id)} <span class="ls-tag ${s.status === 'running' ? 'green' : 'stopped'}">${esc(s.status)}</span></h4>
                <p>PID: ${s.pid || '—'} · Preset: ${esc(s.preset || '—')} · Started: ${esc((s.started_at || '').slice(0, 19))}</p>
            </div>
            <button class="ls-btn ls-btn-sm" onclick="showFFmpegLog('${esc(s.session_id)}')">📄 Log</button>
            ${s.status === 'running' ? `<button class="ls-btn ls-btn-sm ls-btn-danger" onclick="stopFFmpegSession('${esc(s.session_id)}')">⏹ Stop</button>` : ''}
        </div>
    `).join('');
}

function showFFmpegLog(sessionId) {
    _currentLogSession = sessionId;
    refreshFFmpegLog();
    openModal('modal-ffmpeg-log');
}

async function refreshFFmpegLog() {
    const data = await apiGet('/ffmpeg/log/' + _currentLogSession + '?tail=100');
    document.getElementById('ffmpeg-log-content').textContent = data?.log || 'No log available.';
}

async function stopFFmpegSession(sessionId) {
    const result = await apiPost('/ffmpeg/stop/' + sessionId, {});
    if (result?.status === 'success') {
        toast('FFmpeg stopped', 'success');
        loadFFmpegSessions();
        loadActiveStreams();
    } else {
        toast(result?.message || 'Failed', 'error');
    }
}

// ═══ Schedules ═══
async function loadSchedules() {
    const container = document.getElementById('schedule-list');
    const data = await apiGet('/schedules');
    const schedules = data?.schedules || [];

    if (schedules.length === 0) {
        container.innerHTML = '<div class="ls-empty"><div class="ls-empty-icon">📅</div><p>No scheduled streams.</p></div>';
        return;
    }

    container.innerHTML = schedules.map(s => `
        <div class="ls-broadcast-row">
            <div class="ls-broadcast-info">
                <h4>📅 ${esc(s.title || 'Untitled')}</h4>
                <p>Run at: ${esc(s.run_at || '')} · Preset: ${esc(s.preset || '')} · ${esc(s.privacy || '')}</p>
            </div>
            <span class="ls-tag ${s.status === 'pending' ? 'ready' : (s.status === 'executed' ? 'green' : 'stopped')}">${esc(s.status || 'pending')}</span>
            <button class="ls-btn ls-btn-sm ls-btn-danger" onclick="removeSchedule('${esc(s.id)}')">🗑</button>
        </div>
    `).join('');
}

function openScheduleModal() {
    document.getElementById('sched-title').value = '';
    document.getElementById('sched-desc').value = '';
    document.getElementById('sched-input').value = '';
    openModal('modal-schedule');
}

async function addSchedule() {
    const title = document.getElementById('sched-title').value.trim();
    const runAt = document.getElementById('sched-run-at').value;
    if (!title || !runAt) { toast('Title and run time are required', 'error'); return; }

    const result = await apiPost('/schedules', {
        token_id: _currentCredId,
        title: title,
        description: document.getElementById('sched-desc').value.trim(),
        run_at: new Date(runAt).toISOString(),
        privacy: document.getElementById('sched-privacy').value,
        preset: document.getElementById('sched-preset').value,
        input_source: document.getElementById('sched-input').value.trim(),
    });

    if (result?.status === 'success') {
        toast('📅 Schedule added!', 'success');
        closeModal('modal-schedule');
        loadSchedules();
    } else {
        toast(result?.message || 'Failed', 'error');
    }
}

async function removeSchedule(id) {
    if (!confirm('Remove this schedule?')) return;
    await apiDelete('/schedules/' + id);
    toast('Schedule removed', 'success');
    loadSchedules();
}

// ═══ Settings ═══
async function loadSettings() {
    // FFmpeg info
    const ffmpegData = await apiGet('/ffmpeg-check');
    const ffmpegInfo = document.getElementById('ffmpeg-info');
    if (ffmpegData?.available) {
        ffmpegInfo.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
                <span class="ls-tag green">✅ Available</span>
                <span style="font-size:0.82rem;color:var(--text-muted)">${esc(ffmpegData.path || '')}</span>
            </div>
            <pre style="background:var(--bg);padding:10px;border-radius:8px;font-size:0.8rem;color:var(--text-muted);border:1px solid var(--border)">${esc(ffmpegData.version || '')}</pre>`;
    } else {
        ffmpegInfo.innerHTML = '<span class="ls-tag stopped">❌ Not Found</span><p style="margin-top:8px;color:var(--text-muted)">Install FFmpeg and add it to your system PATH.</p>';
    }

    // Presets
    const presetsData = await apiGet('/presets');
    const presetsInfo = document.getElementById('presets-info');
    const presets = presetsData?.presets || {};
    presetsInfo.innerHTML = Object.entries(presets).map(([k, v]) => `
        <div style="padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:8px;margin-bottom:8px">
            <div style="font-weight:600;margin-bottom:4px;color:var(--text)">${esc(v.label || k)}</div>
            <div style="font-size:0.82rem;color:var(--text-muted)">${esc(v.description || '')}</div>
        </div>
    `).join('');
}

// ═══ Refresh All ═══
function refreshAll() {
    loadActiveStreams();
    loadFFmpegSessions();
}

// ═══ Auto-refresh active streams ═══
let _refreshInterval = null;
function startAutoRefresh() {
    _refreshInterval = setInterval(() => {
        const panel = document.querySelector('#panel-active.active');
        if (panel) loadActiveStreams();
    }, 10000);
}

// ═══ Init ═══
document.addEventListener('DOMContentLoaded', async () => {
    await loadCredentials();
    await checkFFmpeg();
    loadActiveStreams();
    startAutoRefresh();
});
