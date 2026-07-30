import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LLMConfigPanel from '../LLMConfigPanel'

const mockProviders = [
  {
    name: 'openrouter',
    title: 'OpenRouter',
    needs_key: true,
    fields: [
      { key: 'api_key', label: 'OpenRouter API key', secret: true, required: true, help: '', placeholder: 'sk-or-…', default: '' },
      { key: 'base_url', label: 'Endpoint (optionnel)', secret: false, required: false, help: '', placeholder: '', default: 'https://openrouter.ai/api/v1' },
    ],
    recommended_model: 'google/gemini-flash-1.5',
    blurb: '',
  },
]

const scorerConfigured = {
  role: 'scorer',
  provider: 'openrouter',
  model: 'google/gemini-flash-1.5',
  api_key_configured: true,
  base_url: null,
  source: 'user',
}

function mockUrl(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input.toString()
}

describe('LLMConfigPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('affiche les rôles configurés (scorer, embedder, review, ask)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config') return new Response(JSON.stringify([scorerConfigured]), { status: 200 })
      if (url === '/api/llm-config/providers') return new Response(JSON.stringify(mockProviders), { status: 200 })
      return new Response(JSON.stringify({}), { status: 200 })
    })

    render(<LLMConfigPanel />)

    await waitFor(() => {
      expect(screen.getByText('Scorer')).toBeInTheDocument()
    })
    expect(screen.getByText('Embedder')).toBeInTheDocument()
    expect(screen.getByText('Review LLM')).toBeInTheDocument()
    expect(screen.getByText('Ask AI')).toBeInTheDocument()
    // scorer is configured -> Actif; the other 3 fall back
    expect(screen.getByText(/Actif/)).toBeInTheDocument()
  })

  it('champ api_key toujours vide en mode édition (type password)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config') return new Response(JSON.stringify([scorerConfigured]), { status: 200 })
      if (url === '/api/llm-config/providers') return new Response(JSON.stringify(mockProviders), { status: 200 })
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigPanel />)

    await waitFor(() => {
      expect(screen.getByText('Scorer')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Modifier'))

    const apiKeyInput = await screen.findByLabelText('API key') as HTMLInputElement
    expect(apiKeyInput.value).toBe('')
    expect(apiKeyInput.type).toBe('password')
  })

  it('bouton Supprimer appelle DELETE puis rafraîchit la liste', async () => {
    const calls: string[] = []
    let getCallCount = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, opts?: RequestInit) => {
      const url = mockUrl(input)
      calls.push(`${opts?.method ?? 'GET'} ${url}`)
      if (url === '/api/llm-config' && (!opts?.method || opts.method === 'GET')) {
        getCallCount += 1
        return new Response(JSON.stringify([scorerConfigured]), { status: 200 })
      }
      if (url === '/api/llm-config/providers') return new Response(JSON.stringify(mockProviders), { status: 200 })
      if (url === '/api/llm-config/scorer' && opts?.method === 'DELETE') {
        return new Response(JSON.stringify({ status: 'ok', role: 'scorer' }), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigPanel />)

    await waitFor(() => {
      expect(screen.getByText('Scorer')).toBeInTheDocument()
    })

    await user.click(screen.getByText('Supprimer'))

    await waitFor(() => {
      expect(calls).toContain('DELETE /api/llm-config/scorer')
    })
    await waitFor(() => {
      expect(getCallCount).toBeGreaterThanOrEqual(2)
    })
  })

  it('affiche un badge fallback si le rôle n\'a pas de config user (source=env)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      // Only scorer is configured — embedder/review/ask fall back to env.
      if (url === '/api/llm-config') return new Response(JSON.stringify([scorerConfigured]), { status: 200 })
      if (url === '/api/llm-config/providers') return new Response(JSON.stringify(mockProviders), { status: 200 })
      return new Response(JSON.stringify({}), { status: 200 })
    })

    render(<LLMConfigPanel />)

    await waitFor(() => {
      expect(screen.getByText('Embedder')).toBeInTheDocument()
    })

    expect(screen.getAllByText(/Fallback/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Ollama \(global\)/)).toBeInTheDocument()
  })
})
