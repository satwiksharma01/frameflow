// Starts Frameflow's Python engine and reads what it prints. Arguments always go as an array, never
// through a shell, so a folder with spaces in its path is one argument.
import { spawn, type ChildProcess } from 'child_process'
import type { BuildEvent, ThinkRequest } from '../shared/types'

export interface Engine {
  /** One answer from the engine kept running for the app: `call('describe', { folder })`. */
  call<T>(method: string, params: Record<string, unknown>): Promise<T>
  /** Builds a video, reporting each step as it happens. Resolves when the build has ended, well or not. */
  build(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>
  /** Opens a built video's project in OpenShot, reporting its steps as a build does. */
  open(folder: string, onEvent: (e: BuildEvent) => void): Promise<void>
  /**
   * A thinking job: `python -m project.app_think <args>`, with `env` as its thinker. One for a folder
   * stops any still running for it. Its `done` carries what the job made, or that it was refused as changed.
   */
  think(
    folder: string,
    args: string[],
    env: Record<string, string>,
    onEvent: (e: BuildEvent) => void
  ): Promise<void>
  building(folder: string): boolean
  /** Stops a video's build or thinking job and what it started; its `done` says it was stopped. False
   *  when none is running. */
  stop(job: 'building' | 'thinking', folder: string): boolean
  stopAll(): void
}

// The thinker's own variables. A thinking job is given the ones the creator's settings make, never the
// app's: a stray FRAMEFLOW_THINKER or FRAMEFLOW_KEY around the app must not choose who thinks.
const THINKER_VARIABLES = [
  'FRAMEFLOW_THINKER',
  'FRAMEFLOW_SERVICE',
  'FRAMEFLOW_MODEL',
  'FRAMEFLOW_BASE_URL',
  'FRAMEFLOW_KEY'
]

/**
 * The command line of a thinking job. Every free text is one `--name=<text>` argument, so words starting
 * with a dash arrive as words, and every file must be one the creator picked in the app's file dialog.
 */
export function thinkArgs(folder: string, request: ThinkRequest, picked: string[]): string[] {
  const args = [request.kind, folder]
  if (request.kind === 'start') {
    const files = (name: string, paths: string[]): void => {
      for (const path of paths) {
        if (!picked.includes(path)) throw new Error(`${path} was not picked in Frameflow`)
        args.push(`--${name}=${path}`)
      }
    }
    args.push(`--prompt=${request.prompt}`)
    files('footage', request.footage)
    files('asset', request.assets)
    files('music', request.music)
    files('look', request.looks)
    if (request.script) files('script', [request.script])
    if (request.shape) {
      if (!['9:16', '16:9', '1:1'].includes(request.shape)) {
        throw new Error(`${request.shape} is not a shape Frameflow makes`)
      }
      args.push(`--shape=${request.shape}`)
    }
  } else if (request.kind !== 'approve') {
    if (request.kind === 'answer') {
      if (!Number.isInteger(request.question))
        throw new Error('The question to answer is not a number')
      args.push(`--question=${request.question}`)
    }
    args.push(`--words=${request.words}`)
    if (request.kind === 'change') args.push(`--version=${request.version}`)
  }
  return args
}

export function createEngine({
  python,
  root,
  timeout = 60_000
}: {
  python: string[]
  root: string
  /** How long a call may wait for its answer, in milliseconds. */
  timeout?: number
}): Engine {
  // By `building <folder>`, `opening <folder>` and `thinking <folder>`. A build is previewing once its report is written.
  const jobs = new Map<
    string,
    { child: ChildProcess; previewing: boolean; resolve(): void; stopped(): void }
  >()
  const running = new Set<ChildProcess>()

  // With `thinker`, the job's thinker is that and nothing the app's own environment says.
  function start(args: string[], thinker?: Record<string, string>): ChildProcess {
    const inherited = { ...process.env }
    if (thinker) for (const name of THINKER_VARIABLES) delete inherited[name]
    // A key goes to its service's own address: a proxy set for Claude Code, machine-wide, must not get it.
    if (thinker?.FRAMEFLOW_THINKER === 'key') delete inherited.ANTHROPIC_BASE_URL
    const child = spawn(python[0], [...python.slice(1), ...args], {
      cwd: root,
      windowsHide: true,
      detached: process.platform !== 'win32', // its own process group, so stop() can end what it started too
      // Unbuffered, so a build's steps arrive as they happen and not all at its end.
      env: { ...inherited, ...thinker, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' }
    })
    // Decode as text across chunks: a character cut in two by a pipe read must arrive whole.
    child.stdout?.setEncoding('utf8')
    child.stderr?.setEncoding('utf8')
    running.add(child)
    child.once('close', () => running.delete(child))
    child.once('error', () => running.delete(child))
    return child
  }

  // The engine kept running for answers (`project.app_api serve`): one JSON line per request, matched to its
  // answer by id, so pictures and changes can be answered out of order. It starts on the first call, and
  // again on the next one after it stops.
  interface Server {
    child: ChildProcess
    pending: Map<
      number,
      { resolve(v: unknown): void; reject(e: Error): void; timer: NodeJS.Timeout }
    >
    err: string
  }
  let server: Server | null = null
  let nextId = 1

  function serverNow(): Server {
    if (server) return server
    const s: Server = {
      child: start(['-m', 'project.app_api', 'serve']),
      pending: new Map(),
      err: ''
    }
    let partial = ''
    s.child.stdout?.on('data', (chunk: string) => {
      const lines = (partial + chunk).split('\n')
      partial = lines.pop() ?? ''
      for (const line of lines) {
        let answer: { id?: number; result?: unknown; error?: unknown }
        try {
          answer = JSON.parse(line)
        } catch {
          continue // not an answer: something else the engine printed
        }
        const waiting = answer.id === undefined ? undefined : s.pending.get(answer.id)
        if (!waiting) continue
        s.pending.delete(answer.id!)
        clearTimeout(waiting.timer)
        if ('error' in answer) waiting.reject(new Error(String(answer.error)))
        else waiting.resolve(answer.result)
      }
    })
    s.child.stderr?.on('data', (chunk: string) => (s.err = (s.err + chunk).slice(-2000)))
    s.child.stdin?.on('error', () => {}) // a pipe to an engine that has gone; its close says why
    const gone = (why: string): void => {
      if (server === s) server = null
      for (const waiting of s.pending.values()) {
        clearTimeout(waiting.timer)
        waiting.reject(new Error(why))
      }
      s.pending.clear()
    }
    s.child.once('error', (e) => gone(`Could not start \`${python[0]}\`: ${e.message}`))
    s.child.once('close', () =>
      gone(s.err.trim() ? `The engine stopped: ${s.err.trim()}` : 'The engine stopped.')
    )
    server = s
    return s
  }

  function call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const s = serverNow()
      const id = nextId++
      const timer = setTimeout(() => {
        s.pending.delete(id)
        reject(new Error(`The engine did not answer ${method}.`))
      }, timeout)
      s.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer })
      s.child.stdin?.write(JSON.stringify({ id, method, params }) + '\n')
    })
  }

  // A build or an open: what the engine prints as it goes becomes steps and details, then it is done.
  // A build is built when its preview starts; building it again then stops that run and starts anew.
  function job(
    doing: 'building' | 'opening' | 'thinking',
    folder: string,
    args: string[],
    onEvent: (e: BuildEvent) => void,
    env?: Record<string, string>
  ): Promise<void> {
    const key = `${doing} ${folder}`
    const thinking = doing === 'thinking'
    const running = jobs.get(key)
    // A new thinking job is the creator's latest word: it stops the one before it.
    // Its call ends here, not when its process has gone: the window must stop listening for it before
    // the new job says anything, or it would take the new job's steps for its own.
    if (running?.previewing || (running && thinking)) {
      stop(running.child)
      running.resolve()
    } else if (running) return Promise.reject(new Error(`${folder} is already ${doing}`))
    return new Promise((resolve) => {
      const child = start(args, env)
      const stopped = (): void => {
        onEvent({ type: 'done', ok: false, stopped: true })
        resolve()
      }
      const self = { child, previewing: false, resolve, stopped }
      jobs.set(key, self)
      let pending = ''
      let err = ''
      let result: Record<string, unknown> | undefined
      const line = (text: string): void => {
        if (jobs.get(key) !== self) return // replaced: what it still prints is not the new build's
        if (thinking && text.startsWith('==> Done ')) {
          // What the job made, for the app to read: not a step to show.
          try {
            result = JSON.parse(text.slice(9))
          } catch {
            // not JSON: the job ends with nothing made
          }
        } else if (thinking && text.startsWith('Ready: ')) {
          onEvent({ type: 'detail', text: text.trim() }) // a test's answer, which is no step of its own
        } else if (text.trim() === '==> Making a preview to watch in the app') {
          self.previewing = true
          onEvent({ type: 'built' })
        } else if (text.startsWith('==> ')) onEvent({ type: 'step', text: text.slice(4).trim() })
        else if (text.startsWith('    ') && text.trim())
          onEvent({ type: 'detail', text: text.trim() })
      }
      child.stdout?.on('data', (chunk) => {
        const lines = (pending + chunk).split(/\r?\n/)
        pending = lines.pop() ?? ''
        lines.forEach(line)
      })
      child.stderr?.on('data', (chunk) => (err += chunk))
      const end = (ok: boolean, message?: string, code?: number | null): void => {
        // Once, and not for a replaced run: that one ends without a word.
        if (jobs.get(key) === self) {
          if (pending) line(pending)
          jobs.delete(key)
          if (ok) onEvent(result ? { type: 'done', ok, result } : { type: 'done', ok })
          else
            onEvent({
              type: 'done',
              ok,
              message,
              ...(thinking && code === 3 && { changed: true as const }), // changed outside the app
              ...(thinking && code === 4 && { refused: true as const }) // not a change words can make
            })
        }
        resolve()
      }
      child.once('error', (e) => end(false, `Could not start \`${python[0]}\`: ${e.message}`))
      child.once('close', (code) =>
        end(
          code === 0,
          err.replace(/\r\n/g, '\n').trim() || `The engine stopped (exit ${code}).`,
          code
        )
      )
    })
  }

  // A build starts programs of its own (FFmpeg, whisper, HyperFrames' browser); ending Python alone
  // would leave them writing into the video's folder. End the whole tree.
  function stop(child: ChildProcess): void {
    if (child.pid === undefined) return
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
        windowsHide: true,
        stdio: 'ignore'
      })
    } else {
      try {
        process.kill(-child.pid, 'SIGTERM')
      } catch {
        child.kill()
      }
    }
  }

  return {
    call,
    build: (folder, onEvent) =>
      job('building', folder, ['-m', 'project.produce', folder, '--build'], onEvent),
    open: (folder, onEvent) =>
      job('opening', folder, ['-m', 'project.app_api', 'open', folder], onEvent),
    think: (folder, args, env, onEvent) =>
      job('thinking', folder, ['-m', 'project.app_think', ...args], onEvent, env),
    building: (folder) => jobs.has(`building ${folder}`),
    stop: (doing, folder) => {
      const running = jobs.get(`${doing} ${folder}`)
      if (!running) return false
      jobs.delete(`${doing} ${folder}`) // what it still prints, and its end, are no longer its own
      stop(running.child)
      running.stopped()
      return true
    },
    stopAll: () => {
      server = null // a call from now on starts a new engine; the stopping one answers no more
      running.forEach(stop)
    }
  }
}
