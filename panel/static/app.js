const HITOKOTO_TYPES = [
  '动画', '漫画', '游戏', '文学', '原创', '网络',
  '影视', '诗词', '网易云', '哲学', '抖机灵', '其他',
];

const TAB_META = {
  overview: { title: '总览', kicker: 'Overview' },
  friends: { title: '续火好友', kicker: 'Targets' },
  cookie: { title: 'Cookie', kicker: 'Auth' },
  config: { title: '基础配置', kicker: 'Config' },
  notify: { title: '飞书通知', kicker: 'Notify' },
  logs: { title: '运行日志', kicker: 'Runtime' },
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const gate = $('#gate');
const app = $('#app');

let state = { settings: {}, accounts: [] };
/** @type {{name:string, enabled:boolean}[]} */
let friends = [];
let runTimer = null;
let currentTab = 'overview';

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}

let toastTimer = null;
function showToast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: options.body ? { 'Content-Type': 'application/json' } : {},
    ...options,
  });
  if (res.status === 401) {
    showGate();
    throw new Error('未登录');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

function showGate() {
  gate.hidden = false;
  app.hidden = true;
  document.body.style.overflow = 'hidden';
  clearInterval(runTimer); runTimer = null;
}

function showApp() {
  gate.hidden = true;
  app.hidden = false;
  document.body.style.overflow = '';
}

function currentAccount() {
  return state.accounts[0] || { username: '', unique_id: '', targets: [], cookies: {} };
}

function currentUniqueId() {
  return ($('#acc-unique-id')?.value || currentAccount().unique_id || '').trim();
}

function switchTab(tab) {
  currentTab = tab;
  $$('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.tab === tab));
  $$('.tab-panel').forEach((el) => el.classList.toggle('active', el.dataset.panel === tab));
  const meta = TAB_META[tab] || TAB_META.overview;
  $('#page-title').textContent = meta.title;
  $('#page-kicker').textContent = meta.kicker;
}

$('#main-nav').addEventListener('click', (event) => {
  const btn = event.target.closest('[data-tab]');
  if (!btn) return;
  switchTab(btn.dataset.tab);
});

document.addEventListener('click', (event) => {
  const go = event.target.closest('[data-go]');
  if (go) switchTab(go.dataset.go);
});

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const error = $('#login-error');
  error.textContent = '';
  try {
    await api('/api/login', {
      method: 'POST',
      body: JSON.stringify({ password: $('#password').value }),
    });
    $('#password').value = '';
    showApp();
    await refreshAll();
    switchTab('overview');
  } catch (err) {
    error.textContent = err.message;
  }
});

$('#logout').addEventListener('click', async () => {
  try { await api('/api/logout', { method: 'POST' }); } catch { /* ignore */ }
  showGate();
});

function renderHitokoto(selected) {
  const chosen = new Set(selected);
  $('#hitokoto-options').innerHTML = HITOKOTO_TYPES.map((type) => `
    <label class="choice-pill">
      <input type="checkbox" value="${escapeHtml(type)}" ${chosen.has(type) ? 'checked' : ''} />
      <span>${escapeHtml(type)}</span>
    </label>`).join('');
}

function normalizeFriendName(name) {
  return String(name || '').trim();
}

function loadFriendsFromAccount(account) {
  const targets = account?.targets || [];
  friends = targets
    .map((name) => normalizeFriendName(name))
    .filter(Boolean)
    .map((name) => ({ name, enabled: true }));
}

function selectedNames() {
  return friends.filter((f) => f.enabled).map((f) => f.name);
}

function renderFriends() {
  const filter = ($('#friend-filter')?.value || '').trim().toLowerCase();
  const list = $('#friend-list');
  const empty = $('#friend-empty');
  const visible = friends.filter((f) => !filter || f.name.toLowerCase().includes(filter));

  $('#friend-total').textContent = String(friends.length);
  $('#friend-selected').textContent = String(selectedNames().length);
  $('#nav-friend-count').textContent = String(selectedNames().length);
  $('#stat-targets').textContent = String(selectedNames().length);

  if (!visible.length) {
    list.innerHTML = '';
    empty.hidden = false;
    empty.textContent = friends.length ? '没有匹配的好友' : '还没有好友，在上方添加后勾选即可。';
    return;
  }
  empty.hidden = true;
  list.innerHTML = visible.map((friend) => {
    const idx = friends.findIndex((f) => f.name === friend.name);
    const initial = escapeHtml((friend.name || '?').slice(0, 1).toUpperCase());
    return `
      <label class="friend-item ${friend.enabled ? 'active' : ''}" data-idx="${idx}">
        <input type="checkbox" data-friend-check="${idx}" ${friend.enabled ? 'checked' : ''} />
        <div class="meta">
          <div class="name">${escapeHtml(friend.name)}</div>
          <div class="sub">${friend.enabled ? '续火中' : '未选中'} · ${initial}</div>
        </div>
        <button type="button" class="remove" data-friend-del="${idx}" title="删除">×</button>
      </label>`;
  }).join('');
}

