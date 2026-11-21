// The storyboard's keyboard map, as one pure function.

export type Action =
  | 'next'
  | 'previous'
  | 'down'
  | 'up'
  | 'first'
  | 'last'
  | 'move-earlier'
  | 'move-later'
  | 'delete'
  | 'edit-words'
  | 'undo'
  | 'redo'
  | 'palette'
  | 'play'

type Keys = Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'shiftKey' | 'altKey'>

/** What a key press does on the storyboard. In a text field only the palette's keys pass: the field
 *  keeps the rest, its own Ctrl+Z included. */
export function actionFor(e: Keys, inField: boolean): Action | null {
  const command = e.ctrlKey || e.metaKey
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key
  if (command && key === 'k') return 'palette'
  if (inField) return null
  if (command && key === 'z') return e.shiftKey ? 'redo' : 'undo'
  if (e.ctrlKey && key === 'y') return 'redo'
  if (command) return null
  if (e.altKey)
    return key === 'ArrowLeft' ? 'move-earlier' : key === 'ArrowRight' ? 'move-later' : null
  const plain: Record<string, Action> = {
    ArrowRight: 'next',
    ArrowLeft: 'previous',
    ArrowDown: 'down',
    ArrowUp: 'up',
    Home: 'first',
    End: 'last',
    Delete: 'delete',
    Backspace: 'delete',
    Enter: 'edit-words',
    ' ': 'play'
  }
  return plain[key] ?? null
}

/** Whether a key press comes from somewhere the creator types. */
export function inTextField(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
  )
}
