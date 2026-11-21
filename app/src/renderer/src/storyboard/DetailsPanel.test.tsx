import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Scene } from '@shared/types'
import { DetailsPanel } from './DetailsPanel'
import { tierList, twoCuts } from './fixture'
import { toView, type SceneView } from './model'
import type { EditResult } from './useStoryboard'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'
const scenes = toView(tierList).sections.flatMap((s) => s.scenes)
const footage: SceneView = scenes[5] // scene 6: "the goal is to remove all the repetitive editing work"
const title: SceneView = {
  ...scenes[1],
  kind: 'title',
  says: 'Meet the Nomad',
  narration: 'Meet the Nomad',
  text: 'Nomad',
  source: 'Title'
}

function panel(
  scene: SceneView,
  edit = vi.fn(async (): Promise<EditResult> => ({ ok: true, notes: [] })),
  file: string | null = null
): typeof edit {
  window.frameflow = { thumbnail: async () => null, chooseFile: vi.fn(async () => file) } as never
  render(<DetailsPanel scene={scene} folder={FOLDER} aspect="9:16" edit={edit} />)
  return edit
}

const words = (): HTMLElement =>
  screen.getByRole('button', { name: /^What (is said|the voice says)/ })

it('Enter on the words opens them for editing and Esc puts them back', async () => {
  const edit = panel(footage)
  words().focus()
  await userEvent.keyboard('{Enter}')
  const field = screen.getByRole('textbox', { name: 'What is said' })
  expect(field).toHaveValue('the goal is to remove all the repetitive editing work')
  await userEvent.type(field, ' again')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('textbox', { name: 'What is said' })).toBeNull()
  expect(words()).toHaveTextContent('the goal is to remove all the repetitive editing work')
  expect(edit).not.toHaveBeenCalled()
})

it('new words are sent as a words change, and "Finding it in your recording…" shows while it looks', async () => {
  let answer: (r: EditResult) => void = () => {}
  const edit = panel(
    footage,
    vi.fn(() => new Promise<EditResult>((resolve) => (answer = resolve)))
  )
  await userEvent.click(words())
  const field = screen.getByRole('textbox', { name: 'What is said' })
  await userEvent.clear(field)
  await userEvent.type(field, 'remove all the repetitive editing work{Enter}')
  expect(edit).toHaveBeenCalledWith({
    op: 'words',
    number: 6,
    words: 'remove all the repetitive editing work'
  })
  expect(screen.getByText('Finding it in your recording…')).toBeInTheDocument()
  answer({ ok: true, notes: [] })
  await waitFor(() => expect(screen.queryByText('Finding it in your recording…')).toBeNull())
})

it('words not said are shown under the field and the old words come back', async () => {
  const refused = 'Not said in your recording. The words stay as they were.'
  panel(
    footage,
    vi.fn(async (): Promise<EditResult> => ({ ok: false, refused }))
  )
  await userEvent.click(words())
  const field = screen.getByRole('textbox', { name: 'What is said' })
  await userEvent.clear(field)
  await userEvent.type(field, 'goodbye{Enter}')
  expect(await screen.findByText(refused)).toBeInTheDocument()
  expect(words()).toHaveTextContent('the goal is to remove all the repetitive editing work')
})

it('Shift+Enter adds no new line: the words are one line', async () => {
  const edit = panel(footage)
  await userEvent.click(words())
  const field = screen.getByRole('textbox', { name: 'What is said' })
  await userEvent.type(field, '{Shift>}{Enter}{/Shift}')
  expect((field as HTMLTextAreaElement).value).not.toContain('\n')
  expect(edit).not.toHaveBeenCalled()
})

it("a title's words on screen are changed with a title change", async () => {
  const edit = panel(title)
  const field = screen.getByRole('textbox', { name: 'On screen' })
  await userEvent.clear(field)
  await userEvent.type(field, 'The Nomad{Enter}')
  expect(edit).toHaveBeenCalledWith({ op: 'title', number: 2, text: 'The Nomad' })
  expect(screen.getByRole('button', { name: /^What the voice says/ })).toBeInTheDocument()
})

it('adding a card sends the whole list with the new card', async () => {
  const card: Scene['cards'][number] = { kind: 'lower_third', text: 'Satwik' }
  const edit = panel({ ...footage, cards: [card] })
  await userEvent.click(screen.getByRole('button', { name: 'Add a card' }))
  expect(edit).toHaveBeenCalledWith({
    op: 'over',
    number: 6,
    cards: [card, { kind: 'product', text: 'New card' }]
  })
})

it('removing a card sends the list without it', async () => {
  const cards: Scene['cards'] = [
    { kind: 'lower_third', text: 'Satwik' },
    { kind: 'product', text: 'Nomad', price: '$129' }
  ]
  const edit = panel({ ...footage, cards })
  await userEvent.click(screen.getAllByRole('button', { name: 'Remove card' })[0])
  expect(edit).toHaveBeenCalledWith({ op: 'over', number: 6, cards: [cards[1]] })
})

it("a card's words are changed when the field is left", async () => {
  const edit = panel({ ...footage, cards: [{ kind: 'product', text: 'Nomad' }] })
  await userEvent.type(screen.getByRole('textbox', { name: 'Pops up on' }), 'editing work')
  await userEvent.tab()
  expect(edit).toHaveBeenCalledWith({
    op: 'over',
    number: 6,
    cards: [{ kind: 'product', text: 'Nomad', when: 'editing work' }]
  })
})