function addFriend(rawName) {
  const name = normalizeFriendName(rawName);
  if (!name) {
    showToast('请输入好友昵称或抖音号');
    return;
  }
  if (friends.some((f) => f.name === name)) {
    // 已存在则勾选
    friends = friends.map((f) => f.name === name ? { ...f, enabled: true } : f);
    showToast('该好友已在列表中，已勾选');
  } else {
    friends = [{ name, enabled: true }, ...friends];
    showToast(`已添加 ${name}`);
  }
  $('#friend-input').value = '';
  renderFriends();
  renderStats();
}

$('#friend-add').addEventListener('click', () => addFriend($('#friend-input').value));
$('#friend-input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    addFriend($('#friend-input').value);
  }
});
$('#friend-filter').addEventListener('input', renderFriends);

$('#friend-list').addEventListener('click', (event) => {
  const del = event.target.closest('[data-friend-del]');
  if (del) {
    event.preventDefault();
    event.stopPropagation();
    const idx = Number(del.dataset.friendDel);
    const name = friends[idx]?.name;
    friends = friends.filter((_, i) => i !== idx);
    renderFriends();
    renderStats();
    showToast(name ? `已删除 ${name}` : '已删除');
    return;
  }
});

$('#friend-list').addEventListener('change', (event) => {
  const box = event.target.closest('[data-friend-check]');
  if (!box) return;
  const idx = Number(box.dataset.friendCheck);
  if (!friends[idx]) return;
  friends[idx] = { ...friends[idx], enabled: box.checked };
  renderFriends();
  renderStats();
});

$('#friend-select-all').addEventListener('click', () => {
  friends = friends.map((f) => ({ ...f, enabled: true }));
  renderFriends();
  renderStats();
});
$('#friend-select-none').addEventListener('click', () => {
  friends = friends.map((f) => ({ ...f, enabled: false }));
  renderFriends();
  renderStats();
});
$('#friend-remove-checked').addEventListener('click', () => {
  const before = friends.length;
  friends = friends.filter((f) => !f.enabled);
  renderFriends();
  renderStats();
  showToast(`已删除 ${before - friends.length} 人`);
});

async function saveFriends() {
  const username = ($('#acc-username').value || '').trim() || currentAccount().username || 'Sherry';
  const uniqueId = currentUniqueId();
  if (!uniqueId) {
    showToast('请先填写 unique_id');
    return;
  }
  const settings = { ...(state.settings || {}) };
  // 保留当前表单里的基础配置值
  for (const el of $$('[data-field]')) {
    settings[el.dataset.field] = el.value;
  }
  settings.hitokotoTypes = $$('#hitokoto-options input:checked').map((el) => el.value);

  const accounts = [{
    username,
    unique_id: uniqueId,
    targets: selectedNames(),
  }];

  const button = $('#save-friends');
  button.disabled = true;
  try {
    const res = await api('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ settings, accounts }),
    });
    showToast(`已保存 ${selectedNames().length} 个续火好友`);
    await loadConfig();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  } finally {
    button.disabled = false;
  }
}
$('#save-friends').addEventListener('click', saveFriends);

