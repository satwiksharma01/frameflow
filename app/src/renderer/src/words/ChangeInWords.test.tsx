import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BuildEvent, Described, SettingsView, ThinkRequest } from '@shared/types'
import { claudeCode, openAiKey } from '../prompt/fixture'
import { think, useThought } from '../prompt/thinking'
import { say } from '../shell/say'
import { Toasts } from '../shell/Toasts'
import { tierList } from '../storyboard/fixture'
import { Storyboard } from '../storyboard/Storyboard'
import { slowExits } from '../test-setup'
import { VideoStep } from '../video/VideoScreen'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'
const FIELD = 'Change it in words, like “make scene 4 shorter”'
const WORDS = 'Put the S-tier verdict first'
const CHANGED =
  'The storyboard changed outside the app, so it was reloaded. Your last change was not made.'
const SIGN_IN = 'Claude Code is not signed in. Sign in to it, or choose another way in Settings.'

// The storyboard once the change has landed: scene 9 first.
const moved: Described = {
  ...tierList,
  version: 'v2',
  can_undo: true,
  scenes: [tierList.scenes[8], ...tierList.scenes.slice(0, 8)].map((s, i) => ({
    ...s,
    number: i + 1
  }))
}

type Done = Extract<BuildEvent, { type: 'done' }>

/** The engine for this file: `say` sends what the job prints, `end` ends it, with a `done` or, for one
 *  a newer job replaced, without. */
function engine(settings: SettingsView = claudeCode): {
  think: ReturnType<typeof vi.fn>
  describe: ReturnType<typeof vi.fn>
  undo: ReturnType<typeof vi.fn>
  stop: ReturnType<typeof vi.fn>
  say: (...events: BuildEvent[]) => void
  end: (done?: Done) => Promise<void>
} {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const think = vi.fn(
    (_folder: string, _request: ThinkRequest, listener: (e: BuildEvent) => void) => {
      onEvent = listener
      return new Promise<void>((resolve) => (finish = resolve))
    }
  )
  const describe = vi.fn(async () => tierList)
  const undo = vi.fn(async () => ({ described: { ...tierList, version: 'v3' }, notes: [] }))
  const stop = vi.fn(async () => true)
  window.frameflow = {
    describe,
    think,
    undo,
    stop,
    settings: async () => settings,
    thumbnail: async () => null
  } as never
  return {
    think,
    describe,
    undo,
    stop,
    say: (...events) => act(() => events.forEach((e) => onEvent(e))),
    end: async (done) => {
      await act(async () => {
        if (done) onEvent(done)
        finish()
      })
    }
  }
}

function board(onSettings?: () => void): ReturnType<typeof render> {
  return render(
    <>
      <Storyboard folder={FOLDER} footer={(_, words) => words} onSettings={onSettings} />
      <Toasts />
    </>
  )
}

const field = (): HTMLElement => screen.getByRole('textbox', { name: FIELD })
const scene = (n: number): HTMLElement =>
  screen.getByRole('button', { name: new RegExp(`^Scene ${n}:`) })

async function send(words = WORDS): Promise<void> {
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(field())
  await userEvent.keyboard(`${words}{Enter}`)
}

it('a sentence is sent with the storyboard’s version when Enter is pressed', async () => {
  const fake = engine()
  board()
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(field()).toHaveAttribute('placeholder', FIELD)
  await userEvent.click(field())
  await userEvent.keyboard('Put the S-tier ')
  expect(fake.think).not.toHaveBeenCalled()
  await userEvent.keyboard('verdict first{Enter}')
  expect(fake.think).toHaveBeenCalledTimes(1)
  expect(fake.think).toHaveBeenCalledWith(
    FOLDER,
    { kind: 'change', words: WORDS, version: 'v1' },
    expect.any(Function)
  )
})

it('while it thinks the sentence stays, the thinker is named and the storyboard is as it was', async () => {
  const fake = engine()
  board()
  await send()
  expect(field()).toHaveValue(WORDS)
  expect(field()).toHaveAttribute('readonly')
  expect(await screen.findByText('Making the change with Claude Code…')).toBeInTheDocument()
  expect(scene(1)).toHaveFocus() // sent, the keys work on the scenes again
  expect(fake.describe).toHaveBeenCalledTimes(1)
  expect(scene(1)).toHaveAccessibleName('Scene 1: main problem with video editing')
})

