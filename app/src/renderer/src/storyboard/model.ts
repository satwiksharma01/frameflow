// A described video, worked out for the storyboard screen: its chapters, each scene's rule and checks,
// and the two figures at the top.
import type { Described, Report, Scene } from '@shared/types'

export interface SceneView extends Scene {
  /** The scene's length against the longest scene, 0 to 1: how long its rule is drawn. */
  rule: number
  /** What the last build found on this scene, in the creator's words and in order, each with the timeline
   *  second to listen around. */
  checks: { what: string; at: number }[]
}

export interface SectionView {
  number: number
  title: string | null
  start: number | null
  scenes: SceneView[]
  /** False for a chapter the editor suggested that the creator has not renamed or kept. */
  confirmed: boolean
}

export interface Figures {
  scenes: number
  seconds: number | null
  target: number
  over: boolean
  estimated: boolean
}

export function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}

// A cut is inside a scene, where its long pauses were cut, or at its end; one at the end of one scene
// and the start of the next is the first one's.
function holds(scene: Scene, at: number): boolean {
  return (
    scene.start !== null &&
    scene.seconds !== null &&
    scene.start < at &&
    at <= scene.start + scene.seconds + 0.05
  )
}

function checks(
  scene: Scene,
  scenes: Scene[],
  report: Report | null | undefined
): SceneView['checks'] {
  if (!report || scene.start === null || scene.seconds === null) return []
  const start = scene.start
  const end = start + scene.seconds
  const joins = (report.joins && 'suspect' in report.joins ? report.joins.suspect : [])
    .filter((j) => scenes.find((s) => holds(s, j.at)) === scene)
    .map((j) => {
      const last = j.before
        .trim()
        .split(/\s+/)
        .at(-1)
        ?.replace(/[^\p{L}\p{N}'’-]/gu, '')
      return { what: last ? `May clip “${last}”` : 'May clip its last word', at: j.at }
    })
  const problems = ('problems' in report.picture ? report.picture.problems : [])
    .filter((p) => p.at !== null && p.at >= start && p.at < end)
    .map((p) => ({ what: p.what.charAt(0).toUpperCase() + p.what.slice(1), at: p.at! }))
  return [...joins, ...problems].sort((a, b) => a.at - b.at)
}

export function toView(d: Described): { sections: SectionView[]; figures: Figures } {
  const report = d.built ? d.report : null
  const longest = Math.max(0, ...d.scenes.map((s) => s.seconds ?? 0))
  const scenes: SceneView[] = d.scenes.map((s) => ({
    ...s,
    rule: longest && s.seconds ? Math.round((s.seconds / longest) * 1000) / 1000 : 0,
    checks: checks(s, d.scenes, report)
  }))

  const named = d.sections?.length ? d.sections : [{ title: null, from: 1 }]
  const sections = named.map((section, i) => {
    const mine = scenes.slice(section.from - 1, (named[i + 1]?.from ?? scenes.length + 1) - 1)
    return {
      number: i + 1,
      title: section.title,
      start: mine[0]?.start ?? null,
      scenes: mine,
      confirmed: 'confirmed' in section ? section.confirmed !== false : true
    }
  })

  // Before a build, a sum is offered only when every scene's length is known: part of it would be read
  // as the video's length.
  const known = scenes.length > 0 && scenes.every((s) => s.seconds !== null)
  const seconds = report
    ? report.seconds
    : known
      ? scenes.reduce((sum, s) => sum + s.seconds!, 0)
      : null
  const target = d.target_seconds ?? 0
  return {
    sections,
    figures: {
      scenes: scenes.length,
      seconds,
      target,
      over: seconds !== null && target > 0 && seconds > target * 1.1,
      estimated: !report
    }
  }
}

/** Which scenes' numbers fit under the video's rules in a strip `width` px wide, as SceneRules draws them
 *  (2 px apart, each number left on its rule, about 7 px a digit at 11 px): the current one first, then the
 *  first and the last, then the next, each only where it would not touch one already placed. */
export function numbered(scenes: SceneView[], current: SceneView | null, width: number): number[] {
  const total = scenes.reduce((sum, s) => sum + (s.seconds ?? 0), 0)
  const perSecond = Math.max(0, width - 2 * (scenes.length - 1)) / (total || 1)
  let x = 0
  const left = scenes.map((s) => {
    const at = x
    x += (s.seconds ?? 0) * perSecond + 2
    return at
  })
  const room = (n: number): number => String(n).padStart(2, '0').length * 7 + 4 // its digits and a gap
  const placed: number[] = []
  for (const n of [current?.number, 1, scenes.length, current && current.number + 1]) {
    if (!n || n > scenes.length || placed.includes(n)) continue
    // Rules run in order, so of two numbers the lower one is on the left.
    if (placed.every((p) => Math.abs(left[n - 1] - left[p - 1]) >= room(Math.min(n, p))))
      placed.push(n)
  }
  return placed
}

/** What the last build found, in one line; or that the storyboard has changed since, or was never built. */
export function summary(d: Described): string {
  const report = d.built ? d.report : null
  if (!report) return d.ever_built === false ? 'Not built yet.' : 'Not built since it last changed.'
  const parts = ['Built.']
  if (report.joins && 'checked' in report.joins) {
    const suspect = report.joins.suspect.length
    const clean = `${report.joins.checked - suspect} of ${report.joins.checked} cuts sound clean`
    parts.push(suspect ? `${clean}, ${suspect} to listen to.` : `${clean}.`)
  } else if (report.joins) {
    parts.push(`Cuts not listened to: ${report.joins.skipped}.`)
  }
  if ('problems' in report.picture) {
    const problems = report.picture.problems.length
    parts.push(problems ? `Picture: ${problems} to look at.` : 'Picture: nothing wrong.')
  } else {
    parts.push(`Picture not checked: ${report.picture.skipped}.`)
  }
  return parts.join(' ')
}