function renderStats() {
  const account = currentAccount();
  const health = account.cookies || {};
  const settings = state.settings || {};
  const cookieEl = $('#stat-cookie');
  const ovCookie = $('#ov-cookie');
  const setDot = (el, kind) => { if (el) el.className = `dot ${kind || ''}`.trim(); };

  let cookieText = '—';
  let cookieKind = 'soft';
  let cookieColor = 'var(--text)';
  let cookiePct = 0;
  let meterClass = '';
  if (!health.has_sessionid) {
    cookieText = '失效'; cookieKind = 'err'; cookieColor = 'var(--danger)'; cookiePct = 8; meterClass = 'err';
  } else if (health.days_left != null && health.days_left < 0) {
    cookieText = '已过期'; cookieKind = 'err'; cookieColor = 'var(--danger)'; cookiePct = 12; meterClass = 'err';
  } else if (health.days_left != null && health.days_left < 7) {
    cookieText = `剩 ${health.days_left} 天`; cookieKind = 'warn'; cookieColor = 'var(--warn)';
    cookiePct = Math.max(15, Math.min(90, (health.days_left / 60) * 100)); meterClass = 'warn';
  } else if (health.days_left != null) {
    cookieText = `剩 ${health.days_left} 天`; cookieKind = 'ok'; cookieColor = 'var(--accent)';
    cookiePct = Math.max(20, Math.min(100, (health.days_left / 60) * 100));
  } else {
    cookieText = '正常'; cookieKind = 'ok'; cookieColor = 'var(--accent)'; cookiePct = 80;
  }

  cookieEl.textContent = cookieText;
  cookieEl.style.color = cookieColor;
  ovCookie.textContent = cookieText;
  ovCookie.style.color = cookieColor;
  setDot($('#dot-cookie'), cookieKind);

  const selected = selectedNames().length || (account.targets || []).length;
  const totalFriends = friends.length || selected;
  $('#stat-targets').textContent = String(selected);
  $('#nav-friend-count').textContent = String(selected);
  const friendSub = $('#ov-friend-sub');
  if (friendSub) friendSub.textContent = totalFriends ? `已勾选 ${selected} / 共 ${totalFriends}` : '尚未添加好友';
  const friendMeter = $('#ov-friend-meter');
  if (friendMeter) {
    const pct = totalFriends ? Math.round((selected / totalFriends) * 100) : 0;
    friendMeter.style.width = `${pct}%`;
    friendMeter.parentElement.className = `meter ${selected ? '' : 'warn'}`.trim();
  }
  const cookieMeter = $('#ov-cookie-meter');
  if (cookieMeter) {
    cookieMeter.style.width = `${Math.round(cookiePct)}%`;
    cookieMeter.parentElement.className = `meter ${meterClass}`.trim();
  }

  const detail = [];
  if (health.count) detail.push(`${health.count} 条 Cookie`);
  if (health.expires_at) detail.push(`到期 ${new Date(health.expires_at * 1000).toLocaleString('zh-CN')}`);
  $('#cookie-detail').textContent = detail.join(' · ') || '配置 Cookie 与好友后，可一键执行或等待定时任务';
  const cookieSub = $('#ov-cookie-sub');
  if (cookieSub) cookieSub.textContent = detail[0] || '会话有效期';

  const hour = new Date().getHours();
  const hello = hour < 6 ? '夜深了' : hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
  const greet = $('#ov-greeting');
  if (greet) greet.textContent = `${hello}，续火看板`;

  const accTag = $('#ov-account-tag');
  if (accTag) accTag.textContent = `账号 ${account.username || '—'}`;
  const modeTag = $('#ov-mode-tag');
  if (modeTag) modeTag.textContent = `匹配 ${settings.matchMode === 'nickname' ? '昵称' : (settings.matchMode || '—')}`;

  // health ring
  const ring = $('#ov-health-ring');
  const healthText = $('#ov-health-text');
  if (ring && healthText) {
    let state = 'unknown';
    let text = '待配置';
    if (!health.has_sessionid) { state = 'err'; text = 'Cookie 失效'; }
    else if (health.days_left != null && health.days_left < 0) { state = 'err'; text = '已过期'; }
    else if (health.days_left != null && health.days_left < 7) { state = 'warn'; text = '即将过期'; }
    else if (!selected) { state = 'warn'; text = '未选好友'; }
    else { state = 'ok'; text = '运行就绪'; }
    ring.dataset.state = state;
    healthText.textContent = text;
  }
}

async function loadConfig() {
  const data = await api('/api/config');
  state = data;
  const settings = data.settings || {};
  const account = currentAccount();

  for (const el of $$('[data-field]')) {
    const key = el.dataset.field;
    if (settings[key] !== undefined) el.value = settings[key];
  }

  $('#acc-username').value = account.username || '';
  $('#acc-unique-id').value = account.unique_id || '';

  let types = [];
  try { types = JSON.parse(settings.hitokotoTypes || '[]'); } catch { types = []; }
  renderHitokoto(types);
  loadFriendsFromAccount(account);
  renderFriends();
  renderStats();
}

