/**
 * 幕牆圖紙結構分析系統 — 前端邏輯
 * Tab 1: 圖紙分析 (上傳 + 規則引擎 + AI 講解)
 * Tab 2: DWG 資料庫 (多資料庫、資料夾初始化、位置圖↔加工圖對照)
 */

const API_BASE = '/api';

// ===================================================================
// Tab 切換
// ===================================================================
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        if (tab.dataset.tab === 'database') initDatabaseTab();
    });
});

// ===================================================================
// Tab 1: 圖紙分析
// ===================================================================
const uploadZone = document.getElementById('uploadZone');
const fileInput = document.getElementById('fileInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const useAIToggle = document.getElementById('useAI');
const uploadStatus = document.getElementById('uploadStatus');
const resultsSection = document.getElementById('resultsSection');
let selectedFile = null;

uploadZone.addEventListener('click', () => fileInput.click());
uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('dragover'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
uploadZone.addEventListener('drop', (e) => {
    e.preventDefault(); uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) handleFileSelect(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files.length > 0) handleFileSelect(fileInput.files[0]); });

function handleFileSelect(file) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp'].includes(ext)) {
        showStatus(`不支援的格式: ${ext}`, 'error'); return;
    }
    selectedFile = file;
    uploadZone.querySelector('p:first-of-type').textContent = `已選擇: ${file.name}`;
    analyzeBtn.disabled = false;
    uploadStatus.classList.add('hidden');
}

analyzeBtn.addEventListener('click', async () => {
    if (!selectedFile) return;
    const formData = new FormData(); formData.append('file', selectedFile);
    const endpoint = useAIToggle.checked ? `${API_BASE}/analyze-and-explain?use_ai=true` : `${API_BASE}/analyze`;
    showStatus('分析中...', 'loading'); resultsSection.classList.add('hidden');
    try {
        const resp = await fetch(endpoint, { method: 'POST', body: formData });
        if (!resp.ok) { const err = await resp.json(); throw new Error(err.error || `HTTP ${resp.status}`); }
        showStatus('分析完成', 'success');
        renderResults(await resp.json());
    } catch (err) { showStatus(`錯誤: ${err.message}`, 'error'); }
});

function showStatus(msg, type) {
    uploadStatus.textContent = msg; uploadStatus.className = `status ${type}`; uploadStatus.classList.remove('hidden');
}

