// Which thinker the creator chose, kept in the app's data folder, and their API key, kept there only as
// Windows encrypts it. The key leaves this file one way: as FRAMEFLOW_KEY in one thinking job's environment.
import { safeStorage } from 'electron'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { join } from 'path'
import type { Settings, SettingsView } from '../shared/types'

const THINKING: readonly string[] = ['auto', 'agent:claude', 'agent:opencode', 'key']
const SERVICES: readonly string[] = ['anthropic', 'openai', 'openrouter', 'gemini', 'custom']

const settingsFile = (dir: string): string => join(dir, 'settings.json')
const keyFile = (dir: string): string => join(dir, 'thinking.key')

// Only what is a setting, whatever the window or the file holds: a job's thinker is one of these or `auto`.
function known(s: Partial<Settings> | null): Settings {
  const out: Settings = {
    thinking: s && THINKING.includes(s.thinking as string) ? s.thinking! : 'auto'
  }
  if (s && SERVICES.includes(s.service as string)) out.service = s.service
  if (s && typeof s.model === 'string' && s.model) out.model = s.model
  if (s && typeof s.baseUrl === 'string' && s.baseUrl) out.baseUrl = s.baseUrl
  return out
}

/** The settings as kept, with the service the key was saved for: the key is sent to no other. */
export type Kept = Settings & { keyService?: Settings['service'] }

export function loadSettings(dir: string): Kept {
  try {
    const read = JSON.parse(readFileSync(settingsFile(dir), 'utf8'))
    const out: Kept = known(read)
    if (read && SERVICES.includes(read.keyService)) out.keyService = read.keyService
    return out
  } catch {
    return known(null) // none saved yet, or a file that cannot be read
  }
}

function write(dir: string, s: Kept): void {
  mkdirSync(dir, { recursive: true })
  writeFileSync(settingsFile(dir), JSON.stringify(s, null, 2))
}

export function saveSettings(dir: string, s: Settings): void {
  // Whose key it is stays as it was kept: the window cannot say a key is for another service.
  write(dir, { ...known(s), keyService: loadSettings(dir).keyService })
}

export function saveKey(dir: string, key: string): void {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Windows could not keep the key safely, so it was not saved.')
  }
  mkdirSync(dir, { recursive: true })
  writeFileSync(keyFile(dir), safeStorage.encryptString(key.trim())) // a pasted key often ends in a line break
  const kept = loadSettings(dir)
  write(dir, { ...kept, keyService: kept.service })
}

export function forgetKey(dir: string): void {
  rmSync(keyFile(dir), { force: true })
}

/** The key, for a thinking job's environment only; null when none is kept or it cannot be read. */
export function loadKey(dir: string): string | null {
  try {
    return safeStorage.decryptString(readFileSync(keyFile(dir))) || null
  } catch {
    return null
  }
}

/** What the settings page is shown: whether a key is kept, never the key. */
export function settingsView(dir: string, agents: SettingsView['agents']): SettingsView {
  const { keyService, ...s } = loadSettings(dir)
  const hasKey = !!s.service && keyService === s.service && loadKey(dir) !== null
  return { ...s, hasKey, agents }
}

/** The agents found, kept for the session: each look runs every agent's `--version` on the engine's one
 *  request thread, ahead of the creator's edits. Only a fresh look, which the settings page asks for, looks
 *  again; a look that failed is not kept. */
export function keptAgents(
  find: () => Promise<SettingsView['agents']>
): (fresh: boolean) => Promise<SettingsView['agents']> {
  let kept: Promise<SettingsView['agents']> | null = null
  return (fresh) => {
    if (fresh || !kept) {
      const look = find()
      kept = look
      look.catch(() => {
        if (kept === look) kept = null
      })
    }
    return kept
  }
}

/** The thinker's variables for one job (project/thinkers.py). Only a key thinker is given the key, and
 *  only the service it was saved for. */
export function thinkerEnv(s: Kept, key: string | null): Record<string, string> {
  const { thinking, service, model, baseUrl } = known(s)
  if (!service || s.keyService !== service) key = null
  if (thinking !== 'key') return { FRAMEFLOW_THINKER: thinking }
  return {
    FRAMEFLOW_THINKER: 'key',
    ...(service && { FRAMEFLOW_SERVICE: service }),
    ...(model && { FRAMEFLOW_MODEL: model }),
    ...(baseUrl && { FRAMEFLOW_BASE_URL: baseUrl }),
    ...(key && { FRAMEFLOW_KEY: key })
  }
}