$('#save-config').addEventListener('click', async () => {
  const settings = {};
  for (const el of $$('[data-field]')) settings[el.dataset.field] = el.value;
  settings.hitokotoTypes = $$('#hitokoto-options input:checked').map((el) => el.value);

  const username = ($('#acc-username').value || '').trim() || currentAccount().username || 'Sherry';
  const uniqueId = currentUniqueId() || currentAccount().unique_id;
  if (!uniqueId) {
    showToast('请先填写 unique_id');
    return;
  }

  const accounts = [{
    username,
    unique_id: uniqueId,
    targets: selectedNames().length ? selectedNames() : (currentAccount().targets || []),
  }];

  const button = $('#save-config');
  button.disabled = true;
  try {
    const res = await api('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ settings, accounts }),
    });
    showToast(`已保存 ${res.updated.length} 项配置`);
    await loadConfig();
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  } finally {
    button.disabled = false;
  }
});

$('#import-cookies').addEventListener('click', async () => {
  const uniqueId = currentUniqueId();
  const raw = $('#cookie-paste').value.trim();
  if (!uniqueId) { showToast('请先在好友页填写 unique_id'); return; }
  if (!raw) { showToast('请粘贴 Cookie JSON'); return; }
  const button = $('#import-cookies');
  button.disabled = true;
  try {
    const res = await api('/api/cookies', {
      method: 'POST',
      body: JSON.stringify({ unique_id: uniqueId, cookies: raw }),
    });
    const days = res.health?.days_left;
    const extra = days == null ? '' : (days < 0 ? `（已过期 ${Math.abs(days)} 天）` : `（剩余 ${days} 天）`);
    showToast(`已写入 ${res.key}，共 ${res.cookie_count} 条${extra}`);
    $('#cookie-paste').value = '';
    await loadConfig();
  } catch (err) {
    showToast(`导入失败：${err.message}`);
  } finally {
    button.disabled = false;
  }
});

async function loadNotify() {
  const data = await api('/api/notify');
  $('#feishu-webhook').value = data.feishu_webhook || '';
  const tag = $('#ov-notify-tag');
  if (tag) tag.textContent = data.feishu_webhook ? '通知 已开启' : '通知 未配置';
}

$('#save-notify').addEventListener('click', async () => {
  const button = $('#save-notify');
  button.disabled = true;
  try {
    await api('/api/notify', {
      method: 'PUT',
      body: JSON.stringify({ feishu_webhook: $('#feishu-webhook').value.trim() }),
    });
    showToast('飞书 Webhook 已保存');
  } catch (err) {
    showToast(`保存失败：${err.message}`);
  } finally {
    button.disabled = false;
  }
});

$('#test-notify').addEventListener('click', async () => {
  const button = $('#test-notify');
  button.disabled = true;
  try {
    const fw = $('#feishu-webhook').value.trim();
    if (fw) {
      await api('/api/notify', {
        method: 'PUT',
        body: JSON.stringify({ feishu_webhook: fw }),
      });
    }
    const res = await api('/api/notify/test', { method: 'POST' });
    showToast(res.message || '测试通知已发送');
  } catch (err) {
    showToast(`测试失败：${err.message}`);
  } finally {
    button.disabled = false;
  }
});

function renderRunRows(targetSel, runs) {
  const el = $(targetSel);
  if (!el) return;
  el.innerHTML = runs.length ? runs.map((run) => {
    const ok = run.status === 'Success';
    const when = String(run.start_time).replace('T', ' ').slice(0, 19);
    return `<div class="run-row">
      <span class="t">${escapeHtml(when)}</span>
      <span>${run.duration_s}s</span>
      <span class="badge ${ok ? 'ok' : 'err'}">${ok ? '成功' : escapeHtml(run.message || '失败')}</span>
    </div>`;
  }).join('') : '<p class="empty">暂无运行记录。</p>';
}

async function loadRuns() {
  const data = await api('/api/runs');
  const schedule = data.schedule || '未配置';
  $('#cron-spec').textContent = schedule;
  $('#ov-cron').textContent = schedule;
  const cronSub = $('#ov-cron-sub');
  if (cronSub) {
    // very light parse of "30 8 * * *"
    const parts = String(schedule).trim().split(/\s+/);
    if (parts.length >= 2 && /^\d+$/.test(parts[0]) && /^\d+$/.test(parts[1])) {
      cronSub.textContent = `每天 ${parts[1].padStart(2, '0')}:${parts[0].padStart(2, '0')}`;
    } else {
      cronSub.textContent = 'cron 表达式';
    }
  }

  const runs = data.runs || [];
  const lastOk = runs.length ? runs[0].status === 'Success' : null;
  const lastText = runs.length ? (lastOk ? '成功' : '失败') : '—';
  $('#stat-last').textContent = lastText;
  $('#ov-last').textContent = lastText;
  $('#stat-last').style.color = lastOk === false ? 'var(--danger)' : 'var(--accent)';
  $('#ov-last').style.color = lastOk === false ? 'var(--danger)' : 'var(--accent)';
  const dotLast = $('#dot-last');
  if (dotLast) dotLast.className = `dot ${lastOk === false ? 'err' : (lastOk ? 'ok' : 'soft')}`;
  const lastSub = $('#ov-last-sub');
  if (lastSub) {
    if (!runs.length) lastSub.textContent = '尚无记录';
    else {
      const when = String(runs[0].start_time).replace('T', ' ').slice(5, 16);
      lastSub.textContent = `${when} · ${runs[0].duration_s || 0}s`;
    }
  }

  renderRunRows('#runs', runs);
  renderRunRows('#runs-overview', runs.slice(0, 5));
  renderRunPulse(runs.slice(0, 7));
}

