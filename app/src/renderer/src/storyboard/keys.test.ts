import { actionFor } from './keys'

const press = (key: string, mods: Partial<Record<'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey', boolean>> = {}, inField = false) =>
  actionFor({ key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods }, inField)

it('arrows move the selection, Home and End go to the ends', () => {
  expect([press('ArrowRight'), press('ArrowLeft'), press('ArrowDown'), press('ArrowUp')]).toEqual([
    'next',
    'previous',
    'down',
    'up'
  ])
  expect([press('Home'), press('End')]).toEqual(['first', 'last'])
})

it('Alt and an arrow move the scene itself', () => {
  expect(press('ArrowLeft', { altKey: true })).toBe('move-earlier')
  expect(press('ArrowRight', { altKey: true })).toBe('move-later')
})

it('Delete and Backspace delete, Enter opens the words', () => {
  expect([press('Delete'), press('Backspace'), press('Enter')]).toEqual(['delete', 'delete', 'edit-words'])
})

it('Ctrl or Cmd Z undoes, with Shift or Ctrl Y it redoes', () => {
  expect(press('z', { ctrlKey: true })).toBe('undo')
  expect(press('z', { metaKey: true })).toBe('undo')
  expect(press('Z', { ctrlKey: true, shiftKey: true })).toBe('redo')
  expect(press('y', { ctrlKey: true })).toBe('redo')
})

it('Ctrl or Cmd K opens the palette, even from a text field', () => {
  expect(press('k', { ctrlKey: true })).toBe('palette')
  expect(press('k', { metaKey: true }, true)).toBe('palette')
})

it('in a text field every other key is the field’s own, its undo included', () => {
  for (const [key, mods] of [
    ['z', { ctrlKey: true }],
    ['Delete', {}],
    ['Enter', {}],
    ['ArrowLeft', { altKey: true }]
  ] as const) {
    expect(press(key, mods, true)).toBeNull()
  }
})

it('Space plays outside a field and types a space in one', () => {
  expect(press(' ')).toBe('play')
  expect(press(' ', {}, true)).toBeNull()
})

it('other keys map to nothing', () => {
  expect(press('a')).toBeNull()
  expect(press('ArrowRight', { ctrlKey: true })).toBeNull()
})
