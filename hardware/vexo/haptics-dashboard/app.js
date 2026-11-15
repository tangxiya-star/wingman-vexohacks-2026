'use strict';

const $ = id => document.getElementById(id);
const phaseLabels = {
  idle: 'Waiting for both hand raises',
  preparing: 'Getting ready…',
  inviting: 'Notifying both participants…',
  awaiting_actions: 'Waiting for both hand raises',
  confirming: 'Match confirmed',
  approaching: 'Match confirmed',
  stopping: 'Stopping…',
  stopped: 'Demo stopped',
  expired: 'Demo ended',
  failed: 'Round incomplete',
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
      throw new Error(data.error || 'The action could not be completed.');
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Request timed out. Check the current status.');
    if (error instanceof TypeError || error instanceof SyntaxError) throw new Error('Could not reach the local service.');
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
  if (!band || band.status === 'stale') status(`band-${number}`, 'Status unknown', 'warning');
  else if (!connected) status(`band-${number}`, 'Disconnected', 'warning');
  else status(`band-${number}`, 'Connected', 'ready');

  const gesture = `gesture-${number}`;
  if (!connected) status(gesture, 'Gesture status unavailable');
  else if (!band.ready) status(gesture, 'Getting ready for a hand raise');
  else if (band.active) status(gesture, 'Hand raise detected', 'ready');
  else status(gesture, 'Waiting for a hand raise');
}

function controls() {
  const active = activePhases.has(latest?.phase);
  $('stop').hidden = !active && !stopping;
  $('stop').disabled = stopping;
  $('force-match').disabled = !online || stopping || Boolean(pending);
  $('reset-wingman').disabled = !online || stopping || Boolean(pending);
  $('reset').disabled = !online || active || stopping || Boolean(pending);
  $('reset').title = active ? 'Stop the demo before resetting gestures.' : '';
  $('connect').hidden = !online || active || stopping || latest?.whoop?.ready;
  $('connect').disabled = Boolean(pending) || latest?.whoop?.connecting;
  text('connect', pending === 'connect' || latest?.whoop?.connecting ? 'Reconnecting WHOOP…' : 'Reconnect WHOOP');
}

function render(data) {
  latest = data;
  online = true;
  const watch = data.watch || {};
  const whoop = data.whoop || {};
  if (watch.watch_ready) status('watch', 'Haptics ready', 'ready');
  else if (watch.watch_connected) status('watch', watch.watch_can_alert ? 'Notifications only' : 'Open VexoWatch', 'warning');
  else status('watch', 'Haptics disconnected', 'warning');

  if (whoop.ready) status('whoop', 'Haptics ready', 'ready');
  else if (whoop.connecting) status('whoop', 'Reconnecting haptics…');
  else status('whoop', whoop.connected ? 'Haptics unavailable' : 'Haptics disconnected', 'warning');

  const bands = data.motion?.bands || [];
  for (const number of [62, 77]) bandStatus(number, bands.find(band => band.band_number === number));

  status('phase', data.matched ? 'MATCH' : phaseLabels[data.phase] || 'Waiting for both hand raises', data.matched ? 'ready' : '');
  let detail = '';
  if (data.phase === 'failed') {
    detail = data.detail || '';
  } else if (data.phase === 'confirming') {
    detail = data.paused_reason || 'Sending the first vibration.';
  } else if (data.matched && (data.phase === 'stopped' || data.phase === 'expired')) {
    detail = phaseLabels[data.phase];
  } else if (data.phase === 'approaching') {
    const proximity = data.proximity || {};
    const cadence = Number.isFinite(proximity.interval) ? `${proximity.label} · Target interval: ${proximity.interval} s` : '';
    detail = [cadence, data.paused_reason].filter(Boolean).join(' · ');
  } else if (data.phase === 'idle' && !whoop.ready) {
    detail = 'Waiting for WHOOP haptics to connect.';
  } else if (data.phase === 'idle' && !watch.watch_ready) {
    detail = 'Open VexoWatch and connect it to enable Apple Watch haptics.';
  }
  line('detail', detail);
  controls();
}

function disconnected() {
  online = false;
  for (const id of ['watch', 'whoop']) status(id, 'Status unknown', 'warning');
  for (const number of [62, 77]) bandStatus(number);
  status('phase', 'Local service disconnected');
  line('detail', '');
  controls();
}

async function pollState() {
  const epoch = actionEpoch;
  try {
    const data = await request('/api/state');
    if (typeof data.phase !== 'string') throw new Error('Status unavailable');
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
  const resetting = kind === 'reset' || kind === 'reset-wingman';
  feedback(resetting ? 'Resetting…' : kind === 'force-match' ? 'Confirming the match…' : '');
  controls();
  try {
    const data = await post(path, body, timeout);
    if (epoch === actionEpoch) {
      actionEpoch += 1;
      render(data);
      const messages = {
        'force-match': 'Match confirmed on Wingman A and B.',
        'reset-wingman': 'Wingman A and B are back at the start.',
        reset: 'Gesture status reset.',
      };
      feedback(messages[kind] || '');
    }
  } catch (error) {
    if (epoch === actionEpoch) feedback(error.message, true);
  } finally {
    pending = null;
    controls();
  }
}

$('reset').addEventListener('click', () => action('reset', '/api/motion/reset', {}, 4000));
$('force-match').addEventListener('click', () => action('force-match', '/api/wingman/force-match', {}, 6000));
$('reset-wingman').addEventListener('click', () => action('reset-wingman', '/api/wingman/reset', {}, 30000));
$('connect').addEventListener('click', () => action('connect', '/api/connect', {}, 47000));
$('stop').addEventListener('click', async () => {
  if (stopping) return;
  actionEpoch += 1;
  stopping = true;
  feedback('Stopping…');
  controls();
  try {
    render(await post('/api/stop', {}, 25000));
    feedback('');
  } catch (error) {
    feedback(`Could not confirm that the demo stopped. ${error.message}`, true);
  } finally {
    stopping = false;
    controls();
  }
});

pollState();
pollHeartRate();