function renderRunPulse(runs) {
  const host = $('#run-pulse');
  if (!host) return;
  const items = [...runs].reverse(); // old -> new
  if (!items.length) {
    host.innerHTML = '<p class="empty">暂无运行数据</p>';
    $('#ov-success-rate').textContent = '—';
    $('#ov-avg-duration').textContent = '—';
    $('#ov-streak').textContent = '—';
    return;
  }
  const maxDur = Math.max(...items.map((r) => Number(r.duration_s) || 1), 1);
  host.innerHTML = items.map((run) => {
    const ok = run.status === 'Success';
    const dur = Number(run.duration_s) || 0;
    const h = Math.max(18, Math.round((dur / maxDur) * 78));
    const label = String(run.start_time).replace('T', ' ').slice(5, 10);
    return `<div class="pulse-bar ${ok ? '' : 'fail'}">
      <div class="bar" style="height:${h}px"><i style="height:100%"></i></div>
      <div class="label">${escapeHtml(label)}</div>
    </div>`;
  }).join('');

  const success = items.filter((r) => r.status === 'Success').length;
  const avg = items.reduce((s, r) => s + (Number(r.duration_s) || 0), 0) / items.length;
  let streak = 0;
  for (const r of runs) { // newest first
    if (r.status === 'Success') streak += 1;
    else break;
  }
  $('#ov-success-rate').textContent = `${Math.round((success / items.length) * 100)}%`;
  $('#ov-avg-duration').textContent = `${avg.toFixed(1)}s`;
  $('#ov-streak').textContent = `${streak} 次`;
}

async function loadLogs() {
  const data = await api('/api/logs?limit=3');
  const blocks = data.blocks || [];
  $('#log-blocks').innerHTML = blocks.length ? blocks.map((block, index) => {
    const when = (block.start.match(/\[(.*?)\]/) || [, block.start])[1];
    const omitted = block.total_lines > block.lines.length
      ? `（仅显示末 ${block.lines.length} / ${block.total_lines} 行）` : '';
    return `<details class="log-block" ${index === 0 ? 'open' : ''}>
      <summary>
        <span>${escapeHtml(when)} ${escapeHtml(omitted)}</span>
        <span class="badge ${block.failed ? 'err' : 'ok'}">${block.failed ? '失败' : '成功'}</span>
      </summary>
      <pre>${escapeHtml(block.lines.join('\n'))}</pre>
    </details>`;
  }).join('') : '<p class="empty">还没有日志。</p>';
}

$('#refresh-logs').addEventListener('click', async () => {
  try {
    await Promise.all([loadRuns(), loadLogs()]);
    showToast('日志已刷新');
  } catch (err) {
    showToast(err.message);
  }
});

$('#run-now').addEventListener('click', async () => {
  const button = $('#run-now');
  button.disabled = true;
  try {
    await api('/api/run', { method: 'POST' });
    showToast('已开始执行，可能需要 1–3 分钟');
    clearInterval(runTimer);
    runTimer = setInterval(pollRun, 4000);
  } catch (err) {
    showToast(err.message);
    button.disabled = false;
  }
});

async function pollRun() {
  let data;
  try { data = await api('/api/run'); }
  catch { clearInterval(runTimer); return; }
  if (!data.running) {
    clearInterval(runTimer);
    runTimer = null;
    $('#run-now').disabled = false;
    showToast(data.returncode === 0 ? '执行成功' : `执行失败（退出码 ${data.returncode}）`);
    await refreshAll();
  }
}

async function refreshAll() {
  await Promise.all([loadConfig(), loadNotify(), loadRuns(), loadLogs()]);
}

(async function bootstrap() {
  try {
    await api('/api/me');
    showApp();
    await refreshAll();
    switchTab('overview');
  } catch {
    showGate();
  }
})();