function renderResults(data) {
    const a = data.analysis || data; resultsSection.classList.remove('hidden');
    renderDrawingType(a); renderSummary(a.summary); renderGrid(a.grid_system);
    renderPanelLayout(a.panel_layout); renderAnnotations(a.annotations); renderSectionMarks(a.section_marks);
    if (data.ai_explanation) { const c = document.getElementById('aiCard'); c.classList.remove('hidden'); document.getElementById('aiContent').textContent = data.ai_explanation; }
    else document.getElementById('aiCard').classList.add('hidden');
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function renderDrawingType(a) {
    const dt = a.drawing_type || 'unknown', conf = a.drawing_type_confidence || 0;
    const names = { position: '位置圖 (Setting-out)', fabrication: '加工圖 (Fabrication)', detail: '大樣圖 (Detail)', assembly: '組裝圖 (Assembly)' };
    document.getElementById('drawingTypeContent').innerHTML = `<span class="type-badge ${dt}">${names[dt] || dt}</span> <span style="margin-left:12px;font-size:0.85rem;color:var(--text-secondary)">信心度: ${(conf*100).toFixed(0)}%</span>`;
}
function renderSummary(s) {
    if (!s) return;
    document.getElementById('summaryText').textContent = s.text || JSON.stringify(s, null, 2);
    document.getElementById('summaryText').insertAdjacentHTML('beforebegin',
        `<div class="stats-grid"><div class="stat-item"><div class="stat-value">${s.axes||0}</div><div class="stat-label">軸線總數</div></div><div class="stat-item"><div class="stat-value">${s.panels||0}</div><div class="stat-label">面板總數</div></div><div class="stat-item"><div class="stat-value">${s.dimensions||0}</div><div class="stat-label">尺寸標註</div></div><div class="stat-item"><div class="stat-value">${s.fab_marks||0}</div><div class="stat-label">加工標記</div></div></div>`);
}
function renderGrid(g) {
    if (!g || g.total_axes === 0) { document.getElementById('gridContent').innerHTML = '<p style="color:var(--text-secondary)">未偵測到軸網系統</p>'; return; }
    let hR = '', vR = '';
    (g.horizontal_axes||[]).forEach(a => { hR += `<tr><td>${a.label}</td><td>${a.position_px} px</td><td>${a.length_px} px</td><td>${(a.confidence*100).toFixed(0)}%</td></tr>`; });
    (g.vertical_axes||[]).forEach(a => { vR += `<tr><td>${a.label}</td><td>${a.position_px} px</td><td>${a.length_px} px</td><td>${(a.confidence*100).toFixed(0)}%</td></tr>`; });
    document.getElementById('gridContent').innerHTML = `<div class="stats-grid"><div class="stat-item"><div class="stat-value">${g.total_axes}</div><div class="stat-label">軸線總數</div></div><div class="stat-item"><div class="stat-value">${g.bay_count}</div><div class="stat-label">跨數</div></div><div class="stat-item"><div class="stat-value">${g.intersection_count}</div><div class="stat-label">交點數</div></div></div><div style="display:flex;gap:24px;margin-top:16px;flex-wrap:wrap;"><div style="flex:1;min-width:200px;"><h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">水平軸線 (由下至上)</h4><table class="axis-table"><thead><tr><th>軸號</th><th>位置</th><th>長度</th><th>信心</th></tr></thead><tbody>${hR||'<tr><td colspan="4">無</td></tr>'}</tbody></table></div><div style="flex:1;min-width:200px;"><h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">垂直軸線 (由左至右)</h4><table class="axis-table"><thead><tr><th>軸號</th><th>位置</th><th>長度</th><th>信心</th></tr></thead><tbody>${vR||'<tr><td colspan="4">無</td></tr>'}</tbody></table></div></div>`;
}
function renderPanelLayout(layout) {
    if (!layout || layout.total_panels === 0) { document.getElementById('panelContent').innerHTML = '<p style="color:var(--text-secondary)">未偵測到面板</p>'; return; }
    const names = { vision: '視野玻璃', spandrel: '背襯面板', operable: '可開啟窗', louver: '百葉', structural: '結構面板', other: '其他' };
    let bars = ''; const types = layout.type_summary || {}, total = layout.total_panels || 1;
    for (const [t, c] of Object.entries(types)) { const pct = ((c/total)*100).toFixed(0); bars += `<div class="type-bar-wrap"><div class="type-bar-label"><span>${names[t]||t}</span><span>${c} 個 (${pct}%)</span></div><div class="type-bar-track"><div class="type-bar-fill" style="width:${pct}%"></div></div></div>`; }
    let aspects = ''; const aps = layout.aspect_summary || {};
    for (const [g, c] of Object.entries(aps)) { if (c > 0) aspects += `<span class="fab-mark-tag">${g}: ${c} 個</span>`; }
    document.getElementById('panelContent').innerHTML = `<div class="stat-item" style="margin-bottom:16px;"><div class="stat-value">${layout.total_panels}</div><div class="stat-label">面板總數</div></div><h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:8px;">類型分佈</h4>${bars||'<p style="color:var(--text-secondary)">無類型資料</p>'}<h4 style="font-size:0.85rem;color:var(--text-secondary);margin:12px 0 6px;">長寬比分佈</h4><div>${aspects||'無資料'}</div>`;
}
function renderAnnotations(ann) {
    if (!ann) { document.getElementById('annotationContent').innerHTML = '<p style="color:var(--text-secondary)">無標註資料</p>'; return; }
    const fNames = { weld: '焊接', cut: '切割', drill: '鑽孔', notch: '開槽', fold: '折彎', assembly: '組裝' };
    let tags = ''; (ann.fab_marks||[]).forEach(m => { tags += `<span class="fab-mark-tag">${fNames[m.type]||m.type}: (${m.position?.[0]||'-'}, ${m.position?.[1]||'-'})</span>`; });
    let dRows = ''; (ann.dimensions||[]).forEach(d => { dRows += `<tr><td>${d.value}</td><td>${d.orientation||'-'}</td><td>(${d.position?.[0]||'-'}, ${d.position?.[1]||'-'})</td><td>${d.type||'-'}</td></tr>`; });
    const tb = ann.title_block || {};
    document.getElementById('annotationContent').innerHTML = `<div class="stats-grid" style="margin-bottom:16px;"><div class="stat-item"><div class="stat-value">${ann.dimension_count||0}</div><div class="stat-label">尺寸標註</div></div><div class="stat-item"><div class="stat-value">${ann.text_region_count||0}</div><div class="stat-label">文字區域</div></div><div class="stat-item"><div class="stat-value">${ann.fab_mark_count||0}</div><div class="stat-label">加工標記</div></div><div class="stat-item"><div class="stat-value">${tb.detected?'有':'無'}</div><div class="stat-label">圖框資訊</div></div></div><h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">加工標記</h4><div>${tags||'<span style="color:var(--text-secondary)">未偵測到加工標記</span>'}</div><h4 style="font-size:0.85rem;color:var(--text-secondary);margin:12px 0 6px;">尺寸標註</h4><table class="axis-table"><thead><tr><th>數值</th><th>方向</th><th>位置</th><th>類型</th></tr></thead><tbody>${dRows||'<tr><td colspan="4">無尺寸標註</td></tr>'}</tbody></table>`;
}
function renderSectionMarks(marks) {
    const card = document.getElementById('sectionMarkCard'), content = document.getElementById('sectionMarkContent');
    if (!marks || marks.total_marks === 0) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    const s = marks.summary || {};
    content.innerHTML = `<div class="stats-grid" style="margin-bottom:16px;"><div class="stat-item"><div class="stat-value">${marks.total_marks||0}</div><div class="stat-label">總標記數</div></div><div class="stat-item"><div class="stat-value">${s.drawing_numbers||0}</div><div class="stat-label">圖紙編號</div></div><div class="stat-item"><div class="stat-value">${s.part_numbers||0}</div><div class="stat-label">零件編號</div></div><div class="stat-item"><div class="stat-value">${s.section_refs||0}</div><div class="stat-label">剖面參照</div></div></div>${(s.drawing_number_list||[]).length?`<h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">圖紙編號</h4><div>${s.drawing_number_list.map(d=>`<span class="fab-mark-tag" style="background:rgba(79,143,255,0.15);border-color:var(--accent);">${d}</span>`).join(' ')}</div>`:''}`;
}

// ===================================================================
// Tab 2: DWG 資料庫
// ===================================================================
let dbLoaded = false;
let currentDb = '';

function dbParam(prefix) {
    prefix = prefix || '&';
    return currentDb ? `${prefix}db=${encodeURIComponent(currentDb)}` : '';
}

async function initDatabaseTab() {
    if (dbLoaded) return;
    dbLoaded = true;
    await refreshProjectList();

    document.getElementById('pickFolderBtn').addEventListener('click', async () => {
        const btn = document.getElementById('pickFolderBtn');
        btn.disabled = true; btn.textContent = '選擇中...';
        try {
            const r = await fetch(`${API_BASE}/db/pick-folder`);
            const data = await r.json();
            if (data.folder_path) {
                document.getElementById('initFolderInput').value = data.folder_path;
                document.getElementById('initFolderBtn').disabled = false;
            } else {
                showInitStatus(data.error || '未選擇', 'error');
            }
        } catch (err) { showInitStatus('無法開啟選擇器: ' + err.message, 'error'); }
        btn.disabled = false; btn.textContent = '📁 選擇資料夾';
    });

    document.getElementById('initFolderBtn').addEventListener('click', async () => {
        const folderPath = document.getElementById('initFolderInput').value.trim();
        if (!folderPath) return;
        const btn = document.getElementById('initFolderBtn');
        btn.disabled = true; btn.textContent = '初始化中...';
        showInitStatus('正在讀取 DWG 檔案並建立資料庫...', 'loading');
        try {
            const r = await fetch(`${API_BASE}/db/init?folder_path=${encodeURIComponent(folderPath)}`, { method: 'POST' });
            const data = await r.json();
            if (data.status === 'running') {
                for (let i = 0; i < 120; i++) {
                    await new Promise(resolve => setTimeout(resolve, 1000));
                    const sr = await fetch(`${API_BASE}/db/init-status?folder_path=${encodeURIComponent(folderPath)}`);
                    const sd = await sr.json();
                    if (sd.status === 'done') {
                        showInitStatus(`✅ 完成！${sd.result.fab_count} 張加工圖, ${sd.result.layout_count} 張位置圖`, 'success');
                        await refreshProjectList();
                        document.getElementById('dbSelector').value = data.db_path;
                        await switchDatabase(data.db_path);
                        break;
                    } else if (sd.status === 'error') {
                        showInitStatus(`❌ ${sd.error}`, 'error'); break;
                    }
                }
            }
        } catch (err) { showInitStatus('❌ ' + err.message, 'error'); }
        btn.disabled = false; btn.textContent = '初始化';
    });

    document.getElementById('dbSelector').addEventListener('change', async () => {
        await switchDatabase(document.getElementById('dbSelector').value);
    });

    document.getElementById('reverseLookupBtn').addEventListener('click', reverseLookup);
    document.getElementById('reverseLookupInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') reverseLookup(); });
    document.getElementById('dbSearchBtn').addEventListener('click', () => searchDrawings());
    document.getElementById('dbListAllBtn').addEventListener('click', () => searchDrawings(true));
    document.getElementById('dbSearch').addEventListener('keydown', (e) => { if (e.key === 'Enter') searchDrawings(); });
    document.getElementById('detailClose').addEventListener('click', () => {
        document.getElementById('detailCard').classList.add('hidden');
    });
}

