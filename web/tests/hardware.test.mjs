import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { buildSync } from 'esbuild'

const require = createRequire(import.meta.url)
const { createElement } = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const compiled = buildSync({
  stdin: {
    contents: `export * from './src/hardware'; export * from './src/voice/LiveCards'; export {devMode, hardwareMode} from './src/ws';`,
    resolveDir: fileURLToPath(new URL('..', import.meta.url)),
    loader: 'ts',
  },
  bundle: true, platform: 'node', format: 'cjs', packages: 'external', write: false,
})
const module = { exports: {} }
const previousLocation = globalThis.location
globalThis.location = new URL('http://127.0.0.1:5174/?band=A&hardware=1&dev=1')
try {
  new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, module, module.exports)
} finally {
  if (previousLocation === undefined) delete globalThis.location
  else globalThis.location = previousLocation
}
const { appendHeart, freshHeart, updateStageHeart, motionLabel, HeartCard, BandsCard, hardwareMode, devMode } = module.exports

test('hardware mode disables the fake console even when dev=1 is supplied', () => {
  assert.equal(hardwareMode, true)
  assert.equal(devMode, false)
})

test('source timestamps, null invalidation and clock-based staleness are preserved', () => {
  let samples = appendHeart([], { bpm: 91, at: 100_000, source: 'Apple Watch' })
  assert.equal(samples[0].at, 100_000)
  assert.equal(freshHeart(samples[0], 107_999), true)
  assert.equal(freshHeart(samples[0], 108_001), false)
  assert.equal(freshHeart(samples[0], 98_999), false)
  samples = appendHeart(samples, { bpm: null, at: 99_999, source: 'Apple Watch' })
  assert.equal(freshHeart(samples.at(-1), 100_000), false, 'null clears even when the bridge has an older source timestamp')
  assert.deepEqual(appendHeart(samples, { bpm: NaN, at: 100_001 }), [])
  assert.deepEqual(appendHeart(samples, { bpm: 80, at: Infinity }), [])
})

test('stale and null cards show -- and stop pulsing, with the actual source label', () => {
  const originalNow = Date.now
  Date.now = () => 100_000
  try {
    const live = renderToStaticMarkup(createElement(HeartCard, { samples: [{ bpm: 91, at: 99_000, source: 'Apple Watch' }] }))
    assert.match(live, /91<small>bpm/)
    assert.match(live, /Apple Watch/)
    assert.match(live, /animation-play-state:running/)
    for (const sample of [{ bpm: 91, at: 90_000, source: 'WHOOP' }, { bpm: null, at: 100_000, source: 'WHOOP' }]) {
      const stopped = renderToStaticMarkup(createElement(HeartCard, { samples: [sample] }))
      assert.match(stopped, /--<small>bpm/)
      assert.match(stopped, /Heart rate unavailable/)
      assert.match(stopped, /animation-play-state:paused/)
      assert.match(stopped, /Waiting for WHOOP/)
    }
  } finally {
    Date.now = originalNow
  }
})

test('stage heart rate continues through a missing feed and resumes with the next valid reading', () => {
  let state = updateStageHeart({ samples: [], backup: true }, 100_000)
  assert.equal(state.samples.at(-1).bpm, 90)
  state = updateStageHeart(state, 101_000, { reading: { bpm: 96, at: 101_000, source: 'WHOOP' } })
  assert.equal(state.backup, false)
  assert.equal(state.samples.at(-1).bpm, 96)
  state = updateStageHeart(state, 102_000, { reading: { bpm: null, at: 102_000 } })
  assert.equal(state.backup, true)
  assert.equal(state.samples.at(-1).bpm, 96)
  assert.equal(updateStageHeart(state, 105_000, { step: -1 }), state)
  state = updateStageHeart(state, 106_000, { step: -1 })
  assert.equal(state.samples.at(-1).bpm, 95)
  state = updateStageHeart(state, 107_000, { reading: { bpm: 103, at: 105_500, source: 'WHOOP' } })
  assert.equal(state.backup, false)
  assert.equal(state.samples.at(-1).bpm, 103)

  const disconnected = updateStageHeart(state, 107_500, { disconnected: true })
  assert.equal(disconnected.samples.at(-1).bpm, 100)
  assert.equal(updateStageHeart(disconnected, 111_500).samples.at(-1).bpm, 99)
  assert.equal(updateStageHeart(state, 114_000).backup, true)
  const card = renderToStaticMarkup(createElement(HeartCard, { samples: disconnected.samples, holdLatest: true }))
  assert.match(card, /100<small>bpm/)
  assert.doesNotMatch(card, /WHOOP|simulated|unavailable/)
})

test('confirmed match does not manufacture raised or triggered hardware states', () => {
  const html = renderToStaticMarkup(createElement(BandsCard, {
    you: 'unknown', them: 'down', latched: true, met: true, theirName: 'Sam', instruction: '',
  }))
  assert.match(html, /Unavailable/)
  assert.match(html, /Waiting/)
  assert.doesNotMatch(html, /is-up|turned green|Both raised/)
  assert.equal(motionLabel('up', true), 'Triggered')
  assert.equal(motionLabel('down', true), 'Waiting')
  assert.equal(motionLabel('up', false), 'Raised')
})
