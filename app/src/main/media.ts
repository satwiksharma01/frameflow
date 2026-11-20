// Which file a thumbnail or preview URL may reach. Kept apart from ipc.ts, which needs Electron, so it
// can be tested.
import { basename, dirname, extname, isAbsolute, relative, resolve } from 'path'

export function inside(parent: string, path: string): boolean {
  const rel = relative(parent, path)
  return rel !== '' && !rel.startsWith('..') && !isAbsolute(rel)
}

/** The thumbnail a `ff-media` URL names, under one of the videos in `videos`; null for anything else.
 *  The path is resolved first, so `..` cannot climb out of the thumbnails to the rest of a video. */
export function thumbnailAt(videos: string, url: string): string | null {
  const path = resolve(new URL(url).searchParams.get('p') ?? '')
  const thumbs = dirname(path)
  const isThumb =
    basename(thumbs) === 'thumbs' &&
    basename(dirname(thumbs)) === 'app_cache' &&
    extname(path) === '.jpg'
  return inside(videos, path) && isThumb ? path : null
}

/** The preview a `ff-media` URL names: a `-preview.mp4` directly in one of the videos' folders; null for
 *  anything else. `relative` compares as Windows does, whatever the case of the drive letter. */
export function previewAt(videos: string, url: string): string | null {
  const path = resolve(new URL(url).searchParams.get('p') ?? '')
  const isPreview =
    relative(videos, dirname(dirname(path))) === '' && basename(path).endsWith('-preview.mp4')
  return isPreview ? path : null
}

/** The bytes a `Range` header asks for, in a file of `size` bytes; null when it asks for no one range,
 *  so the whole file is sent. */
export function rangeOf(
  header: string | null,
  size: number
): { start: number; end: number } | 'unsatisfiable' | null {
  const [, first, last] = /^bytes=(\d*)-(\d*)$/.exec(header ?? '') ?? []
  if (first === undefined || (first === '' && last === '')) return null
  if (first === '') {
    const n = Number(last) // the last n bytes
    return n > 0 && size > 0 ? { start: Math.max(0, size - n), end: size - 1 } : 'unsatisfiable'
  }
  const start = Number(first)
  if (last !== '' && Number(last) < start) return null // not a range at all
  if (start >= size) return 'unsatisfiable'
  return { start, end: last === '' ? size - 1 : Math.min(Number(last), size - 1) }
}
