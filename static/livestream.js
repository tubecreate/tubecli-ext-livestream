/**
 * Livestream Extension — Client-side Logic
 * YouTube Livestream Manager with FFmpeg RTMP push
 */
const API = '/api/v1/livestream';
let _currentCredId = '';
let _currentLogSession = '';
let _advancedLayers = [];
let _activeWindows = [];

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
    const advancedGroup = document.getElementById('advanced-scene-group');

    inputGroup.style.display = 'none';
    optionsRow.style.display = 'none';
    customGroup.style.display = 'none';
    if(advancedGroup) advancedGroup.style.display = 'none';

    if (preset === 'custom') {
        customGroup.style.display = 'block';
    } else if (preset === 'advanced_scene') {
        optionsRow.style.display = 'flex';
        if(advancedGroup) advancedGroup.style.display = 'block';
        fetchActiveWindows();
        if (_advancedLayers.length === 0) addAdvancedLayer();
    } else if (preset === 'camera_win' || preset === 'screen_win' || preset === 'screen_win_dd' || preset === 'screen_linux') {
        optionsRow.style.display = 'flex';
    } else {
        inputGroup.style.display = 'block';
        optionsRow.style.display = 'flex';
    }
}

// ─── Advanced Scene Logic ───
let _windowsData = []; // {title, x, y, w, h}[]

async function fetchActiveWindows() {
    const data = await apiGet('/windows');
    if (data?.status === 'success') {
        _windowsData = data.windows || [];
        _activeWindows = _windowsData.map(w => w.title || w);
        renderAdvancedLayers();
    }
}

function addAdvancedLayer() {
    _advancedLayers.push({
        type: 'window',     // 'fullscreen', 'window', or 'file'
        source: '',
        x: 0, y: 0,
        w: 1920, h: 1080,
        sx: 0, sy: 0,       // source crop (fullscreen only)
    });
    renderAdvancedLayers();
}

function removeAdvancedLayer(index) {
    _advancedLayers.splice(index, 1);
    renderAdvancedLayers();
}

function updateAdvancedLayer(index, field, value) {
    if (!_advancedLayers[index]) return;
    const numFields = ['x', 'y', 'w', 'h', 'sx', 'sy'];
    _advancedLayers[index][field] = numFields.includes(field) ? Number(value) : value;
    renderVisualCanvas();
}

function onWindowSelected(layerIndex, title) {
    const layer = _advancedLayers[layerIndex];
    if (!layer) return;
    layer.source = title;
    const winData = _windowsData.find(w => w.title === title);
    if (winData) {
        layer.w = winData.w;
        layer.h = winData.h;
        if (layer.type === 'fullscreen') {
            layer.sx = winData.x;
            layer.sy = winData.y;
        }
    }
    renderAdvancedLayers();
}