function showInitStatus(msg, type) {
    const div = document.getElementById('initStatus');
    div.classList.remove('hidden');
    div.innerHTML = `<span class="status ${type}">${msg}</span>`;
}

async function refreshProjectList() {
    try {
        const r = await fetch(`${API_BASE}/db/projects`);
        const data = await r.json();
        const sel = document.getElementById('dbSelector');
        const currentVal = sel.value;
        sel.innerHTML = data.projects.map(p =>
            `<option value="${p.db_path}">${p.project_code} — ${p.fab_count} 張加工圖, ${p.layout_count} 張位置圖</option>`
        ).join('');
        if (data.projects.length === 0) {
            sel.innerHTML = '<option value="">無可用資料庫，請先初始化</option>';
            return;
        }
        if (currentVal && data.projects.some(p => p.db_path === currentVal)) {
            sel.value = currentVal;
        } else {
            sel.value = data.projects[0].db_path;
            await switchDatabase(data.projects[0].db_path);
        }
    } catch (err) {
        document.getElementById('dbSelector').innerHTML = '<option value="">載入失敗</option>';
    }
}

async function switchDatabase(dbPath) {
    currentDb = dbPath;
    document.getElementById('reverseLookupResult').classList.add('hidden');
    document.getElementById('detailCard').classList.add('hidden');
    try {
        const r = await fetch(`${API_BASE}/db/status${dbParam('?')}`);
        const status = await r.json();
        if (!status.exists) return;
        document.getElementById('dbStatusCard').classList.remove('hidden');
        document.getElementById('dbStatusContent').innerHTML = `
            <div class="stats-grid">
                <div class="stat-item"><div class="stat-value">${status.project_code||'-'}</div><div class="stat-label">專案編號</div></div>
                <div class="stat-item"><div class="stat-value">${status.layout_count}</div><div class="stat-label">位置圖</div></div>
                <div class="stat-item"><div class="stat-value">${status.fab_count}</div><div class="stat-label">加工圖</div></div>
                <div class="stat-item"><div class="stat-value">${status.text_count}</div><div class="stat-label">文字實體</div></div>
            </div>
        `;
        loadLayout();
        loadFabToLayout();
        checkMissing();
    } catch (err) { console.error('switchDatabase:', err); }
}

