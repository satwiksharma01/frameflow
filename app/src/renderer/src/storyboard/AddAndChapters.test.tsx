import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Mock } from 'vitest'
import type { Described, EditAnswer, EditOp, Scene } from '@shared/types'
import { AddScene } from './AddScene'
import { ChapterHeading } from './ChapterHeading'
import { tierList } from './fixture'
import { toView } from './model'
import { slowExits } from '../test-setup'
import { Storyboard } from './Storyboard'
import type { EditResult } from './useStoryboard'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'
const ok = (): Mock<(op: EditOp, toast?: string) => Promise<EditResult>> =>
  vi.fn(async () => ({ ok: true, notes: [] }))

async function choose(item: string): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'Add a scene' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: item }))
}

it('a title added at the end of a chapter is selected, with its words on screen ready to type', async () => {
  const added: Scene = {
    ...tierList.scenes[0],
    number: 6,
    key: 'new-title',
    kind: 'title',
    says: 'New title',
    text: 'New title',
    source: 'Title',
    seconds: 2,
    start: null
  }
  const scenes = [...tierList.scenes.slice(0, 5), added, ...tierList.scenes.slice(5)].map(
    (s, i) => ({ ...s, number: i + 1 })
  )
  const answer: Described = { ...tierList, built: false, report: null, version: 'v2', scenes }
  const edit = vi.fn(async (): Promise<EditAnswer> => ({ described: answer, notes: [] }))
  window.frameflow = { describe: async () => tierList, edit, thumbnail: async () => null } as never
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  const problem = screen.getByRole('heading', { name: /Problem/ }).closest('section')!
  await userEvent.click(within(problem).getByRole('button', { name: 'Add a scene' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'A title' }))
  expect(edit).toHaveBeenCalledWith(
    FOLDER,
    { op: 'add', after: 5, scene: { kind: 'title', text: 'New title' } },
    'v1'
  )
  await waitFor(() =>
    expect(screen.getByRole('button', { name: /^Scene 6:/ })).toHaveAttribute(
      'aria-current',
      'true'
    )
  )
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'On screen' })).toHaveFocus())
})

it('a file of yours is added after the scene the tile follows', async () => {
  const edit = ok()
  window.frameflow = { chooseFile: async () => 'C:/me/walk.mp4' } as never
  render(<AddScene after={5} edit={edit} />)
  await choose('A file of yours…')
  await waitFor(() =>
    expect(edit).toHaveBeenCalledWith(
      { op: 'add', after: 5, scene: { kind: 'file', path: 'C:/me/walk.mp4' } },
      'Scene added'
    )
  )
})

it('nothing is added when the file dialog is cancelled', async () => {
  const edit = ok()
  window.frameflow = { chooseFile: vi.fn(async () => null) } as never
  render(<AddScene after={5} edit={edit} />)
  await choose('A file of yours…')
  await waitFor(() => expect(window.frameflow.chooseFile).toHaveBeenCalled())
  expect(edit).not.toHaveBeenCalled()
})

it('words from your recording are found and added', async () => {
  const edit = ok()
  render(<AddScene after={9} edit={edit} />)
  await choose('From your recording…')
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Words you say in it' }),
    'a complete first cut{Enter}'
  )
  expect(edit).toHaveBeenCalledWith(
    { op: 'add', after: 9, scene: { kind: 'recording', words: 'a complete first cut' } },
    'Scene added'
  )
  await waitFor(() =>
    expect(screen.queryByRole('textbox', { name: 'Words you say in it' })).toBeNull()
  )
})

it('words not said in the recording keep the field open with the reason', async () => {
  const refused = 'Not said in your recordings.'
  render(
    <AddScene after={9} edit={vi.fn(async (): Promise<EditResult> => ({ ok: false, refused }))} />
  )
  await choose('From your recording…')
  await userEvent.type(
    screen.getByRole('textbox', { name: 'Words you say in it' }),
    'goodbye{Enter}'
  )
  expect(await screen.findByText(refused)).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Words you say in it' })).toHaveValue('goodbye')
})

const sections = toView(tierList).sections

it('a suggested chapter shows the tag until it is renamed or kept', () => {
  const { rerender } = render(
    <ChapterHeading section={{ ...sections[1], confirmed: false }} edit={ok()} />
  )
  expect(screen.getByText('Suggested')).toBeInTheDocument()
  rerender(<ChapterHeading section={{ ...sections[1], confirmed: true }} edit={ok()} />)
  expect(screen.queryByText('Suggested')).toBeNull()
})

it('renaming a chapter sends the new name, and Esc leaves it', async () => {
  const edit = ok()
  render(<ChapterHeading section={sections[1]} edit={edit} />)
  await userEvent.click(screen.getByRole('button', { name: 'Turn' }))
  const field = screen.getByRole('textbox', { name: 'Chapter name' })
  await userEvent.clear(field)
  await userEvent.type(field, 'The turn{Escape}')
  expect(edit).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: 'Turn' }))
  await userEvent.clear(screen.getByRole('textbox', { name: 'Chapter name' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Chapter name' }), 'The turn{Enter}')
  expect(edit).toHaveBeenCalledWith({ op: 'rename_chapter', number: 2, title: 'The turn' })
})

it('Rename from the chapter menu leaves the cursor in the name field', async () => {
  const edit = ok()
  const menu = slowExits()
  render(<ChapterHeading section={sections[1]} edit={edit} />)
  await userEvent.click(screen.getByRole('button', { name: 'Chapter options' }))
  const item = await screen.findByRole('menuitem', { name: 'Rename' })
  await userEvent.click(item)
  await screen.findByLabelText('Chapter name') // found by label: the page is hidden while the menu closes
  // As the menu shrinks away while it closes, the pointer leaves the item, and the menu takes the focus.
  fireEvent.pointerLeave(item, { pointerType: 'mouse' })
  await act(async () => menu.finish())
  await act(() => new Promise((r) => setTimeout(r, 50))) // Radix hands the focus back a tick later
  expect(screen.getByRole('textbox', { name: 'Chapter name' })).toHaveFocus()
  await userEvent.keyboard('The turn{Enter}')
  expect(edit).toHaveBeenCalledWith({ op: 'rename_chapter', number: 2, title: 'The turn' })
})

it('keeping a suggested chapter confirms it', async () => {
  const edit = ok()
  render(<ChapterHeading section={{ ...sections[1], confirmed: false }} edit={edit} />)
  await userEvent.click(screen.getByRole('button', { name: 'Chapter options' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Keep this chapter' }))
  expect(edit).toHaveBeenCalledWith({ op: 'keep_chapter', number: 2 })
})

it('removing a chapter asks nothing and offers Undo', async () => {
  const edit = ok()
  render(<ChapterHeading section={sections[1]} edit={edit} />)
  await userEvent.click(screen.getByRole('button', { name: 'Chapter options' }))
  await userEvent.click(await screen.findByRole('menuitem', { name: 'Remove chapter' }))
  expect(edit).toHaveBeenCalledWith({ op: 'remove_chapter', number: 2 }, 'Chapter removed')
  expect(screen.queryByRole('dialog')).toBeNull()
})
