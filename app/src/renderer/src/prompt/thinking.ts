// The thinking jobs in progress, kept outside any screen as builds are: leaving the prompt step, or the
// video, and coming back finds the job where it is, with its steps.
import { useSyncExternalStore } from 'react'
import type { BuildEvent, SettingsView, ThinkRequest } from '@shared/types'

export type Start = Extract<ThinkRequest, { kind: 'start' }>
export type Done = Extract<BuildEvent, { type: 'done' }>

// A key's service by the name Settings gives it; another address is named by the address.
const SERVICES: Record<string, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
  gemini: 'Gemini'
}

/** Who thinks as the settings choose it, whether it is an agent found on this PC, and whether it looks
 *  facts up on the web: an agent does, and of the keys only Anthropic's. */
export function thinker(view: SettingsView | null): {
  name: string | null
  here: boolean
  searches: boolean
} {
  if (view?.thinking === 'key') {
    const service = view.service ?? 'anthropic'
    return {
      name: service === 'custom' ? (view.baseUrl ?? null) : SERVICES[service],
      here: false,
      searches: service === 'anthropic'
    }
  }
  const agent =
    view?.thinking === 'auto'
      ? view.agents.find((a) => a.found)
      : view?.agents.find((a) => `agent:${a.id}` === view.thinking)
  return { name: agent?.found ? agent.name : null, here: !!agent?.found, searches: true }
}

export interface Thought {
  running: boolean
  /** What the job running, or the last one, was asked to do. */
  kind: ThinkRequest['kind'] | null
  steps: string[]
  /** The engine's line when the last job failed; null otherwise. */
  failure: string | null
  /** The last job asked for, which Try again asks for again. */
  request: ThinkRequest | null
  /** The idea and the material the plan was last written from, while the app runs. */
  start: Start | null
}

const IDLE: Thought = {
  running: false,
  kind: null,
  steps: [],
  failure: null,
  request: null,
  start: null
}

// Kept per engine, so a different engine (a test's) starts with none.
const stores = new WeakMap<
  object,
  { thoughts: Map<string, Thought>; listeners: Set<() => void>; latest: Map<string, object> }
>()

function store(): {
  thoughts: Map<string, Thought>
  listeners: Set<() => void>
  latest: Map<string, object>
} {
  if (!stores.has(window.frameflow))
    stores.set(window.frameflow, { thoughts: new Map(), listeners: new Set(), latest: new Map() })
  return stores.get(window.frameflow)!
}

export function useThought(folder: string | null): Thought {
  const { thoughts, listeners } = store()
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => (folder && thoughts.get(folder)) || IDLE
  )
}

/** A change by hand has landed: what a failed job said is about a plan that is no longer there. */
export function forgetFailure(folder: string): void {
  const { thoughts, listeners } = store()
  const thought = thoughts.get(folder)
  if (thought?.failure == null) return
  thoughts.set(folder, { ...thought, failure: null })
  listeners.forEach((listener) => listener())
}

/** Ask the thinker for one job on a video. Resolves with its end, or with null when a newer job for the
 *  same video replaced it: the engine ends that one without a word, and nothing is shown for it. */
export function think(folder: string, request: ThinkRequest): Promise<Done | null> {
  const { thoughts, listeners, latest } = store()
  const run = {}
  latest.set(folder, run)
  const current = (): Thought => thoughts.get(folder) ?? IDLE
  const set = (change: Partial<Thought>): void => {
    if (latest.get(folder) !== run) return
    thoughts.set(folder, { ...current(), ...change })
    listeners.forEach((listener) => listener())
  }
  set({
    running: true,
    kind: request.kind,
    steps: [],
    failure: null,
    request,
    ...(request.kind === 'start' && { start: request })
  })

  let done: Done | null = null
  return window.frameflow
    .think(folder, request, (event) => {
      if (event.type === 'step') set({ steps: [...current().steps, event.text] })
      else if (event.type === 'done') done = event
    })
    .catch((e: Error) => {
      done = { type: 'done', ok: false, message: e.message }
    })
    .then(() => {
      if (latest.get(folder) !== run) return null
      const ended = done as Done | null
      // No end of its own: a job this store did not start took its place. A change in words that fails
      // says so in a toast where it was asked; kept here, the prompt step would show it as the plan's.
      if (!ended || ended.ok || ended.changed || request.kind === 'change')
        set({ running: false, steps: [] })
      else set({ running: false, failure: ended.message ?? '' })
      return ended
    })
}
