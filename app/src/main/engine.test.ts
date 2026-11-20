// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { afterAll, afterEach, beforeAll, expect, it, vi } from 'vitest'
import type { BuildEvent } from '../shared/types'
import { createEngine, thinkArgs, type Engine } from './engine'

// A stand-in for `python`: it answers as `project.app_api serve`, `project.app_api open`,
// `project.app_think` and `project.produce --build` would.
const FAKE = `
const [, module, command] = process.argv.slice(2)
// What a real build does: start a program of its own (FFmpeg, HyperFrames' browser, OpenShot's render), and wait on it.
// On Windows Node ends its own children when it dies and Python does not: detached stands in for Python's.
const program = () => {
  const grandchild = process.getBuiltinModule('child_process').spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore', detached: process.platform === 'win32' })
  console.log('    started ' + grandchild.pid)
  setInterval(() => {}, 1000)
}
if (module === 'project.app_api' && command === 'serve') {
  const say = (answer) => process.stdout.write(JSON.stringify(answer) + '\\n')
  let pending = ''
  process.stdin.setEncoding('utf8')
  process.stdin.on('data', (chunk) => {
    const lines = (pending + chunk).split('\\n')
    pending = lines.pop()
    for (const line of lines) {
      const { id, method, params } = JSON.parse(line)
      if (method === 'videos') say({ id, result: [{ folder: params.root, title: 'T' }] })
      else if (method === 'echo') say({ id, result: params })
      else if (method === 'cwd') say({ id, result: process.cwd() })
      else if (method === 'pid') say({ id, result: process.pid })
      else if (method === 'late') setTimeout(() => say({ id, result: 'late' }), 300)
      else if (method === 'soon') say({ id, result: 'soon' })
      else if (method === 'silent') {}
      else if (method === 'die') { process.stderr.write('Traceback: boom\\n'); process.exit(3) }
      else if (method === 'split') {
        // One answer in two writes, cut inside the three bytes of its en dash.
        const bytes = Buffer.from(JSON.stringify({ id, result: '0:45–0:47' }) + '\\n')
        const cut = bytes.indexOf(0xe2) + 1
        process.stdout.write(bytes.subarray(0, cut))
        setTimeout(() => process.stdout.write(bytes.subarray(cut)), 150)
      }
      else say({ id, error: 'storyboard.json is not valid JSON' })
    }
  })
} else if (module === 'project.app_api' && command === 'open') {
  console.log('==> Opening it in OpenShot')
  console.error('Build the video first: there is no OpenShot project yet.')
  process.exit(1)
} else if (module === 'project.app_think') {
  const [, folder = ''] = process.argv.slice(4)
  const mine = Object.fromEntries(Object.entries(process.env).filter(([name]) => name.startsWith('FRAMEFLOW_')))
  if (command === 'test') { console.log('Ready: Claude Code'); process.exit(0) }
  console.log('==> Writing the plan with Claude Code')
  console.log('    args ' + JSON.stringify(process.argv.slice(4)))
  console.log('    env ' + JSON.stringify(mine))
  console.log('    base ' + JSON.stringify(process.env.ANTHROPIC_BASE_URL ?? null))
  if (folder.includes('outside')) { console.error('The storyboard changed outside the app.'); process.exit(3) }
  if (folder.includes('refused')) { console.error('The music has no volume to change.'); process.exit(4) }
  if (folder.includes('tree')) program()
  else if (command === 'approve') console.log('==> Done {"storyboard": "C:/v/storyboard.json"}')
} else {
  const folder = command
  console.log('==> Building the project')
  console.log('    5 scenes, 9.0s (brief asked for about 15s)')
  if (folder.includes('broken')) { console.error('storyboard.json needs fixing:\\n  scene 2 (footage): ends after its recording'); process.exit(1) }
  if (folder.includes('tree')) program()
  else if (folder.includes('slow')) setTimeout(() => console.log('==> Looking at the picture'), 20000)
  else console.log('==> Looking at the picture')
  if (folder.includes('previewed')) {
    console.log('==> Making a preview to watch in the app')
    if (folder.includes('long')) program()
    else console.log('    skipped: OpenShot is not installed')
  }
}
`