function renderAdvancedLayers() {
    renderVisualCanvas();
    const container = document.getElementById('layers-container');
    if (!container) return;

    container.innerHTML = _advancedLayers.map((layer, i) => {
        const t = layer.type;
        const icon = t === 'fullscreen' ? '🖥️' : t === 'window' ? '🪟' : '📁';

        // Source input varies by type
        let sourceHtml = '';
        if (t === 'window' || t === 'fullscreen') {
            const options = _windowsData.map(w => {
                const title = w.title || w;
                return `<option value="${esc(title)}" ${title === layer.source ? 'selected' : ''}>${esc(title)} (${w.w}\u00d7${w.h})</option>`;
            }).join('');
            const placeholder = t === 'window' ? '-- Ch\u1ecdn c\u1eeda s\u1ed5 --' : '-- Ch\u1ecdn v\u00f9ng (optional) --';
            sourceHtml = `
                <select class="ls-layer-input" style="flex:2;min-width:180px;" onchange="onWindowSelected(${i}, this.value)">
                    <option value="">${placeholder}</option>
                    ${options}
                </select>`;
        } else {
            sourceHtml = `<input type="text" class="ls-layer-input" style="flex:2;min-width:180px;" placeholder="C:\\\\video.mp4 or image.png" value="${esc(layer.source)}" oninput="updateAdvancedLayer(${i}, 'source', this.value)">`;
        }

        // Crop position (fullscreen only)
        const cropHtml = t === 'fullscreen' ? `
                <div style="display:flex;gap:4px;align-items:center;margin-top:4px;">
                    <span style="font-size:0.75rem;color:var(--text-muted);white-space:nowrap;">\ud83d\udccd Crop:</span>
                    SX: <input type="number" class="ls-layer-input ls-num-input" value="${layer.sx || 0}" oninput="updateAdvancedLayer(${i}, 'sx', this.value)">
                    SY: <input type="number" class="ls-layer-input ls-num-input" value="${layer.sy || 0}" oninput="updateAdvancedLayer(${i}, 'sy', this.value)">
                </div>` : '';

        // Hint text
        let hintHtml = '';
        if (t === 'window') hintHtml = `<div style="font-size:0.72rem;color:#f5a623;margin-top:4px;opacity:0.8;">\u26a0\ufe0f GPU apps (Chrome, games) c\u00f3 th\u1ec3 b\u1ecb \u0111en \u2192 d\u00f9ng Full Screen ho\u1eb7c t\u1eaft HW Accel.</div>`;
        else if (t === 'fullscreen') hintHtml = `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;">\u2705 GPU safe. V\u1ecb tr\u00ed c\u1ed1 \u0111\u1ecbnh \u2014 ko \u0111i theo c\u1eeda s\u1ed5 khi di chuy\u1ec3n.</div>`;

        return `
        <div class="ls-layer-row">
            <div class="ls-layer-header">
                <span class="ls-tag">${icon} Layer ${i+1}</span>
                <div style="display:flex;gap:4px;">
                    ${i > 0 ? `<button class="ls-btn ls-btn-sm" onclick="moveLayer(${i}, -1)" title="Move up">\u2191</button>` : ''}
                    ${i < _advancedLayers.length - 1 ? `<button class="ls-btn ls-btn-sm" onclick="moveLayer(${i}, 1)" title="Move down">\u2193</button>` : ''}
                    <button class="ls-btn ls-btn-sm ls-btn-danger" onclick="removeAdvancedLayer(${i})">\u2715</button>
                </div>
            </div>
            <div class="ls-layer-grid">
                <select class="ls-layer-input" onchange="updateAdvancedLayer(${i}, 'type', this.value); renderAdvancedLayers()">
                    <option value="fullscreen" ${t === 'fullscreen' ? 'selected' : ''}>\ud83d\udda5\ufe0f Full Screen (GPU safe)</option>
                    <option value="window" ${t === 'window' ? 'selected' : ''}>\ud83e\ude9f Window (follows)</option>
                    <option value="file" ${t === 'file' ? 'selected' : ''}>\ud83d\udcc1 File / Image</option>
                </select>
                ${sourceHtml}
                <div style="display:flex;gap:4px;align-items:center;margin-top:4px;">
                    <span style="font-size:0.75rem;color:var(--text-muted);white-space:nowrap;">\ud83c\udfaf Canvas:</span>
                    X: <input type="number" id="layer-${i}-x" class="ls-layer-input ls-num-input" value="${layer.x}" oninput="updateAdvancedLayer(${i}, 'x', this.value)">
                    Y: <input type="number" id="layer-${i}-y" class="ls-layer-input ls-num-input" value="${layer.y}" oninput="updateAdvancedLayer(${i}, 'y', this.value)">
                </div>
                <div style="display:flex;gap:4px;align-items:center;">
                    W: <input type="number" id="layer-${i}-w" class="ls-layer-input ls-num-input" value="${layer.w}" oninput="updateAdvancedLayer(${i}, 'w', this.value)">
                    H: <input type="number" id="layer-${i}-h" class="ls-layer-input ls-num-input" value="${layer.h}" oninput="updateAdvancedLayer(${i}, 'h', this.value)">
                </div>
                ${cropHtml}
                ${hintHtml}
            </div>
        </div>`;
    }).join('');

    container.innerHTML += `
        <button class="ls-btn ls-btn-sm ls-btn-outline" onclick="fetchActiveWindows()" style="margin-top:8px;width:100%;">
            \u21bb Refresh Windows
        </button>`;
}

// Move layer up or down (changes z-order)
function moveLayer(index, direction) {
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= _advancedLayers.length) return;
    const tmp = _advancedLayers[index];
    _advancedLayers[index] = _advancedLayers[newIndex];
    _advancedLayers[newIndex] = tmp;
    renderAdvancedLayers();
}

