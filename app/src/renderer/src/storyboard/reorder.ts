import type { EditOp } from '@shared/types'

/** The change a drop makes: the scene with key `active` takes the place of the scene with key `over`. */
export function moveOp(keys: string[], active: string, over: string): EditOp | null {
  const from = keys.indexOf(active) + 1
  const to = keys.indexOf(over) + 1
  if (!from || !to || from === to) return null
  return { op: 'move', from, to }
}
