// Offline DOM/fetch harness for the real motion UI, including reset races.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../dashboard/app.js'), 'utf8');
const motionScript = script.slice(script.indexOf('const bandNumbers ='));

function harness() {
  const elements = new Map();
  function byId(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        textContent: '', dataset: {}, hidden: false, disabled: false,
        addEventListener() {},
        classList: {
          toggle(name, value) { if (value) classes.add(name); else classes.delete(name); },
          contains(name) { return classes.has(name); },
        },
      });
    }
    return elements.get(id);
  }
  const requests = [];
  const context = vm.createContext({
    byId, document: { hidden: false, addEventListener() {} },
    window: { addEventListener() {} }, AbortController,
    setTimeout() { return 1; }, clearTimeout() {}, refresh() {},
    fetch(url, options) {
      return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
    },
  });
  vm.runInContext(motionScript, context);
  return { context, byId, requests, matched: () => byId('motion-match').classList.contains('is-match') };
}

function snapshot(round = 'initial', triggered = true) {
  return {
    match: triggered, mode: 'accel-latch', reset_generation: round, server_time: 100,
    bands: [62, 77].map((number) => ({
      band_number: number, mode: 'accel-latch', raised: false, connected: true,
      ready: true, updated_at: 100, reset_generation: round,
      triggered, active: triggered, status: triggered ? 'triggered' : 'waiting_motion',
    })),
  };
}

function response(data) {
  return { ok: true, json: async () => data };
}

async function main() {
  {
    const ui = harness();
    ui.context.renderMotion(snapshot());
    assert.equal(ui.matched(), true);
    assert.equal(ui.byId('match-label').textContent, 'MATCH');
    const reset = ui.context.resetMotionRound();
    assert.equal(ui.byId('motion-reset').disabled, true);
    assert.equal(ui.matched(), true, 'pending POST must not pretend the reset succeeded');
    await ui.context.resetMotionRound();
    assert.equal(ui.requests.length, 2, 'second click cannot start another reset');
    assert.equal(ui.requests[1].url, '/api/motion/reset');
    assert.equal(ui.requests[1].options.method, 'POST');
    assert.equal(ui.requests[1].options.body, '{}');
    ui.requests[1].resolve(response({ generation: 'next', ...snapshot('next', false) }));
    await reset;
    assert.equal(ui.matched(), false);
    assert.equal(ui.byId('match-label').textContent, '等待配对');
    assert.equal(ui.byId('motion-reset').disabled, false);
    ui.requests[0].resolve(response(snapshot()));
    await new Promise(setImmediate);
    assert.equal(ui.matched(), false, 'a pre-reset GET cannot restore the previous MATCH');
    assert.equal(ui.byId('band-62-status').textContent, '等待快速动作');
  }
  {
    const ui = harness();
    ui.context.renderMotion(snapshot());
    const reset = ui.context.resetMotionRound();
    ui.requests[1].resolve({ ok: false, status: 503 });
    await reset;
    assert.equal(ui.matched(), true, 'failed POST must preserve the last confirmed state');
    assert.equal(ui.byId('band-62-status').textContent, '已触发');
    assert.equal(ui.byId('motion-feedback').dataset.error, 'true');
    assert.equal(ui.byId('motion-reset').disabled, false);
  }
  {
    const ui = harness();
    const mixed = snapshot();
    Object.assign(mixed.bands[0], { mode: 'pose', raised: true, status: 'raised' });
    ui.context.renderMotion(mixed);
    assert.equal(ui.matched(), false);
    const oldRound = snapshot();
    oldRound.reset_generation = 'next';
    ui.context.renderMotion(oldRound);
    assert.equal(ui.matched(), false);
    assert.equal(ui.byId('band-62-status').textContent, '准备中');
    const stale = snapshot();
    stale.bands[1].updated_at = 97;
    ui.context.renderMotion(stale);
    assert.equal(ui.matched(), false);
    assert.equal(ui.byId('band-77-status').textContent, '数据暂停');
    const legacy = { match: true, server_time: 100, bands: [62, 77].map((number) => ({
      band_number: number, raised: true, connected: true, ready: true,
      status: 'raised', updated_at: 100,
    })) };
    ui.context.renderMotion(legacy);
    assert.equal(ui.matched(), true);
    assert.equal(ui.byId('motion-title').textContent, '一起举手');
    assert.equal(ui.byId('motion-actions').hidden, true);
  }
  process.stdout.write('Motion UI reset race, error, freshness, mode and legacy checks passed.\n');
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
