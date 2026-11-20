import userEvent from '@testing-library/user-event'
import { act, render, screen, waitFor } from '@testing-library/react'
import type { BuildEvent, Section, ThinkRequest, Video } from '@shared/types'
import App from './App'
import { springEasing } from './lib/motion'
import { claudeCode, FOLDER, IDEA, pitch, planned, unplanned } from './prompt/fixture'
import { tierList } from './storyboard/fixture'

const step = (name: string): HTMLElement => screen.getByRole('button', { name })
const idea = (): HTMLElement => screen.getByRole('textbox', { name: 'What you want' })

it('with no videos yet, the app opens on a new video’s prompt', async () => {
  window.frameflow = { videos: async () => [], settings: async () => claudeCode } as never
  render(<App />)
  expect(await screen.findByRole('textbox', { name: 'What you want' })).toHaveValue('')
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('New video')
  expect(step('Prompt')).toHaveAttribute('aria-current', 'step')
  expect(step('Storyboard')).toBeDisabled()
  expect(step('Video')).toBeDisabled()
})

it('when the engine does not start, it says what it said, and Try again asks again', async () => {
  const videos = vi
    .fn()
    .mockRejectedValueOnce(new Error('Could not start `python`: spawn python ENOENT'))
    .mockResolvedValue([])
  window.frameflow = { videos, settings: async () => claudeCode } as never
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not start `python`: spawn python ENOENT'
  )
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('textbox', { name: 'What you want' })).toBeInTheDocument()
  expect(videos).toHaveBeenCalledTimes(2)
})

it('the storyboard’s headings step down one level at a time, with chapters or without', async () => {
  const reel: Video = {
    folder: 'E:\\my projects\\frameflow\\output\\reference-swap',
    title: 'Editing tier list',
    has_storyboard: true,
    built: true,
    cover: 'scene-1'
  }
  const levels = async (sections: Section[]): Promise<number[]> => {
    window.frameflow = {
      videos: async () => [reel],
      describe: async () => ({ ...tierList, sections }),
      thumbnail: async () => null,
      looks: async () => []
    } as never
    const { unmount } = render(<App />)
    await screen.findAllByRole('option')
    const found = screen.getAllByRole('heading').map((h) => Number(h.tagName.slice(1)))
    unmount()
    return found
  }
  expect(await levels([])).toEqual([1, 2, 3])
  expect(await levels(tierList.sections!)).toEqual([1, 2, 2, 2, 2, 3])
})

describe('the steps', () => {
  const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'
  const reel: Video = {
    folder: FOLDER,
    title: 'Editing tier list',
    has_storyboard: true,
    built: true,
    cover: 'scene-1'
  }
  const step = (name: string): HTMLElement => screen.getByRole('button', { name })

  beforeEach(() => {
    window.frameflow = {
      videos: async () => [reel],
      describe: async () => ({ ...tierList, preview: 'ff-media://preview/?p=x' }),
      thumbnail: async () => null,
      looks: async () => []
    } as never
  })

  it('the Video step opens the video screen, and Storyboard comes back with the same scene selected', async () => {
    render(<App />)
    await userEvent.click(await screen.findByRole('option', { name: /^Scene 4\b/ }))
    expect(step('Storyboard')).toHaveAttribute('aria-current', 'step')
    expect(step('Prompt')).toBeEnabled()
    await userEvent.click(step('Video'))
    expect(step('Video')).toHaveAttribute('aria-current', 'step')
    expect(step('Storyboard')).not.toHaveAttribute('aria-current')
    expect(await screen.findByRole('region', { name: 'The video' })).toBeInTheDocument()
    expect(screen.queryByRole('listbox', { name: 'Scenes' })).toBeNull()
    await userEvent.keyboard(' ') // the keys work on the video screen at once
    expect(document.querySelector('video')!.paused).toBe(false)
    await userEvent.click(step('Storyboard'))
    const four = await screen.findByRole('option', { name: /^Scene 4\b/ })
    expect(four).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(four).toHaveFocus())
  })

  it('Video slides in from the right and Storyboard from the left, 200 ms; with less motion they fade, 150 ms', async () => {
    const animate = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'animate', { value: animate, configurable: true })
    try {
      render(<App />)
      await screen.findAllByRole('option')
      expect(animate).not.toHaveBeenCalled()
      await userEvent.click(step('Video'))
      expect(animate).toHaveBeenLastCalledWith(
        [
          { opacity: 0, transform: 'translateX(48px)' },
          { opacity: 1, transform: 'none' }
        ],
        { duration: 200, easing: springEasing() }
      )
      await userEvent.click(step('Storyboard'))
      expect(animate).toHaveBeenLastCalledWith(
        [
          { opacity: 0, transform: 'translateX(-48px)' },
          { opacity: 1, transform: 'none' }
        ],
        { duration: 200, easing: springEasing() }
      )
      window.matchMedia = vi.fn(() => ({ matches: true })) as never
      await userEvent.click(step('Video'))
      expect(animate).toHaveBeenLastCalledWith([{ opacity: 0 }, { opacity: 1 }], {
        duration: 150,
        easing: springEasing()
      })
      expect(animate).toHaveBeenCalledTimes(3)
    } finally {
      Reflect.deleteProperty(HTMLElement.prototype, 'animate')
      Reflect.deleteProperty(window, 'matchMedia')
    }
  })
})

