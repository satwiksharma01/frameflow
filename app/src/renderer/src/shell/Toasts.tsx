import { Toaster } from 'sonner'

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
            'flex w-[360px] items-center gap-4 rounded-xl bg-ink px-4 py-3 text-[13px] text-ground shadow-toast',
          title: 'font-bold',
          description: 'mt-0.5 text-[12px] text-dim',
          actionButton:
            'ml-auto min-h-8 flex-none cursor-pointer rounded-md px-3 font-bold text-ground outline-offset-2 hover:bg-ground/10'
        }
      }}
    />
  )
}
