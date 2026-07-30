import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import OnboardingWizard from '../OnboardingWizard'

const validBootstrapResponse = {
  domain_label: 'Test',
  scoring_clusters: [],
  facet_schema: { version: 1, dimensions: [] },
  keywords: [],
  suggested_source_queries: [],
  degraded: false,
}

const mockProviders = [
  {
    name: 'ollama',
    title: 'Ollama (modèles locaux)',
    needs_key: false,
    fields: [
      { key: 'base_url', label: 'URL du serveur Ollama', secret: false, required: false, help: '', placeholder: '', default: '' },
    ],
    recommended_model: 'llama3.2:3b',
    blurb: 'Modèles locaux — aucune clé requise, zéro coût.',
  },
]

function mockUrl(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input.toString()
}

/** Default fetch handler covering every call the wizard makes across steps.
 * Individual tests override specific routes via `overrides`. */
function makeFetchMock(overrides: Record<string, () => Response> = {}) {
  return vi.fn(async (input: RequestInfo | URL, opts?: RequestInit) => {
    const url = mockUrl(input)
    const method = opts?.method ?? 'GET'
    const key = `${method} ${url}`
    if (overrides[key]) return overrides[key]()
    if (overrides[url]) return overrides[url]()

    if (url === '/api/onboarding/step1') return new Response(JSON.stringify({}), { status: 200 })
    if (url === '/api/onboarding/step3') return new Response(JSON.stringify({}), { status: 200 })
    if (url === '/api/llm-config/providers') return new Response(JSON.stringify(mockProviders), { status: 200 })
    if (url === '/api/discovery/run') return new Response(JSON.stringify({}), { status: 200 }) // no run_id → DiscoveryStep shows its error/skip fallback
    if (url === '/api/profile/bootstrap') return new Response(JSON.stringify(validBootstrapResponse), { status: 200 })
    if (url === '/api/profile/config') return new Response(JSON.stringify({}), { status: 200 })
    if (url === '/api/feeds/catalog') return new Response(JSON.stringify([]), { status: 200 })
    return new Response(JSON.stringify({}), { status: 200 })
  })
}

/** Walk Thesis (skip) → LLM (Ollama) → Sources (skip, no run_id) → lands on Clusters (step 4). */
async function advanceToClustersStep(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText('Skip')) // step 1 → step 2 (LLM)

  await waitFor(() => {
    expect(screen.getByText('Configure your LLM provider')).toBeInTheDocument()
  })
  await waitFor(() => {
    expect(screen.getByText('Ollama (modèles locaux)')).toBeInTheDocument()
  })
  await user.click(screen.getByText('Ollama (modèles locaux)'))
  await user.click(screen.getByText('Valider')) // step 2 → step 3 (Sources)

  await waitFor(() => {
    expect(screen.getByText('Skip — configure sources later')).toBeInTheDocument()
  })
  await user.click(screen.getByText('Skip — configure sources later')) // step 3 → step 4 (Clusters), runId is null so DiscoveryStep is in its error/fallback stage

  await waitFor(() => {
    expect(screen.getByText('Configure your research profile')).toBeInTheDocument()
  })
}

/** Walk all the way to Step 5 ("First run"). */
async function advanceToFirstRunStep(user: ReturnType<typeof userEvent.setup>) {
  await advanceToClustersStep(user)
  await user.click(screen.getByText('Save & continue →')) // step 4 → step 5
}

describe('OnboardingWizard — Step 5 poll trigger error handling', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows an error state with a Retry button when /api/poll/trigger returns a non-2xx', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock({
      'POST /api/poll/trigger': () => new Response('Bad Gateway', { status: 502 }),
    }))

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)
    await advanceToFirstRunStep(user)

    await waitFor(() => {
      expect(screen.getByText(/Failed to start the background poll/)).toBeInTheDocument()
    })
    expect(screen.queryByText('Running your first poll')).not.toBeInTheDocument()
    expect(screen.getByText('Retry →')).toBeInTheDocument()
  })

  it('shows the error state when the fetch itself throws (poller unreachable)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock({
      'POST /api/poll/trigger': () => { throw new Error('network error') },
    }))

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)
    await advanceToFirstRunStep(user)

    await waitFor(() => {
      expect(screen.getByText(/Failed to start the background poll/)).toBeInTheDocument()
    })
  })

  it('retrying after a failed poll trigger re-fires the request and recovers', async () => {
    let triggerCallCount = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock({
      'POST /api/poll/trigger': () => {
        triggerCallCount += 1
        return triggerCallCount === 1
          ? new Response('Bad Gateway', { status: 502 })
          : new Response(JSON.stringify({}), { status: 200 })
      },
    }))

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)
    await advanceToFirstRunStep(user)

    await waitFor(() => {
      expect(screen.getByText('Retry →')).toBeInTheDocument()
    })
    expect(triggerCallCount).toBe(1)

    await user.click(screen.getByText('Retry →'))

    await waitFor(() => {
      expect(screen.getByText('Running your first poll')).toBeInTheDocument()
    })
    expect(triggerCallCount).toBe(2)
  })
})

