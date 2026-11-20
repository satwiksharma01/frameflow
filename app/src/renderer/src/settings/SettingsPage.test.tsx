import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { BuildEvent, SettingsView } from '@shared/types'
import { SettingsPage } from './SettingsPage'

const KEY = 'sk-test-0123456789' // made up: no service knows it
const BOTH = [
  { id: 'claude', name: 'Claude Code', found: true, version: '2.1.316' },
  { id: 'opencode', name: 'OpenCode', found: true, version: '1.17.9' }
]
const ONLY_CLAUDE = [BOTH[0], { id: 'opencode', name: 'OpenCode', found: false, version: null }]

const radio = (name: RegExp | string): HTMLInputElement => screen.getByRole('radio', { name })
const button = (name: string): HTMLElement => screen.getByRole('button', { name })

/** A test of the thinker that this file drives: `say` sends what the engine prints, `end` finishes it. */
function fakeTest(): {
  testThinking: ReturnType<typeof vi.fn>
  say: (...events: BuildEvent[]) => void
  end: (ok: boolean, message?: string) => Promise<void>
} {
  let onEvent: (e: BuildEvent) => void = () => {}
  let finish: () => void = () => {}
  const testThinking = vi.fn((listener: (e: BuildEvent) => void) => {
    onEvent = listener
    return new Promise<void>((resolve) => (finish = resolve))
  })
  return {
    testThinking,
    say: (...events) => act(() => events.forEach((e) => onEvent(e))),
    end: async (ok, message) => {
      await act(async () => {
        onEvent(ok ? { type: 'done', ok } : { type: 'done', ok, message })
        finish()
      })
    }
  }
}

type Api = Record<
  'settings' | 'saveSettings' | 'saveKey' | 'forgetKey' | 'testThinking',
  ReturnType<typeof vi.fn>
>

async function show(view: Partial<SettingsView> = {}, more: object = {}): Promise<Api> {
  const api = {
    settings: vi.fn(async () => ({ thinking: 'auto', hasKey: false, agents: BOTH, ...view })),
    saveSettings: vi.fn(async () => {}),
    saveKey: vi.fn(async () => {}),
    forgetKey: vi.fn(async () => {}),
    testThinking: vi.fn(async () => {}),
    ...more
  }
  window.frameflow = api as never
  render(<SettingsPage />)
  await screen.findByRole('radio', { name: 'An agent on this PC' })
  return api
}

it('says what the page is for, in the confirmed words', async () => {
  await show()
  expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'How Frameflow thinks' })).toBeInTheDocument()
  expect(
    screen.getByText(
      'Frameflow writes the plan, the storyboard and your changes in words with an agent on this PC or with your own API key. Everything it writes is checked before it is used.'
    )
  ).toBeInTheDocument()
  expect(screen.getByText('Uses your own plan with that agent. No key needed.')).toBeInTheDocument()
  expect(
    screen.getByText(
      'Test makes one small request, so a key is billed a fraction of a cent. When nothing is chosen, Frameflow uses Claude Code if it is on this PC, then OpenCode, then asks for a key.'
    )
  ).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '01 How Frameflow thinks' })).toHaveAttribute(
    'aria-current',
    'true'
  )
})

it('lists the agents as found or not found, and one not found cannot be chosen', async () => {
  const api = await show({ agents: ONLY_CLAUDE })
  expect(radio(/^Claude Code/).closest('label')).toHaveTextContent('Claude CodeFound · 2.1.316')
  expect(radio(/^OpenCode/).closest('label')).toHaveTextContent('OpenCodeNot found')
  expect(radio(/^OpenCode/)).toBeDisabled()
  await userEvent.click(radio(/^OpenCode/))
  expect(api.saveSettings).not.toHaveBeenCalled()
  await userEvent.click(radio(/^Claude Code/))
  expect(api.saveSettings).toHaveBeenLastCalledWith({ thinking: 'agent:claude' })
  expect(radio(/^Claude Code/)).toBeChecked()
  expect(screen.queryByRole('radio', { name: /Codex/ })).toBeNull()
})

it('with nothing chosen, Automatic reads the agent found on this PC', async () => {
  await show()
  expect(radio('An agent on this PC')).toBeChecked()
  expect(radio(/^Automatic/)).toBeChecked()
  expect(radio(/^Automatic/).closest('label')).toHaveTextContent(
    'AutomaticClaude Code (found on this PC)'
  )
})

