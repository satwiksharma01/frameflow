// The builds in progress, kept outside any screen: opening another video and coming back finds a
// build where it is, not a Build button that would start a second one.
import { useSyncExternalStore } from 'react'
import type { BuildEvent } from '@shared/types'

export interface Build {
  /** A build is previewing once its report and checks are written; Build then starts a new one. */
  state: 'idle' | 'building' | 'previewing' | 'failed'
  steps: string[]
  detail: string
  message: string
  /** Rises when a build is built and again when its run ends well; a screen reads the storyboard again. */
  built: number
}

const IDLE: Build = { state: 'idle', steps: [], detail: '', message: '', built: 0 }

// Kept per engine, so a different engine (a test's) starts with none.
const stores = new WeakMap<object, { builds: Map<string, Build>; listeners: Set<() => void> }>()

// Each video's latest build: one stopped by a newer build shows nothing more.
const latest = new Map<string, object>()

function store(): { builds: Map<string, Build>; listeners: Set<() => void> } {
  if (!stores.has(window.frameflow)) stores.set(window.frameflow, { builds: new Map(), listeners: new Set() })
  return stores.get(window.frameflow)!
}

export function useBuild(folder: string): Build {
  const { builds, listeners } = store()
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => builds.get(folder) ?? IDLE
  )
}

/** Start building a video, unless it is building already. */
export function startBuild(folder: string): void {
  const { builds, listeners } = store()
  const current = (): Build => builds.get(folder) ?? IDLE
  if (current().state === 'building') return
  const run = {}
  latest.set(folder, run)
  const set = (change: Partial<Build>): void => {
    if (latest.get(folder) !== run) return
    builds.set(folder, { ...current(), ...change })
    listeners.forEach((listener) => listener())
  }
  set({ state: 'building', steps: [], detail: '', message: '' })

  let ok = false
  let said = ''
  const onEvent = (event: BuildEvent): void => {
    if (event.type === 'step') set({ steps: [...current().steps, event.text], detail: '' })
    else if (event.type === 'detail') set({ detail: event.text })
    else if (event.type === 'built') {
      set({ state: 'previewing', steps: [], detail: '', built: current().built + 1 })
    } else {
      ok = event.ok
      said = event.message ?? ''
    }
  }
  window.frameflow
    .build(folder, onEvent)
    .catch((e: Error) => {
      said = e.message
    })
    .then(() => {
      if (ok) set({ state: 'idle', steps: [], detail: '', built: current().built + 1 })
      else set({ state: 'failed', message: said || 'The build stopped without saying why.' })
    })
}
