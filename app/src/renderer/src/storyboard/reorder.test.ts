import { moveOp } from './reorder'

const keys = ['a', 'b', 'c', 'd', 'e']

it('moveOp gives the numbers of the scene moved and where it lands', () => {
  expect(moveOp(keys, 'b', 'd')).toEqual({ op: 'move', from: 2, to: 4 })
  expect(moveOp(keys, 'e', 'a')).toEqual({ op: 'move', from: 5, to: 1 })
})

it('moveOp is null for a drop on itself, or on nothing it knows', () => {
  expect(moveOp(keys, 'c', 'c')).toBeNull()
  expect(moveOp(keys, 'c', 'z')).toBeNull()
  expect(moveOp(keys, 'z', 'c')).toBeNull()
})
