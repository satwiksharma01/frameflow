import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Described, EditAnswer, EditOp } from '@shared/types'
import { Toasts } from '../shell/Toasts'
import { tierList } from './fixture'
import { selectAfter, useStoryboard } from './useStoryboard'

const FOLDER = 'E:\\my projects\\frameflow\\output\\reference-swap'

/** The engine's answer to a change: the storyboard as it then is, with its new version. */
function after(
  described: Described,
  version: string,
  changes: Partial<Described> = {}
): EditAnswer {
  return { described: { ...described, version, can_undo: true, ...changes }, notes: [] }
}

function engine(overrides: Record<string, unknown> = {}): Record<string, ReturnType<typeof vi.fn>> {
  const fake = {
    describe: vi.fn(async () => tierList),
    edit: vi.fn(async (_f: string, _op: EditOp, version: string) => after(tierList, `${version}+`)),
    undo: vi.fn(async (_f: string, version: string) => after(tierList, `${version}<`)),
    redo: vi.fn(async (_f: string, version: string) => after(tierList, `${version}>`)),
    ...overrides
  }
  window.frameflow = fake as never
  return fake as Record<string, ReturnType<typeof vi.fn>>
}

async function ready(): Promise<{ current: ReturnType<typeof useStoryboard> }> {
  const { result } = renderHook(() => useStoryboard(FOLDER))
  await waitFor(() => expect(result.current.status).toBe('ready'))
  return result
}

it('a change waits for the one before and is sent with that one’s version', async () => {
  const fake = engine()
  const board = await ready()
  await act(async () => {
    await Promise.all([
      board.current.edit({ op: 'delete', number: 3 }),
      board.current.edit({ op: 'delete', number: 2 })
    ])
  })
  expect(fake.edit.mock.calls.map((c) => c[2])).toEqual(['v1', 'v1+'])
})

it('three quick undos run one after another and none is refused', async () => {
  const fake = engine({ describe: vi.fn(async () => ({ ...tierList, can_undo: true })) })
  const board = await ready()
  await act(async () => {
    await Promise.all([board.current.undo(), board.current.undo(), board.current.undo()])
  })
  expect(fake.undo.mock.calls.map((c) => c[1])).toEqual(['v1', 'v1<', 'v1<<'])
})

it('undo does nothing when there is nothing to undo', async () => {
  const fake = engine()
  const board = await ready()
  await act(() => board.current.undo())
  expect(fake.undo).not.toHaveBeenCalled()
})

it('a move shows the new order before the engine answers', async () => {
  let answer: (a: EditAnswer) => void = () => {}
  engine({ edit: vi.fn(() => new Promise<EditAnswer>((resolve) => (answer = resolve))) })
  const board = await ready()
  let done: Promise<unknown> = Promise.resolve()
  act(() => {
    done = board.current.edit({ op: 'move', from: 9, to: 1 })
  })
  await waitFor(() => expect(board.current.described!.scenes[0].key).toBe('scene-9'))
  expect(board.current.described!.scenes.map((s) => s.number)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9])
  expect(board.current.busy).toBe(true)
  await act(async () => {
    answer(after(tierList, 'v2'))
    await done
  })
  expect(board.current.busy).toBe(false)
})

it('a refused move puts the order back and says why', async () => {
  engine({ edit: vi.fn(async () => ({ refused: 'There is no scene 12.', changed: false })) })
  const board = await ready()
  let result: unknown
  await act(async () => {
    result = await board.current.edit({ op: 'move', from: 9, to: 1 })
  })
  expect(result).toEqual({ ok: false, refused: 'There is no scene 12.' })
  expect(board.current.described!.scenes[0].key).toBe('scene-1')
})

it('a change refused as changed outside the app reloads and says the last change was not made', async () => {
  const message =
    'The storyboard changed outside the app, so it was reloaded. Your last change was not made.'
  const fake = engine({ edit: vi.fn(async () => ({ refused: message, changed: true })) })
  render(<Toasts />)
  const board = await ready()
  await act(async () => {
    await board.current.edit({ op: 'delete', number: 1 })
  })
  expect(fake.describe).toHaveBeenCalledTimes(2)
  expect(await screen.findByText(message)).toBeInTheDocument()
})

it('a delete with a toast offers Undo, and Undo undoes it', async () => {
  const fake = engine()
  render(<Toasts />)
  const board = await ready()
  await act(async () => {
    await board.current.edit({ op: 'delete', number: 3 }, 'Scene 3 deleted')
  })
  expect(await screen.findByText('Scene 3 deleted')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
  await waitFor(() => expect(fake.undo).toHaveBeenCalledWith(FOLDER, 'v1+'))
})

it('a later change without a toast of its own takes the last one’s Undo away', async () => {
  const note = 'Card “Nomad” now shows from the start of the scene.'
  const fake = engine()
  render(<Toasts />)
  const board = await ready()
  await act(async () => {
    await board.current.edit({ op: 'delete', number: 3 }, 'Scene 3 deleted')
  })
  expect(await screen.findByRole('button', { name: 'Undo' })).toBeInTheDocument()
  fake.edit.mockImplementationOnce(async () => ({ ...after(tierList, 'v3'), notes: [note] }))
  await act(async () => {
    await board.current.edit({ op: 'over', number: 2, caption: 'Big sale' })
  })
  expect(await screen.findByText(note)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull() // it would undo the caption, not the delete
  await act(async () => {
    await board.current.edit({ op: 'over', number: 2, caption: 'Bigger sale' })
  })
  await waitFor(() => expect(screen.queryByText(note)).toBeNull())
})

it('notes from the engine are shown', async () => {
  const note =
    'Card “Nomad” now shows from the start of the scene: “Hello” is not said in it any more.'
  engine({ edit: vi.fn(async () => ({ ...after(tierList, 'v2'), notes: [note] })) })
  render(<Toasts />)
  const board = await ready()
  await act(async () => {
    await board.current.edit({ op: 'words', number: 1, words: 'there' })
  })
  expect(await screen.findByText(note)).toBeInTheDocument()
})

it('a storyboard that cannot be read says why', async () => {
  engine({
    describe: vi.fn(async () => Promise.reject(new Error('storyboard.json is not valid JSON')))
  })
  const { result } = renderHook(() => useStoryboard(FOLDER))
  await waitFor(() => expect(result.current.status).toBe('failed'))
  expect(result.current.message).toBe('storyboard.json is not valid JSON')
})

it('selectAfter follows a moved scene, stays put on a delete and lands on an added scene', () => {
  expect(selectAfter({ op: 'move', from: 9, to: 2 }, 9, 9)).toBe(2)
  expect(selectAfter({ op: 'delete', number: 4 }, 4, 9)).toBe(4)
  expect(selectAfter({ op: 'delete', number: 9 }, 9, 9)).toBe(8)
  expect(selectAfter({ op: 'add', after: 3, scene: { kind: 'title', text: 'Hi' } }, 3, 9)).toBe(4)
  expect(selectAfter({ op: 'words', number: 5, words: 'x' }, 5, 9)).toBe(5)
})
