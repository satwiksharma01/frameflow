import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Described, FrameflowApi } from '@shared/types'
import { observers } from '../test-setup'
import { tierList, twoCuts, unbuilt } from './fixture'
import { Storyboard } from './Storyboard'
import { Toasts } from '../shell/Toasts'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'

function engine(
  described: Described | Error,
  thumbnail: FrameflowApi['thumbnail'] = async () => 'ff-media://thumb/?p=x.jpg'
): { describe: ReturnType<typeof vi.fn> } {
  const describe = vi.fn(async () => {
    if (described instanceof Error) throw described
    return described
  })
  window.frameflow = { describe, thumbnail } as never
  return { describe }
}

const scene = (n: number): HTMLElement =>
  screen.getByRole('button', { name: new RegExp(`^Scene ${n}:`) })

it('shows nine scenes in three chapters, with the count and the running time', async () => {
  engine(tierList)
  render(<Storyboard folder={FOLDER} />)
  expect(await screen.findAllByRole('button', { name: /^Scene \d+:/ })).toHaveLength(9)
  const list = screen.getByRole('group', { name: 'Scenes' }) // the details panel has its own heading
  expect(
    within(list)
      .getAllByRole('heading', { level: 2 })
      .map((h) => h.textContent)
  ).toEqual([
    expect.stringContaining('Problem'),
    expect.stringContaining('Turn'),
    expect.stringContaining('Answer')
  ])
  const figures = screen.getByRole('group', { name: 'Length' })
  expect(figures).toHaveTextContent('9 scenes')
  expect(figures).toHaveTextContent('20.1/20 seconds')
})

it("the selected scene's rule is the only red one, and the details panel shows its words", async () => {
  engine(tierList)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(scene(1)).toHaveAttribute('aria-current', 'true')
  await userEvent.click(scene(6))
  expect(
    screen
      .getAllByRole('button', { name: /^Scene \d+:/ })
      .filter((o) => o.getAttribute('aria-current') === 'true')
  ).toEqual([scene(6)])
  expect(document.querySelectorAll('[data-rule="selected"]')).toHaveLength(1)
  expect(scene(6).querySelector('[data-rule="selected"]')).not.toBeNull()
  const details = screen.getByRole('complementary', { name: 'Scene 6' })
  expect(details).toHaveTextContent('the goal is to remove all the repetitive editing work')
  expect(details).toHaveTextContent('Your recording 5:12–5:15')
})

it('Right moves the selection to the next scene, End to the last, Home to the first', async () => {
  engine(tierList)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  scene(1).focus()
  await userEvent.keyboard('{ArrowRight}')
  expect(scene(2)).toHaveAttribute('aria-current', 'true')
  expect(scene(2)).toHaveFocus()
  await userEvent.keyboard('{End}')
  expect(scene(9)).toHaveAttribute('aria-current', 'true')
  await userEvent.keyboard('{ArrowRight}')
  expect(scene(9)).toHaveAttribute('aria-current', 'true')
  await userEvent.keyboard('{Home}')
  expect(scene(1)).toHaveAttribute('aria-current', 'true')
})

it('scene 6 says it may clip a word; no other scene shows a check', async () => {
  engine(tierList)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(within(scene(6)).getByText('May clip “work”')).toBeInTheDocument()
  expect(
    screen
      .getAllByRole('button', { name: /^Scene \d+:/ })
      .filter((o) => /May clip/.test(o.textContent ?? ''))
  ).toHaveLength(1)
})

it('a screen reader hears each scene’s length, and what to check where there is something', async () => {
  engine(tierList)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(scene(6)).toHaveAccessibleDescription(
    expect.stringMatching(/^2\.7 seconds\. Check: May clip “work”\. To move a scene/)
  )
  expect(scene(1)).toHaveAccessibleDescription(expect.stringMatching(/^\d+\.\d seconds\./))
  expect(scene(1)).not.toHaveAccessibleDescription(expect.stringContaining('Check'))
})