async function loadFabToLayout() {
    try {
        const r = await fetch(`${API_BASE}/db/fab-to-layout${dbParam('?')}`);
        if (!r.ok) return;
        const data = await r.json();
        const fabs = data.fabrication_drawings;
        if (fabs.length === 0) return;

        document.getElementById('fabToLayoutCard').classList.remove('hidden');
        document.getElementById('fabToLayoutSummary').innerHTML = `
            共 <strong>${data.count}</strong> 張加工圖
            | 無對應位置圖: <strong style="color:var(--orange);">${fabs.filter(f => f.layout_count === 0).length}</strong> 張
        `;

        const tbody = document.querySelector('#fabToLayoutTable tbody');
        tbody.innerHTML = fabs.map(f => {
            const layouts = f.layout_drawings || [];
            const layoutStr = layouts.length > 0
                ? layouts.map(l => `<span class="dn-link layout-link" data-dn="${l.drawing_number}" title="${l.filename}">${l.drawing_number}</span>`).join(', ')
                : '<span style="color:var(--orange);">⚠ 無</span>';
            return `
                <tr>
                    <td><span class="dn-link" data-dn="${f.drawing_number}">${f.drawing_number}</span></td>
                    <td>${f.filename}</td>
                    <td>${f.width_mm ? f.width_mm + ' × ' + f.height_mm : '-'}</td>
                    <td>${f.quantity ?? 1}</td>
                    <td>${f.color || '-'}</td>
                    <td>${layoutStr}</td>
                </tr>
            `;
        }).join('');

        tbody.querySelectorAll('.dn-link').forEach(el => {
            el.addEventListener('click', () => showDrawingDetail(el.dataset.dn));
        });
    } catch (err) { console.error('loadFabToLayout:', err); }
}

