import { contextBridge, ipcRenderer } from 'electron'
import type { BuildEvent, FrameflowApi } from '../shared/types'

// Electron wraps a handler's error as "Error invoking remote method 'x': Error: <what it said>"; the
// creator is shown only what the engine said.
function ask<T>(channel: string, ...args: unknown[]): Promise<T> {
  return ipcRenderer.invoke(channel, ...args).catch((e: Error) => {
    throw new Error(e.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, ''))
  })
}

// A build, an open or a thinking job: its events arrive on `<channel>-event` while its request runs.
async function job(
  channel: string,
  folder: string,
  onEvent: (e: BuildEvent) => void,
  ...more: unknown[]
): Promise<void> {
  const listener = (_: unknown, of: string, event: BuildEvent): void => {
    if (of === folder) onEvent(event)
  }
  ipcRenderer.on(`${channel}-event`, listener)
  try {
    await ask(channel, folder, ...more)
  } finally {
    ipcRenderer.removeListener(`${channel}-event`, listener)
  }
}

const api: FrameflowApi = {
  videos: () => ask('ff:videos'),
  describe: (folder) => ask('ff:describe', folder),
  thumbnail: (folder, key) => ask('ff:thumbnail', folder, key),
  edit: (folder, op, version) => ask('ff:edit', folder, op, version),
  undo: (folder, version) => ask('ff:undo', folder, version),
  redo: (folder, version) => ask('ff:redo', folder, version),
  looks: (folder) => ask('ff:looks', folder),
  chooseFile: () => ask('ff:choose-file'),
  build: (folder, onEvent) => job('ff:build', folder, onEvent),
  open: (folder, onEvent) => job('ff:open', folder, onEvent),
  onBuildFinished: (cb) => {
    ipcRenderer.on('ff:build-finished', (_, folder: string, ok: boolean) => cb(folder, ok))
  },
  settings: (fresh) => ask('ff:settings', fresh === true),
  saveSettings: (s) => ask('ff:save-settings', s),
  saveKey: (key) => ask('ff:save-key', key),
  forgetKey: () => ask('ff:forget-key'),
  testThinking: (onEvent) => job('ff:test-thinking', '', onEvent), // its events come under no folder
  newVideo: (prompt) => ask('ff:new-video', prompt),
  think: (folder, request, onEvent) => job('ff:think', folder, onEvent, request),
  stop: (which, folder) => ask('ff:stop', which, folder),
  editPlan: (folder, fields) => ask('ff:edit-plan', folder, fields),
  chooseFiles: (kind) => ask('ff:choose-files', kind)
}

contextBridge.exposeInMainWorld('frameflow', api)
