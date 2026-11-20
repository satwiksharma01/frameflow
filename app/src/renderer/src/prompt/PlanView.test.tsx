import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Plan } from '@shared/types'
import { Toasts } from '../shell/Toasts'
import { FOLDER, pitch, planned, QUESTIONS } from './fixture'
import { PlanView } from './PlanView'

function show(
  plan: Plan = pitch,
  unopened: number[] = []
): {
  editPlan: ReturnType<typeof vi.fn>
  onChanged: ReturnType<typeof vi.fn>
  onAsk: ReturnType<typeof vi.fn>
} {
  const editPlan = vi.fn(async (_folder: string, fields: Partial<Plan>) => planned(fields))
  window.frameflow = { editPlan } as never
  const onChanged = vi.fn()
  const onAsk = vi.fn()
  render(
    <>
      <PlanView
        folder={FOLDER}
        plan={plan}
        unopened={unopened}
        by="Claude Code"
        searches={false} // whether a needed fact says why is the prompt step's test
        onChanged={onChanged}
        onAsk={onAsk}
      />
      <Toasts />
    </>
  )
  return { editPlan, onChanged, onAsk }
}

it('opens with the figures: the length, the shape and the facts, and who wrote it', () => {
  show()
  const figures = screen.getByRole('group', { name: 'The plan in figures' })
  expect(figures).toHaveTextContent('1:00 minutes')
  expect(figures).toHaveTextContent('16:9')
  expect(figures).toHaveTextContent('startup pitch')
  expect(figures).toHaveTextContent('2 facts')
  expect(figures).toHaveTextContent('Written by Claude Code')
  expect(screen.getByText('The storyboard fills this when you approve')).toBeInTheDocument()
})

it.each([
  ['Title', 'title', 'Frameflow pitch'],
  ['For', 'audience', 'YouTube creators and builders who edit their own videos'],
  ['Tone', 'tone', 'confident and plain-spoken'],
  ['What it says', 'summary', pitch.summary]
])('%s is changed by hand, in place, through editPlan', async (label, field, value) => {
  const { editPlan, onChanged } = show()
  await userEvent.click(screen.getByRole('button', { name: `Change ${label}` }))
  const box = screen.getByRole('textbox', { name: label })
  expect(box).toHaveValue(value)
  expect(box).toHaveFocus()
  await userEvent.clear(box)
  await userEvent.type(box, 'Made new{Enter}')
  expect(editPlan).toHaveBeenCalledWith(FOLDER, { [field]: 'Made new' })
  expect(onChanged).toHaveBeenCalledWith(planned({ [field]: 'Made new' }))
})

