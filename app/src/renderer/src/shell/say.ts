import { toast } from 'sonner'

/** Say what a change did, or why it was not made, in place of whatever was said before. Its Undo goes
 *  with it (sonner would keep it on an update), so Undo only ever undoes the change it names. */
export function say(message: string, more: { description?: string; undo?: () => void } = {}): void {
  // A change to another video, said apart, gives way: one toast shows at a time, and this is the one
  // the creator is acting on.
  toast.dismiss('words')
  toast(message, {
    id: 'edit',
    description: more.description,
    action: more.undo ? { label: 'Undo', onClick: more.undo } : undefined
  })
}