describe('settings', () => {
  const reel: Video = {
    folder: 'E:\\my projects\\frameflow\\output\\reference-swap',
    title: 'Editing tier list',
    has_storyboard: true,
    built: true,
    cover: 'scene-1'
  }
  const settings = async (): Promise<object> => ({ thinking: 'auto', hasKey: false, agents: [] })
  const gear = (): HTMLElement => screen.getByRole('button', { name: 'Settings' })
  const page = (): Promise<HTMLElement> =>
    screen.findByRole('heading', { name: 'How Frameflow thinks' })

  it('the gear at the foot of the rail opens Settings with no video, and closes it again', async () => {
    window.frameflow = { videos: async () => [], settings } as never
    render(<App />)
    await screen.findByRole('textbox', { name: 'What you want' })
    expect(gear()).not.toHaveAttribute('aria-current')
    await userEvent.click(gear())
    expect(await page()).toBeInTheDocument()
    expect(gear()).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('textbox', { name: 'What you want' })).toBeNull()
    await userEvent.click(gear())
    expect(await screen.findByRole('textbox', { name: 'What you want' })).toBeInTheDocument()
  })

  it('Ctrl K offers Settings, and a video in the rail leaves it', async () => {
    window.frameflow = {
      videos: async () => [reel],
      describe: async () => tierList,
      thumbnail: async () => null,
      looks: async () => [],
      settings
    } as never
    render(<App />)
    await screen.findAllByRole('option')
    await userEvent.keyboard('{Control>}k{/Control}')
    await userEvent.click(await screen.findByRole('option', { name: 'Settings' }))
    expect(await page()).toBeInTheDocument()
    expect(screen.queryByRole('listbox', { name: 'Scenes' })).toBeNull()
    const video = screen.getByRole('button', { name: 'Editing tier list' })
    expect(video).not.toHaveAttribute('aria-current')
    await userEvent.click(video)
    expect(await screen.findByRole('listbox', { name: 'Scenes' })).toBeInTheDocument()
    expect(video).toHaveAttribute('aria-current', 'page')
    expect(gear()).not.toHaveAttribute('aria-current')
  })
})