async function reverseLookup() {
    const dn = document.getElementById('reverseLookupInput').value.trim();
    if (!dn) return;
    const resultDiv = document.getElementById('reverseLookupResult');
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<span class="status loading">查詢中...</span>';
    try {
        const r = await fetch(`${API_BASE}/db/find-layout?dn=${encodeURIComponent(dn)}${dbParam()}`);
        const data = await r.json();
        if (!data.found) { resultDiv.innerHTML = `<span class="status error">${data.error}</span>`; return; }
        const fab = data.fabrication;
        const layouts = data.layout_drawings;
        let html = '<div class="reverse-result">';
        html += `<div class="stats-grid" style="margin-bottom:12px;">`;
        html += `<div class="stat-item"><div class="stat-value">${fab.drawing_number}</div><div class="stat-label">圖號</div></div>`;
        html += `<div class="stat-item"><div class="stat-value">${fab.width_mm||'-'} × ${fab.height_mm||'-'} mm</div><div class="stat-label">尺寸</div></div>`;
        html += `<div class="stat-item"><div class="stat-value">${fab.quantity||1}</div><div class="stat-label">數量</div></div>`;
        html += `<div class="stat-item"><div class="stat-value">${fab.color||'-'}</div><div class="stat-label">顏色</div></div>`;
        html += `</div>`;
        if (layouts.length > 0) {
            html += `<h4 style="font-size:0.9rem;color:var(--green);margin-bottom:8px;">對應的位置圖 (${layouts.length} 張)</h4>`;
            html += layouts.map(l => `
                <div class="layout-match">
                    <span class="type-badge layout">位置圖</span>
                    <strong class="dn-link" data-dn="${l.drawing_number}">${l.drawing_number}</strong>
                    <span style="color:var(--text-secondary);margin-left:8px;">${l.filename}</span>
                </div>
            `).join('');
        } else {
            html += `<p style="color:var(--orange);">⚠ 此加工圖未被任何位置圖引用</p>`;
        }
        const texts = data.texts || [];
        if (texts.length > 0) {
            html += `<details style="margin-top:12px;"><summary style="cursor:pointer;color:var(--text-secondary);font-size:0.85rem;">文字內容 (${texts.length} 個)</summary>`;
            html += `<div class="text-chips" style="margin-top:8px;">${texts.map(t => `<span class="text-chip" title="${t.entity}">${escHtml(t.text)}</span>`).join('')}</div>`;
            html += `</details>`;
        }
        html += '</div>';
        resultDiv.innerHTML = html;
        resultDiv.querySelectorAll('.dn-link').forEach(el => {
            el.addEventListener('click', () => showDrawingDetail(el.dataset.dn));
        });
    } catch (err) { resultDiv.innerHTML = `<span class="status error">查詢失敗: ${err.message}</span>`; }
}