const alive = (pid: number): boolean => {
  try {
    process.kill(pid, 0)
    return true
  } catch {
    return false
  }
}

let dir: string
let engine: Engine

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'ff engine ')) // a space in the path, as in "E:\my projects"
  writeFileSync(join(dir, 'fake.js'), FAKE)
  engine = createEngine({ python: [process.execPath, join(dir, 'fake.js')], root: dir })
})
afterEach(() => engine.stopAll())
afterAll(() => rmSync(dir, { recursive: true, force: true }))

it('call resolves with the answer to its own request', async () => {
  expect(await engine.call('videos', { root: dir })).toEqual([{ folder: dir, title: 'T' }])
})

it('calls run in the root folder', async () => {
  expect(await engine.call('cwd', {})).toBe(dir)
})

it('two calls answered out of order each get their own answer', async () => {
  const [late, soon] = await Promise.all([engine.call('late', {}), engine.call('soon', {})])
  expect([late, soon]).toEqual(['late', 'soon'])
})

it('one engine answers many calls', async () => {
  const pids = await Promise.all([
    engine.call('pid', {}),
    engine.call('pid', {}),
    engine.call('pid', {})
  ])
  expect(new Set(pids).size).toBe(1)
})

it("an error answer rejects with the engine's own words", async () => {
  await expect(engine.call('describe', { folder: dir })).rejects.toThrow(
    'storyboard.json is not valid JSON'
  )
})

it('call says what it could not start when the program is not there', async () => {
  const missing = createEngine({ python: ['no-such-python-here'], root: dir })
  await expect(missing.call('videos', { root: dir })).rejects.toThrow(
    /Could not start `no-such-python-here`/
  )
})

it('an engine that dies rejects what was pending, and the next call starts a new one', async () => {
  const first = await engine.call('pid', {})
  const waiting = engine.call('late', {})
  await expect(engine.call('die', {})).rejects.toThrow('The engine stopped: Traceback: boom')
  await expect(waiting).rejects.toThrow('The engine stopped')
  const second = await engine.call('pid', {})
  expect(second).not.toBe(first)
})

it('a call left unanswered is rejected in time', async () => {
  const impatient = createEngine({
    python: [process.execPath, join(dir, 'fake.js')],
    root: dir,
    timeout: 300
  })
  await expect(impatient.call('silent', {})).rejects.toThrow('The engine did not answer silent.')
  impatient.stopAll()
})

it('a character split across two chunks of an answer arrives whole', async () => {
  expect(await engine.call('split', {})).toBe('0:45–0:47')
})

it('a folder path with spaces arrives as one value', async () => {
  const folder = join(dir, 'my video', 'take 2')
  expect(await engine.call('echo', { folder })).toEqual({ folder })
})

it('stopAll ends the programs a build started, not only the build', async () => {
  let pid = 0
  const running = engine.build(join(dir, 'tree'), (e) => {
    if (e.type === 'detail' && e.text.startsWith('started ')) pid = Number(e.text.slice(8))
  })
  await vi.waitFor(() => expect(pid).toBeGreaterThan(0), { timeout: 5000 })
  expect(alive(pid)).toBe(true)
  engine.stopAll()
  await running
  await vi.waitFor(() => expect(alive(pid)).toBe(false), { timeout: 10000 })
}, 20000)

it('build turns "==> " lines into steps and indented lines into details, then says it is done', async () => {
  const events: BuildEvent[] = []
  await engine.build(join(dir, 'reel'), (e) => events.push(e))
  expect(events).toEqual([
    { type: 'step', text: 'Building the project' },
    { type: 'detail', text: '5 scenes, 9.0s (brief asked for about 15s)' },
    { type: 'step', text: 'Looking at the picture' },
    { type: 'done', ok: true }
  ])
})

it('a build says it is built when its preview starts, and done when the run ends', async () => {
  const events: BuildEvent[] = []
  await engine.build(join(dir, 'previewed'), (e) => events.push(e))
  expect(events).toEqual([
    { type: 'step', text: 'Building the project' },
    { type: 'detail', text: '5 scenes, 9.0s (brief asked for about 15s)' },
    { type: 'step', text: 'Looking at the picture' },
    { type: 'built' },
    { type: 'detail', text: 'skipped: OpenShot is not installed' },
    { type: 'done', ok: true }
  ])
})

