import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BuildEvent, Described, SettingsView, ThinkRequest } from '@shared/types'
import { Toasts } from '../shell/Toasts'
import {
  claudeCode,
  FOLDER,
  IDEA,
  openAiKey,
  pitch,
  planned,
  QUESTIONS,
  unplanned
} from './fixture'
import { PromptStep } from './PromptStep'
import { think } from './thinking'

const CHANGED =
  'The storyboard changed outside the app, so it was reloaded. Your last change was not made.'

/** The thinking jobs this file drives: `say` sends what the engine prints for the latest one, `end` ends
 *  it, with a `done` or, for one a newer job replaced, without. */
function fakeThink(): {
  think: ReturnType<typeof vi.fn>
  say: (...events: BuildEvent[]) => void
  end: (done?: Extract<BuildEvent, { type: 'done' }>) => Promise<void>
} {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const think = vi.fn(
    (_folder: string, _request: ThinkRequest, listener: (e: BuildEvent) => void) => {
      onEvent = listener
      return new Promise<void>((resolve) => (finish = resolve))
    }
  )
  return {
    think,
    say: (...events) => act(() => events.forEach((e) => onEvent(e))),
    end: async (done) => {
      await act(async () => {
        if (done) onEvent(done)
        finish()
      })
    }
  }
}

function api(
  described: Described | (() => Described) = unplanned,
  more: object = {},
  settings: SettingsView = claudeCode
): ReturnType<typeof fakeThink> & Record<string, ReturnType<typeof vi.fn>> {
  const fake = fakeThink()
  const frameflow = {
    think: fake.think,
    describe: vi.fn(async () => (typeof described === 'function' ? described() : described)),
    settings: vi.fn(async () => settings),
    newVideo: vi.fn(async () => FOLDER),
    chooseFiles: vi.fn(async () => []),
    editPlan: vi.fn(async () => planned()),
    ...more
  }
  window.frameflow = frameflow as never
  return { ...frameflow, ...fake } as never
}

const button = (name: string): HTMLElement => screen.getByRole('button', { name })
const idea = (): HTMLElement => screen.getByRole('textbox', { name: 'What you want' })
const steps = (): string[] =>
  within(screen.getByRole('list', { name: 'Plan steps' }))
    .getAllByRole('listitem')
    .map((s) => s.textContent ?? '')

it('New video gives an empty prompt, and Write the plan is off until there is an idea', async () => {
  api()
  render(<PromptStep folder={null} />)
  expect(idea()).toHaveValue('')
  expect(idea()).toHaveAttribute(
    'placeholder',
    'Say what you want: the video, who it is for, how long, and anything it must say.'
  )
  expect(
    screen.getByText('Nothing added. Frameflow makes it from titles, graphics and a voiceover.')
  ).toBeInTheDocument()
  expect(
    screen.getByText(
      'Frameflow writes the plan from your idea and your material. Nothing is made until you approve it.'
    )
  ).toBeInTheDocument()
  expect(await screen.findByText('Written by Claude Code, found on this PC')).toBeInTheDocument()
  expect(button('Write the plan')).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Approve and write the storyboard' })).toBeNull()
  expect(screen.queryByRole('textbox', { name: 'Change the plan in words' })).toBeNull()
  await userEvent.type(idea(), '   ')
  expect(button('Write the plan')).toBeDisabled()
  await userEvent.type(idea(), 'A reel')
  expect(button('Write the plan')).toBeEnabled()
})

