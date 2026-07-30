import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import LLMConfigStep from '../LLMConfigStep'

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
    blurb: 'Accès à tous les grands modèles via une seule clé.',
  },
  {
    name: 'ollama',
    title: 'Ollama (modèles locaux)',
    needs_key: false,
    fields: [
      { key: 'base_url', label: 'URL du serveur Ollama', secret: false, required: false, help: 'URL où ollama serve écoute.', placeholder: 'http://host.docker.internal:11434', default: '' },
    ],
    recommended_model: 'llama3.2:3b',
    blurb: 'Modèles locaux — aucune clé requise, zéro coût.',
  },
]

function mockUrl(input: RequestInfo | URL): string {
  return typeof input === 'string' ? input : input.toString()
}

describe('LLMConfigStep', () => {
  const onNext = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the provider list on initial load', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByText('OpenRouter')).toBeInTheDocument()
    })
    expect(screen.getByText('Ollama (modèles locaux)')).toBeInTheDocument()
  })

  it('shows the api_key field when OpenRouter is selected', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByText('OpenRouter')).toBeInTheDocument()
    })
    await user.click(screen.getByText('OpenRouter'))

    expect(screen.getByLabelText('API key')).toBeInTheDocument()
  })

  it('shows an editable Model field defaulting to the recommended model, and submits the edited value', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByText('Ollama (modèles locaux)')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Ollama (modèles locaux)'))

    const modelInput = screen.getByLabelText('Model') as HTMLInputElement
    expect(modelInput.value).toBe('llama3.2:3b') // recommended_model default, but visible & editable

    await user.clear(modelInput)
    await user.type(modelInput, 'mistral:7b')
    await user.click(screen.getByText('Valider'))

    expect(onNext).toHaveBeenCalledWith(expect.objectContaining({ provider: 'ollama', model: 'mistral:7b' }))
  })

  it('shows "Aucune clé requise" when Ollama is selected', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByText('Ollama (modèles locaux)')).toBeInTheDocument()
    })
    await user.click(screen.getByText('Ollama (modèles locaux)'))

    expect(screen.getByText(/Aucune clé requise/)).toBeInTheDocument()
    expect(screen.queryByLabelText('API key')).not.toBeInTheDocument()
  })

  it('auto-selects the detected provider when an OpenRouter-shaped key is entered', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      if (url === '/api/llm-config/detect') {
        return new Response(JSON.stringify({ provider: 'openrouter' }), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByLabelText('API key')).toBeInTheDocument()
    })

    await user.type(screen.getByLabelText('API key'), 'sk-or-test')
    await user.tab() // blur

    await waitFor(() => {
      expect(screen.getByText('✓ Auto-detected')).toBeInTheDocument()
    })
  })

  it('has no skip/bypass option — LLM config is a hard gate', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByText('OpenRouter')).toBeInTheDocument()
    })

    expect(screen.queryByText(/Passer/)).not.toBeInTheDocument()
  })

  it('disables "Valider" until a non-Ollama provider passes the connection test', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = mockUrl(input)
      if (url === '/api/llm-config/providers') {
        return new Response(JSON.stringify(mockProviders), { status: 200 })
      }
      return new Response(JSON.stringify({}), { status: 200 })
    })

    const user = userEvent.setup()
    render(<LLMConfigStep onNext={onNext} />)

    await waitFor(() => {
      expect(screen.getByText('OpenRouter')).toBeInTheDocument()
    })
    await user.click(screen.getByText('OpenRouter'))

    expect(screen.getByText('Valider')).toBeDisabled()
  })
})