it('names the thinker the settings choose', async () => {
  engine(openAiKey)
  board()
  await send()
  expect(await screen.findByText('Making the change with OpenAI…')).toBeInTheDocument()
})

it('done, the storyboard is read again and says what changed, and one Undo takes it all back', async () => {
  const fake = engine()
  board()
  await send()
  fake.describe.mockResolvedValue(moved)
  await fake.end({
    type: 'done',
    ok: true,
    result: { summary: 'Moved scene 9 to the start', notes: [] }
  })
  expect(await screen.findByText('Moved scene 9 to the start')).toBeInTheDocument()
  await waitFor(() =>
    expect(scene(1)).toHaveAccessibleName('Scene 1: I still want the human to have control')
  )
  expect(field()).toHaveValue('')
  expect(field()).not.toHaveAttribute('readonly')
  expect(screen.queryByText(/Making the change/)).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
  await waitFor(() => expect(fake.undo).toHaveBeenCalledWith(FOLDER, 'v2'))
  await waitFor(() =>
    expect(scene(1)).toHaveAccessibleName('Scene 1: main problem with video editing')
  )
  expect(fake.undo).toHaveBeenCalledTimes(1)
})

it('Ctrl Z takes the change back too', async () => {
  const fake = engine()
  board()
  await send()
  fake.describe.mockResolvedValue(moved)
  await fake.end({
    type: 'done',
    ok: true,
    result: { summary: 'Moved scene 9 to the start', notes: [] }
  })
  await waitFor(() =>
    expect(scene(1)).toHaveAccessibleName('Scene 1: I still want the human to have control')
  )
  await userEvent.keyboard('{Control>}z{/Control}')
  await waitFor(() => expect(fake.undo).toHaveBeenCalledWith(FOLDER, 'v2'))
  expect(fake.undo).toHaveBeenCalledTimes(1)
})

it('what the change notes is said with it, as an edit’s notes are', async () => {
  const note =
    'Card “Hi” now shows from the start of the scene: “goodbye” is not said in it any more.'
  const fake = engine()
  board()
  await send('Add a card saying hi')
  await fake.end({ type: 'done', ok: true, result: { summary: 'Added a card', notes: [note] } })
  expect(await screen.findByText('Added a card')).toBeInTheDocument()
  expect(screen.getByText(note)).toBeInTheDocument()
})

it('a refusal says it can’t be changed in words yet, and where to change it by hand', async () => {
  const fake = engine()
  board()
  await send('Make the music quieter')
  await fake.end({
    type: 'done',
    ok: false,
    message: 'The music’s volume is not something these operations change.',
    refused: true
  })
  expect(await screen.findByText('That can’t be changed in words yet.')).toBeInTheDocument()
  expect(
    screen.getByText('Change it by hand on the storyboard, or in OpenShot.')
  ).toBeInTheDocument()
  expect(screen.queryByText(/volume/)).toBeNull()
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  expect(field()).toHaveValue('')
  expect(fake.describe).toHaveBeenCalledTimes(1)
})

it('a storyboard changed meanwhile says so, and is read again', async () => {
  const fake = engine()
  board()
  await send()
  await fake.end({ type: 'done', ok: false, message: CHANGED, changed: true })
  expect(await screen.findByText(CHANGED)).toBeInTheDocument()
  await waitFor(() => expect(fake.describe).toHaveBeenCalledTimes(2))
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull()
  // The sentence stays, to send again against the storyboard as it is now.
  expect(field()).toHaveValue(WORDS)
  expect(field()).not.toHaveAttribute('readonly')
})

