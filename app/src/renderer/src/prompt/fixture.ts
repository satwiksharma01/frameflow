// The pitch (output/frameflow-pitch): its prompt and its plan, as project.app_api describes it before
// a storyboard is written. Test data; the app never ships it.
import type { Described, Plan, SettingsView } from '@shared/types'

export const FOLDER = 'E:\\my projects\\frameflow\\output\\frameflow-pitch'

export const IDEA =
  'A 60-second YouTube pitch for Frameflow, my AI video editor. Creators lose hours editing; Frameflow makes the first cut from a raw recording or a prompt and hands back an editable OpenShot project, so your own edits always win. Back it with real numbers about the creator economy and how much time editing takes. End with: Frameflow is free and open source on GitHub.'

export const pitch: Plan = {
  title: 'Frameflow pitch',
  format: 'startup pitch',
  aspect: '16:9',
  target_seconds: 60,
  audience: 'YouTube creators and builders who edit their own videos',
  tone: 'confident and plain-spoken',
  summary:
    'A one-minute pitch for Frameflow. The creator economy is big and growing, and creators want AI that takes the repetitive work while they keep creative control. It ends on: Frameflow is free and open source on GitHub.',
  facts: [
    {
      claim:
        'The creator economy could roughly double to $480 billion by 2027, from $250 billion in 2023',
      source: 'Goldman Sachs Research',
      url: 'https://www.goldmansachs.com/insights/articles/the-creator-economy-could-approach-half-a-trillion-dollars-by-2027',
      quote:
        'the total addressable market of the creator economy could roughly double in size over the next five years to $480 billion by 2027 from $250 billion today'
    },
    {
      claim:
        'YouTube has paid out $100 billion to creators, artists and media companies over the past four years',
      source: 'YouTube',
      url: 'https://blog.youtube/news-and-events/earn-more-with-brand-partnerships/',
      quote:
        'Over the past four years, YouTube has paid out $100 billion to creators, artists, and media companies.'
    }
  ]
}

/** A needed fact the thinker could not look up, and a question for the creator. */
export const QUESTIONS = [
  'Needed fact: A number for how much time editing takes creators',
  'Should it name a call to action besides GitHub?'
]

export const planned = (plan: Partial<Plan> = {}, draft = true): Described => ({
  title: 'Frameflow pitch',
  scenes: [],
  no_storyboard: true,
  plan: { ...pitch, ...plan },
  plan_is_draft: draft
})

export const unplanned: Described = {
  title: 'frameflow-pitch',
  scenes: [],
  no_storyboard: true,
  plan: null,
  plan_is_draft: false
}

export const claudeCode: SettingsView = {
  thinking: 'auto',
  hasKey: false,
  agents: [
    { id: 'claude', name: 'Claude Code', found: true, version: '2.1.316' },
    { id: 'opencode', name: 'OpenCode', found: false, version: null }
  ]
}

/** A key that cannot look things up: its plan puts each needed fact in its open questions. */
export const openAiKey: SettingsView = {
  thinking: 'key',
  service: 'openai',
  model: 'a-model',
  hasKey: true,
  agents: claudeCode.agents
}
