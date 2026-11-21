// The renderer's requests, answered by the engine. Every folder it names must be a video under the
// engine's output folder; nothing else on the disk is reachable from the window.
import { app, BrowserWindow, dialog, ipcMain, net, Notification, protocol } from 'electron'
import { createReadStream } from 'fs'
import { stat } from 'fs/promises'
import { join } from 'path'
import { Readable } from 'stream'
import { pathToFileURL } from 'url'
import type {
  BuildEvent,
  Described,
  EditAnswer,
  EditOp,
  Settings,
  SettingsView,
  ThinkRequest,
  Video
} from '../shared/types'
import { createChosen } from './chosen'
import { thinkArgs, type Engine } from './engine'
import { ownPage } from './guard'
import { inside, previewAt, rangeOf, thumbnailAt } from './media'
import { noticeFor, thoughtNotice } from './notice'
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

export const MEDIA = 'ff-media' // how thumbnails and previews reach the window: never file://

// A preview, or the part of it a <video> asks for as it seeks. Read with Node's fs, not net.fetch: its
// files open with delete sharing, so a build can replace the preview while the window plays it.
async function served(path: string, header: string | null): Promise<Response> {
  const file = await stat(path).catch(() => null)
  if (!file?.isFile()) return new Response(null, { status: 404 })
  const size = file.size
  const range = rangeOf(header, size)
  if (range === 'unsatisfiable') {
    return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } })
  }
  // Node's web stream and the one Response is typed with are the same thing under two names.
  const body = Readable.toWeb(createReadStream(path, range ?? {})) as ReadableStream
  const headers = { 'Accept-Ranges': 'bytes', 'Content-Type': 'video/mp4' }
  if (!range) return new Response(body, { headers: { ...headers, 'Content-Length': String(size) } })
  return new Response(body, {
    status: 206,
    headers: {
      ...headers,
      'Content-Length': String(range.end - range.start + 1),
      'Content-Range': `bytes ${range.start}-${range.end}/${size}`
    }
  })
}

// The engine names the preview by its path; the window reaches it only by its URL.
function shown(d: Described): Described {
  return d.preview ? { ...d, preview: `${MEDIA}://preview/?p=${encodeURIComponent(d.preview)}` } : d
}

// An undo can bring back the storyboard a preview was built from, so a change's answer is shown too.
function changed(answer: EditAnswer): EditAnswer {
  return 'described' in answer ? { ...answer, described: shown(answer.described) } : answer
}

// What the creator may pick for a new video, by what it is for.
const FILES = {
  footage: { title: 'Choose your recordings', extensions: ['mp4', 'mov', 'webm', 'mkv'] },
  assets: {
    title: 'Choose pictures and clips',
    extensions: ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'mov', 'webm', 'mkv']
  },
  music: { title: 'Choose the music', extensions: ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg'] },
  looks: { title: 'Choose looks', extensions: ['cube'] },
  script: { title: 'Choose the script', extensions: ['txt', 'md'] }
}