describe('the prompt step', () => {
  const reel: Video = {
    folder: 'E:\\my projects\\frameflow\\output\\reference-swap',
    title: 'Editing tier list',
    has_storyboard: true,
    built: true,
    cover: 'scene-1'
  }
  const planless: Video = {
    folder: FOLDER,
    title: 'Frameflow pitch',
    has_storyboard: false,
    built: false,
    cover: null
  }
  const button = (name: string): HTMLElement => screen.getByRole('button', { name })

  /** The thinking jobs: `say` sends what the engine prints for the latest, `end` ends it. */
  function fakeThink(): {
    think: ReturnType<typeof vi.fn>
    say: (...events: BuildEvent[]) => void
    end: (done: Extract<BuildEvent, { type: 'done' }>) => Promise<void>
  } {
    let onEvent: (e: BuildEvent) => void = () => {}
    let finish: () => void = () => {}
    const think = vi.fn((_f: string, _r: ThinkRequest, listener: (e: BuildEvent) => void) => {
      onEvent = listener
      return new Promise<void>((resolve) => (finish = resolve))
    })
    return {
      think,
      say: (...events) => act(() => events.forEach((e) => onEvent(e))),
      end: async (done) => {
        await act(async () => {
          onEvent(done)
          finish()
        })
      }
    }
  }
  const common = {
    thumbnail: async () => null,
    looks: async () => [],
    settings: async () => claudeCode
  }

  it('+ opens a new video; Write the plan makes it, and it opens on its prompt with its steps', async () => {
    const fake = fakeThink()
    const newVideo = vi.fn(async () => FOLDER)
    window.frameflow = {
      ...common,
      videos: async () => [reel], // the engine lists the new video once its material is prepared
      describe: async (f: string) => (f === FOLDER ? unplanned : tierList),
      newVideo,
      chooseFiles: async () => [],
      think: fake.think
    } as never
    render(<App />)
    await screen.findAllByRole('option')
    await userEvent.click(button('New video'))
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('New video')
    expect(button('New video')).toHaveAttribute('aria-current', 'page')
    expect(idea()).toHaveValue('')
    expect(step('Storyboard')).toBeDisabled()
    await userEvent.click(idea())
    await userEvent.paste(IDEA)
    await userEvent.click(button('Write the plan'))
    expect(newVideo).toHaveBeenCalledWith(IDEA)
    // In the rail at once, by its folder's name as the engine names it, and open on its prompt.
    const made = await screen.findByRole('button', { name: 'frameflow-pitch' })
    expect(made).toHaveAttribute('aria-current', 'page')
    expect(button('New video')).not.toHaveAttribute('aria-current')
    expect(step('Prompt')).toHaveAttribute('aria-current', 'step')
    expect(step('Storyboard')).toBeDisabled()
    fake.say({ type: 'step', text: 'Preparing the material' })
    expect(screen.getByRole('list', { name: 'Plan steps' })).toHaveTextContent(
      'Preparing the material'
    )
    expect(idea()).toHaveValue(IDEA)
  })

  it('a video with no storyboard opens on Prompt; Approve lands on the storyboard step with the new storyboard', async () => {
    const fake = fakeThink()
    let written = false
    window.frameflow = {
      ...common,
      videos: async () => [{ ...planless, has_storyboard: written }],
      describe: async () => (written ? { ...tierList, plan: pitch } : planned()),
      think: fake.think
    } as never
    render(<App />)
    const approve = await screen.findByRole('button', { name: 'Approve and write the storyboard' })
    expect(step('Prompt')).toHaveAttribute('aria-current', 'step')
    expect(step('Storyboard')).toBeDisabled()
    expect(step('Video')).toBeDisabled()
    await userEvent.click(approve)
    expect(fake.think).toHaveBeenCalledWith(FOLDER, { kind: 'approve' }, expect.any(Function))
    written = true
    await fake.end({ type: 'done', ok: true, result: { storyboard: `${FOLDER}\\storyboard.json` } })
    expect(await screen.findByRole('listbox', { name: 'Scenes' })).toBeInTheDocument()
    expect(step('Storyboard')).toHaveAttribute('aria-current', 'step')
    expect(step('Video')).toBeEnabled()
    // Watched as it was written, a first storyboard needs no toast: there is nothing to undo.
    expect(screen.queryByText('The storyboard is written')).toBeNull()
  })

  it('back a step, the approved plan is a draft; approving it again writes a new storyboard, and the toast’s Undo brings both back', async () => {
    const fake = fakeThink()
    const undo = vi.fn(async () => ({ described: tierList, notes: [] }))
    const describe = vi.fn(async () => ({
      ...tierList,
      version: 'v2',
      plan: pitch,
      plan_is_draft: false
    }))
    window.frameflow = {
      ...common,
      videos: async () => [reel],
      describe,
      editPlan: async () => ({
        ...tierList,
        plan: { ...pitch, tone: 'warm' },
        plan_is_draft: true
      }),
      think: fake.think,
      undo
    } as never
    render(<App />)
    await screen.findAllByRole('option')
    await userEvent.click(step('Prompt'))
    expect(await screen.findByText(pitch.audience)).toBeVisible()
    const approve = button('Approve and write the storyboard')
    expect(approve).toBeDisabled()
    await userEvent.click(button('Change Tone'))
    await userEvent.keyboard('warm{Enter}')
    await waitFor(() => expect(approve).toBeEnabled())
    await userEvent.click(approve)
    await fake.end({ type: 'done', ok: true, result: { storyboard: 'storyboard.json' } })
    expect(await screen.findByRole('listbox', { name: 'Scenes' })).toBeInTheDocument()
    expect(await screen.findByText('The storyboard is written')).toBeInTheDocument()
    const reads = describe.mock.calls.length
    await userEvent.click(button('Undo'))
    await waitFor(() => expect(undo).toHaveBeenCalledWith(reel.folder, 'v2'))
    await waitFor(() => expect(describe.mock.calls.length).toBeGreaterThan(reads + 1)) // read again
  })

  it.each([
    ['ends', { type: 'done' as const, ok: true, result: { storyboard: 'storyboard.json' } }],
    [
      'is refused as changed',
      {
        type: 'done' as const,
        ok: false,
        changed: true as const,
        message:
          'The storyboard changed outside the app, so it was reloaded. Your last change was not made.'
      }
    ]
  ])(
    'an Approve that %s while its storyboard is shown has it read again, so a hand edit is of the new one',
    async (_, done) => {
      const fake = fakeThink()
      let version = 'v2'
      const edit = vi.fn(async () => ({ described: tierList, notes: [] }))
      window.frameflow = {
        ...common,
        videos: async () => [reel],
        describe: async () => ({ ...tierList, version, plan: pitch, plan_is_draft: true }),
        think: fake.think,
        edit
      } as never
      render(<App />)
      await screen.findAllByRole('option')
      await userEvent.click(step('Prompt'))
      await userEvent.click(
        await screen.findByRole('button', { name: 'Approve and write the storyboard' })
      )
      await userEvent.click(step('Storyboard')) // as the screen invites: you can leave
      await screen.findAllByRole('option')
      version = 'v3' // what the Approve wrote, or what changed under it
      await fake.end(done)
      await userEvent.click(await screen.findByRole('option', { name: /^Scene 4\b/ }))
      await userEvent.keyboard('{Delete}')
      await waitFor(() =>
        expect(edit).toHaveBeenCalledWith(reel.folder, { op: 'delete', number: 4 }, 'v3')
      )
      expect(screen.queryByText('The storyboard could not be written')).toBeNull()
    }
  )

  it('leaving while it thinks keeps it running, and a toast says when it is done', async () => {
    const fake = fakeThink()
    window.frameflow = {
      ...common,
      videos: async () => [planless, reel],
      describe: async (f: string) => (f === FOLDER ? planned() : tierList),
      think: fake.think
    } as never
    render(<App />)
    await userEvent.type(
      await screen.findByRole('textbox', { name: 'Change the plan in words' }),
      'make it 30 seconds{Enter}'
    )
    await userEvent.click(button('Editing tier list'))
    await screen.findAllByRole('option')
    await fake.end({ type: 'done', ok: true })
    expect(await screen.findByText('The plan is written')).toBeInTheDocument()
    expect(screen.getByText('Frameflow pitch')).toBeInTheDocument()
  })
})
