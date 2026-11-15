'use strict';

const $ = id => document.getElementById(id);
const phaseLabels = {
  idle: '等待两人举手',
  preparing: '正在准备',
  inviting: '正在提醒双方',
  awaiting_actions: '等待两人举手',
  confirming: '匹配成功',
  approaching: '匹配成功',
  stopping: '正在停止',
  stopped: '演示已停止',
  expired: '演示已结束',
  failed: '本轮未完成',
};
const activePhases = new Set(['preparing', 'inviting', 'awaiting_actions', 'confirming', 'approaching', 'stopping']);
let latest = null;
let online = false;
let pending = null;
let stopping = false;
let actionEpoch = 0;
let token = null;

function text(id, value) {
  if ($(id).textContent !== value) $(id).textContent = value;
}

function line(id, value) {
  text(id, value);
  $(id).hidden = !value;
}

function status(id, value, kind = '') {
  text(id, value);
  $(id).dataset.kind = kind;
}

async function request(path, options = {}, timeout = 2500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {...options, cache: 'no-store', signal: controller.signal});
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 403) token = null;
      throw new Error(data.error || '操作未完成');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('请求超时，请查看当前状态。');
    if (error instanceof TypeError || error instanceof SyntaxError) throw new Error('无法读取本机服务。');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function post(path, body, timeout) {
  token ??= (await request('/api/session')).token;
  return request(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Vexo-Token': token},
    body: JSON.stringify(body),
  }, timeout);
}

function bandStatus(number, band) {
  const connected = band?.connected === true;
  if (!band || band.status === 'stale') status(`band-${number}`, '状态未知', 'warning');
  else if (!connected) status(`band-${number}`, '未连接', 'warning');
  else status(`band-${number}`, '已连接', 'ready');

  const gesture = `gesture-${number}`;
  if (!connected) status(gesture, '举手状态不可用');
  else if (!band.ready) status(gesture, '举手准备中');
  else if (band.active) status(gesture, '已举手', 'ready');
  else status(gesture, '等待举手');
}

function controls() {
  const active = activePhases.has(latest?.phase);
  $('stop').hidden = !active && !stopping;
  $('stop').disabled = stopping;
  $('reset').disabled = !online || active || stopping || Boolean(pending);
  $('reset').title = active ? '先停止演示，再重置举手' : '';
  $('connect').hidden = !online || active || stopping || latest?.whoop?.ready;
  $('connect').disabled = Boolean(pending) || latest?.whoop?.connecting;
  text('connect', pending === 'connect' || latest?.whoop?.connecting ? '正在重连 WHOOP' : '重连 WHOOP');
}

function render(data) {
  latest = data;
  online = true;
  const watch = data.watch || {};
  const whoop = data.whoop || {};
  if (watch.watch_ready) status('watch', '震动就绪', 'ready');
  else if (watch.watch_connected) status('watch', watch.watch_can_alert ? '仅通知' : '打开手表 App', 'warning');
  else status('watch', '震动未连接', 'warning');

  if (whoop.ready) status('whoop', '震动就绪', 'ready');
  else if (whoop.connecting) status('whoop', '震动重连中');
  else status('whoop', whoop.connected ? '震动未就绪' : '震动未连接', 'warning');

  const bands = data.motion?.bands || [];
  for (const number of [62, 77]) bandStatus(number, bands.find(band => band.band_number === number));

  status('phase', data.matched ? 'MATCH' : phaseLabels[data.phase] || '等待两人举手', data.matched ? 'ready' : '');
  let detail = '';
  if (data.phase === 'failed') {
    detail = data.detail || '';
  } else if (data.phase === 'confirming') {
    detail = data.paused_reason || '正在发送第一次震动。';
  } else if (data.matched && (data.phase === 'stopped' || data.phase === 'expired')) {
    detail = phaseLabels[data.phase];
  } else if (data.phase === 'approaching') {
    const proximity = data.proximity || {};
    const cadence = Number.isFinite(proximity.interval) ? `${proximity.label} · 目标间隔 ${proximity.interval} 秒` : '';
    detail = [cadence, data.paused_reason].filter(Boolean).join('。');
  } else if (data.phase === 'idle' && !whoop.ready) {
    detail = '等待 WHOOP 的震动连接。';
  } else if (data.phase === 'idle' && !watch.watch_ready) {
    detail = '打开并连接 VexoWatch，Apple Watch 也会一起震动。';
  }
  line('detail', detail);
  controls();
}

function disconnected() {
  online = false;
  for (const id of ['watch', 'whoop']) status(id, '状态未知', 'warning');
  for (const number of [62, 77]) bandStatus(number);
  status('phase', '本机服务未连接');
  line('detail', '');
  controls();
}

async function pollState() {
  const epoch = actionEpoch;
  try {
    const data = await request('/api/state');
    if (typeof data.phase !== 'string') throw new Error('状态不可用');
    if (epoch === actionEpoch) render(data);
  } catch {
    if (epoch === actionEpoch) disconnected();
  } finally {
    setTimeout(pollState, 500);
  }
}

async function pollHeartRate() {
  let readings = {};
  try {
    readings = await request('/api/heart-rate');
  } catch {
    // A missing stream clears its reading instead of showing an old value.
  }
  for (const [id, bpm] of [['apple-bpm', readings.apple_watch_bpm], ['whoop-bpm', readings.bpm]]) {
    text(id, Number.isFinite(bpm) ? `${bpm} BPM` : '— BPM');
  }
  setTimeout(pollHeartRate, 1000);
}

function feedback(message, error = false) {
  $('feedback').dataset.error = String(error);
  line('feedback', message);
}

async function action(kind, path, body, timeout) {
  if (pending || stopping) return;
  const epoch = actionEpoch;
  pending = kind;
  feedback(kind === 'reset' ? '正在重置…' : '');
  controls();
  try {
    const data = await post(path, body, timeout);
    if (epoch === actionEpoch) {
      actionEpoch += 1;
      render(data);
      feedback(kind === 'reset' ? '已重置举手状态。' : '');
    }
  } catch (error) {
    if (epoch === actionEpoch) feedback(error.message, true);
  } finally {
    pending = null;
    controls();
  }
}

$('reset').addEventListener('click', () => action('reset', '/api/motion/reset', {}, 4000));
$('connect').addEventListener('click', () => action('connect', '/api/connect', {}, 47000));
$('stop').addEventListener('click', async () => {
  if (stopping) return;
  actionEpoch += 1;
  stopping = true;
  feedback('正在停止…');
  controls();
  try {
    render(await post('/api/stop', {}, 25000));
    feedback('');
  } catch (error) {
    feedback(`未确认停止。 ${error.message}`, true);
  } finally {
    stopping = false;
    controls();
  }
});

pollState();
pollHeartRate();