it('building again while the preview renders stops that run and starts a new build', async () => {
  const folder = join(dir, 'previewed long')
  const first: BuildEvent[] = []
  let pid = 0
  const replaced = engine.build(folder, (e) => {
    first.push(e)
    if (e.type === 'detail' && e.text.startsWith('started ')) pid = Number(e.text.slice(8))
  })
  await vi.waitFor(() => expect(pid).toBeGreaterThan(0), { timeout: 5000 })
  const second: BuildEvent[] = []
  const again = engine.build(folder, (e) => second.push(e))
  await replaced // its promise resolves, though it says nothing more
  await vi.waitFor(() => expect(alive(pid)).toBe(false), { timeout: 10000 })
  await vi.waitFor(() => expect(second).toContainEqual({ type: 'built' }), { timeout: 5000 })
  expect(second.filter((e) => e.type === 'step')).toEqual([
    { type: 'step', text: 'Building the project' },
    { type: 'step', text: 'Looking at the picture' }
  ])
  // Nothing of the new build's, and no done.
  expect(first.map((e) => e.type)).toEqual(['step', 'detail', 'step', 'built', 'detail'])
  engine.stopAll()
  await again
}, 20000)

it('a build that fails is done with what the engine said', async () => {
  const events: BuildEvent[] = []
  await engine.build(join(dir, 'broken'), (e) => events.push(e))
  expect(events.at(-1)).toEqual({
    type: 'done',
    ok: false,
    message: 'storyboard.json needs fixing:\n  scene 2 (footage): ends after its recording'
  })
})

it('a second build of the same folder is refused while the first runs', async () => {
  const folder = join(dir, 'slow')
  const first = engine.build(folder, () => {})
  await expect(engine.build(folder, () => {})).rejects.toThrow('already building')
  engine.stopAll()
  await first
})

it('open streams its steps like a build, and a failure says why', async () => {
  const events: BuildEvent[] = []
  await engine.open(join(dir, 'reel'), (e) => events.push(e))
  expect(events).toEqual([
    { type: 'step', text: 'Opening it in OpenShot' },
    { type: 'done', ok: false, message: 'Build the video first: there is no OpenShot project yet.' }
  ])
})

it('a video can be opened while it builds, but not opened twice at once', async () => {
  const folder = join(dir, 'slow')
  const building = engine.build(folder, () => {})
  const opening = engine.open(folder, () => {})
  await expect(engine.open(folder, () => {})).rejects.toThrow('already opening')
  await opening
  expect(engine.building(folder)).toBe(true)
  engine.stopAll()
  await building
})

it('stopAll ends a running build', async () => {
  const events: BuildEvent[] = []
  const running = engine.build(join(dir, 'slow'), (e) => events.push(e))
  await new Promise((r) => setTimeout(r, 300))
  engine.stopAll()
  await running
  expect(events.at(-1)).toMatchObject({ type: 'done', ok: false })
  expect(engine.building(join(dir, 'slow'))).toBe(false)
})

// What the stand-in printed of a thinking job: its arguments, and the FRAMEFLOW_ variables it was given.
const printed = (events: BuildEvent[], what: 'args' | 'env' | 'base'): unknown => {
  const detail = events.find((e) => e.type === 'detail' && e.text.startsWith(`${what} `))
  return detail?.type === 'detail' ? JSON.parse(detail.text.slice(what.length + 1)) : undefined
}