it('Esc leaves a field as it was', async () => {
  const { editPlan } = show()
  await userEvent.click(screen.getByRole('button', { name: 'Change Tone' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Tone' }), ' and warm{Escape}')
  expect(editPlan).not.toHaveBeenCalled()
  expect(screen.queryByRole('textbox', { name: 'Tone' })).toBeNull()
  expect(screen.getByText('confident and plain-spoken')).toBeInTheDocument()
})

it('the shape the plan proposes is changed in the plan', async () => {
  const { editPlan } = show()
  await userEvent.click(screen.getByRole('combobox', { name: 'Shape' }))
  const options = within(await screen.findByRole('listbox')).getAllByRole('option')
  expect(options.map((o) => o.textContent)).toEqual(['16:9', '9:16', '1:1'])
  await userEvent.click(options[1])
  expect(editPlan).toHaveBeenCalledWith(FOLDER, { aspect: '9:16' })
})

it('lists each fact with its number, the claim, the quote from its page and who says it', () => {
  show()
  const facts = within(screen.getByRole('region', { name: 'Facts' })).getAllByRole('listitem')
  expect(facts).toHaveLength(2)
  expect(facts[0]).toHaveTextContent('01')
  expect(facts[0]).toHaveTextContent(pitch.facts![0].claim)
  expect(facts[0]).toHaveTextContent(pitch.facts![0].quote)
  expect(facts[0]).toHaveTextContent('Goldman Sachs Research')
})

it('an open question is answered in a line, or removed', async () => {
  const { editPlan, onAsk } = show({ ...pitch, open_questions: QUESTIONS })
  const questions = within(screen.getByRole('region', { name: 'Open questions' })).getAllByRole(
    'listitem'
  )
  expect(questions).toHaveLength(2)
  const second = within(questions[1])
  await userEvent.type(second.getByRole('textbox', { name: 'Answer in a line' }), 'No{Enter}')
  expect(onAsk).toHaveBeenCalledWith({ kind: 'answer', question: 2, words: 'No' })
  await userEvent.click(second.getByRole('button', { name: 'Remove' }))
  expect(editPlan).toHaveBeenCalledWith(FOLDER, { remove_question: 2 })
})

it('a needed fact asks for its page and the words on it, or Drop, shown without its mark', async () => {
  const { editPlan, onAsk } = show({ ...pitch, open_questions: QUESTIONS })
  const [fact, question] = within(
    screen.getByRole('region', { name: 'Open questions' })
  ).getAllByRole('listitem')
  const asked = within(fact)
  expect(fact).toHaveTextContent(/^01A number for how much time editing takes creators/)
  expect(fact).not.toHaveTextContent('Needed fact')
  expect(fact).toHaveTextContent(
    'This key cannot look things up, so give the page and the words on it, or drop it.'
  )
  await userEvent.type(
    asked.getByRole('textbox', { name: 'The page’s address' }),
    'https://example.com/editing-survey'
  )
  await userEvent.type(asked.getByRole('textbox', { name: 'The page’s address' }), '{Enter}')
  expect(onAsk).not.toHaveBeenCalled() // not without the words on it
  await userEvent.type(
    asked.getByRole('textbox', { name: 'The words on it' }),
    'creators spend 30 percent of their week editing{Enter}'
  )
  expect(onAsk).toHaveBeenCalledWith({
    kind: 'answer',
    question: 1,
    words:
      'Page: https://example.com/editing-survey — Words: creators spend 30 percent of their week editing'
  })
  await userEvent.click(asked.getByRole('button', { name: 'Drop' }))
  expect(editPlan).toHaveBeenCalledWith(FOLDER, { remove_question: 1 })
  // A question is still answered in a line.
  expect(within(question).getByRole('textbox', { name: 'Answer in a line' })).toBeInTheDocument()
})

it('a needed fact the thinker wrote in lower case starts with a capital', () => {
  show({ ...pitch, open_questions: ['Needed fact: how many hours creators spend editing a week'] })
  const [fact] = within(screen.getByRole('region', { name: 'Open questions' })).getAllByRole(
    'listitem'
  )
  expect(fact).toHaveTextContent(/^01How many hours creators spend editing a week/)
})

it('every question that is not a needed fact is answered in a line, with or without a question mark', () => {
  show({ ...pitch, open_questions: ['The product’s name', QUESTIONS[1]] })
  const region = screen.getByRole('region', { name: 'Open questions' })
  expect(within(region).getAllByRole('textbox', { name: 'Answer in a line' })).toHaveLength(2)
  expect(within(region).queryByRole('textbox', { name: 'The page’s address' })).toBeNull()
  expect(within(region).getAllByRole('button', { name: 'Remove' })).toHaveLength(2)
})

it('a fact whose page Frameflow could not open says so under its quote, quietly', () => {
  show(pitch, [2])
  const region = screen.getByRole('region', { name: 'Facts' })
  const [first, second] = within(region).getAllByRole('listitem')
  expect(within(second).getByText('Frameflow could not open this page.')).toHaveClass('text-quiet')
  expect(second.querySelector('.text-signal-ink')).toBeNull()
  expect(first).not.toHaveTextContent('Frameflow could not open this page.')
  expect(region).not.toHaveTextContent('each opened on its page')
})

it('with every page opened, the facts say so', () => {
  show(pitch, [])
  expect(screen.getByRole('region', { name: 'Facts' })).toHaveTextContent('each opened on its page')
  expect(screen.queryByText('Frameflow could not open this page.')).toBeNull()
})

it('the length is changed on its figure, as m:ss or seconds; Esc leaves it, and the focus comes back', async () => {
  const { editPlan } = show()
  const figure = screen.getByRole('button', { name: /change length$/ })
  await userEvent.click(figure)
  const box = screen.getByRole('textbox', { name: 'Length' })
  expect(box).toHaveValue('1:00')
  expect(box).toHaveFocus()
  await userEvent.keyboard('0:45{Enter}')
  expect(editPlan).toHaveBeenLastCalledWith(FOLDER, { target_seconds: 45 })
  await waitFor(() => expect(screen.getByRole('button', { name: /change length$/ })).toHaveFocus())

  await userEvent.click(screen.getByRole('button', { name: /change length$/ }))
  await userEvent.keyboard('90{Enter}')
  expect(editPlan).toHaveBeenLastCalledWith(FOLDER, { target_seconds: 90 })

  await userEvent.click(screen.getByRole('button', { name: /change length$/ }))
  await userEvent.keyboard('3:00{Escape}')
  expect(editPlan).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('textbox', { name: 'Length' })).toBeNull()
  await waitFor(() => expect(screen.getByRole('button', { name: /change length$/ })).toHaveFocus())
})

it('a length the engine refuses changes nothing and says why, as a row does', async () => {
  const { editPlan, onChanged } = show()
  editPlan.mockRejectedValueOnce(
    new Error('That change was not made: at target_seconds: 0 is less than or equal to 0')
  )
  await userEvent.click(screen.getByRole('button', { name: /change length$/ }))
  await userEvent.keyboard('0{Enter}')
  expect(editPlan).toHaveBeenCalledWith(FOLDER, { target_seconds: 0 })
  expect(onChanged).not.toHaveBeenCalled()
  expect(
    await screen.findByText(
      'That change was not made: at target_seconds: 0 is less than or equal to 0'
    )
  ).toBeVisible()
  expect(screen.getByRole('group', { name: 'The plan in figures' })).toHaveTextContent(
    '1:00 minutes'
  )
})

it('a length typed another way but the same sends nothing, so an approved plan stays approved', async () => {
  const { editPlan } = show({ ...pitch, target_seconds: 30 })
  await userEvent.click(screen.getByRole('button', { name: /change length$/ }))
  expect(screen.getByRole('textbox', { name: 'Length' })).toHaveValue('30')
  await userEvent.keyboard('0:30{Enter}')
  expect(editPlan).not.toHaveBeenCalled()
})

it('both figures are 32 px targets, drawn where the figures stand', () => {
  show()
  expect(
    screen.getByRole('button', { name: /change length$/ }).getAttribute('aria-label')
  ).toBeNull()
  expect(screen.getByRole('button', { name: /change length$/ })).toHaveAccessibleName(
    /^1:00 minutes, change length$/
  )
  for (const name of [/change length$/, /change kind$/])
    expect(screen.getByRole('button', { name })).toHaveClass('py-[9px]', '-my-[9px]')
})

it('the kind of video is retyped on its word, and the focus comes back', async () => {
  const { editPlan } = show()
  await userEvent.click(screen.getByRole('button', { name: /change kind$/ }))
  const box = screen.getByRole('textbox', { name: 'Kind' })
  expect(box).toHaveValue('startup pitch')
  expect(box).toHaveFocus()
  await userEvent.keyboard('product pitch{Enter}')
  expect(editPlan).toHaveBeenCalledWith(FOLDER, { format: 'product pitch' })
  await waitFor(() => expect(screen.getByRole('button', { name: /change kind$/ })).toHaveFocus())
})

it('a change the engine refuses changes nothing and says why', async () => {
  const { editPlan, onChanged } = show()
  editPlan.mockRejectedValueOnce(new Error('That change was not made: at title: is too short'))
  await userEvent.click(screen.getByRole('button', { name: 'Change Title' }))
  await userEvent.clear(screen.getByRole('textbox', { name: 'Title' }))
  await userEvent.type(screen.getByRole('textbox', { name: 'Title' }), ' {Enter}')
  expect(onChanged).not.toHaveBeenCalled()
  expect(await screen.findByText('That change was not made: at title: is too short')).toBeVisible()
})
