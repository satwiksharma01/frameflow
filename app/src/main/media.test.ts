// @vitest-environment node
import { join, resolve, sep } from 'path'
import { expect, it } from 'vitest'
import { inside, previewAt, rangeOf, thumbnailAt } from './media'

const videos = resolve('/frameflow/output')
const url = (path: string): string => `ff-media://thumb/?p=${encodeURIComponent(path)}`

it('a folder is one of the videos only by its full path: a relative one is refused', () => {
  expect(inside(videos, join(videos, 'reel'))).toBe(true)
  expect(inside(videos, videos)).toBe(false)
  // Relative, the app would resolve it against its own folder and the engine against the repository.
  const here = join(process.cwd(), 'output')
  expect(inside(here, join(here, 'reel'))).toBe(true)
  expect(inside(here, join('output', 'reel'))).toBe(false)
})

it("a video's thumbnail is served", () => {
  const thumb = join(videos, 'reel', 'app_cache', 'thumbs', '0a1b2c3d4e5f.jpg')
  expect(thumbnailAt(videos, url(thumb))).toBe(thumb)
})

it('a path that climbs out of the thumbnails is refused', () => {
  const climbing = [join(videos, 'reel', 'app_cache', 'thumbs'), '..', '..', 'inputs.json'].join(
    sep
  )
  expect(thumbnailAt(videos, url(climbing))).toBeNull()
  expect(thumbnailAt(videos, url(join(videos, 'reel', 'storyboard.json')))).toBeNull()
})

it('nothing outside the videos is served, and only pictures', () => {
  expect(thumbnailAt(videos, url(resolve('/elsewhere/app_cache/thumbs/x.jpg')))).toBeNull()
  expect(
    thumbnailAt(videos, url(join(videos, 'reel', 'app_cache', 'thumbs', 'notes.txt')))
  ).toBeNull()
})

it("a video's preview is served, and nothing else in its folder", () => {
  const preview = join(videos, 'reel', 'Editing-tier-list-preview.mp4')
  const at = (path: string): string | null =>
    previewAt(videos, `ff-media://preview/?p=${encodeURIComponent(path)}`)
  expect(at(preview)).toBe(preview)
  expect(at(join(videos, 'reel', 'storyboard.json'))).toBeNull()
  expect(at(join(videos, 'reel', 'app_cache', 'x-preview.mp4'))).toBeNull()
  expect(at([videos, 'reel', '..', '..', 'secret', 'x-preview.mp4'].join(sep))).toBeNull()
  expect(at(resolve('/elsewhere/reel/x-preview.mp4'))).toBeNull()
})

it('ranges are read as Chromium sends them', () => {
  expect(rangeOf('bytes=0-', 1000)).toEqual({ start: 0, end: 999 })
  expect(rangeOf('bytes=500-599', 1000)).toEqual({ start: 500, end: 599 })
  expect(rangeOf('bytes=-100', 1000)).toEqual({ start: 900, end: 999 })
  expect(rangeOf('bytes=990-2000', 1000)).toEqual({ start: 990, end: 999 })
  expect(rangeOf('bytes=1000-', 1000)).toBe('unsatisfiable')
  expect(rangeOf(null, 1000)).toBeNull()
  expect(rangeOf('items=1-2', 1000)).toBeNull()
})