export function registerIpc(engine: Engine, root: string, page: string): void {
  // Only the app's own page is answered: a page the window should never have shown gets nothing.
  const handle = (channel: string, listener: Parameters<typeof ipcMain.handle>[1]): void =>
    ipcMain.handle(channel, (event, ...args) => {
      if (!ownPage(page, event.senderFrame?.url ?? ''))
        throw new Error('Frameflow answers only its own window')
      return listener(event, ...args)
    })
  const videos = join(root, 'output')
  const data = app.getPath('userData') // the settings and the key: never in the repository or a video
  const chosen = createChosen()
  const video = (folder: string): string => {
    if (!inside(videos, folder)) throw new Error(`${folder} is not one of Frameflow's videos`)
    return folder
  }

  protocol.handle(MEDIA, (request) => {
    const preview = previewAt(videos, request.url)
    if (preview) return served(preview, request.headers.get('range'))
    const path = thumbnailAt(videos, request.url)
    return path ? net.fetch(pathToFileURL(path).toString()) : new Response(null, { status: 403 })
  })

  handle('ff:videos', () => engine.call<Video[]>('videos', { root: videos }))
  handle('ff:describe', async (_, folder: string) =>
    shown(await engine.call<Described>('describe', { folder: video(folder) }))
  )
  handle('ff:thumbnail', async (_, folder: string, key: string) => {
    const path = await engine.call<string | null>('thumbnail', { folder: video(folder), key })
    return path && `${MEDIA}://thumb/?p=${encodeURIComponent(path)}`
  })
  handle('ff:looks', (_, folder: string) =>
    engine.call<string[]>('looks', { folder: video(folder) })
  )
  // Only files the creator picked here may join a video: the engine refuses any other new path.
  handle('ff:edit', async (_, folder: string, op: EditOp, version: string) =>
    changed(
      await engine.call<EditAnswer>('edit', {
        folder: video(folder),
        op,
        version,
        chosen: chosen.list()
      })
    )
  )
  handle('ff:undo', async (_, folder: string, version: string) =>
    changed(await engine.call<EditAnswer>('undo', { folder: video(folder), version }))
  )
  handle('ff:redo', async (_, folder: string, version: string) =>
    changed(await engine.call<EditAnswer>('redo', { folder: video(folder), version }))
  )
  handle('ff:choose-file', async (event) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    const options = {
      title: 'Choose a picture or a clip',
      properties: ['openFile' as const],
      filters: [
        {
          name: 'Pictures and clips',
          extensions: ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'mov', 'webm', 'mkv']
        },
        { name: 'Pictures', extensions: ['jpg', 'jpeg', 'png', 'webp'] },
        { name: 'Clips', extensions: ['mp4', 'mov', 'webm', 'mkv'] }
      ]
    }
    const picked = window
      ? await dialog.showOpenDialog(window, options)
      : await dialog.showOpenDialog(options)
    if (picked.canceled || !picked.filePaths[0]) return null
    chosen.add(picked.filePaths[0])
    return picked.filePaths[0]
  })
  // A desktop notice, only while the window is not the one in front: the video's title, then what happened.
  const tell = async (
    window: BrowserWindow | null,
    folder: string,
    body: (title: string) => string
  ): Promise<void> => {
    if (!window || window.isDestroyed() || window.isFocused() || !Notification.isSupported()) return
    const title = await engine
      .call<Described>('describe', { folder })
      .then((d) => d.title)
      .catch(() => 'Your video')
    new Notification({ title: 'Frameflow', body: body(title) }).show()
  }
  handle('ff:build', async (event, folder: string) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    const notice = noticeFor()
    let ok = false
    await engine.build(video(folder), (e: BuildEvent) => {
      if (e.type === 'done') ok = e.ok
      if (!event.sender.isDestroyed()) event.sender.send('ff:build-event', folder, e)
      const says = notice(e)
      if (says) void tell(window, folder, (title) => `${title} ${says}`)
    })
    if (!event.sender.isDestroyed()) event.sender.send('ff:build-finished', folder, ok)
  })
  handle('ff:choose-files', async (event, kind: keyof typeof FILES) => {
    if (!Object.hasOwn(FILES, kind)) throw new Error(`Frameflow has no files of the kind ${kind}`)
    const window = BrowserWindow.fromWebContents(event.sender)
    const { title, extensions } = FILES[kind]
    const options = {
      title,
      properties:
        kind === 'script'
          ? ['openFile' as const]
          : ['openFile' as const, 'multiSelections' as const],
      filters: [{ name: title, extensions }]
    }
    const picked = window
      ? await dialog.showOpenDialog(window, options)
      : await dialog.showOpenDialog(options)
    if (picked.canceled) return []
    picked.filePaths.forEach(chosen.add)
    return picked.filePaths
  })

  const agents = keptAgents(() => engine.call<SettingsView['agents']>('thinkers', {}))
  handle('ff:settings', async (_, fresh: unknown): Promise<SettingsView> =>
    settingsView(data, await agents(fresh === true))
  )
  handle('ff:save-settings', (_, s: Settings) => saveSettings(data, s))
  handle('ff:save-key', (_, key: string) => saveKey(data, String(key)))
  handle('ff:forget-key', () => forgetKey(data))
  handle('ff:new-video', (_, prompt: string) =>
    engine.call<string>('new_video', { root: videos, prompt })
  )
  handle('ff:edit-plan', async (_, folder: string, fields: Record<string, unknown>) =>
    shown(await engine.call<Described>('edit_plan', { folder: video(folder), fields }))
  )

  // A thinking job, with the thinker the settings name. The key goes to the engine in the job's
  // environment and nowhere else: should anything the job says repeat it, it is struck out here too.
  const think = (
    event: Electron.IpcMainInvokeEvent,
    channel: string,
    folder: string,
    args: string[],
    also?: (e: BuildEvent) => void
  ): Promise<void> => {
    const key = loadKey(data)
    return engine.think(folder, args, thinkerEnv(loadSettings(data), key), (e: BuildEvent) => {
      // Every text in the event but its type: a short key for a local service could be a word like "done".
      const said: BuildEvent = key
        ? JSON.parse(JSON.stringify(e), (name, value) =>
            typeof value === 'string' && name !== 'type'
              ? value.split(key).join('[the key]')
              : value
          )
        : e
      if (!event.sender.isDestroyed()) event.sender.send(`${channel}-event`, folder, said)
      also?.(said)
    })
  }
  // The creator may leave while it thinks: the notice tells when it is done, as a build's does.
  handle('ff:think', (event, folder: string, request: ThinkRequest) => {
    const window = BrowserWindow.fromWebContents(event.sender)
    return think(
      event,
      'ff:think',
      folder,
      thinkArgs(video(folder), request, chosen.list()),
      (e) => {
        const says = thoughtNotice(request.kind, e)
        if (says) void tell(window, folder, (title) => `${title}: ${says}`)
      }
    )
  })
  // No folder: a test asks the thinker for one answer and writes nothing.
  handle('ff:test-thinking', (event) => think(event, 'ff:test-thinking', '', ['test']))
  handle('ff:stop', (_, job: unknown, folder: string) => {
    if (job !== 'build' && job !== 'think') throw new Error(`Frameflow has no job called ${job}`)
    return engine.stop(job === 'build' ? 'building' : 'thinking', video(folder))
  })
  handle('ff:open', (event, folder: string) =>
    engine.open(video(folder), (e: BuildEvent) => {
      if (!event.sender.isDestroyed()) event.sender.send('ff:open-event', folder, e)
    })
  )
}