it('Write the plan makes the video, then writes its plan from the idea and the picked files, showing its steps', async () => {
  const picked: Record<string, string[]> = {
    footage: ['E:\\recordings\\talk.mp4'],
    assets: ['E:\\pictures\\desk.png', 'E:\\pictures\\walk.mp4'],
    music: ['E:\\music\\bed.mp3'],
    script: ['E:\\words\\script.txt'],
    looks: ['E:\\looks\\warm.cube']
  }
  const fake = api(unplanned, { chooseFiles: vi.fn(async (kind: string) => picked[kind]) })
  const onCreated = vi.fn()
  const { rerender } = render(<PromptStep folder={null} onCreated={onCreated} />)
  for (const name of ['Recording', 'Pictures or clips', 'Music', 'Script', 'Look'])
    await userEvent.click(button(name))
  expect(fake.chooseFiles.mock.calls.map(([kind]) => kind)).toEqual([
    'footage',
    'assets',
    'music',
    'script',
    'looks'
  ])
  const added = within(screen.getByRole('list', { name: 'Your material' }))
    .getAllByRole('listitem')
    .map((f) => f.textContent)
  expect(added).toEqual(['talk.mp4', 'desk.png', 'walk.mp4', 'bed.mp3', 'script.txt', 'warm.cube'])
  expect(screen.queryByText(/^Nothing added/)).toBeNull()

  await userEvent.click(idea())
  await userEvent.paste(IDEA)
  await userEvent.click(button('Write the plan'))
  expect(fake.newVideo).toHaveBeenCalledWith(IDEA)
  // The shape is not asked first: the plan proposes it.
  expect(fake.think).toHaveBeenCalledWith(
    FOLDER,
    {
      kind: 'start',
      prompt: IDEA,
      footage: picked.footage,
      assets: picked.assets,
      music: picked.music,
      looks: picked.looks,
      script: 'E:\\words\\script.txt'
    },
    expect.any(Function)
  )
  expect(onCreated).toHaveBeenCalledWith(FOLDER)

  rerender(<PromptStep key={FOLDER} folder={FOLDER} onCreated={onCreated} />) // the app opens it
  fake.say(
    { type: 'step', text: 'Preparing the material' },
    { type: 'step', text: 'Writing the plan with Claude Code' }
  )
  expect(steps()).toEqual(['01Preparing the material', '02Writing the plan with Claude Code…'])
  expect(screen.getByText('You can leave; you will be told when it is done.')).toBeInTheDocument()
  expect(screen.getByText('Writing the plan…')).toBeInTheDocument()
  expect(button('Approve and write the storyboard')).toBeDisabled()
  expect(idea()).toHaveValue(IDEA) // what it was asked from stays on the left
  expect(screen.getByRole('list', { name: 'Your material' })).toHaveTextContent('talk.mp4')
})

it('leaving while it thinks keeps it running; coming back shows its steps, then the plan', async () => {
  let described = unplanned
  const fake = api(() => described)
  const onThought = vi.fn()
  const first = render(<PromptStep folder={FOLDER} onThought={onThought} />)
  await userEvent.click(idea())
  await userEvent.paste(IDEA)
  await userEvent.click(button('Write the plan'))
  expect(fake.newVideo).not.toHaveBeenCalled() // the video's folder is made already
  fake.say({ type: 'step', text: 'Preparing the material' })
  first.unmount() // the creator opens another video

  fake.say({ type: 'step', text: 'Writing the plan with Claude Code' }) // the job carries on

  render(<PromptStep folder={FOLDER} onThought={onThought} />)
  expect(steps()).toEqual(['01Preparing the material', '02Writing the plan with Claude Code…'])
  expect(fake.think).toHaveBeenCalledTimes(1)
  expect(idea()).toHaveValue(IDEA)

  described = planned()
  await fake.end({ type: 'done', ok: true })
  expect(onThought).toHaveBeenCalledTimes(1) // said once, though the screen it began on is gone
  expect(onThought).toHaveBeenCalledWith(FOLDER, 'start', { type: 'done', ok: true }, false)
  expect(
    await screen.findByText('YouTube creators and builders who edit their own videos')
  ).toBeVisible()
  expect(screen.queryByRole('list', { name: 'Plan steps' })).toBeNull()
  expect(screen.getByText('Prepared · Plan written · 2 facts checked')).toBeInTheDocument()
})