// ─── Visual Canvas ───
let _activeBoxId = -1;

function renderVisualCanvas() {
    const canvas = document.getElementById('ls-visual-canvas');
    if (!canvas) return;
    
    const cw = Number(document.getElementById('canvas-w')?.value) || 1920;
    const ch = Number(document.getElementById('canvas-h')?.value) || 1080;
    
    canvas.style.aspectRatio = `${cw}/${ch}`;
    canvas.innerHTML = '';
    
    _advancedLayers.forEach((layer, i) => {
        const box = document.createElement('div');
        box.className = 'ls-visual-box' + (_activeBoxId === i ? ' active' : '');
        box.dataset.index = i;
        
        box.style.left = `${(layer.x / cw) * 100}%`;
        box.style.top = `${(layer.y / ch) * 100}%`;
        box.style.width = `${(layer.w / cw) * 100}%`;
        box.style.height = `${(layer.h / ch) * 100}%`;
        
        const label = layer.type === 'window'
            ? (layer.source ? layer.source.substring(0, 25) : `Layer ${i+1}: Window`)
            : `Layer ${i+1}: File`;
        box.innerText = label;
        
        const handle = document.createElement('div');
        handle.className = 'ls-visual-handle';
        box.appendChild(handle);
        
        canvas.appendChild(box);
        
        _attachDrag(box, handle, i, cw, ch, canvas);
    });
}

function _attachDrag(box, handle, idx, cw, ch, canvas) {
    let mode = null; // 'drag' | 'resize'
    let sx, sy, ox, oy, ow, oh;

    function onDown(e, m) {
        e.preventDefault();
        e.stopPropagation();
        mode = m;
        sx = e.clientX;
        sy = e.clientY;
        const layer = _advancedLayers[idx];
        ox = layer.x; oy = layer.y; ow = layer.w; oh = layer.h;
        
        // Mark active visually without DOM rebuild
        _activeBoxId = idx;
        canvas.querySelectorAll('.ls-visual-box').forEach(b => b.classList.remove('active'));
        box.classList.add('active');
        
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }

    box.addEventListener('mousedown', (e) => {
        if (e.target === handle) return;
        onDown(e, 'drag');
    });
    handle.addEventListener('mousedown', (e) => onDown(e, 'resize'));

    function onMove(e) {
        const rect = canvas.getBoundingClientRect();
        const scaleX = cw / rect.width;
        const scaleY = ch / rect.height;
        const dx = (e.clientX - sx) * scaleX;
        const dy = (e.clientY - sy) * scaleY;
        const layer = _advancedLayers[idx];

        if (mode === 'drag') {
            layer.x = Math.round(ox + dx);
            layer.y = Math.round(oy + dy);
            box.style.left = `${(layer.x / cw) * 100}%`;
            box.style.top  = `${(layer.y / ch) * 100}%`;
            const ix = document.getElementById(`layer-${idx}-x`);
            const iy = document.getElementById(`layer-${idx}-y`);
            if (ix) ix.value = layer.x;
            if (iy) iy.value = layer.y;
        } else {
            layer.w = Math.max(20, Math.round(ow + dx));
            layer.h = Math.max(20, Math.round(oh + dy));
            box.style.width  = `${(layer.w / cw) * 100}%`;
            box.style.height = `${(layer.h / ch) * 100}%`;
            const iw = document.getElementById(`layer-${idx}-w`);
            const ih = document.getElementById(`layer-${idx}-h`);
            if (iw) iw.value = layer.w;
            if (ih) ih.value = layer.h;
        }
    }

    function onUp() {
        mode = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
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
    } else if (preset === 'advanced_scene') {
        body.ffmpeg_args.canvas_w = document.getElementById('canvas-w')?.value || 1920;
        body.ffmpeg_args.canvas_h = document.getElementById('canvas-h')?.value || 1080;
        body.ffmpeg_args.layers = _advancedLayers;

        if (_advancedLayers.length === 0) {
            toast('Add at least one layer to stream', 'error');
            btn.disabled = false; btn.textContent = '🚀 Create & Go Live';
            return;
        }
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
