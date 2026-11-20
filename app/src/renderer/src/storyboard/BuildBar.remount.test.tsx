import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BuildEvent } from '@shared/types'
import { BuildBar } from './BuildBar'
import { unbuilt } from './fixture'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'

function fakeBuild(): {
  build: ReturnType<typeof vi.fn>
  say: (event: BuildEvent) => void
  end: (ok: boolean, message?: string) => Promise<void>
} {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const build = vi.fn((_folder: string, listener: (e: BuildEvent) => void) => {
    onEvent = listener
    return new Promise<void>((resolve) => (finish = resolve))
  })
  return {
    build,
    say: (event) => act(() => onEvent(event)),
    end: async (ok, message) => {
      await act(async () => {
        onEvent(ok ? { type: 'done', ok } : { type: 'done', ok, message })
        finish()
      })
    }
  }
}

it('a build keeps running when its video is left and opened again', async () => {
  const { build, say, end } = fakeBuild()
  window.frameflow = { build } as never
  const left = render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: 'Build video' }))
  say({ type: 'step', text: 'Building the project' })
  left.unmount() // the creator opens another video

  say({ type: 'step', text: 'Listening to every cut' }) // the build carries on meanwhile

  const onBuilt = vi.fn()
  render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={onBuilt} />)
  expect(screen.getByRole('button', { name: 'Building' })).toBeDisabled()
  const steps = within(screen.getByRole('list', { name: 'Build steps' })).getAllByRole('listitem')
  expect(steps.map((s) => s.textContent)).toEqual([
    'Building the project',
    'Listening to every cut'
  ])
  await userEvent.click(screen.getByRole('button', { name: 'Building' }))
  expect(build).toHaveBeenCalledTimes(1)

  await end(true)
  expect(onBuilt).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: 'Build video' })).toBeEnabled()
})

it("another video's build does not show on this one", async () => {
  const { build } = fakeBuild()
  window.frameflow = { build } as never
  const first = render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: 'Build video' }))
  first.unmount()
  render(<BuildBar folder="E:\\other video" described={unbuilt} onBuilt={() => {}} />)
  expect(screen.getByRole('button', { name: 'Build video' })).toBeEnabled()
})

it('the step a build failed on is marked as failed, not as done', async () => {
  const { build, say, end } = fakeBuild()
  window.frameflow = { build } as never
  render(<BuildBar folder={FOLDER} described={unbuilt} onBuilt={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: 'Build video' }))
  say({ type: 'step', text: 'Recording the voiceover and preparing the pictures' })
  say({ type: 'step', text: 'Building the project' })
  await end(false, 'the editor could not write the project')
  const steps = within(screen.getByRole('list', { name: 'Build steps' })).getAllByRole('listitem')
  expect(steps.map((s) => s.getAttribute('data-state'))).toEqual(['done', 'failed'])
})
