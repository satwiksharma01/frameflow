// What a build's or a thinking job's desktop notice says, and when. Kept apart from ipc.ts, which
// needs Electron, so it can be tested.
import type { BuildEvent, ThinkRequest } from '../shared/types'

/** Follows one run's events. A video is built once its checks are written, so a run that fails or is
 *  stopped while its preview renders says nothing more; one that fails before then could not be built. */
export function noticeFor(): (e: BuildEvent) => 'is built' | 'could not be built' | null {
  let built = false
  return (e) => {
    if (e.type === 'built') {
      built = true
      return 'is built'
    }
    return e.type === 'done' && !e.ok && !built ? 'could not be built' : null
  }
}

/** What a thinking job's desktop notice says when it ends. A change in words says what it did in the
 *  window, so only the plan's jobs and Approve are told. */
export function thoughtNotice(kind: ThinkRequest['kind'], e: BuildEvent): string | null {
  if (e.type !== 'done' || kind === 'change') return null
  const what = kind === 'approve' ? 'storyboard' : 'plan'
  return e.ok ? `the ${what} is written` : `the ${what} could not be written`
}