it('a scene holding two suspect cuts shows both on its card and in the details panel', async () => {
  engine(twoCuts)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(6))
  const details = screen.getByRole('complementary', { name: 'Scene 6' })
  for (const check of ['May clip “all”', 'May clip “work”']) {
    expect(within(scene(6)).getByText(check)).toBeInTheDocument()
    expect(within(details).getByText(check)).toBeInTheDocument()
  }
})

it('a video not built yet says "about" and shows no start times', async () => {
  engine(unbuilt)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(screen.getByRole('group', { name: 'Length' })).toHaveTextContent('about 20.1/20 seconds')
  expect(scene(1)).not.toHaveTextContent('0:00')
  expect(scene(1)).toHaveTextContent('1.5 s')
})

it('a storyboard without chapters has no chapter headings and no index', async () => {
  engine({ ...tierList, sections: [] })
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  const list = screen.getByRole('group', { name: 'Scenes' })
  expect(within(list).queryByRole('heading', { level: 2 })).toBeNull()
  expect(screen.queryByRole('navigation', { name: 'Chapters' })).toBeNull()
})

it('a video without a storyboard shows nothing here: the prompt step writes one', async () => {
  const { describe } = engine({ title: 'Morning routine', scenes: [], no_storyboard: true })
  const { container } = render(<Storyboard folder={FOLDER} />)
  await waitFor(() => expect(describe).toHaveBeenCalled())
  await waitFor(() => expect(screen.queryByLabelText('Loading the storyboard')).toBeNull())
  expect(screen.queryByText('No storyboard yet')).toBeNull()
  expect(screen.queryByText(/--storyboard/)).toBeNull()
  expect(container).toBeEmptyDOMElement()
})