it('the picture is replaced with the file the creator picks, and nothing is sent when they cancel', async () => {
  const edit = panel(title, undefined, 'C:/me/shot.png')
  await userEvent.click(screen.getByRole('button', { name: 'Replace the picture…' }))
  await waitFor(() =>
    expect(edit).toHaveBeenCalledWith(
      { op: 'picture', number: 2, path: 'C:/me/shot.png' },
      'Picture replaced'
    )
  )
})

it('cancelling the file dialog sends nothing', async () => {
  const edit = panel(footage)
  await userEvent.click(screen.getByRole('button', { name: 'Cover with a picture or clip…' }))
  expect(window.frameflow.chooseFile).toHaveBeenCalled()
  expect(edit).not.toHaveBeenCalled()
})

it('B-roll is offered on footage only', () => {
  panel(footage)
  expect(screen.getByRole('button', { name: 'Add B-roll…' })).toBeInTheDocument()
})

it('a title has no B-roll to add', () => {
  panel(title)
  expect(screen.queryByRole('button', { name: 'Add B-roll…' })).toBeNull()
})

it('Listen plays from a second and a half before the check to one after', async () => {
  window.frameflow = { thumbnail: async () => null } as never
  const onDone = vi.fn()
  const props = {
    scene: footage,
    folder: FOLDER,
    aspect: '9:16' as const,
    edit: vi.fn(async (): Promise<EditResult> => ({ ok: true, notes: [] })),
    onDone
  }
  const { rerender } = render(<DetailsPanel {...props} preview="ff-media://preview/?p=x" />)
  expect(footage.checks).toEqual([{ what: 'May clip “work”', at: 11.433 }])
  const listen = screen.getByRole('button', { name: 'Listen' })
  expect(listen).toHaveClass('h-8') // 32 px; jsdom lays nothing out
  await userEvent.click(listen)
  const video = document.querySelector('video')!
  expect(video.currentTime).toBeCloseTo(9.933)
  expect(document.querySelector('[data-frame]')).toHaveClass('hidden')
  video.currentTime = 12.4
  fireEvent.timeUpdate(video)
  expect(document.querySelector('video')).not.toBeNull()
  video.currentTime = 12.433
  fireEvent.timeUpdate(video)
  expect(document.querySelector('video')).toBeNull()
  expect(document.querySelector('[data-frame]')).not.toHaveClass('hidden')
  expect(onDone).toHaveBeenCalledTimes(1) // the focus goes back to the scenes
  rerender(<DetailsPanel {...props} preview={null} />)
  expect(screen.queryByRole('button', { name: 'Listen' })).toBeNull()
})

it('each of two checks has its own Listen, playing around its own moment', async () => {
  const six = toView(twoCuts).sections.flatMap((s) => s.scenes)[5]
  window.frameflow = { thumbnail: async () => null } as never
  render(
    <DetailsPanel
      scene={six}
      folder={FOLDER}
      aspect="9:16"
      preview="ff-media://preview/?p=x"
      edit={vi.fn(async (): Promise<EditResult> => ({ ok: true, notes: [] }))}
    />
  )
  expect(screen.getByText('May clip “all”')).toBeInTheDocument()
  expect(screen.getByText('May clip “work”')).toBeInTheDocument()
  const [all, work] = screen.getAllByRole('button', { name: 'Listen' })
  await userEvent.click(all)
  expect(document.querySelector('video')!.currentTime).toBeCloseTo(8.5)
  await userEvent.click(work)
  expect(document.querySelector('video')!.currentTime).toBeCloseTo(9.933)
})

it('the words read at 19 px with room between their lines', () => {
  panel(footage)
  expect(screen.getByText(footage.says)).toHaveClass('text-[19px]', 'leading-[1.3]')
})

it('Delete scene sends a delete with an Undo toast and asks nothing', async () => {
  const edit = panel(footage)
  await userEvent.click(screen.getByRole('button', { name: 'Delete scene' }))
  expect(edit).toHaveBeenCalledWith({ op: 'delete', number: 6 }, 'Scene 6 deleted')
  expect(screen.queryByRole('dialog')).toBeNull()
})

it('what pops up follows the storyboard when it changes under the fields, as an undo does', async () => {
  const edit = vi.fn(async (): Promise<EditResult> => ({ ok: true, notes: [] }))
  const card = { kind: 'product' as const, text: 'Nomad', when: 'editing work' }
  const before: SceneView = { ...footage, caption: 'Big sale', cards: [card] }
  window.frameflow = { thumbnail: async () => null } as never
  const { rerender } = render(
    <DetailsPanel scene={before} folder={FOLDER} aspect="9:16" edit={edit} />
  )
  expect(screen.getByRole('textbox', { name: 'Caption' })).toHaveValue('Big sale')
  // Undone: the caption is gone, and the card's words were dropped by the engine.
  const after: SceneView = {
    ...footage,
    caption: null,
    cards: [{ kind: 'product', text: 'Nomad' }]
  }
  rerender(<DetailsPanel scene={after} folder={FOLDER} aspect="9:16" edit={edit} />)
  expect(screen.getByRole('textbox', { name: 'Caption' })).toHaveValue('')
  expect(screen.getByRole('textbox', { name: 'Pops up on' })).toHaveValue('')
  await userEvent.click(screen.getByRole('textbox', { name: 'Caption' }))
  await userEvent.click(screen.getByRole('textbox', { name: 'Pops up on' }))
  await userEvent.tab()
  expect(edit).not.toHaveBeenCalled() // nothing old is sent back
})
