// @vitest-environment node
import { expect, it } from 'vitest'
import type { BuildEvent } from '../shared/types'
import { noticeFor, thoughtNotice } from './notice'

/** What one run's desktop notice says at each of its events, if anything. */
const notices = (events: BuildEvent[]): (string | null)[] => events.map(noticeFor())

it('the notice says the video is built when its checks are written, not when its preview is', () => {
  expect(
    notices([
      { type: 'step', text: 'Listening to every cut' },
      { type: 'built' },
      { type: 'detail', text: 'skipped: OpenShot is not installed' },
      { type: 'done', ok: true }
    ])
  ).toEqual([null, 'is built', null, null])
})

it('a run stopped by Build again gives no notice', () => {
  // Stopped while its preview renders: it was built, and its end sends no done.
  expect(notices([{ type: 'built' }, { type: 'detail', text: 'started 4242' }])).toEqual([
    'is built',
    null
  ])
})

it('a run that fails before its checks says it could not be built', () => {
  expect(
    notices([
      { type: 'step', text: 'Building the project' },
      { type: 'done', ok: false, message: 'the editor could not write the project' }
    ])
  ).toEqual([null, 'could not be built'])
})

it('a run that fails while its preview renders gives no second notice', () => {
  expect(
    notices([{ type: 'built' }, { type: 'done', ok: false, message: 'Traceback: MemoryError' }])
  ).toEqual(['is built', null])
})

it('a thinking job tells when its plan or its storyboard is written, or could not be', () => {
  const done = { type: 'done', ok: true } as const
  const failed = { type: 'done', ok: false, message: 'Claude Code stopped: not signed in' } as const
  expect(thoughtNotice('start', { type: 'step', text: 'Preparing the material' })).toBeNull()
  expect(thoughtNotice('start', done)).toBe('the plan is written')
  expect(thoughtNotice('plan-change', failed)).toBe('the plan could not be written')
  expect(thoughtNotice('answer', done)).toBe('the plan is written')
  expect(thoughtNotice('approve', { ...done, result: { storyboard: 'x' } })).toBe(
    'the storyboard is written'
  )
  expect(thoughtNotice('approve', failed)).toBe('the storyboard could not be written')
  // A change in words says what it did in the window.
  expect(thoughtNotice('change', done)).toBeNull()
})