it("an engine failure shows the engine's words, and Try again asks again", async () => {
  const { describe } = engine(new Error('storyboard.json is not valid JSON: line 3'))
  render(<Storyboard folder={FOLDER} />)
  expect(await screen.findByText('storyboard.json is not valid JSON: line 3')).toBeInTheDocument()
  expect(screen.getByText(/python -m project\.app_api describe/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(describe).toHaveBeenCalledTimes(2))
})

it('a scene with no picture of its own shows its number on a plain frame', async () => {
  engine(tierList, async () => null)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await waitFor(() => expect(scene(3).querySelector('[data-frame="plain"]')).toHaveTextContent('3'))
  expect(scene(3).querySelector('img')).toBeNull()
})

it('a thumbnail is not asked for until its scene is near the viewport', async () => {
  observers.auto = false
  const thumbnail = vi.fn(async () => 'ff-media://thumb/?p=x.jpg')
  engine(tierList, thumbnail)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(thumbnail).not.toHaveBeenCalled()
  observers.show(scene(4).querySelector('[data-frame]')!)
  await waitFor(() => expect(thumbnail).toHaveBeenCalledWith(FOLDER, 'scene-4'))
  expect(thumbnail).toHaveBeenCalledTimes(1)
  await waitFor(() =>
    expect(scene(4).querySelector('img')).toHaveAttribute('src', 'ff-media://thumb/?p=x.jpg')
  )
})

it('a title scene shows its words in its frame, and asks for no picture', async () => {
  const thumbnail = vi.fn(async () => null)
  const scenes = tierList.scenes.map((s) =>
    s.number === 2 ? { ...s, kind: 'title' as const, text: 'Where does your week go?' } : s
  )
  engine({ ...tierList, scenes }, thumbnail)
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(scene(2).querySelector('[data-frame="title"]')).toHaveTextContent(
    'Where does your week go?'
  )
  await waitFor(() => expect(thumbnail).toHaveBeenCalledWith(FOLDER, 'scene-1'))
  expect(thumbnail).not.toHaveBeenCalledWith(FOLDER, 'scene-2')
})

it('a scene whose length is not known yet draws no rule', async () => {
  const scenes = unbuilt.scenes.map((s) => (s.number === 3 ? { ...s, seconds: null } : s))
  engine({ ...unbuilt, scenes })
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  expect(scene(3).querySelector('[data-rule]')).toBeNull()
  expect(scene(4).querySelector('[data-rule]')).not.toBeNull()
})

describe('playing', () => {
  const PREVIEW = 'ff-media://preview/?p=x'
  const video = (): HTMLVideoElement | null => document.querySelector('video')
  function at(seconds: number): void {
    video()!.currentTime = seconds
    fireEvent.timeUpdate(video()!)
  }

  it('Space plays the selected scene from its start and stops at its end', async () => {
    engine({ ...tierList, preview: PREVIEW })
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    const picture = screen
      .getByRole('complementary', { name: 'Scene 6' })
      .querySelector<HTMLElement>('[data-frame]')!
    await userEvent.keyboard(' ')
    expect(video()).toHaveAttribute('src', PREVIEW)
    expect(video()!.currentTime).toBe(8.7)
    expect(picture).toHaveClass('hidden') // the video is in its place
    at(11.4)
    expect(video()).not.toBeNull()
    at(11.433)
    expect(video()).toBeNull()
    expect(picture).not.toHaveClass('hidden')
    await waitFor(() =>
      expect(picture.querySelector('img')).toHaveAttribute('src', 'ff-media://thumb/?p=x.jpg')
    )
  })

  it('Space again, or Esc, stops it, and the arrows still move the selection', async () => {
    engine({ ...tierList, preview: PREVIEW })
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    await userEvent.keyboard(' ')
    expect(video()).not.toBeNull()
    await userEvent.keyboard(' ')
    expect(video()).toBeNull()
    await userEvent.keyboard(' ')
    expect(video()).not.toBeNull()
    await userEvent.keyboard('{Escape}')
    expect(video()).toBeNull()
    expect(scene(6)).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}')
    expect(scene(7)).toHaveAttribute('aria-current', 'true')
  })

  it('Space on a video changed since its build says to build it, and plays nothing', async () => {
    engine({ ...tierList, preview: null })
    render(
      <>
        <Storyboard folder={FOLDER} />
        <Toasts />
      </>
    )
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    await userEvent.keyboard(' ')
    expect(await screen.findByText('Build the video to play its scenes.')).toBeInTheDocument()
    expect(video()).toBeNull()
  })
})

