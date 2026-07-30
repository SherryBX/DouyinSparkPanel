const HITOKOTO_TYPES = [
  '动画', '漫画', '游戏', '文学', '原创', '网络',
  '影视', '诗词', '网易云', '哲学', '抖机灵', '其他',
];

const $ = (sel) => document.querySelector(sel);
const gate = $('#gate');
const app = $('#app');

let state = { settings: {}, accounts: [] };
let runTimer = null;

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
  gate.hidden = true;
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

function currentUniqueId() {
  const account = state.accounts[0];
  return account?.unique_id
    || document.querySelector('[data-acc-field="unique_id"]')?.value?.trim()
    || '';
}

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
    await Promise.all([loadConfig(), loadNotify(), loadRuns(), loadLogs()]);
  } catch (err) {
    error.textContent = err.message;
  }
});

$('#logout').addEventListener('click', async () => {
  try { await api('/api/logout', { method: 'POST' }); } catch { /* 忽略 */ }
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

function renderAccounts() {
  const html = state.accounts.map((account, index) => {
    const health = account.cookies || {};
    let badge = '<span class="badge err">无 Cookie</span>';
    if (health.has_sessionid) {
      const days = health.days_left;
      if (days === null || days === undefined) {
        badge = `<span class="badge ok">${health.count} 条 Cookie</span>`;
      } else if (days < 0) {
        badge = `<span class="badge err">已过期 ${Math.abs(days)} 天</span>`;
      } else if (days < 7) {
        badge = `<span class="badge warn">剩 ${days} 天</span>`;
      } else {
        badge = `<span class="badge ok">剩 ${days} 天</span>`;
      }
    }
    return `
      <div class="account-card">
        <div class="account-head">
          <div>
            <p class="eyebrow">Account ${String(index + 1).padStart(2, '0')}</p>
            <h3>${escapeHtml(account.username || '未命名')}</h3>
            <p><code class="inline">${escapeHtml(account.cookies_key)}</code></p>
          </div>
          ${badge}
        </div>
        <div class="grid two">
          <label class="field">
            <span>用户名（仅用于标识）</span>
            <input data-acc="${index}" data-acc-field="username"
                   value="${escapeHtml(account.username)}" />
          </label>
          <label class="field">
            <span>unique_id（决定 Cookie 变量名）</span>
            <input data-acc="${index}" data-acc-field="unique_id"
                   value="${escapeHtml(account.unique_id)}" />
          </label>
        </div>
        <label class="field mt">
          <span>续火好友（每行一个，共 ${account.targets.length} 个）</span>
          <textarea rows="6" data-acc="${index}" data-acc-field="targets"
          >${escapeHtml(account.targets.join('\n'))}</textarea>
        </label>
      </div>`;
  }).join('');
  $('#accounts').innerHTML = html || '<p class="empty">配置里还没有账号。</p>';
}

function renderStats() {
  const account = state.accounts[0];
  const health = account?.cookies || {};
  const cookieEl = $('#stat-cookie');
  const dotCookie = $('#dot-cookie');
  const dotLast = $('#dot-last');

  const setDot = (el, kind) => {
    if (!el) return;
    el.className = `dot ${kind || ''}`.trim();
  };

  if (!health.has_sessionid) {
    cookieEl.textContent = '失效';
    cookieEl.style.color = 'var(--danger)';
    setDot(dotCookie, 'err');
  } else if (health.days_left !== null && health.days_left !== undefined && health.days_left < 0) {
    cookieEl.textContent = '已过期';
    cookieEl.style.color = 'var(--danger)';
    setDot(dotCookie, 'err');
  } else if (health.days_left !== null && health.days_left !== undefined && health.days_left < 7) {
    cookieEl.textContent = `剩 ${health.days_left} 天`;
    cookieEl.style.color = 'var(--warn)';
    setDot(dotCookie, 'warn');
  } else {
    cookieEl.textContent = health.days_left != null ? `剩 ${health.days_left} 天` : '正常';
    cookieEl.style.color = 'var(--accent)';
    setDot(dotCookie, 'ok');
  }

  $('#stat-targets').textContent = account ? account.targets.length : '—';

  const detail = [];
  if (health.count) detail.push(`${health.count} 条 Cookie`);
  if (health.expires_at) {
    detail.push(`到期 ${new Date(health.expires_at * 1000).toLocaleString('zh-CN')}`);
  }
  $('#cookie-detail').textContent = detail.join(' · ') || '尚未配置 Cookie';

  // keep last-run dot in sync if already rendered
  if (dotLast && !dotLast.className.includes('ok') && !dotLast.className.includes('err')) {
    setDot(dotLast, 'soft');
  }
}

async function loadConfig() {
  const data = await api('/api/config');
  state = data;
  const settings = data.settings || {};

  for (const el of document.querySelectorAll('[data-field]')) {
    const key = el.dataset.field;
    if (settings[key] !== undefined) el.value = settings[key];
  }

  let types = [];
  try { types = JSON.parse(settings.hitokotoTypes || '[]'); } catch { types = []; }
  renderHitokoto(types);
  renderAccounts();
  renderStats();
}

$('#save-config').addEventListener('click', async () => {
  const settings = {};
  for (const el of document.querySelectorAll('[data-field]')) {
    settings[el.dataset.field] = el.value;
  }
  settings.hitokotoTypes = [...document.querySelectorAll('#hitokoto-options input:checked')]
    .map((el) => el.value);

  const accounts = state.accounts.map((account, index) => {
    const read = (field) => {
      const el = document.querySelector(`[data-acc="${index}"][data-acc-field="${field}"]`);
      return el ? el.value : '';
    };
    return {
      username: read('username').trim(),
      unique_id: read('unique_id').trim(),
      targets: read('targets').split(/\r?\n|,/).map((t) => t.trim()).filter(Boolean),
    };
  });

  const button = $('#save-config');
  button.disabled = true;
  try {
    const res = await api('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ settings, accounts }),
    });
    showToast(`已保存 ${res.updated.length} 项，备份 ${res.backup.split('/').pop()}`);
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
  if (!uniqueId) {
    showToast('请先填写 unique_id');
    return;
  }
  if (!raw) {
    showToast('请粘贴 Cookie JSON');
    return;
  }

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

// --------------------------------------------------------------------- 飞书通知

async function loadNotify() {
  const data = await api('/api/notify');
  $('#feishu-webhook').value = data.feishu_webhook || '';
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
    // 先保存当前输入，避免测到旧值
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

async function loadRuns() {
  const data = await api('/api/runs');
  $('#cron-spec').textContent = data.schedule || '未配置';

  const runs = data.runs || [];
  const lastOk = runs.length ? runs[0].status === 'Success' : null;
  $('#stat-last').textContent = runs.length
    ? (lastOk ? '成功' : '失败')
    : '—';
  $('#stat-last').style.color = lastOk === false
    ? 'var(--danger)' : 'var(--accent)';
  const dotLast = $('#dot-last');
  if (dotLast) {
    dotLast.className = `dot ${lastOk === false ? 'err' : (lastOk ? 'ok' : 'soft')}`;
  }

  $('#runs').innerHTML = runs.length ? runs.map((run) => {
    const ok = run.status === 'Success';
    const when = String(run.start_time).replace('T', ' ').slice(0, 19);
    return `<div class="run-row">
      <span class="t">${escapeHtml(when)}</span>
      <span>${run.duration_s}s</span>
      <span class="badge ${ok ? 'ok' : 'err'}">${ok ? '成功' : escapeHtml(run.message || '失败')}</span>
    </div>`;
  }).join('') : '<p class="empty">暂无运行记录。</p>';
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
  try {
    data = await api('/api/run');
  } catch {
    clearInterval(runTimer);
    return;
  }
  if (!data.running) {
    clearInterval(runTimer);
    runTimer = null;
    $('#run-now').disabled = false;
    showToast(data.returncode === 0 ? '执行成功' : `执行失败（退出码 ${data.returncode}）`);
    await Promise.all([loadRuns(), loadLogs(), loadConfig()]);
  }
}

(async function bootstrap() {
  try {
    await api('/api/me');
    showApp();
    await Promise.all([loadConfig(), loadNotify(), loadRuns(), loadLogs()]);
  } catch {
    showGate();
  }
})();
