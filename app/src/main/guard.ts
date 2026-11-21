// Which page the window may show, and which links may leave it for the creator's browser. Kept apart
// from index.ts and ipc.ts, which need Electron, so it can be tested.

/** True when `url` is the app's own `page`: the dev server's address, or the built index.html. */
export function ownPage(page: string, url: string): boolean {
  try {
    const own = new URL(page)
    const asked = new URL(url)
    // A file has no origin of its own to compare ("null"), so a built page is matched by its path.
    return own.protocol === 'file:'
      ? asked.protocol === 'file:' && asked.pathname === own.pathname
      : asked.origin === own.origin
  } catch {
    return false
  }
}

/** True for a link the creator's browser may open: a web page, never a file or another app's scheme. */
export function openable(url: string): boolean {
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}
