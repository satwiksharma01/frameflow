import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BuildEvent, Described } from '@shared/types'
import { BuildBar } from './BuildBar'
import { tierList, unbuilt } from './fixture'
import { summary } from './model'
import { Storyboard } from './Storyboard'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'

/** A build the test drives: `say` sends what the engine prints, `end` finishes it. */
function fakeBuild(): {
  build: ReturnType<typeof vi.fn>
  say: (...events: BuildEvent[]) => void
  end: (ok?: boolean, message?: string) => Promise<void>
} {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const build = vi.fn((_folder: string, listener: (e: BuildEvent) => void) => {
    onEvent = listener
    return new Promise<void>((resolve) => (finish = resolve))
  })
  return {
    build,
    say: (...events) => act(() => events.forEach((e) => onEvent(e))),
    end: async (ok = true, message) => {
      await act(async () => {
        onEvent(ok ? { type: 'done', ok } : { type: 'done', ok, message })
        finish()
      })
    }
  }
}

const button = (name: string): HTMLElement => screen.getByRole('button', { name })

it('Build video starts a build and is disabled while it runs', async () => {
  const { build, end } = fakeBuild()
  window.frameflow = { build } as never
  render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={() => {}} />)
  await userEvent.click(button('Build video'))
  expect(build).toHaveBeenCalledWith(FOLDER, expect.any(Function))
  expect(button('Building')).toBeDisabled()
  await end()
  expect(button('Build video')).toBeEnabled()
})

it('a second click while building starts nothing', async () => {
  const { build } = fakeBuild()
  window.frameflow = { build } as never
  render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={() => {}} />)
  await userEvent.click(button('Build video'))
  await userEvent.click(button('Building'))
  expect(build).toHaveBeenCalledTimes(1)
})

it('steps appear in order: the current one is busy, earlier ones are done, with the latest detail', async () => {
  const { build, say } = fakeBuild()
  window.frameflow = { build } as never
  render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={() => {}} />)
  await userEvent.click(button('Build video'))
  say(
    { type: 'step', text: 'Building the project' },
    { type: 'detail', text: '9 scenes, 20.1s (brief asked for about 20s)' },
    { type: 'step', text: 'Listening to every cut' },
    { type: 'detail', text: '7 of 8 joins sound clean' }
  )
  const steps = within(screen.getByRole('list', { name: 'Build steps' })).getAllByRole('listitem')
  expect(steps.map((s) => [s.textContent, s.getAttribute('data-state')])).toEqual([
    ['Building the project', 'done'],
    ['Listening to every cut', 'current']
  ])
  expect(screen.getByText('7 of 8 joins sound clean')).toBeInTheDocument()
})

it('a failed build shows what the engine said and offers Build again', async () => {
  const { build, say, end } = fakeBuild()
  window.frameflow = { build } as never
  const onBuilt = vi.fn()
  render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={onBuilt} />)
  await userEvent.click(button('Build video'))
  say({ type: 'step', text: 'Recording the voiceover and preparing the pictures' })
  await end(false, 'storyboard.json needs fixing:\n  scene 2 (footage): ends after its recording')
  expect(screen.getByRole('alert')).toHaveTextContent('scene 2 (footage): ends after its recording')
  expect(button('Build again')).toBeEnabled()
  expect(onBuilt).not.toHaveBeenCalled()
  expect(screen.getByRole('list', { name: 'Build steps' })).toHaveTextContent(
    'Recording the voiceover'
  )
})

it('while the preview is made the footer says "Making the preview…" and Build video is offered', async () => {
  const { build, say } = fakeBuild()
  window.frameflow = { build } as never
  render(<BuildBar folder={FOLDER} described={tierList} onBuilt={() => {}} />)
  await userEvent.click(button('Build video'))
  say({ type: 'step', text: 'Listening to every cut' }, { type: 'built' })
  expect(screen.getByText(`${summary(tierList)} Making the preview…`)).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: 'Build steps' })).toBeNull()
  await userEvent.click(button('Build video'))
  expect(build).toHaveBeenCalledTimes(2)
  expect(button('Building')).toBeDisabled()
})