it('a change in words runs plan-change; a failure after 3 rounds shows the engine’s line and keeps the draft', async () => {
  const fake = api(planned())
  const onThought = vi.fn()
  render(<PromptStep folder={FOLDER} onThought={onThought} />)
  const words = await screen.findByRole('textbox', { name: 'Change the plan in words' })
  expect(words).toHaveAttribute('placeholder', 'Change the plan in words…')
  await userEvent.type(words, 'make it 30 seconds, for founders{Enter}')
  const asked = { kind: 'plan-change', words: 'make it 30 seconds, for founders' }
  expect(fake.think).toHaveBeenCalledWith(FOLDER, asked, expect.any(Function))
  expect(words).toBeDisabled()

  const line =
    "Claude Code's answer still had problems after 3 fix rounds: target_seconds: must be over 0"
  await fake.end({ type: 'done', ok: false, message: line })
  const failed = screen.getByRole('alert')
  expect(failed).toHaveTextContent('The plan could not be written.')
  expect(failed).toHaveTextContent(line)
  expect(within(failed).getByText('The plan could not be written.')).toHaveClass('text-signal-ink')
  expect(screen.queryByRole('button', { name: 'Open Settings' })).toBeNull()
  // The draft is as it was.
  expect(screen.getByText('YouTube creators and builders who edit their own videos')).toBeVisible()
  expect(fake.editPlan).not.toHaveBeenCalled()
  expect(fake.describe).toHaveBeenCalledTimes(1)
  expect(onThought).toHaveBeenCalledWith(
    FOLDER,
    'plan-change',
    { type: 'done', ok: false, message: line },
    false
  )

  await userEvent.click(button('Try again'))
  expect(fake.think).toHaveBeenCalledTimes(2)
  expect(fake.think).toHaveBeenLastCalledWith(FOLDER, asked, expect.any(Function))
  expect(screen.queryByRole('alert')).toBeNull()
})

it('a problem with the thinker that Settings can fix shows as a note with Open Settings', async () => {
  const fake = api()
  const onSettings = vi.fn()
  render(<PromptStep folder={FOLDER} onSettings={onSettings} />)
  await userEvent.click(idea())
  await userEvent.paste(IDEA)
  await userEvent.click(button('Write the plan'))
  fake.say({ type: 'step', text: 'Preparing the material' })
  const line = 'No agent was found on this PC. Choose one, or add an API key, in Settings.'
  await fake.end({ type: 'done', ok: false, message: line })
  const note = screen.getByRole('alert')
  expect(note).toHaveTextContent(line)
  expect(note).not.toHaveTextContent('The plan could not be written.')
  expect(note.querySelector('.text-signal-ink')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  await userEvent.click(button('Open Settings'))
  expect(onSettings).toHaveBeenCalledTimes(1)
  expect(screen.getByText('The plan was not written')).toBeInTheDocument()
  expect(button('Write the plan again from this')).toBeEnabled()
})

it('a job replaced by a newer one shows nothing for it', async () => {
  const fake = api(planned())
  const onThought = vi.fn()
  render(<PromptStep folder={FOLDER} onThought={onThought} />)
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  fake.say({ type: 'step', text: 'Checking the facts' })
  await fake.end() // replaced: its call ends with no word of its own
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('list', { name: 'Plan steps' })).toBeNull()
  expect(onThought).not.toHaveBeenCalled()
  expect(button('Approve and write the storyboard')).toBeEnabled()
})

it('a job the creator stopped shows no failure, and its plan can be approved again', async () => {
  const fake = api(planned())
  const onThought = vi.fn()
  render(
    <>
      <PromptStep folder={FOLDER} onThought={onThought} />
      <Toasts />
    </>
  )
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  fake.say({ type: 'step', text: 'Checking the facts' })
  const done = { type: 'done' as const, ok: false, stopped: true as const }
  await fake.end(done)
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByText(/could not be written/)).toBeNull()
  expect(screen.queryByRole('list', { name: 'Plan steps' })).toBeNull()
  expect(button('Approve and write the storyboard')).toBeEnabled()
  expect(onThought).toHaveBeenCalledWith(FOLDER, 'approve', done, false) // the app reads it again
})

it('a storyboard changed outside the app is said in the app’s words, not as a failure', async () => {
  const fake = api(planned())
  const onThought = vi.fn()
  render(
    <>
      <PromptStep folder={FOLDER} onThought={onThought} />
      <Toasts />
    </>
  )
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  const done = { type: 'done' as const, ok: false, message: CHANGED, changed: true as const }
  await fake.end(done)
  expect(await screen.findByText(CHANGED)).toBeInTheDocument()
  expect(screen.queryByText('The plan could not be written.')).toBeNull()
  // The app is told too: its storyboard on another step is read again.
  expect(onThought).toHaveBeenCalledWith(FOLDER, 'approve', done, false)
  await waitFor(() => expect(fake.describe).toHaveBeenCalledTimes(2)) // read again
})