it('Automatic reads OpenCode when only it is found, and says when there is none', async () => {
  const none = BOTH.map((a) => ({ ...a, found: false, version: null }))
  await show({ agents: [none[0], BOTH[1]] })
  expect(radio(/^Automatic/).closest('label')).toHaveTextContent('OpenCode (found on this PC)')
  document.body.innerHTML = ''
  await show({ agents: none })
  expect(radio(/^Automatic/).closest('label')).toHaveTextContent('No agent found on this PC')
})

it('choosing a key shows service, key and model, and the address for another address', async () => {
  const api = await show()
  expect(screen.queryByLabelText('Key')).toBeNull()
  await userEvent.click(radio('Your own API key'))
  expect(api.saveSettings).toHaveBeenLastCalledWith({ thinking: 'key', service: 'anthropic' })
  expect(
    screen.getByText(
      'Each use is billed to your account. The key is kept encrypted by Windows and never shown again.'
    )
  ).toBeInTheDocument()
  const service = screen.getByRole('combobox', { name: 'Service' })
  expect(service).toHaveTextContent('Anthropic')
  expect(screen.getByLabelText('Key')).toHaveAttribute('type', 'password')
  expect(screen.getByLabelText('Model')).toBeInTheDocument()
  expect(screen.queryByLabelText('Address')).toBeNull()

  await userEvent.click(service)
  const options = within(await screen.findByRole('listbox')).getAllByRole('option')
  expect(options.map((o) => o.textContent)).toEqual([
    'Anthropic',
    'OpenAI',
    'OpenRouter',
    'Gemini',
    'Another address'
  ])
  await userEvent.click(options[4])
  expect(api.saveSettings).toHaveBeenLastCalledWith({ thinking: 'key', service: 'custom' })
  await userEvent.type(await screen.findByLabelText('Address'), 'http://localhost:11434/v1')
  await userEvent.type(screen.getByLabelText('Model'), 'llama3.2')
  await userEvent.tab()
  expect(api.saveSettings).toHaveBeenLastCalledWith({
    thinking: 'key',
    service: 'custom',
    model: 'llama3.2',
    baseUrl: 'http://localhost:11434/v1'
  })
})

it('the key is typed in a password field, cleared once saved, and never shown again', async () => {
  const api = await show({ thinking: 'key', service: 'anthropic' })
  const field = screen.getByLabelText('Key')
  expect(field).toHaveAttribute('type', 'password')
  expect(button('Save')).toBeDisabled()
  await userEvent.type(field, KEY)
  await userEvent.click(button('Save'))
  expect(api.saveKey).toHaveBeenCalledWith(KEY)
  // The settings are kept first, so the key is saved for the service on screen.
  expect(api.saveSettings.mock.invocationCallOrder[0]).toBeLessThan(
    api.saveKey.mock.invocationCallOrder[0]
  )
  expect(await screen.findByText('A key is saved')).toBeInTheDocument()
  expect(screen.queryByLabelText('Key')).toBeNull()
  expect(document.body.innerHTML).not.toContain(KEY)

  // Replace asks for a new one in an empty field; Cancel keeps the one saved.
  await userEvent.click(button('Replace'))
  expect(screen.getByLabelText('Key')).toHaveValue('')
  expect(screen.getByLabelText('Key')).toHaveFocus()
  await userEvent.click(button('Cancel'))
  expect(screen.getByText('A key is saved')).toBeInTheDocument()

  await userEvent.click(button('Forget'))
  expect(api.forgetKey).toHaveBeenCalledTimes(1)
  expect(await screen.findByLabelText('Key')).toHaveValue('')
  expect(screen.queryByText('A key is saved')).toBeNull()
})

it('a saved key reads "A key is saved", with Replace and Forget, and no field', async () => {
  await show({ thinking: 'key', service: 'anthropic', hasKey: true })
  expect(screen.getByText('A key is saved')).toBeInTheDocument()
  expect(button('Replace')).toBeEnabled()
  expect(button('Forget')).toBeEnabled()
  expect(document.querySelector('input[type=password]')).toBeNull()
})