describe('the keyboard', () => {
  function editing(): ReturnType<typeof vi.fn> {
    const edit = vi.fn(async (_f: string, _op: unknown, version: string) => ({
      described: { ...tierList, version: `${version}+` },
      notes: []
    }))
    window.frameflow = {
      describe: async () => tierList,
      edit,
      thumbnail: async () => null
    } as never
    return edit
  }

  it('Alt+Right moves the selected scene later and keeps it selected', async () => {
    const edit = editing()
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(2))
    await userEvent.keyboard('{Alt>}{ArrowRight}{/Alt}')
    expect(edit).toHaveBeenCalledWith(FOLDER, { op: 'move', from: 2, to: 3 }, 'v1')
    await waitFor(() => expect(scene(3)).toHaveAttribute('aria-current', 'true'))
  })

  it('Delete removes the selected scene and offers Undo', async () => {
    const edit = editing()
    render(
      <>
        <Storyboard folder={FOLDER} />
        <Toasts />
      </>
    )
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(4))
    await userEvent.keyboard('{Delete}')
    expect(edit).toHaveBeenCalledWith(FOLDER, { op: 'delete', number: 4 }, 'v1')
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(await screen.findByText('Scene 4 deleted')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument()
  })

  it('deleting the only scene says why it can not be done', async () => {
    const refused = 'A video needs at least one scene.'
    window.frameflow = {
      describe: async () => tierList,
      edit: vi.fn(async () => ({ refused, changed: false })),
      thumbnail: async () => null
    } as never
    render(
      <>
        <Storyboard folder={FOLDER} />
        <Toasts />
      </>
    )
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(1))
    await userEvent.keyboard('{Delete}')
    expect(await screen.findByText(refused)).toBeInTheDocument()
  })

  it('keys pressed on a chapter menu or an add tile stay theirs', async () => {
    const edit = editing()
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    screen.getAllByRole('button', { name: 'Add a scene' })[0].focus()
    await userEvent.keyboard('{Delete}')
    expect(edit).not.toHaveBeenCalled()
  })

  it('Enter opens the selected scene’s words for typing', async () => {
    editing()
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'What is said' })).toHaveFocus())
  })

  it('after the words are sent with Enter, or left with Esc, the arrows move the selection again', async () => {
    const edit = editing()
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    await userEvent.keyboard('{Enter}')
    const field = await screen.findByRole('textbox', { name: 'What is said' })
    await waitFor(() => expect(field).toHaveFocus())
    await userEvent.keyboard(' again{Enter}')
    await waitFor(() => expect(scene(6)).toHaveFocus())
    expect(edit).toHaveBeenCalledTimes(1)
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'What is said' })).toHaveFocus())
    await userEvent.keyboard(' and again{Escape}')
    await waitFor(() => expect(scene(6)).toHaveFocus())
    expect(edit).toHaveBeenCalledTimes(1) // Esc sent nothing
    await userEvent.keyboard('{ArrowRight}')
    expect(scene(7)).toHaveAttribute('aria-current', 'true')
  })

  it('after a chapter is renamed with Enter the focus is back on the selected scene, and Esc sends nothing', async () => {
    const edit = editing()
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(2))
    await userEvent.click(screen.getByRole('button', { name: 'Turn' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Chapter name' })).toHaveFocus())
    await userEvent.keyboard('{Control>}a{/Control}The turn{Enter}')
    await waitFor(() => expect(scene(2)).toHaveFocus())
    expect(edit).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Answer' }))
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Chapter name' })).toHaveFocus())
    await userEvent.keyboard('Later{Escape}')
    await waitFor(() => expect(scene(2)).toHaveFocus())
    expect(edit).toHaveBeenCalledTimes(1)
  })

  it('words refused after the creator has gone on to another scene are said in a toast', async () => {
    const refused = 'Not said in your recording. The words stay as they were.'
    window.frameflow = {
      describe: async () => tierList,
      edit: vi.fn(async () => ({ refused, changed: false })),
      thumbnail: async () => null
    } as never
    render(
      <>
        <Storyboard folder={FOLDER} />
        <Toasts />
      </>
    )
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'What is said' })).toHaveFocus())
    await userEvent.keyboard(' goodbye everyone')
    await userEvent.click(scene(7)) // leaving the field sends the words; its panel is gone when the answer comes
    expect(await screen.findByText(refused)).toBeInTheDocument()
  })

  it('Ctrl+Z in the words field undoes the typing, not the storyboard', async () => {
    const undo = vi.fn(async () => ({ described: tierList, notes: [] }))
    window.frameflow = {
      describe: async () => ({ ...tierList, can_undo: true }),
      undo,
      thumbnail: async () => null
    } as never
    render(<Storyboard folder={FOLDER} />)
    await screen.findAllByRole('button', { name: /^Scene \d+:/ })
    await userEvent.click(scene(6))
    await userEvent.keyboard('{Enter}')
    const field = await screen.findByRole('textbox', { name: 'What is said' })
    await waitFor(() => expect(field).toHaveFocus())
    await userEvent.keyboard('{Control>}z{/Control}')
    expect(undo).not.toHaveBeenCalled()
    await userEvent.keyboard('{Escape}')
    scene(6).focus()
    await userEvent.keyboard('{Control>}z{/Control}')
    await waitFor(() => expect(undo).toHaveBeenCalledWith(FOLDER, 'v1'))
  })
})
