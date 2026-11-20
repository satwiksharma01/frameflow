import { toast, Toaster } from 'sonner'

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

/** Where a change says what it did, with Undo: bottom right, above the footer, one at a time. */
export function Toasts(): React.JSX.Element {
  return (
    <Toaster
      position="bottom-right"
      offset={{ bottom: 76, right: 24 }}
      visibleToasts={1}
      duration={6000}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            'flex w-[360px] items-center gap-4 rounded-xl bg-ink px-4 py-3 text-[13px] text-ground shadow-[0_8px_24px_rgb(0_0_0/0.4)]',
          title: 'font-bold',
          description: 'mt-0.5 text-[12px] text-[#3a3a38]',
          actionButton:
            'ml-auto min-h-8 flex-none cursor-pointer rounded-md px-3 font-bold text-ground outline-offset-2 hover:bg-black/10'
        }
      }}
    />
  )
}
