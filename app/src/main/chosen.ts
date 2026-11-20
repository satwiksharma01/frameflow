// The files the creator picked in the app's file dialog this session. Only these may join a video:
// the engine refuses any other new path, so a page could not slip a file of its own choosing in.
import type { EditOp } from '../shared/types'

export function createChosen(): { add(path: string): void; list(): string[] } {
  const paths = new Set<string>()
  return { add: (path) => void paths.add(path), list: () => [...paths] }
}

/** The file paths a change names. */
export function pathsIn(op: EditOp): string[] {
  if (op.op === 'picture') return [op.path]
  if (op.op === 'add' && op.scene.kind === 'file') return [op.scene.path]
  if (op.op === 'over') return (op.broll ?? []).map((b) => b.path)
  return []
}
