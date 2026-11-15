'use strict';

const byId = (id) => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const statusLabels = { waiting: '连接中', live: '实时接收', stale: '数据暂停', disconnected: '重新连接中', paused: '心率暂停' };
const statusMessages = {
  waiting: '等待 WHOOP 心率广播，请保持手环在 Mac 附近。',
  live: '已连接 WHOOP，页面自动更新。',
  stale: '暂时没有新读数。请确认手环戴好，心率广播保持开启。',
  disconnected: 'WHOOP 暂时断开，正在自动重连。请把手环靠近 Mac。',
  paused: '心率接收已暂停，举手匹配仍正常运行。',
};

function svgElement(name, attrs) {
  const element = document.createElementNS(svgNS, name);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
}

function drawChart(history, now) {
  const chart = byId('chart');
  chart.replaceChildren();
  const points = (Array.isArray(history) ? history : []).filter((p) =>
    Number.isFinite(p.time) && Number.isFinite(p.bpm) && p.time >= now - 60 && p.time <= now + 1);
  byId('empty').hidden = points.length > 0;
  if (!points.length) return;

  const values = points.map((p) => p.bpm);
  const middle = (Math.min(...values) + Math.max(...values)) / 2;
  const low = Math.floor(Math.min(Math.min(...values) - 5, middle - 15) / 5) * 5;
  const high = Math.ceil(Math.max(Math.max(...values) + 5, middle + 15) / 5) * 5;
  const left = 38, right = 750, top = 14, bottom = 176;
  const x = (t) => left + Math.max(0, Math.min(1, (t - now + 60) / 60)) * (right - left);
  const y = (bpm) => bottom - (bpm - low) / (high - low) * (bottom - top);
  for (const tick of [low, (low + high) / 2, high]) {
    chart.append(svgElement('line', { x1: left, x2: right, y1: y(tick), y2: y(tick), stroke: '#e9ebef', 'stroke-width': 1 }));
    const label = svgElement('text', { x: 0, y: y(tick) + 4 });
    label.textContent = Math.round(tick);
    chart.append(label);
  }
  let path = '', previous = null;
  for (const point of points) {
    // A missing stream creates a gap; never draw invented data across it.
    const command = !previous || point.time - previous.time > 3 ? 'M' : 'L';
    path += `${command}${x(point.time).toFixed(2)},${y(point.bpm).toFixed(2)} `;
    previous = point;
  }
  chart.append(svgElement('path', { d: path, fill: 'none', stroke: '#c63e48', 'stroke-width': 2.5,
    'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'vector-effect': 'non-scaling-stroke' }));
  const latest = points[points.length - 1];
  chart.append(svgElement('circle', { cx: x(latest.time), cy: y(latest.bpm), r: 3.5, fill: '#c63e48' }));
}

function render(data) {
  const state = typeof data.message === 'string' && /^心率接收(?:暂)?暂停/.test(data.message)
    ? 'paused' : Object.hasOwn(statusLabels, data.status) ? data.status : 'waiting';
  const live = state === 'live' && Number.isFinite(data.bpm);
  byId('source').textContent = data.source_name || 'WHOOP';
  byId('bpm').textContent = live ? Math.round(data.bpm) : '--';
  byId('status').className = `status ${state}`;
  byId('status-text').textContent = statusLabels[state];
  document.body.classList.toggle('live', live);
  byId('message').textContent = statusMessages[state];
  if (Number.isFinite(data.last_received_at)) {
    const stamp = new Date(data.last_received_at * 1000).toLocaleTimeString('zh-CN', { hour12: false });
    const age = Math.max(0, Math.floor(data.server_time - data.last_received_at));
    byId('updated').textContent = `最近更新 ${stamp}${age > 2 ? ` · ${age} 秒前` : ''}`;
  } else {
    byId('updated').textContent = '等待首个心率读数';
  }
  drawChart(data.history, Number.isFinite(data.server_time) ? data.server_time : Date.now() / 1000);
}

async function refresh() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);
  try {
    const response = await fetch('/api/state', { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch {
    byId('bpm').textContent = '--';
    byId('status').className = 'status disconnected';
    byId('status-text').textContent = '本地服务断开';
    byId('message').textContent = '本地接收程序暂时没有响应。请确认启动文件仍在运行，页面会自动重试。';
    document.body.classList.remove('live');
  } finally {
    clearTimeout(timeout);
    setTimeout(refresh, 1000);
  }
}

const bandNumbers = [62, 77];
const motionLabels = {
  raised: '已举起', lowered: '未举起', untrained: '待校准', unknown: '姿态待确认',
  triggered: '已触发', waiting_motion: '等待快速动作', arming: '准备中',
  disconnected: '未连接', stale: '数据暂停', waiting: '等待数据',
};
let motionTimer = null;
let motionController = null;
let motionGeneration = 0;
let motionRound = null;
let motionMode = 'pose';
let motionResetPending = false;

function motionPrompt() {
  if (motionMode === 'mixed') return '两只手环模式不同，暂不匹配';
  return motionMode === 'accel-latch' ? '各自快速举手一次，点亮本轮匹配' : '同时举起两个手环，点亮匹配';
}

function setMatch(active, message) {
  byId('motion-match').classList.toggle('is-match', active);
  byId('match-label').textContent = active ? 'MATCH' : '等待配对';
  // Avoid repeatedly announcing the same state on every poll.
  if (byId('match-message').textContent !== message) byId('match-message').textContent = message;
}

function clearMotion(state = 'waiting') {
  for (const number of bandNumbers) {
    byId(`band-${number}`).dataset.state = state;
    byId(`band-${number}-status`).textContent = motionLabels[state];
  }
  setMatch(false, state === 'disconnected' ? '等待手环状态恢复' : motionPrompt());
}

function renderMotion(data) {
  if (!data || !Array.isArray(data.bands) || !Number.isFinite(data.server_time)) {
    throw new Error('Invalid motion state');
  }
  const round = data.reset_generation ?? 'initial';
  if (typeof round !== 'string' || !round) throw new Error('Invalid reset generation');
  const states = bandNumbers.map((number) => {
    const candidates = data.bands.filter((band) => band && band.band_number === number);
    if (candidates.length !== 1) throw new Error('Missing or duplicate band');
    const band = candidates[0];
    const mode = band.mode ?? 'pose';
    if (mode !== 'pose' && mode !== 'accel-latch') throw new Error('Invalid motion mode');
    let status = Object.hasOwn(motionLabels, band.status) ? band.status : 'stale';
    if (status !== 'stale') {
      if (band.connected !== true) status = 'disconnected';
      else if (!Number.isFinite(band.updated_at) || data.server_time - band.updated_at > 2
        || band.updated_at > data.server_time + 1) status = 'stale';
      else if (band.ready !== true) status = mode === 'accel-latch' ? 'arming' : 'untrained';
      else if (mode === 'accel-latch') {
        if (band.reset_generation !== round) status = 'arming';
        else if (status === 'triggered' && (band.triggered !== true || band.active !== true)) status = 'stale';
        else if (status === 'waiting_motion' && band.triggered !== false) status = 'stale';
        else if (!['triggered', 'waiting_motion', 'arming'].includes(status)) status = 'stale';
      } else if (status === 'raised' && band.raised !== true) status = 'stale';
      else if (status === 'lowered' && band.raised !== false) status = 'stale';
      else if (!['raised', 'lowered', 'unknown', 'untrained'].includes(status)) status = 'stale';
    }
    const active = mode === 'accel-latch'
      ? status === 'triggered' && band.triggered === true && band.active === true
      : status === 'raised' && band.raised === true;
    return { number, status, mode, active };
  });
  motionRound = round;
  motionMode = states.every((band) => band.mode === states[0].mode) ? states[0].mode : 'mixed';
  const accelerationDemo = motionMode !== 'pose';
  byId('motion-title').textContent = accelerationDemo ? '快速动作触发演示' : '一起举手';
  byId('motion-description').textContent = accelerationDemo
    ? '明显的快速动作触发后保持亮起，点击“重置本轮”重新开始；这里不表示手臂高度或当前姿态。'
    : '校准下垂和上举姿态后显示当前状态；快速举手单独记录。';
  byId('motion-actions').hidden = !accelerationDemo;
  for (const band of states) {
    byId(`band-${band.number}`).dataset.state = band.status;
    byId(`band-${band.number}-status`).textContent = motionLabels[band.status];
  }
  const matched = data.match === true && motionMode !== 'mixed' && states.every((band) => band.active);
  setMatch(matched, matched
    ? (motionMode === 'accel-latch' ? '两个手环本轮均已触发' : '两个手环都已举起')
    : motionPrompt());
}

async function refreshMotion() {
  if (document.hidden || motionResetPending) return;
  const generation = motionGeneration;
  const roundAtRequest = motionRound;
  const controller = new AbortController();
  motionController = controller;
  const timeout = setTimeout(() => controller.abort(), 1500);
  try {
    const response = await fetch('/api/motion', { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (generation === motionGeneration && roundAtRequest === motionRound
      && !document.hidden && !motionResetPending) renderMotion(data);
  } catch {
    if (generation === motionGeneration) clearMotion('disconnected');
  } finally {
    clearTimeout(timeout);
    if (generation === motionGeneration) {
      motionController = null;
      if (!document.hidden && !motionResetPending) motionTimer = setTimeout(refreshMotion, 500);
    }
  }
}

async function resetMotionRound() {
  if (motionResetPending) return;
  motionResetPending = true;
  motionGeneration += 1;
  clearTimeout(motionTimer);
  motionTimer = null;
  if (motionController) motionController.abort();
  motionController = null;
  byId('motion-reset').disabled = true;
  byId('motion-feedback').dataset.error = 'false';
  byId('motion-feedback').textContent = '正在重置…';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetch('/api/motion/reset', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      cache: 'no-store', signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (typeof data.generation !== 'string' || data.generation !== data.reset_generation) {
      throw new Error('Invalid reset response');
    }
    motionGeneration += 1;
    renderMotion(data);
    byId('motion-feedback').textContent = '本轮已重置。静止片刻后可开始下一轮。';
  } catch {
    byId('motion-feedback').dataset.error = 'true';
    byId('motion-feedback').textContent = '未能确认重置，请重试。';
  } finally {
    clearTimeout(timeout);
    motionResetPending = false;
    byId('motion-reset').disabled = false;
    if (!document.hidden) motionTimer = setTimeout(refreshMotion, 0);
  }
}

function resetMotionPolling() {
  motionGeneration += 1;
  clearTimeout(motionTimer);
  motionTimer = null;
  if (motionController) motionController.abort();
  motionController = null;
  clearMotion();
  if (!document.hidden && !motionResetPending) refreshMotion();
}

byId('motion-reset').addEventListener('click', resetMotionRound);
document.addEventListener('visibilitychange', resetMotionPolling);
window.addEventListener('pagehide', () => {
  motionGeneration += 1;
  clearTimeout(motionTimer);
  if (motionController) motionController.abort();
  clearMotion();
});
window.addEventListener('pageshow', resetMotionPolling);

refresh();
resetMotionPolling();
