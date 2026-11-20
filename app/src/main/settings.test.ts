// @vitest-environment node
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

// A stand-in for Windows' keeping: it never touches the real one.
const safe = vi.hoisted(() => ({ available: true }))
vi.mock('electron', () => ({
  safeStorage: {
    isEncryptionAvailable: () => safe.available,
    encryptString: (text: string) => Buffer.from([...text].reverse().join(''), 'utf8'),
    decryptString: (kept: Buffer) => [...kept.toString('utf8')].reverse().join('')
  }
}))

import {
  forgetKey,
  keptAgents,
  loadKey,
  loadSettings,
  saveKey,
  saveSettings,
  settingsView,
  thinkerEnv
} from './settings'

const KEY = 'sk-test-0123456789'
let dir: string

beforeEach(() => {
  safe.available = true
  dir = mkdtempSync(join(tmpdir(), 'ff settings '))
})
afterEach(() => rmSync(dir, { recursive: true, force: true }))

it('with nothing saved, the thinker is chosen automatically', () => {
  expect(loadSettings(dir)).toEqual({ thinking: 'auto' })
  expect(loadKey(dir)).toBeNull()
})

it('saved settings are read back, without anything that is not a setting', () => {
  saveSettings(dir, {
    thinking: 'key',
    service: 'custom',
    model: 'llama3',
    baseUrl: 'http://localhost:11434/v1',
    key: KEY
  } as never)
  expect(loadSettings(dir)).toEqual({
    thinking: 'key',
    service: 'custom',
    model: 'llama3',
    baseUrl: 'http://localhost:11434/v1'
  })
})

it('a thinker or a service Frameflow does not know is not kept', () => {
  saveSettings(dir, { thinking: 'standin:C:/x.json', service: 'mine' } as never)
  expect(loadSettings(dir)).toEqual({ thinking: 'auto' })
})

it('a saved key reaches a job as FRAMEFLOW_KEY, and is not kept as written', () => {
  saveSettings(dir, { thinking: 'key', service: 'openai', model: 'gpt-x' })
  saveKey(dir, KEY)
  expect(thinkerEnv(loadSettings(dir), loadKey(dir))).toEqual({
    FRAMEFLOW_THINKER: 'key',
    FRAMEFLOW_SERVICE: 'openai',
    FRAMEFLOW_MODEL: 'gpt-x',
    FRAMEFLOW_KEY: KEY
  })
  for (const name of readdirSync(dir))
    expect(readFileSync(join(dir, name), 'utf8')).not.toContain(KEY)
})

it('an agent is given no key, though one is saved', () => {
  expect(thinkerEnv({ thinking: 'agent:claude', service: 'openai', model: 'gpt-x' }, KEY)).toEqual({
    FRAMEFLOW_THINKER: 'agent:claude'
  })
  expect(thinkerEnv({ thinking: 'standin:C:/x.json' } as never, KEY)).toEqual({
    FRAMEFLOW_THINKER: 'auto'
  })
})

it('what the settings page is shown says a key is kept, and never the key', () => {
  saveSettings(dir, { thinking: 'key', service: 'anthropic' })
  saveKey(dir, KEY)
  const agents = [{ id: 'claude', name: 'Claude Code', found: true, version: '2.0' }]
  const view = settingsView(dir, agents)
  expect(view).toEqual({ thinking: 'key', service: 'anthropic', hasKey: true, agents })
  expect(JSON.stringify(view)).not.toContain(KEY)
  expect(Object.keys(view).some((name) => /key/i.test(name) && name !== 'hasKey')).toBe(false)
})

it('when Windows cannot keep a key safely, saving says so and writes nothing', () => {
  safe.available = false
  expect(() => saveKey(dir, KEY)).toThrow(
    'Windows could not keep the key safely, so it was not saved.'
  )
  expect(readdirSync(dir)).toEqual([])
  expect(settingsView(dir, []).hasKey).toBe(false)
})

it('forgetting the key removes it', () => {
  saveSettings(dir, { thinking: 'key', service: 'gemini', model: 'gemini-x' })
  saveKey(dir, KEY)
  expect(settingsView(dir, []).hasKey).toBe(true)
  forgetKey(dir)
  expect(loadKey(dir)).toBeNull()
  expect(settingsView(dir, []).hasKey).toBe(false)
  expect(existsSync(join(dir, 'thinking.key'))).toBe(false)
  forgetKey(dir) // and again, with none kept
})

it('a saved key belongs to the service it was saved for, and goes to no other', () => {
  saveSettings(dir, { thinking: 'key', service: 'anthropic' })
  saveKey(dir, KEY)
  // The window cannot say whose key it is.
  saveSettings(dir, {
    thinking: 'key',
    service: 'custom',
    model: 'llama3',
    baseUrl: 'http://elsewhere.test/v1',
    keyService: 'custom'
  } as never)
  expect(thinkerEnv(loadSettings(dir), loadKey(dir))).toEqual({
    FRAMEFLOW_THINKER: 'key',
    FRAMEFLOW_SERVICE: 'custom',
    FRAMEFLOW_MODEL: 'llama3',
    FRAMEFLOW_BASE_URL: 'http://elsewhere.test/v1'
  })
  const view = settingsView(dir, [])
  expect(view.hasKey).toBe(false)
  expect(view).not.toHaveProperty('keyService')
  // Back on its own service, the key is still kept.
  saveSettings(dir, { thinking: 'key', service: 'anthropic' })
  expect(thinkerEnv(loadSettings(dir), loadKey(dir)).FRAMEFLOW_KEY).toBe(KEY)
  expect(settingsView(dir, []).hasKey).toBe(true)
})

it('a key saved with no service chosen is sent to none', () => {
  saveKey(dir, KEY)
  saveSettings(dir, { thinking: 'key', service: 'openai', model: 'gpt-x' })
  expect(thinkerEnv(loadSettings(dir), loadKey(dir))).not.toHaveProperty('FRAMEFLOW_KEY')
  expect(settingsView(dir, []).hasKey).toBe(false)
})

it('the agents are found once a session, and looked for again only when a fresh look is asked', async () => {
  const claude = [{ id: 'claude', name: 'Claude Code', found: true, version: '2.1.316' }]
  const find = vi.fn(async () => claude)
  const agents = keptAgents(find)
  await Promise.all([agents(false), agents(false)])
  expect(await agents(false)).toEqual(claude)
  expect(find).toHaveBeenCalledTimes(1)
  await agents(true)
  expect(find).toHaveBeenCalledTimes(2)
  await agents(false)
  expect(find).toHaveBeenCalledTimes(2)
})

it('a look for the agents that failed is not kept', async () => {
  const find = vi.fn().mockRejectedValueOnce(new Error('The engine stopped.')).mockResolvedValue([])
  const agents = keptAgents(find)
  await expect(agents(false)).rejects.toThrow('The engine stopped.')
  await expect(agents(false)).resolves.toEqual([])
})