it('a build stopped by Build again is not shown as failed, and only the new build shows', async () => {
  const runs: { say: (e: BuildEvent) => void; end: () => void }[] = []
  const build = vi.fn(
    (_folder: string, onEvent: (e: BuildEvent) => void) =>
      new Promise<void>((resolve) => runs.push({ say: onEvent, end: resolve }))
  )
  window.frameflow = { build } as never
  render(<BuildBar folder={FOLDER} described={tierList} onBuilt={() => {}} />)
  await userEvent.click(button('Build video'))
  act(() => runs[0].say({ type: 'built' }))
  await userEvent.click(button('Build video'))
  // Until the stopped run's request ends, its listener hears the new build's events too.
  act(() => runs.forEach((run) => run.say({ type: 'step', text: 'Building the project' })))
  await act(async () => runs[0].end()) // stopped: it ends without a done
  expect(screen.queryByRole('alert')).toBeNull()
  expect(button('Building')).toBeDisabled()
  const steps = within(screen.getByRole('list', { name: 'Build steps' })).getAllByRole('listitem')
  expect(steps.map((s) => s.textContent)).toEqual(['Building the project'])
})

it('the storyboard reloads when the build is built, before its preview is made', async () => {
  const { build, say, end } = fakeBuild()
  const describe = vi.fn().mockResolvedValueOnce(unbuilt).mockResolvedValue(tierList)
  window.frameflow = { build, describe, thumbnail: async () => null } as never
  render(
    <Storyboard
      folder={FOLDER}
      footer={(state) => (
        <BuildBar folder={FOLDER} described={state.described!} onBuilt={state.reload} />
      )}
    />
  )
  await screen.findAllByRole('option')
  await userEvent.click(button('Build video'))
  say({ type: 'step', text: 'Listening to every cut' }, { type: 'built' })
  await waitFor(() => expect(describe).toHaveBeenCalledTimes(2))
  expect(await screen.findAllByText('May clip “work”')).not.toHaveLength(0)
  await end()
  await waitFor(() => expect(describe).toHaveBeenCalledTimes(3)) // again, for its preview
})

it('says what the last build found, and that a changed storyboard is not built', () => {
  expect(summary(tierList)).toBe(
    'Built. 7 of 8 cuts sound clean, 1 to listen to. Picture: nothing wrong.'
  )
  expect(summary(unbuilt)).toBe('Not built since it last changed.')
  const skipped: Described = {
    ...tierList,
    report: { ...tierList.report!, joins: null, picture: { skipped: 'OpenShot is not installed' } }
  }
  expect(summary(skipped)).toBe('Built. Picture not checked: OpenShot is not installed.')
})

it('when the build ends, the storyboard is described again and scene 6 shows its check', async () => {
  const { build, end } = fakeBuild()
  const describe = vi.fn().mockResolvedValueOnce(unbuilt).mockResolvedValue(tierList)
  window.frameflow = { build, describe, thumbnail: async () => null } as never
  render(
    <Storyboard
      folder={FOLDER}
      footer={(state) => (
        <BuildBar folder={FOLDER} described={state.described!} onBuilt={state.reload} />
      )}
    />
  )
  await screen.findAllByRole('option')
  expect(screen.queryByText('May clip “work”')).toBeNull()
  await userEvent.click(button('Build video'))
  await end()
  await waitFor(() => expect(describe).toHaveBeenCalledTimes(2))
  expect(await screen.findAllByText('May clip “work”')).not.toHaveLength(0)
  expect(screen.getByRole('group', { name: 'Length' })).toHaveTextContent('20.1/20 seconds')
  expect(screen.getAllByRole('option')).toHaveLength(9) // still on screen: no flash back to loading
})
