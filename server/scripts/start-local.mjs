// Starts only the web app, backend and HTTP adapter. Existing BLE owners stay running.
import { spawn } from 'node:child_process'
import { access } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../../', import.meta.url))
const serverDir = fileURLToPath(new URL('../', import.meta.url))
const webDir = fileURLToPath(new URL('../../web/', import.meta.url))
const backend = 'http://127.0.0.1:8787'
const frontend = 'http://127.0.0.1:5174'
const children = []
let stopping = false
function stop(code = 0) {
  if (stopping) return
  stopping = true
  process.exitCode = code
  for (const child of children) child.kill('SIGTERM')
  if (children.length) setTimeout(() => { for (const child of children) child.kill('SIGKILL'); process.exit(code) }, 5000).unref()
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => stop())
function start(args, cwd, env = {}) {
  const child = spawn(process.execPath, args, { cwd, env: { ...process.env, ...env }, stdio: 'inherit' })
  children.push(child)
  child.on('error', () => { console.error('Could not start a local service.'); stop(1) })
  child.on('exit', () => { if (!stopping) { console.error('A local service exited; stopping only services started here.'); stop(1) } })
}
async function response(url) {
  try { return await fetch(url, { signal: AbortSignal.timeout(1000) }) } catch { return null }
}
async function health() {
  const res = await response(backend + '/health')
  if (!res) return null
  const body = await res.json().catch(() => null)
  if (!res.ok || body?.agents !== 'mastra' || !('motion_mode' in body)) throw new Error('Port 8787 is occupied by another or outdated backend.')
  if (body.motion_mode !== 'accel-latch') throw new Error('Existing backend must use HARDWARE_MODE=accel-latch.')
  return body
}
async function waitFor(check, label) {
  const until = Date.now() + 12000
  while (Date.now() < until && !stopping) {
    if (await check()) return
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
  throw new Error(`${label} did not become ready.`)
}

try {
  await Promise.all([access(repo + 'web/node_modules/vite/bin/vite.js'), access(serverDir + 'node_modules/ws')])
  if (!await health()) {
    start(['--env-file-if-exists=.env', 'src/index.mjs'], serverDir,
      { PORT: '8787', HOST: '127.0.0.1', HARDWARE_MODE: 'accel-latch' })
    await waitFor(health, 'Backend')
  }
  const page = await response(frontend)
  if (page && (!page.ok || !(await page.text()).includes('<title>Wingman</title>'))) throw new Error('Port 5174 is already occupied by another app.')
  if (!page) {
    start([repo + 'web/node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5174', '--strictPort'], webDir)
    await waitFor(async () => (await response(frontend))?.ok, 'Frontend')
  }
  if (!(await health()).hardware_bridge) {
    start(['--env-file-if-exists=.env', 'scripts/vexo-bridge.mjs'], serverDir, { WINGMAN_URL: 'ws://127.0.0.1:8787' })
    await waitFor(async () => (await health())?.hardware_bridge, 'Hardware adapter')
  }
  console.log(`\nA / Vexo 62: ${frontend}/?band=A&hardware=1\nB / Vexo 77: ${frontend}/?band=B&hardware=1\nRoom: ${frontend}/room?hardware=1`)
  console.log('Existing hardware services are untouched. Keep this terminal open for services started here.')
} catch (error) {
  console.error(error.code === 'ENOENT' ? 'Install dependencies first: npm ci in server/ and web/.' : error.message)
  stop(1)
}