it('think runs the thinking command with the thinker it is given, and none the app inherited', async () => {
  process.env['FRAMEFLOW_THINKER'] = 'standin:C:/x.json'
  process.env['FRAMEFLOW_KEY'] = 'inherited'
  process.env['FRAMEFLOW_WHISPER_CLI'] = 'C:/whisper-cli.exe'
  try {
    const folder = join(dir, 'reel')
    const events: BuildEvent[] = []
    await engine.think(
      folder,
      ['plan-change', folder, '--words=-- shorter'],
      { FRAMEFLOW_THINKER: 'agent:claude' },
      (e) => events.push(e)
    )
    expect(printed(events, 'args')).toEqual(['plan-change', folder, '--words=-- shorter'])
    // Where whisper is stays: a thinking job may transcribe.
    expect(printed(events, 'env')).toEqual({
      FRAMEFLOW_THINKER: 'agent:claude',
      FRAMEFLOW_WHISPER_CLI: 'C:/whisper-cli.exe'
    })
    expect(events[0]).toEqual({ type: 'step', text: 'Writing the plan with Claude Code' })
    expect(events.at(-1)).toEqual({ type: 'done', ok: true })
  } finally {
    delete process.env['FRAMEFLOW_THINKER']
    delete process.env['FRAMEFLOW_KEY']
    delete process.env['FRAMEFLOW_WHISPER_CLI']
  }
})

it('a key job goes to its service, not to an address the app inherited; an agent keeps it', async () => {
  const before = process.env['ANTHROPIC_BASE_URL']
  process.env['ANTHROPIC_BASE_URL'] = 'http://proxy.test' // a proxy set for Claude Code, machine-wide
  try {
    const folder = join(dir, 'reel')
    const base = async (thinker: Record<string, string>): Promise<unknown> => {
      const events: BuildEvent[] = []
      await engine.think(folder, ['plan-change', folder, '--words=shorter'], thinker, (e) =>
        events.push(e)
      )
      return printed(events, 'base')
    }
    expect(await base({ FRAMEFLOW_THINKER: 'key', FRAMEFLOW_SERVICE: 'anthropic' })).toBeNull()
    expect(await base({ FRAMEFLOW_THINKER: 'agent:claude' })).toBe('http://proxy.test')
  } finally {
    if (before === undefined) delete process.env['ANTHROPIC_BASE_URL']
    else process.env['ANTHROPIC_BASE_URL'] = before
  }
})

it("a thinking job's Done line is what it made, and not a step", async () => {
  const folder = join(dir, 'reel')
  const events: BuildEvent[] = []
  await engine.think(folder, ['approve', folder], {}, (e) => events.push(e))
  expect(events.filter((e) => e.type === 'step')).toEqual([
    { type: 'step', text: 'Writing the plan with Claude Code' }
  ])
  expect(events.at(-1)).toEqual({
    type: 'done',
    ok: true,
    result: { storyboard: 'C:/v/storyboard.json' }
  })
})

it('a test of the thinker says its Ready line as a detail', async () => {
  const events: BuildEvent[] = []
  await engine.think('', ['test'], {}, (e) => events.push(e))
  expect(events).toEqual([
    { type: 'detail', text: 'Ready: Claude Code' },
    { type: 'done', ok: true }
  ])
})

it('a thinking job refused because the storyboard changed outside the app says so', async () => {
  const folder = join(dir, 'outside')
  const events: BuildEvent[] = []
  await engine.think(folder, ['change', folder, '--words=shorter', '--version=v1'], {}, (e) =>
    events.push(e)
  )
  expect(events.at(-1)).toEqual({
    type: 'done',
    ok: false,
    message: 'The storyboard changed outside the app.',
    changed: true
  })
})

it('a change the thinker refused says so, apart from a failure', async () => {
  const folder = join(dir, 'refused')
  const events: BuildEvent[] = []
  await engine.think(folder, ['change', folder, '--words=quieter', '--version=v1'], {}, (e) =>
    events.push(e)
  )
  expect(events.at(-1)).toStrictEqual({
    type: 'done',
    ok: false,
    message: 'The music has no volume to change.',
    refused: true
  })
})

