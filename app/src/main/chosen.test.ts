// @vitest-environment node
import { expect, it } from 'vitest'
import { createChosen, pathsIn } from './chosen'

it('pathsIn names a picture, a file added and each B-roll, and nothing else', () => {
  expect(pathsIn({ op: 'picture', number: 2, path: 'C:/me/shot.png' })).toEqual(['C:/me/shot.png'])
  expect(pathsIn({ op: 'add', after: 1, scene: { kind: 'file', path: 'C:/me/walk.mp4' } })).toEqual(['C:/me/walk.mp4'])
  expect(pathsIn({ op: 'add', after: 1, scene: { kind: 'title', text: 'Hook' } })).toEqual([])
  expect(
    pathsIn({ op: 'over', number: 1, broll: [{ path: 'C:/me/a.mp4' }, { path: 'C:/me/b.png', when: 'there' }] })
  ).toEqual(['C:/me/a.mp4', 'C:/me/b.png'])
  expect(pathsIn({ op: 'over', number: 1, caption: 'Hi' })).toEqual([])
  expect(pathsIn({ op: 'delete', number: 1 })).toEqual([])
})

it('a chosen path is listed once however often it is picked', () => {
  const chosen = createChosen()
  chosen.add('C:/me/shot.png')
  chosen.add('C:/me/shot.png')
  chosen.add('C:/me/walk.mp4')
  expect(chosen.list()).toEqual(['C:/me/shot.png', 'C:/me/walk.mp4'])
})
