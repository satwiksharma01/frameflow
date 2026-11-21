import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Described, EditAnswer, EditOp } from '@shared/types'
import { tierList } from '../storyboard/fixture'
import { slowExits } from '../test-setup'
import { Storyboard } from '../storyboard/Storyboard'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'

function engine(described: Described = tierList): ReturnType<typeof vi.fn> {
  const edit = vi.fn(async (_f: string, _op: EditOp, version: string): Promise<EditAnswer> => ({
    described: { ...described, version: `${version}+` },
    notes: []
  }))
  window.frameflow = { describe: async () => described, edit, thumbnail: async () => null } as never
  return edit
}

const scene = (n: number): HTMLElement =>
  screen.getByRole('button', { name: new RegExp(`^Scene ${n}:`) })

it('Ctrl K opens the palette and Escape closes it', async () => {
  engine()
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.keyboard('{Control>}k{/Control}')
  expect(await screen.findByRole('dialog')).toBeInTheDocument()
  expect(screen.getByPlaceholderText('Type a command or a scene…')).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('closing the palette gives the focus back to the selected scene, so the arrows work', async () => {
  engine()
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(3))
  await userEvent.keyboard('{Control>}k{/Control}')
  await screen.findByRole('dialog')
  await userEvent.keyboard('{Escape}')
  await waitFor(() => expect(scene(3)).toHaveFocus())
  await userEvent.keyboard('{ArrowRight}')
  expect(scene(4)).toHaveAttribute('aria-current', 'true')
})

it('typing "turn" offers the chapter, and choosing it selects its first scene', async () => {
  engine()
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.type(await screen.findByPlaceholderText('Type a command or a scene…'), 'turn')
  await userEvent.click(await screen.findByRole('option', { name: /Chapter 02 · Turn/ }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(scene(6)).toHaveAttribute('aria-current', 'true')
})

it('Delete it sends a delete for the selected scene', async () => {
  const edit = engine()
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(3))
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.click(await screen.findByRole('option', { name: /Delete it/ }))
  expect(edit).toHaveBeenCalledWith(FOLDER, { op: 'delete', number: 3 }, 'v1')
})

it('Change its words leaves the cursor in the words field once the palette has closed', async () => {
  const dialog = slowExits()
  const edit = engine()
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(6))
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.click(await screen.findByRole('option', { name: /Change its words/ }))
  const field = await screen.findByLabelText('What is said')
  await waitFor(() => expect(field).toHaveFocus())
  await act(async () => dialog.finish())
  await act(() => new Promise((r) => setTimeout(r, 50))) // Radix hands the focus back a tick later
  await userEvent.keyboard('editing work{Enter}')
  expect(edit).toHaveBeenCalledWith(FOLDER, { op: 'words', number: 6, words: 'editing work' }, 'v1')
})

it('Add a title after it leaves the cursor in its words on screen once the palette has closed', async () => {
  const dialog = slowExits()
  const title = {
    ...tierList.scenes[0],
    kind: 'title' as const,
    says: '',
    text: 'New title',
    key: 'title-1'
  }
  const scenes = [...tierList.scenes.slice(0, 3), title, ...tierList.scenes.slice(3)]
  const added: Described = { ...tierList, scenes: scenes.map((s, i) => ({ ...s, number: i + 1 })) }
  window.frameflow = {
    describe: async () => tierList,
    edit: vi.fn(async () => ({ described: { ...added, version: 'v2' }, notes: [] })),
    thumbnail: async () => null
  } as never
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(3))
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.click(await screen.findByRole('option', { name: /Add a title after it/ }))
  await waitFor(() => expect(screen.getByLabelText('On screen')).toHaveFocus())
  await act(async () => dialog.finish())
  await act(() => new Promise((r) => setTimeout(r, 50))) // Radix hands the focus back a tick later
  expect(screen.getByLabelText('On screen')).toHaveFocus()
})

it('Undo is greyed out when there is nothing to undo', async () => {
  engine({ ...tierList, can_undo: false, can_redo: false })
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.keyboard('{Control>}k{/Control}')
  expect(await screen.findByRole('option', { name: /^Undo/ })).toHaveAttribute(
    'aria-disabled',
    'true'
  )
})

it('Listen to its check plays around the selected scene’s check', async () => {
  engine({ ...tierList, preview: 'ff-media://preview/?p=x' })
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.click(scene(6))
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.click(await screen.findByRole('option', { name: /Listen to its check/ }))
  expect(document.querySelector('video')!.currentTime).toBeCloseTo(9.933)
})

it('without a preview Play it and Listen are greyed out, and a scene with no check has no Listen', async () => {
  engine({ ...tierList, preview: null })
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.keyboard('{Control>}k{/Control}')
  expect(await screen.findByRole('option', { name: /Play it/ })).toHaveAttribute(
    'aria-disabled',
    'true'
  )
  expect(screen.queryByRole('option', { name: /Listen to its check/ })).toBeNull()
  await userEvent.keyboard('{Escape}')
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  await userEvent.click(scene(6))
  await userEvent.keyboard('{Control>}k{/Control}')
  expect(await screen.findByRole('option', { name: /Listen to its check/ })).toHaveAttribute(
    'aria-disabled',
    'true'
  )
})

it('the captions switch in the palette says what it will do', async () => {
  const edit = engine()
  render(<Storyboard folder={FOLDER} />)
  await screen.findAllByRole('button', { name: /^Scene \d+:/ })
  await userEvent.keyboard('{Control>}k{/Control}')
  await userEvent.click(
    await screen.findByRole('option', { name: /Turn word-by-word captions off/ })
  )
  expect(edit).toHaveBeenCalledWith(FOLDER, { op: 'video', spoken_captions: false }, 'v1')
})