async function loadLayout() {
    try {
        const r = await fetch(`${API_BASE}/db/layout${dbParam('?')}`);
        if (!r.ok) return;
        const data = await r.json();
        const layouts = data.layouts || [];
        if (layouts.length === 0) return;

        document.getElementById('layoutCard').classList.remove('hidden');
        document.getElementById('layoutSummary').innerHTML = `
            <span class="type-badge layout">位置圖</span>
            共 <strong>${layouts.length}</strong> 張位置圖，
            涵蓋 <strong>${data.total_fab_in_layouts}</strong> 張加工圖
        `;

        // 為每張位置圖建一個表格
        let allHtml = '';
        layouts.forEach((lo, idx) => {
            const layout = lo.layout;
            const fabs = lo.fabrication_drawings;
            const collapseId = `layoutCollapse${idx}`;
            allHtml += `
                <div class="layout-group" style="margin-top:${idx > 0 ? '16px' : '0'};">
                    <div class="layout-group-header" style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border);cursor:pointer;" onclick="document.getElementById('${collapseId}').classList.toggle('hidden');this.querySelector('.arrow').classList.toggle('rotated');">
                        <span class="arrow" style="transition:transform 0.2s;">▶</span>
                        <strong>${layout.drawing_number}</strong>
                        <span style="color:var(--text-secondary);font-size:0.85rem;">${layout.filename}</span>
                        <span style="color:var(--text-secondary);font-size:0.85rem;margin-left:auto;">${lo.fab_count} 張加工圖</span>
                    </div>
                    <div id="${collapseId}" class="${idx > 0 ? 'hidden' : ''}">
                        <div class="table-wrap">
                            <table class="data-table">
                                <thead><tr><th>圖號</th><th>寬 W (mm)</th><th>高 H (mm)</th><th>數量</th><th>顏色</th><th>操作</th></tr></thead>
                                <tbody>
                                    ${fabs.map(f => `
                                        <tr>
                                            <td><span class="dn-link" data-dn="${f.drawing_number}">${f.drawing_number}</span></td>
                                            <td>${f.width_mm ?? '-'}</td>
                                            <td>${f.height_mm ?? '-'}</td>
                                            <td>${f.quantity ?? 1}</td>
                                            <td>${f.color || '-'}</td>
                                            <td><button class="btn btn-sm btn-outline detail-btn" data-dn="${f.drawing_number}">詳情</button></td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                        ${lo.external_refs.length > 0 ? `
                            <div style="margin-top:6px;font-size:0.8rem;color:var(--text-secondary);">
                                外部引用: ${lo.external_refs.map(e => `<span class="fab-mark-tag" style="background:rgba(245,158,11,0.12);border-color:var(--orange);">${e}</span>`).join(' ')}
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        });

        // Put it all in a container
        const container = document.createElement('div');
        container.innerHTML = allHtml;
        const oldTbody = document.querySelector('#layoutTable tbody');
        const tableWrap = document.querySelector('#layoutCard .table-wrap');
        // Replace old table content area
        const layoutCard = document.getElementById('layoutCard');
        // Remove old table-wrap if exists
        const oldWrap = layoutCard.querySelector('.table-wrap');
        if (oldWrap) oldWrap.remove();
        const oldGroups = layoutCard.querySelectorAll('.layout-group');
        oldGroups.forEach(g => g.remove());
        layoutCard.appendChild(container);

        // Event listeners
        layoutCard.querySelectorAll('.dn-link, .detail-btn').forEach(el => {
            el.addEventListener('click', () => showDrawingDetail(el.dataset.dn));
        });

        // External refs summary
        if (data.all_external_refs && data.all_external_refs.length > 0) {
            let extDiv = document.getElementById('externalRefs');
            if (!extDiv) {
                extDiv = document.createElement('div');
                extDiv.id = 'externalRefs';
                extDiv.className = 'external-refs';
                extDiv.innerHTML = '<h4>所有外部引用 (不在本資料夾)</h4><div id="externalRefsList"></div>';
                layoutCard.appendChild(extDiv);
            }
            extDiv.classList.remove('hidden');
            document.getElementById('externalRefsList').innerHTML = data.all_external_refs.map(e =>
                `<span class="fab-mark-tag" style="background:rgba(245,158,11,0.12);border-color:var(--orange);">${e}</span>`
            ).join(' ');
        }
    } catch (err) { console.error('loadLayout:', err); }
}

async function checkMissing() {
    try {
        const r = await fetch(`${API_BASE}/db/missing${dbParam('?')}`);
        const data = await r.json();
        if (data.count === 0) return;
        document.getElementById('missingCard').classList.remove('hidden');
        document.getElementById('missingContent').innerHTML = data.missing.map(m =>
            `<span class="fab-mark-tag" style="background:rgba(239,68,68,0.12);border-color:var(--red);">${m}</span>`
        ).join(' ') + `<p style="margin-top:8px;font-size:0.85rem;color:var(--text-secondary);">以上 ${data.count} 個圖號在位置圖中有引用，但無對應 DWG 檔案</p>`;
    } catch (err) { console.error('checkMissing:', err); }
}

async function searchDrawings(listAll) {
    listAll = listAll || false;
    const q = listAll ? '' : document.getElementById('dbSearch').value.trim();
    try {
        const r = await fetch(`${API_BASE}/db/drawings?search=${encodeURIComponent(q)}${dbParam()}`);
        const data = await r.json();
        const wrap = document.getElementById('searchResultsWrap');
        const tbody = document.querySelector('#searchResultsTable tbody');
        if (data.count === 0) {
            wrap.classList.remove('hidden');
            tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-secondary);text-align:center;">無結果</td></tr>';
            return;
        }
        wrap.classList.remove('hidden');
        const typeNames = { fabrication: '加工圖', layout: '位置圖', unknown: '?' };
        tbody.innerHTML = data.drawings.map(d => `
            <tr>
                <td><span class="dn-link" data-dn="${d.drawing_number}">${d.drawing_number || '-'}</span></td>
                <td>${d.filename}</td>
                <td><span class="type-badge ${d.drawing_type}">${typeNames[d.drawing_type]||d.drawing_type}</span></td>
                <td>${d.width_mm ? d.width_mm + ' × ' + d.height_mm + ' mm' : '-'}</td>
                <td>${d.quantity ?? 1}</td>
                <td><button class="btn btn-sm btn-outline detail-btn" data-dn="${d.drawing_number}">詳情</button></td>
            </tr>
        `).join('');
        tbody.querySelectorAll('.dn-link, .detail-btn').forEach(el => {
            el.addEventListener('click', () => showDrawingDetail(el.dataset.dn));
        });
    } catch (err) { console.error('searchDrawings:', err); }
}

async function showDrawingDetail(drawingNumber) {
    const card = document.getElementById('detailCard');
    const content = document.getElementById('detailContent');
    document.getElementById('detailTitle').textContent = `圖紙細節: ${drawingNumber}`;
    content.innerHTML = '<span class="status loading">載入中...</span>';
    card.classList.remove('hidden');
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
        const r = await fetch(`${API_BASE}/db/drawings/${encodeURIComponent(drawingNumber)}${dbParam('?')}`);
        if (!r.ok) { content.innerHTML = `<span class="status error">${(await r.json()).error}</span>`; return; }
        const d = await r.json();
        const typeNames = { fabrication: '加工圖', layout: '位置圖', unknown: '?' };
        let html = `
            <div class="stats-grid" style="margin-bottom:16px;">
                <div class="stat-item"><div class="stat-value">${d.drawing_number}</div><div class="stat-label">圖號</div></div>
                <div class="stat-item"><div class="stat-value"><span class="type-badge ${d.drawing_type}">${typeNames[d.drawing_type]||d.drawing_type}</span></div><div class="stat-label">類型</div></div>
                <div class="stat-item"><div class="stat-value">${d.width_mm||'-'} × ${d.height_mm||'-'}</div><div class="stat-label">尺寸 (mm)</div></div>
                <div class="stat-item"><div class="stat-value">${d.quantity||1}</div><div class="stat-label">數量</div></div>
            </div>
            <p style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:16px;">檔案: ${d.filename} | 專案: ${d.project_code} | 顏色: ${d.color||'-'} | 材料: ${d.material||'-'}</p>
        `;
        const texts = d.texts || [];
        if (texts.length > 0) {
            html += `<h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">文字內容 (${texts.length} 個)</h4>`;
            html += `<div class="text-chips">${texts.map(t => `<span class="text-chip" title="${t.entity}">${escHtml(t.text)}</span>`).join('')}</div>`;
        }
        const refs = d.refs || [];
        const byRefs = d.referenced_by || [];
        if (refs.length > 0 || byRefs.length > 0) {
            html += `<div style="display:flex;gap:24px;margin-top:16px;">`;
            if (refs.length > 0) {
                html += `<div><h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">引用的圖號 (${refs.length})</h4>`;
                html += refs.map(r => `<span class="fab-mark-tag ref-link" data-dn="${r}">${r}</span>`).join(' ');
                html += `</div>`;
            }
            if (byRefs.length > 0) {
                html += `<div><h4 style="font-size:0.85rem;color:var(--text-secondary);margin-bottom:6px;">被引用 (${byRefs.length})</h4>`;
                html += byRefs.map(b => `<span class="fab-mark-tag ref-link" data-dn="${b.drawing_number}" title="${b.filename}">${b.drawing_number}</span>`).join(' ');
                html += `</div>`;
            }
            html += `</div>`;
        }
        content.innerHTML = html;
        content.querySelectorAll('.ref-link').forEach(el => {
            el.addEventListener('click', () => showDrawingDetail(el.dataset.dn));
        });
    } catch (err) { content.innerHTML = `<span class="status error">載入失敗: ${err.message}</span>`; }
}

function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
