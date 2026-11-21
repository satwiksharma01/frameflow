import { app, shell, BrowserWindow, protocol, session } from 'electron'
import { join, resolve } from 'path'
import { pathToFileURL } from 'url'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import { createEngine } from './engine'
import { openable, ownPage } from './guard'
import { MEDIA, registerIpc } from './ipc'

// Frameflow's own folder: the app sits in it. FRAMEFLOW_ROOT and FRAMEFLOW_PYTHON override both.
const root = process.env['FRAMEFLOW_ROOT'] ?? resolve(app.getAppPath(), '..')
const engine = createEngine({ python: [process.env['FRAMEFLOW_PYTHON'] ?? 'python'], root })

// The dev server's page while developing, the built page otherwise: the only page the window shows.
const page =
  is.dev && process.env['ELECTRON_RENDERER_URL']
    ? process.env['ELECTRON_RENDERER_URL']
    : pathToFileURL(join(__dirname, '../renderer/index.html')).toString()

// Standard and streaming, so a <video> can seek in a preview by asking for ranges of it.
protocol.registerSchemesAsPrivileged([
  {
    scheme: MEDIA,
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true }
  }
])

function createWindow(): void {
  const mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    backgroundColor: '#0e0e0e',
    autoHideMenuBar: true,
    title: 'Frameflow',
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow.show())

  // A link may open in the creator's browser, and only a web page; the window itself opens nothing.
  mainWindow.webContents.setWindowOpenHandler((details) => {
    if (openable(details.url)) void shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // The window shows the app and nothing else: not a file dropped on it, not a page a link points at.
  // Any page it showed would be handed the app's whole API by the preload.
  mainWindow.webContents.on('will-navigate', (event) => {
    if (!ownPage(page, event.url)) event.preventDefault()
  })

  mainWindow.loadURL(page)
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId('com.frameflow.app')
  app.on('browser-window-created', (_, window) => optimizer.watchWindowShortcuts(window))
  // The window asks for nothing: no camera, microphone or location. Notices come from here, not the page.
  session.defaultSession.setPermissionRequestHandler((_, __, answer) => answer(false))
  registerIpc(engine, root, page)
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// A build must not outlive the app that started it.
app.on('before-quit', () => engine.stopAll())

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