it('when the key cannot be saved, it says why and keeps nothing on screen but the field', async () => {
  await show(
    { thinking: 'key', service: 'anthropic' },
    {
      saveKey: vi.fn(async () => {
        throw new Error('Windows could not keep the key safely, so it was not saved.')
      })
    }
  )
  await userEvent.type(screen.getByLabelText('Key'), KEY)
  await userEvent.click(button('Save'))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Windows could not keep the key safely, so it was not saved.'
  )
  expect(screen.queryByText('A key is saved')).toBeNull()
})

it('another service starts with an empty key field: a key belongs to the service it was saved for', async () => {
  const api = await show({ thinking: 'key', service: 'anthropic', model: 'claude-x', hasKey: true })
  api.settings.mockResolvedValue({
    thinking: 'key',
    service: 'openai',
    hasKey: false,
    agents: BOTH
  })
  await userEvent.click(screen.getByRole('combobox', { name: 'Service' }))
  await userEvent.click(await screen.findByRole('option', { name: 'OpenAI' }))
  // The model was the other service's, so it goes too.
  expect(api.saveSettings).toHaveBeenLastCalledWith({ thinking: 'key', service: 'openai' })
  expect(await screen.findByLabelText('Key')).toHaveValue('')
  expect(screen.getByLabelText('Model')).toHaveValue('')
  expect(screen.queryByText('A key is saved')).toBeNull()
  // Only opening the page looks for the agents again: an agent installed since is found there.
  expect(api.settings.mock.calls).toEqual([[true], []])
})

it('every service but Anthropic needs a model before Save and Test', async () => {
  await show({ thinking: 'key', service: 'openai' })
  await userEvent.type(screen.getByLabelText('Key'), KEY)
  expect(screen.getByLabelText('Model')).toHaveAttribute(
    'placeholder',
    'The model’s name, as the service lists it'
  )
  expect(button('Save')).toBeDisabled()
  expect(button('Test')).toBeDisabled()
  expect(screen.getByText('Name a model first.')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Model'), 'gpt-x')
  expect(button('Save')).toBeEnabled()
  expect(button('Test')).toBeDisabled() // no key is saved yet
  await userEvent.click(button('Save'))
  await screen.findByText('A key is saved')
  expect(button('Test')).toBeEnabled()
})

it('Anthropic needs no model, and another address needs its address but no key', async () => {
  await show({ thinking: 'key', service: 'anthropic', hasKey: true })
  expect(button('Test')).toBeEnabled()
  document.body.innerHTML = ''
  await show({ thinking: 'key', service: 'custom', model: 'llama3.2' })
  expect(button('Test')).toBeDisabled()
  expect(screen.getByText('Type the address first.')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Address'), 'http://localhost:11434/v1')
  expect(button('Test')).toBeEnabled()
})

it('Test shows its steps as they happen, then the thinker that is ready', async () => {
  const test = fakeTest()
  const api = await show({ thinking: 'key', service: 'anthropic', hasKey: true }, test)
  await userEvent.click(button('Test'))
  expect(api.saveSettings).toHaveBeenLastCalledWith({ thinking: 'key', service: 'anthropic' })
  await waitFor(() => expect(test.testThinking).toHaveBeenCalledTimes(1))
  expect(button('Testing')).toBeDisabled()
  test.say({ type: 'step', text: 'Asking Anthropic' })
  expect(
    within(screen.getByRole('list', { name: 'Test steps' })).getByText('Asking Anthropic')
  ).toBeInTheDocument()
  test.say({ type: 'detail', text: 'Ready: Anthropic (claude-opus-5)' })
  await test.end(true)
  expect(screen.getByRole('status')).toHaveTextContent(
    'Ready: Anthropic, claude-opus-5 · can look facts up on the web'
  )
  expect(screen.queryByRole('list', { name: 'Test steps' })).toBeNull()
  expect(button('Test')).toBeEnabled()
})

it('a failed test says the plain line it was given, and nothing on the page is red', async () => {
  const test = fakeTest()
  await show({ thinking: 'key', service: 'openai', model: 'gpt-x', hasKey: true }, test)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(test.testThinking).toHaveBeenCalledTimes(1))
  test.say({ type: 'step', text: 'Asking OpenAI' })
  await test.end(false, 'OpenAI refused the key. Check it in Settings.')
  const said = screen.getByRole('alert')
  expect(said).toHaveTextContent('OpenAI refused the key. Check it in Settings.')
  expect(screen.queryByRole('status')).toBeNull()
  expect(document.querySelector('[class*="signal"]')).toBeNull()
  // Changing what is tested takes the old answer away.
  await userEvent.type(screen.getByLabelText('Model'), '2')
  expect(screen.queryByRole('alert')).toBeNull()
})

it('an agent is tested too, and only a service that can search says so', async () => {
  const test = fakeTest()
  await show({ thinking: 'agent:claude' }, test)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(test.testThinking).toHaveBeenCalledTimes(1))
  test.say({ type: 'detail', text: 'Ready: Claude Code' })
  await test.end(true)
  expect(screen.getByRole('status')).toHaveTextContent(
    'Ready: Claude Code · can look facts up on the web'
  )
  document.body.innerHTML = ''
  const other = fakeTest()
  await show({ thinking: 'key', service: 'openai', model: 'gpt-x', hasKey: true }, other)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(other.testThinking).toHaveBeenCalledTimes(1))
  other.say({ type: 'detail', text: 'Ready: OpenAI (gpt-x)' })
  await other.end(true)
  expect(screen.getByRole('status').textContent).toBe('Ready: OpenAI, gpt-x')
})