it('an approved plan with no storyboard yet, as a chat leaves it, can be approved', async () => {
  const fake = api(planned({}, false))
  const onThought = vi.fn()
  render(<PromptStep folder={FOLDER} onThought={onThought} />)
  const approve = await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  expect(approve).toBeEnabled()
  expect(screen.queryByText('Approved. Change the plan to write a new storyboard.')).toBeNull()
  await userEvent.click(approve)
  expect(fake.think).toHaveBeenCalledWith(FOLDER, { kind: 'approve' }, expect.any(Function))
  await fake.end({ type: 'done', ok: true, result: { storyboard: 'x' } })
  expect(onThought).toHaveBeenCalledWith(FOLDER, 'approve', expect.anything(), false) // nothing replaced
})

it('Approve is off while questions remain, and says how many are left', async () => {
  api(planned({ open_questions: QUESTIONS }))
  render(<PromptStep folder={FOLDER} />)
  const approve = await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  expect(approve).toBeDisabled()
  expect(screen.getByText('2 questions left')).toBeInTheDocument()
})

it('Approve runs approve, then the app is told the storyboard is written', async () => {
  const fake = api(planned())
  const onThought = vi.fn()
  render(<PromptStep folder={FOLDER} onThought={onThought} />)
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  expect(fake.think).toHaveBeenCalledWith(FOLDER, { kind: 'approve' }, expect.any(Function))
  fake.say(
    { type: 'step', text: 'Checking the facts' },
    { type: 'step', text: 'Writing the storyboard' }
  )
  expect(steps()).toEqual(['01Checking the facts', '02Writing the storyboard…'])
  expect(button('Approve and write the storyboard')).toBeDisabled()
  const done = {
    type: 'done' as const,
    ok: true,
    result: { storyboard: `${FOLDER}\\storyboard.json` }
  }
  await fake.end(done)
  expect(onThought).toHaveBeenCalledWith(FOLDER, 'approve', done, false)
})

it('back a step, the approved plan is a draft: Approve comes on once it changes, and replaces the storyboard', async () => {
  const approved: Described = { ...planned({}, false), no_storyboard: undefined }
  const fake = api(approved, {
    editPlan: vi.fn(async () => ({
      ...approved,
      plan: { ...approved.plan!, tone: 'warm' },
      plan_is_draft: true
    }))
  })
  const onThought = vi.fn()
  render(<PromptStep folder={FOLDER} onThought={onThought} />)
  const approve = await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  expect(approve).toBeDisabled() // nothing has changed since it was approved
  expect(screen.getByText('Approved. Change the plan to write a new storyboard.')).toBeVisible()
  await userEvent.click(button('Change Tone'))
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Tone' }),
    '{Control>}a{/Control}warm{Enter}'
  )
  expect(fake.editPlan).toHaveBeenCalledWith(FOLDER, { tone: 'warm' })
  await waitFor(() => expect(approve).toBeEnabled())
  expect(screen.queryByText('Approved. Change the plan to write a new storyboard.')).toBeNull()
  await userEvent.click(approve)
  await fake.end({ type: 'done', ok: true, result: { storyboard: 'x' } })
  expect(onThought).toHaveBeenCalledWith(FOLDER, 'approve', expect.anything(), true)
})

const MATERIAL = {
  footage: ['talk.mp4'],
  assets: ['desk.png'],
  music: [],
  looks: ['warm.cube'],
  script: true
}
const NONE = { footage: [], assets: [], music: [], looks: [], script: false }