it('a second thinking job for a folder stops the first, and the programs it started', async () => {
  const folder = join(dir, 'tree')
  const first: BuildEvent[] = []
  let pid = 0
  const replaced = engine.think(folder, ['start', folder], {}, (e) => {
    first.push(e)
    if (e.type === 'detail' && e.text.startsWith('started ')) pid = Number(e.text.slice(8))
  })
  await vi.waitFor(() => expect(pid).toBeGreaterThan(0), { timeout: 5000 })
  const said = first.length
  let settled = false
  void replaced.then(() => (settled = true))
  const second: BuildEvent[] = []
  const again = engine.think(folder, ['approve', join(dir, 'reel')], {}, (e) => second.push(e))
  // Its promise resolves as it is replaced, not when its process has gone: the window stops listening
  // for it before the new job says anything.
  await new Promise((r) => setImmediate(r))
  expect(settled).toBe(true)
  expect(second).toEqual([])
  await again
  await vi.waitFor(() => expect(alive(pid)).toBe(false), { timeout: 10000 })
  expect(first).toHaveLength(said) // nothing of the new job's, and no done
  expect(second.at(-1)).toMatchObject({ type: 'done', ok: true })
}, 20000)

it('stopAll ends a thinking job, and the programs it started', async () => {
  const folder = join(dir, 'tree')
  const events: BuildEvent[] = []
  let pid = 0
  const running = engine.think(folder, ['start', folder], {}, (e) => {
    events.push(e)
    if (e.type === 'detail' && e.text.startsWith('started ')) pid = Number(e.text.slice(8))
  })
  await vi.waitFor(() => expect(pid).toBeGreaterThan(0), { timeout: 5000 })
  engine.stopAll()
  await running
  expect(events.at(-1)).toMatchObject({ type: 'done', ok: false })
  await vi.waitFor(() => expect(alive(pid)).toBe(false), { timeout: 10000 })
}, 20000)

it('thinkArgs gives each free text as one argument, so words starting with a dash stay words', () => {
  expect(thinkArgs('C:/v', { kind: 'plan-change', words: '--shorter, please' }, [])).toEqual([
    'plan-change',
    'C:/v',
    '--words=--shorter, please'
  ])
  expect(thinkArgs('C:/v', { kind: 'answer', question: 2, words: '-1 degrees' }, [])).toEqual([
    'answer',
    'C:/v',
    '--question=2',
    '--words=-1 degrees'
  ])
  expect(thinkArgs('C:/v', { kind: 'approve' }, [])).toEqual(['approve', 'C:/v'])
  expect(thinkArgs('C:/v', { kind: 'change', words: 'cut scene 2', version: 'abc' }, [])).toEqual([
    'change',
    'C:/v',
    '--words=cut scene 2',
    '--version=abc'
  ])
})

it('thinkArgs starts a video with the files the creator picked', () => {
  const picked = [
    'C:/me/a.mp4',
    'C:/me/b.png',
    'C:/me/song.mp3',
    'C:/me/warm.cube',
    'C:/me/script.txt'
  ]
  expect(
    thinkArgs(
      'C:/v',
      {
        kind: 'start',
        prompt: '-- a reel about tea',
        footage: ['C:/me/a.mp4'],
        assets: ['C:/me/b.png'],
        music: ['C:/me/song.mp3'],
        looks: ['C:/me/warm.cube'],
        script: 'C:/me/script.txt',
        shape: '9:16'
      },
      picked
    )
  ).toEqual([
    'start',
    'C:/v',
    '--prompt=-- a reel about tea',
    '--footage=C:/me/a.mp4',
    '--asset=C:/me/b.png',
    '--music=C:/me/song.mp3',
    '--look=C:/me/warm.cube',
    '--script=C:/me/script.txt',
    '--shape=9:16'
  ])
})

it('thinkArgs refuses a file the creator did not pick, a shape that is none, and a question that is no number', () => {
  const start = {
    kind: 'start' as const,
    prompt: 'p',
    footage: [],
    assets: [],
    music: [],
    looks: []
  }
  expect(() =>
    thinkArgs('C:/v', { ...start, assets: ['C:/Users/me/.ssh/id_rsa'] }, ['C:/me/a.mp4'])
  ).toThrow('was not picked')
  expect(() => thinkArgs('C:/v', { ...start, script: 'C:/secret.txt' }, [])).toThrow(
    'was not picked'
  )
  expect(() => thinkArgs('C:/v', { ...start, shape: '4:3' }, [])).toThrow('shape')
  expect(() =>
    thinkArgs('C:/v', { kind: 'answer', question: '1 --x' as never, words: 'w' }, [])
  ).toThrow('question')
})