it('every control is reached with Tab, and the arrows choose within a group', async () => {
  const api = await show({ thinking: 'key', service: 'custom', agents: ONLY_CLAUDE })
  const reached: string[] = []
  for (let i = 0; i < 12; i++) {
    await userEvent.tab()
    const at = document.activeElement as HTMLElement
    if (at === document.body) break
    reached.push(at.id.replace(/^.*-/, '') || at.textContent!)
  }
  // A group of radios is one stop; a button that is off is passed.
  expect(reached).toEqual([
    '01 How Frameflow thinks',
    'auto',
    'bykey',
    'service',
    'key',
    'model',
    'address'
  ])
  await userEvent.type(screen.getByLabelText('Key'), KEY)
  await userEvent.type(screen.getByLabelText('Model'), 'llama3.2')
  await userEvent.type(screen.getByLabelText('Address'), 'http://localhost:11434/v1')
  await userEvent.tab()
  expect(button('Test')).toHaveFocus()

  radio('Your own API key').focus()
  await userEvent.keyboard('{ArrowUp}')
  expect(radio('An agent on this PC')).toBeChecked()
  expect(api.saveSettings).toHaveBeenLastCalledWith(expect.objectContaining({ thinking: 'auto' }))
  radio(/^Automatic/).focus()
  await userEvent.keyboard('{ArrowDown}')
  expect(radio(/^Claude Code/)).toBeChecked()
})

/** Tests of the thinker, one per click of Test: a later one replaces an earlier one, as in the main process. */
function fakeTests(): {
  testThinking: ReturnType<typeof vi.fn>
  runs: { say(...events: BuildEvent[]): void; end(): Promise<void> }[]
} {
  const runs: { say(...events: BuildEvent[]): void; end(): Promise<void> }[] = []
  const testThinking = vi.fn((listener: (e: BuildEvent) => void) => {
    let finish: () => void = () => {}
    runs.push({
      say: (...events) => act(() => events.forEach((e) => listener(e))),
      end: () => act(async () => finish())
    })
    return new Promise<void>((resolve) => (finish = resolve))
  })
  return { testThinking, runs }
}

it('an answer to a test of settings that have changed since is not shown', async () => {
  const tests = fakeTests()
  await show({ thinking: 'key', service: 'openai', model: 'gpt-x', hasKey: true }, tests)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(tests.runs).toHaveLength(1))
  await userEvent.type(screen.getByLabelText('Model'), '2')
  tests.runs[0].say(
    { type: 'step', text: 'Asking OpenAI' },
    { type: 'detail', text: 'Ready: OpenAI (gpt-x)' },
    { type: 'done', ok: true }
  )
  await tests.runs[0].end()
  expect(screen.queryByRole('status')).toBeNull()
  expect(screen.queryByRole('list', { name: 'Test steps' })).toBeNull()
  expect(button('Test')).toBeEnabled()
})