it('after a restart, a video shows the idea and the material it was prepared from, as they are', async () => {
  api({ ...planned(), prompt: IDEA, material: MATERIAL })
  render(<PromptStep folder={FOLDER} />)
  await waitFor(() => expect(idea()).toHaveValue(IDEA))
  // Only files picked in this run can be sent, and preparing again would drop the rest.
  expect(idea()).toHaveAttribute('readonly')
  const added = within(screen.getByRole('list', { name: 'Your material' }))
    .getAllByRole('listitem')
    .map((f) => f.textContent)
  expect(added).toEqual(['talk.mp4', 'desk.png', 'Script', 'warm.cube'])
  expect(screen.queryByRole('button', { name: 'Recording' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Write the plan again from this' })).toBeNull()
  expect(screen.getByRole('textbox', { name: 'Change the plan in words' })).toBeEnabled()
})

it('after a restart, a video with no material shows its idea, and material can still be added', async () => {
  api({ ...planned(), prompt: IDEA, material: NONE })
  render(<PromptStep folder={FOLDER} />)
  await waitFor(() => expect(idea()).toHaveValue(IDEA))
  expect(idea()).not.toHaveAttribute('readonly')
  expect(button('Recording')).toBeInTheDocument()
  expect(button('Write the plan again from this')).toBeEnabled()
  expect(
    screen.getByText('Nothing added. Frameflow makes it from titles, graphics and a voiceover.')
  ).toBeInTheDocument()
})

it('the facts checked are the ones whose page was opened', async () => {
  api({ ...planned(), plan_unopened: [2] })
  render(<PromptStep folder={FOLDER} />)
  expect(await screen.findByText('Prepared · Plan written · 1 fact checked')).toBeInTheDocument()
})

it('the main action, when off, is drawn as the sketch draws it', async () => {
  api(planned({ open_questions: QUESTIONS }))
  render(<PromptStep folder={null} />)
  const off = ['disabled:bg-off', 'disabled:text-quiet', 'disabled:opacity-100']
  expect(button('Write the plan')).toHaveClass(...off)
  cleanup()
  render(<PromptStep folder={FOLDER} />)
  expect(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  ).toHaveClass(...off)
})

it('when a job ends, the focus goes to the plan; it waits there while the job runs', async () => {
  const fake = api(() => planned())
  render(<PromptStep folder={FOLDER} />)
  const words = await screen.findByRole('textbox', { name: 'Change the plan in words' })
  await userEvent.type(words, 'make it warmer{Enter}')
  const heading = screen.getByRole('heading', { name: /The plan/ })
  expect(heading).toHaveFocus() // not the page: the field it was asked from is off
  await fake.end({ type: 'done', ok: true })
  expect(heading).toHaveFocus()
})

it('while it thinks, Stop stops the job, and the focus goes back to the plan', async () => {
  const fake = api(planned(), { stop: vi.fn(async () => true) })
  render(<PromptStep folder={FOLDER} />)
  expect(screen.queryByRole('button', { name: /^Stop/ })).toBeNull()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  await userEvent.click(button('Stop writing the storyboard'))
  expect(fake.stop).toHaveBeenCalledWith('think', FOLDER)
  await fake.end({ type: 'done', ok: false, stopped: true })
  expect(screen.queryByRole('button', { name: /^Stop/ })).toBeNull()
  expect(screen.getByRole('heading', { name: /The plan/ })).toHaveFocus()
})

it('Stop names the job it stops: the plan, or a change made on another step', async () => {
  const fake = api(planned(), { stop: vi.fn(async () => true) })
  render(<PromptStep folder={FOLDER} />)
  const words = await screen.findByRole('textbox', { name: 'Change the plan in words' })
  await userEvent.type(words, 'make it warmer{Enter}')
  expect(button('Stop writing the plan')).toBeInTheDocument()
  await fake.end({ type: 'done', ok: true })
  act(() => void think(FOLDER, { kind: 'change', words: 'shorter', version: 'v1' }))
  expect(button('Stop the change')).toBeInTheDocument()
})

it('when a job fails, the focus goes to Try again, or to Open Settings', async () => {
  const fake = api(planned())
  render(<PromptStep folder={FOLDER} />)
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  await fake.end({ type: 'done', ok: false, message: 'The storyboard still had problems' })
  expect(button('Try again')).toHaveFocus()
  await userEvent.click(button('Try again'))
  await fake.end({
    type: 'done',
    ok: false,
    message: 'Claude Code is not signed in. Sign in to it, or choose another way in Settings.'
  })
  expect(button('Open Settings')).toHaveFocus()
})

it('a failure goes once the plan is changed by hand', async () => {
  const fake = api(planned())
  render(<PromptStep folder={FOLDER} />)
  await userEvent.type(
    await screen.findByRole('textbox', { name: 'Change the plan in words' }),
    'make it warmer{Enter}'
  )
  await fake.end({ type: 'done', ok: false, message: 'The answer still had problems' })
  expect(screen.getByRole('alert')).toBeInTheDocument()
  await userEvent.click(button('Change Tone'))
  await userEvent.keyboard('warm{Enter}')
  await waitFor(() => expect(fake.editPlan).toHaveBeenCalledWith(FOLDER, { tone: 'warm' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
})

it('a failure goes once a later job ends well', async () => {
  const fake = api(planned())
  render(<PromptStep folder={FOLDER} />)
  await userEvent.click(
    await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  )
  await fake.end({ type: 'done', ok: false, message: 'The storyboard still had problems' })
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Change the plan in words' }),
    'make it warmer{Enter}'
  )
  await fake.end({ type: 'done', ok: true })
  expect(screen.queryByRole('alert')).toBeNull()
})

const SENTENCE = 'This key cannot look things up, so give the page and the words on it, or drop it.'

it('a needed fact from Claude Code asks for its page and words with no word about a key', async () => {
  api(planned({ open_questions: QUESTIONS }), {}, claudeCode)
  render(<PromptStep folder={FOLDER} />)
  const region = await screen.findByRole('region', { name: 'Open questions' })
  expect(within(region).getByRole('textbox', { name: 'The page’s address' })).toBeInTheDocument()
  expect(within(region).getByRole('button', { name: 'Drop' })).toBeInTheDocument()
  expect(region).not.toHaveTextContent(SENTENCE)
})

it('a needed fact from a key that cannot look things up says why it asks', async () => {
  api(planned({ open_questions: QUESTIONS }), {}, openAiKey)
  render(<PromptStep folder={FOLDER} />)
  const region = await screen.findByRole('region', { name: 'Open questions' })
  await waitFor(() => expect(region).toHaveTextContent(SENTENCE))
})

it('a video from before this run with no plan has its plan written from its idea and material as they are', async () => {
  const fake = api({ ...unplanned, prompt: IDEA, material: MATERIAL })
  render(<PromptStep folder={FOLDER} />)
  await waitFor(() => expect(idea()).toHaveValue(IDEA))
  const write = button('Write the plan')
  expect(write).toBeEnabled()
  await userEvent.click(write)
  // No files: the engine keeps the material the video was prepared with.
  expect(fake.think).toHaveBeenCalledWith(
    FOLDER,
    { kind: 'start', prompt: IDEA, footage: [], assets: [], music: [], looks: [] },
    expect.any(Function)
  )
  expect(idea()).toHaveAttribute('readonly')
  expect(screen.queryByRole('button', { name: 'Recording' })).toBeNull()
  expect(screen.getByRole('list', { name: 'Your material' })).toHaveTextContent('talk.mp4')
})

it('nothing can be edited before the video is read', () => {
  api()
  window.frameflow.describe = () => new Promise(() => {}) // not answered yet
  render(<PromptStep folder={FOLDER} />)
  expect(idea()).toHaveAttribute('readonly')
  expect(screen.queryByRole('button', { name: 'Recording' })).toBeNull()
})

it('a video that could not be read says so until it is read well', async () => {
  const fake = api()
  fake.describe
    .mockRejectedValueOnce(new Error('inputs.json is not valid JSON: line 4'))
    .mockResolvedValue(planned())
  render(<PromptStep folder={FOLDER} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('inputs.json is not valid JSON')
  void think(FOLDER, { kind: 'plan-change', words: 'make it warmer' }) // a job from elsewhere
  await fake.end({ type: 'done', ok: true })
  expect(await screen.findByText(pitch.audience)).toBeVisible()
  expect(screen.queryByRole('alert')).toBeNull()
})

it('while a change in words runs, the footer says its step, not that the plan is being written', async () => {
  const fake = api(planned())
  render(<PromptStep folder={FOLDER} />)
  await screen.findByRole('button', { name: 'Approve and write the storyboard' })
  // Sent from the storyboard's footer.
  act(() => void think(FOLDER, { kind: 'change', words: 'Put scene 9 first', version: 'v1' }))
  fake.say({ type: 'step', text: 'Making the change' })
  expect(document.querySelector('footer [aria-live]')).toHaveTextContent(/^Making the change…$/)
  expect(screen.queryByText('Writing the plan…')).toBeNull()
})