it('a failure says the engine’s line, and keeps the sentence to send again', async () => {
  const fake = engine()
  board(() => {})
  await send()
  await fake.end({ type: 'done', ok: false, message: 'The thinker stopped: out of memory.' })
  expect(await screen.findByText('The thinker stopped: out of memory.')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Open Settings' })).toBeNull()
  expect(field()).toHaveValue(WORDS)
  await userEvent.click(field())
  await userEvent.keyboard('{Enter}')
  expect(fake.think).toHaveBeenCalledTimes(2)
  expect(fake.think).toHaveBeenLastCalledWith(
    FOLDER,
    { kind: 'change', words: WORDS, version: 'v1' },
    expect.any(Function)
  )
})

it('a failure is not kept as the plan’s, which the prompt step would show', async () => {
  const fake = engine()
  board()
  await send()
  await fake.end({ type: 'done', ok: false, message: 'The thinker stopped: out of memory.' })
  expect(renderHook(() => useThought(FOLDER)).result.current).toMatchObject({
    running: false,
    failure: null
  })
})

it('a change the creator stopped says nothing, and keeps the sentence to send again', async () => {
  const fake = engine()
  board()
  await send()
  const toasts = (): number => document.querySelectorAll('[data-sonner-toast]').length
  const said = toasts() // a toast an earlier test left may still be up
  await fake.end({ type: 'done', ok: false, stopped: true })
  await new Promise((r) => setTimeout(r, 50)) // a toast would be up by now
  expect(screen.queryByText(/Making the change/)).toBeNull()
  expect(toasts()).toBe(said)
  expect(field()).toHaveValue(WORDS)
  expect(renderHook(() => useThought(FOLDER)).result.current).toMatchObject({
    running: false,
    failure: null
  })
})

it('while a change runs, Stop stops it and puts the cursor back in the field', async () => {
  const fake = engine()
  board()
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(screen.queryByRole('button', { name: 'Stop the change' })).toBeNull()
  await send()
  await userEvent.click(screen.getByRole('button', { name: 'Stop the change' }))
  expect(fake.stop).toHaveBeenCalledWith('think', FOLDER)
  expect(field()).toHaveFocus()
  await fake.end({ type: 'done', ok: false, stopped: true })
  expect(screen.queryByRole('button', { name: 'Stop the change' })).toBeNull()
  expect(field()).toHaveValue(WORDS)
})

it('a failure that points to Settings offers Open Settings', async () => {
  const onSettings = vi.fn()
  const fake = engine()
  board(onSettings)
  await send()
  await fake.end({ type: 'done', ok: false, message: SIGN_IN })
  expect(await screen.findByText(SIGN_IN)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Open Settings' }))
  expect(onSettings).toHaveBeenCalledTimes(1)
})

it('a change a newer job replaced shows nothing', async () => {
  const fake = engine()
  board()
  await send()
  const toasts = (): string | undefined =>
    document.querySelector('[data-sonner-toaster]')?.textContent
  const said = toasts() // a toast an earlier test left may still be up
  await fake.end() // the engine ends a replaced job without a word
  expect(screen.queryByText(/Making the change/)).toBeNull()
  expect(toasts()).toBe(said)
  expect(fake.describe).toHaveBeenCalledTimes(1)
})

it('leaving the storyboard while it thinks keeps the job, and coming back shows it', async () => {
  engine()
  const first = board()
  await send()
  first.unmount()
  board()
  expect(await screen.findByText('Making the change with Claude Code…')).toBeInTheDocument()
  expect(field()).toHaveValue(WORDS)
})

it('Ctrl L goes to the field from the scenes, and Esc gives the focus back to them', async () => {
  engine()
  board()
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(3))
  await userEvent.keyboard('{Control>}l{/Control}')
  expect(field()).toHaveFocus()
  expect(field()).toHaveAttribute('aria-keyshortcuts', 'Control+L')
  await userEvent.keyboard('{Escape}')
  expect(scene(3)).toHaveFocus()
})

it('while it thinks, Esc keeps the field and Enter sends nothing more', async () => {
  const fake = engine()
  board()
  await send()
  await userEvent.keyboard('{Control>}l{/Control}')
  expect(field()).toHaveFocus()
  await userEvent.keyboard('{Escape}{Enter}')
  expect(field()).toHaveFocus()
  expect(fake.think).toHaveBeenCalledTimes(1)
})

it('while a plan job runs, the field shows its step and sends nothing, so the job goes on', async () => {
  const fake = engine()
  board()
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  act(() => void think(FOLDER, { kind: 'approve' })) // Approve, asked on the prompt step
  fake.say({ type: 'step', text: 'Writing the storyboard' })
  expect(screen.getByText('Writing the storyboard…')).toBeInTheDocument()
  expect(field()).toHaveAttribute('readonly')
  await userEvent.click(field())
  await userEvent.keyboard(`${WORDS}{Enter}`)
  expect(fake.think).toHaveBeenCalledTimes(1)
  expect(fake.think).toHaveBeenCalledWith(FOLDER, { kind: 'approve' }, expect.any(Function))
  expect(screen.queryByText(/Making the change/)).toBeNull()
})

it('a change that lands after its video has gone names it, and leaves the shown video’s Undo', async () => {
  const fake = engine()
  const first = board()
  await send()
  first.unmount()
  render(<Toasts />)
  act(() => say('Scene 3 deleted', { undo: () => {} })) // the video on screen now, with its own Undo
  expect(await screen.findByText('Scene 3 deleted')).toBeInTheDocument()
  await fake.end({
    type: 'done',
    ok: true,
    result: { summary: 'Removed scene 2', notes: [] } // its own words: this toast outlasts the test
  })
  const landed = (await screen.findByText('Removed scene 2')).closest(
    '[data-sonner-toast]'
  ) as HTMLElement
  expect(within(landed).getByText('Editing tier list')).toBeInTheDocument()
  expect(within(landed).queryByRole('button')).toBeNull()
  expect(screen.getByText('Scene 3 deleted')).toBeInTheDocument()
  // The shown video's next change comes to the front, its Undo in reach.
  const undo = vi.fn()
  act(() => say('Scene 4 deleted', { undo }))
  const next = (await screen.findByText('Scene 4 deleted')).closest(
    '[data-sonner-toast]'
  ) as HTMLElement
  await waitFor(() => expect(next).toHaveAttribute('data-visible', 'true')) // once the other has gone
  await userEvent.click(within(next).getByRole('button', { name: 'Undo' }))
  expect(undo).toHaveBeenCalledTimes(1)
})

it('a click on the field’s hint puts the cursor in it', async () => {
  engine()
  board()
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(screen.getByText('Ctrl L'))
  expect(field()).toHaveFocus()
})

it('the command palette has Change it in words, which leaves the cursor in the field', async () => {
  const dialog = slowExits()
  engine()
  board()
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.click(await screen.findByRole('option', { name: /^Change it in words/ }))
  // By its label: while the palette closes, Radix still hides the page from the accessibility tree.
  await waitFor(() => expect(screen.getByLabelText(FIELD)).toHaveFocus())
  await act(async () => dialog.finish())
  await act(() => new Promise((r) => setTimeout(r, 50))) // Radix hands the focus back a tick later
  expect(field()).toHaveFocus()
})

describe('on the video step', () => {
  function video(): void {
    render(
      <>
        <VideoStep folder={FOLDER} onGoTo={() => {}} />
        <Toasts />
      </>
    )
  }

  it('Esc gives the focus back to the video, so its keys work again', async () => {
    engine()
    video()
    await userEvent.click(await screen.findByRole('textbox', { name: FIELD }))
    await userEvent.keyboard('{Escape}')
    const step = screen.getByRole('region', { name: 'The video' }).parentElement?.parentElement
    expect(step).toHaveAttribute('tabindex', '-1')
    expect(step).toHaveFocus()
  })

  it('sits before the main action, and says a refusal as the storyboard does', async () => {
    const fake = engine()
    video()
    const open = await screen.findByRole('button', { name: 'Open in OpenShot' })
    expect(field().compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await userEvent.click(field())
    await userEvent.keyboard('Make the music quieter{Enter}')
    expect(fake.think).toHaveBeenCalledWith(
      FOLDER,
      { kind: 'change', words: 'Make the music quieter', version: 'v1' },
      expect.any(Function)
    )
    await fake.end({ type: 'done', ok: false, message: 'No volume op.', refused: true })
    expect(await screen.findByText('That can’t be changed in words yet.')).toBeInTheDocument()
  })

  it('a change sent on the storyboard that lands here is read, and undone, here', async () => {
    const fake = engine()
    const first = board()
    await send()
    first.unmount()
    video()
    expect(await screen.findByText('Making the change with Claude Code…')).toBeInTheDocument()
    fake.describe.mockResolvedValue(moved)
    await fake.end({
      type: 'done',
      ok: true,
      result: { summary: 'Moved scene 9 to the start', notes: [] }
    })
    expect(await screen.findByText('Moved scene 9 to the start')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        screen.getByText('I still want the human to have control').closest('li')
      ).toHaveAttribute('data-scene', '1')
    )
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(fake.undo).toHaveBeenCalledWith(FOLDER, 'v2'))
    await waitFor(() =>
      expect(screen.getByText('main problem with video editing').closest('li')).toHaveAttribute(
        'data-scene',
        '1'
      )
    )
  })
})
