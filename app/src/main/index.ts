import { app, shell, BrowserWindow, protocol } from 'electron'
import { join, resolve } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'
import { createEngine } from './engine'
import { MEDIA, registerIpc } from './ipc'

// Frameflow's own folder: the app sits in it. FRAMEFLOW_ROOT and FRAMEFLOW_PYTHON override both.
const root = process.env['FRAMEFLOW_ROOT'] ?? resolve(app.getAppPath(), '..')
const engine = createEngine({ python: [process.env['FRAMEFLOW_PYTHON'] ?? 'python'], root })

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
      sandbox: false
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow.show())

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // The dev server's page while developing, the built page otherwise.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  electronApp.setAppUserModelId('com.frameflow.app')
  app.on('browser-window-created', (_, window) => optimizer.watchWindowShortcuts(window))
  registerIpc(engine, root)
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