describe('OnboardingWizard — step order (Thesis → LLM → Sources → Clusters → First run)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the LLM config step immediately after Continue on step 1', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock())

    render(<OnboardingWizard onComplete={vi.fn()} />)

    const input = screen.getByPlaceholderText(/e.g. AI-Driven/)
    await userEvent.type(input, 'Urban Mobility')
    await userEvent.click(screen.getByText('Continue →'))

    await waitFor(() => {
      expect(screen.getByText('Configure your LLM provider')).toBeInTheDocument()
    })
  })

  it('shows the LLM config step after Skip on step 1 too', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock())

    render(<OnboardingWizard onComplete={vi.fn()} />)
    await userEvent.click(screen.getByText('Skip'))

    await waitFor(() => {
      expect(screen.getByText('Configure your LLM provider')).toBeInTheDocument()
    })
  })

  it('fires discovery/run and bootstrap warm-up only after the LLM step completes', async () => {
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, opts) => {
      const url = mockUrl(input)
      calls.push(`${opts?.method ?? 'GET'} ${url}`)
      return makeFetchMock()(input, opts)
    })

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)
    await user.click(screen.getByText('Skip')) // step 1 → step 2

    expect(calls).not.toContain('POST /api/discovery/run')
    expect(calls).not.toContain('POST /api/profile/bootstrap')

    await waitFor(() => {
      expect(screen.getByText('Ollama (modèles locaux)')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Ollama (modèles locaux)'))
    await user.click(screen.getByText('Valider'))

    await waitFor(() => {
      expect(calls).toContain('POST /api/discovery/run')
      expect(calls).toContain('POST /api/profile/bootstrap')
    })
  })

  it('reaches the Sources step after the LLM step, then Clusters after Sources', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock())
    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)

    await advanceToClustersStep(user)

    expect(screen.getByText('Scoring Clusters')).toBeInTheDocument()
    expect(screen.getByText('Facet Dimensions')).toBeInTheDocument()
  })

  it('retrying on the Sources error state re-fires POST /api/discovery/run', async () => {
    let runCallCount = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock({
      'POST /api/discovery/run': () => {
        runCallCount += 1
        return new Response(JSON.stringify({}), { status: 200 }) // still no run_id — LLM still unreachable
      },
    }))

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)

    await user.click(screen.getByText('Skip')) // step 1 → step 2 (LLM)
    await waitFor(() => {
      expect(screen.getByText('Ollama (modèles locaux)')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Ollama (modèles locaux)'))
    await user.click(screen.getByText('Valider')) // step 2 → step 3 (Sources), fires the first /api/discovery/run

    await waitFor(() => {
      expect(runCallCount).toBe(1)
    })
    await waitFor(() => {
      expect(screen.getByText('Retry →')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Retry →'))

    await waitFor(() => {
      expect(runCallCount).toBe(2)
    })
  })

  it('adds a cluster card on clicking Add cluster', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(makeFetchMock())
    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)

    await advanceToClustersStep(user)
    await user.click(screen.getByText('+ Add cluster'))

    await waitFor(() => {
      const nameInputs = screen.getAllByPlaceholderText('Cluster name')
      expect(nameInputs.length).toBe(1)
    })
    expect(screen.getByPlaceholderText('Cluster description')).toBeInTheDocument()
  })

  it('saves manual clusters via PUT /api/profile/config on Continue', async () => {
    let putPayload: unknown = null
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, opts) => {
      const url = mockUrl(input)
      if (url === '/api/profile/config' && opts?.method === 'PUT') {
        putPayload = JSON.parse(opts.body as string)
        return new Response(JSON.stringify({}), { status: 200 })
      }
      return makeFetchMock()(input, opts)
    })

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)

    await advanceToClustersStep(user)
    await user.click(screen.getByText('+ Add cluster'))
    await waitFor(() => {
      expect(screen.getAllByPlaceholderText('Cluster name').length).toBe(1)
    })

    const nameInput = screen.getByPlaceholderText('Cluster name')
    await user.type(nameInput, 'Urban Mobility')
    await user.click(screen.getByText('Save & continue →'))

    await waitFor(() => {
      expect(putPayload).not.toBeNull()
    })
    const body = putPayload as Record<string, unknown>
    expect(body.scoring_clusters).toBeDefined()
    expect(body.facet_schema).toBeDefined()
    expect(body).not.toHaveProperty('thesis_text')
  })

  it('does NOT call bootstrap API again when saving manual clusters', async () => {
    const calls: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, opts) => {
      const url = mockUrl(input)
      calls.push(url)
      return makeFetchMock()(input, opts)
    })

    const user = userEvent.setup()
    render(<OnboardingWizard onComplete={vi.fn()} />)

    await advanceToClustersStep(user)
    const bootstrapCallsBeforeSave = calls.filter(c => c === '/api/profile/bootstrap').length

    await user.click(screen.getByText('Save & continue →'))

    await waitFor(() => {
      expect(screen.queryByText('Configure your research profile')).not.toBeInTheDocument()
    })
    const bootstrapCallsAfterSave = calls.filter(c => c === '/api/profile/bootstrap').length
    expect(bootstrapCallsAfterSave).toBe(bootstrapCallsBeforeSave)
  })
})