it('a test replaced by a second one says nothing: it was replaced, not failed', async () => {
  const tests = fakeTests()
  await show({ thinking: 'key', service: 'openai', model: 'gpt-x', hasKey: true }, tests)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(tests.runs).toHaveLength(1))
  await userEvent.type(screen.getByLabelText('Model'), '2')
  await userEvent.click(button('Test'))
  await waitFor(() => expect(tests.runs).toHaveLength(2))
  await tests.runs[0].end() // the main process ends a replaced job with no `done`
  expect(screen.queryByRole('alert')).toBeNull()
  expect(button('Testing')).toBeDisabled()
  tests.runs[1].say({ type: 'detail', text: 'Ready: OpenAI (gpt-x2)' }, { type: 'done', ok: true })
  await tests.runs[1].end()
  expect(screen.getByRole('status').textContent).toBe('Ready: OpenAI, gpt-x2')
})

it('the thinker that is ready is read only from the line that starts "Ready: "', async () => {
  const test = fakeTest()
  await show({ thinking: 'agent:claude' }, test)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(test.testThinking).toHaveBeenCalledTimes(1))
  test.say(
    { type: 'detail', text: 'Ready: Claude Code' },
    { type: 'detail', text: 'Finished in 2 s' }
  )
  await test.end(true)
  expect(screen.getByRole('status')).toHaveTextContent(/^Ready: Claude Code · /)
})

it('another service shows no saved key at once, before the settings are read again', async () => {
  const api = await show({ thinking: 'key', service: 'anthropic', hasKey: true })
  api.settings.mockReturnValue(new Promise(() => {})) // finding the agents takes a second or more
  await userEvent.click(screen.getByRole('combobox', { name: 'Service' }))
  await userEvent.click(await screen.findByRole('option', { name: 'OpenAI' }))
  expect(screen.queryByText('A key is saved')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Forget' })).toBeNull()
  expect(screen.getByLabelText('Key')).toHaveValue('')
})

it('the Ready line names the service and its model as "Anthropic, <model>"', async () => {
  const test = fakeTest()
  await show({ thinking: 'key', service: 'anthropic', hasKey: true }, test)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(test.testThinking).toHaveBeenCalledTimes(1))
  test.say({ type: 'detail', text: 'Ready: Anthropic (claude-sonnet-5-5)' })
  await test.end(true)
  expect(screen.getByRole('status')).toHaveTextContent(
    'Ready: Anthropic, claude-sonnet-5-5 · can look facts up on the web'
  )
})

it('Test reads in ink at 13 px in the key form, as it does under the agents', async () => {
  await show({ thinking: 'key', service: 'anthropic', hasKey: true })
  expect(button('Test')).toHaveClass('text-ink', 'text-[13px]')
  document.body.innerHTML = ''
  await show({ thinking: 'agent:claude' })
  expect(button('Test')).toHaveClass('text-ink', 'text-[13px]')
})

it('a new key takes away the answer of a test of the old one, shown or still on its way', async () => {
  const tests = fakeTests()
  await show({ thinking: 'key', service: 'anthropic', hasKey: true }, tests)
  await userEvent.click(button('Test'))
  await waitFor(() => expect(tests.runs).toHaveLength(1))
  tests.runs[0].say(
    { type: 'detail', text: 'Ready: Anthropic (claude-opus-5)' },
    { type: 'done', ok: true }
  )
  await tests.runs[0].end()
  expect(screen.getByRole('status')).toBeInTheDocument()
  await userEvent.click(button('Replace'))
  await userEvent.type(screen.getByLabelText('Key'), KEY)
  await userEvent.click(button('Save'))
  await screen.findByText('A key is saved')
  expect(screen.queryByRole('status')).toBeNull()

  // And one still running when the key is replaced.
  await userEvent.click(button('Test'))
  await waitFor(() => expect(tests.runs).toHaveLength(2))
  await userEvent.click(button('Replace'))
  await userEvent.type(screen.getByLabelText('Key'), KEY)
  await userEvent.click(button('Save'))
  await screen.findByText('A key is saved')
  tests.runs[1].say(
    { type: 'detail', text: 'Ready: Anthropic (claude-opus-5)' },
    { type: 'done', ok: true }
  )
  await tests.runs[1].end()
  expect(screen.queryByRole('status')).toBeNull()
  expect(button('Test')).toBeEnabled()
})

it('says so when the settings cannot be read', async () => {
  window.frameflow = {
    settings: vi.fn(async () => {
      throw new Error('Could not start `python`: spawn python ENOENT')
    })
  } as never
  render(<SettingsPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Could not start `python`: spawn python ENOENT'
  )
})
