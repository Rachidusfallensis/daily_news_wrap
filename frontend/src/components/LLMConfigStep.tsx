import { useEffect, useState, useCallback } from 'react'
import { listProviders, detectProvider, verifyLLMConfig } from '../api/llmConfig'
import type { ProviderDescriptor } from '../types'

export interface LLMConfigResult {
  provider: string
  model: string
  api_key?: string
  base_url?: string
}

interface LLMConfigStepProps {
  onNext: (config: LLMConfigResult) => void | Promise<void>
  saving?: boolean
}

export default function LLMConfigStep({ onNext, saving }: LLMConfigStepProps) {
  const [providers, setProviders] = useState<ProviderDescriptor[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [autoDetected, setAutoDetected] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    listProviders()
      .then(data => { if (!cancelled) setProviders(data) })
      .catch(() => { if (!cancelled) setLoadError('Could not load providers') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const descriptor = providers.find(p => p.name === selected) ?? null
  const baseUrlField = descriptor?.fields.find(f => f.key === 'base_url') ?? null
  const showApiKeyField = descriptor ? descriptor.needs_key : true

  const selectProvider = useCallback((name: string) => {
    const d = providers.find(p => p.name === name)
    setSelected(name)
    setModel(d?.recommended_model ?? '')
    setBaseUrl('')
    setTestResult(null)
  }, [providers])

  const handleApiKeyBlur = useCallback(async () => {
    if (!apiKey.trim()) return
    try {
      const result = await detectProvider(apiKey.trim())
      if (result.provider) {
        setAutoDetected(result.provider)
        selectProvider(result.provider)
      }
    } catch {
      // Auto-detect is best-effort — silent failure, user can still pick manually.
    }
  }, [apiKey, selectProvider])

  const handleTest = useCallback(async () => {
    if (!selected) return
    setTesting(true)
    setTestResult(null)
    try {
      const result = await verifyLLMConfig({
        provider: selected,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
      })
      setTestResult(result)
    } catch {
      setTestResult({ ok: false, error: 'Network error' })
    } finally {
      setTesting(false)
    }
  }, [selected, apiKey, baseUrl])

  const canTest = selected != null && (descriptor?.needs_key === false || apiKey.trim().length > 0)
  const canValidate = selected != null && (selected === 'ollama' || testResult?.ok === true)

  const handleValidate = () => {
    if (!selected) return
    onNext({
      provider: selected,
      model: model || descriptor?.recommended_model || '',
      api_key: descriptor?.needs_key === false ? undefined : (apiKey || undefined),
      base_url: baseUrl || undefined,
    })
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded-lg w-1/3" />
        <div className="h-24 bg-gray-200 rounded-lg" />
        <div className="h-24 bg-gray-200 rounded-lg" />
      </div>
    )
  }

  return (
    <div>
      <h2 className="text-lg font-semibold text-text-primary mb-1">Configure your LLM provider</h2>
      <p className="text-sm text-text-muted mb-7 leading-relaxed">
        Baṣīra needs your own LLM — local or remote — to score and summarize your articles. Every
        request from here on runs on your provider, not a shared default. Paste an API key to
        auto-detect your provider, or pick Ollama for a free local model.{' '}
        <span className="text-[11px] font-mono text-text-muted">FR-MT-77</span>
      </p>

      {showApiKeyField && (
        <div className="mb-6">
          <label htmlFor="llm-api-key" className="block text-sm font-medium text-text-primary mb-1.5">API key</label>
          <div className="relative">
            <input
              id="llm-api-key"
              type={showApiKey ? 'text' : 'password'}
              className="w-full px-3 py-2 pr-16 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm placeholder:text-text-muted/60 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors"
              value={apiKey}
              onChange={e => { setApiKey(e.target.value); setTestResult(null) }}
              onBlur={handleApiKeyBlur}
              placeholder="sk-…"
            />
            <button
              type="button"
              onClick={() => setShowApiKey(s => !s)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-text-muted hover:text-text-primary"
            >
              {showApiKey ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 mb-6">
        {providers.map(p => (
          <button
            key={p.name}
            onClick={() => selectProvider(p.name)}
            className={`text-left border rounded-xl p-4 transition-colors ${selected === p.name ? 'border-accent bg-accent/5' : 'border-border-subtle hover:border-border-hover'}`}
          >
            <div className="text-sm font-semibold text-text-primary mb-1">{p.title}</div>
            {p.blurb && <div className="text-xs text-text-muted leading-relaxed">{p.blurb}</div>}
            {autoDetected === p.name && selected === p.name && (
              <div className="text-[10px] text-accent font-medium mt-1.5">✓ Auto-detected</div>
            )}
          </button>
        ))}
      </div>

      {descriptor && (
        <div className="border border-border-subtle rounded-xl p-4 mb-6 space-y-4">
          {!descriptor.needs_key && (
            <p className="text-xs text-text-muted italic">Aucune clé requise — modèles locaux via Ollama.</p>
          )}

          {baseUrlField && (
            <div>
              <label htmlFor="llm-base-url" className="block text-sm font-medium text-text-primary mb-1.5">
                {baseUrlField.label}{' '}
                {!baseUrlField.required && <span className="text-text-muted text-xs font-normal">optional</span>}
              </label>
              <input
                id="llm-base-url"
                className="w-full px-3 py-2 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm placeholder:text-text-muted/60 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors"
                value={baseUrl}
                onChange={e => { setBaseUrl(e.target.value); setTestResult(null) }}
                placeholder={baseUrlField.placeholder || baseUrlField.default}
              />
              {baseUrlField.help && <p className="text-[11px] text-text-muted mt-1">{baseUrlField.help}</p>}
            </div>
          )}

          <div>
            <label htmlFor="llm-model" className="block text-sm font-medium text-text-primary mb-1.5">
              Model
            </label>
            <input
              id="llm-model"
              className="w-full px-3 py-2 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm placeholder:text-text-muted/60 focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent/30 transition-colors"
              value={model}
              onChange={e => setModel(e.target.value)}
              placeholder={descriptor.recommended_model ?? ''}
            />
            <p className="text-[11px] text-text-muted mt-1">
              {selected === 'ollama'
                ? "The exact model name Ollama will be called with — must match a model you've already pulled (run `ollama list` to check). Defaults to a suggestion, not necessarily what's installed."
                : 'The exact model your provider will be called with.'}
            </p>
          </div>

          <button
            onClick={handleTest}
            disabled={testing || !canTest}
            className="px-4 py-2 rounded-lg border border-border-default text-sm font-medium text-text-primary hover:border-border-hover disabled:opacity-50 transition-colors"
          >
            {testing ? 'Testing…' : 'Tester la connexion'}
          </button>

          {testResult && (
            testResult.ok
              ? <p className="text-xs text-green-600 font-medium">✓ Connexion OK</p>
              : <p className="text-xs text-danger font-medium">✗ {testResult.error || 'Connexion échouée'}</p>
          )}
        </div>
      )}

      {loadError && <p className="text-danger text-xs mb-4">{loadError}</p>}

      <div className="flex items-center justify-end mt-6">
        <button onClick={handleValidate} disabled={saving || !canValidate} className="px-5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-50 transition-colors">
          {saving ? 'Saving…' : 'Valider'}
        </button>
      </div>
    </div>
  )
}
