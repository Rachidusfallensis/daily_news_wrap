import { useEffect, useState, useCallback } from 'react'
import { getLLMConfigs, saveLLMConfig, deleteLLMConfig, verifyLLMConfig, listProviders } from '../api/llmConfig'
import type { LLMConfigOut, ProviderDescriptor } from '../types'

const ROLES = ['scorer', 'embedder', 'review', 'ask'] as const
type Role = typeof ROLES[number]

const ROLE_META: Record<Role, { label: string; description: string; fallbackLabel: string }> = {
  scorer: { label: 'Scorer', description: 'notation des articles', fallbackLabel: 'OpenRouter (global) — via environment' },
  embedder: { label: 'Embedder', description: 'recherche sémantique', fallbackLabel: 'Ollama (global) — nomic-embed-text' },
  review: { label: 'Review LLM', description: 'synthèse littérature', fallbackLabel: 'OpenRouter (global) — via environment' },
  ask: { label: 'Ask AI', description: 'questions libres', fallbackLabel: 'OpenRouter (global) — via environment' },
}

interface TestResult { ok: boolean; error?: string }

function LLMConfigEditForm({
  role, providers, initial, onCancel, onSaved,
}: {
  role: Role
  providers: ProviderDescriptor[]
  initial: LLMConfigOut | null
  onCancel: () => void
  onSaved: () => void | Promise<void>
}) {
  const [provider, setProvider] = useState(initial?.provider ?? providers[0]?.name ?? '')
  const descriptor = providers.find(p => p.name === provider) ?? null
  const hasBaseUrlField = descriptor?.fields.some(f => f.key === 'base_url') ?? false
  const [model, setModel] = useState(initial?.model ?? descriptor?.recommended_model ?? '')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(initial?.base_url ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleProviderChange = (name: string) => {
    const d = providers.find(p => p.name === name)
    setProvider(name)
    setModel(d?.recommended_model ?? '')
    setBaseUrl('')
  }

  const handleSubmit = async () => {
    setSaving(true)
    setError('')
    try {
      // api_key left blank means "keep the existing key" — the backend
      // preserves it rather than wiping it (Story 15.5).
      await saveLLMConfig(role, { provider, model, api_key: apiKey || null, base_url: baseUrl || null })
      await onSaved()
    } catch {
      setError('Failed to save')
      setSaving(false)
    }
  }

  return (
    <div className="border border-border-subtle rounded-xl p-4 space-y-3">
      <div>
        <label htmlFor={`llm-edit-provider-${role}`} className="block text-xs font-medium text-text-muted mb-1">Provider</label>
        <select
          id={`llm-edit-provider-${role}`}
          value={provider}
          onChange={e => handleProviderChange(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm focus:outline-none focus:border-accent"
        >
          {providers.map(p => <option key={p.name} value={p.name}>{p.title}</option>)}
        </select>
      </div>
      <div>
        <label htmlFor={`llm-edit-model-${role}`} className="block text-xs font-medium text-text-muted mb-1">Model</label>
        <input
          id={`llm-edit-model-${role}`}
          value={model}
          onChange={e => setModel(e.target.value)}
          className="w-full px-3 py-2 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm focus:outline-none focus:border-accent"
        />
      </div>
      {descriptor?.needs_key !== false && (
        <div>
          <label htmlFor={`llm-edit-api-key-${role}`} className="block text-xs font-medium text-text-muted mb-1">API key</label>
          <input
            id={`llm-edit-api-key-${role}`}
            type="password"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder="Laisser vide pour conserver"
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm placeholder:text-text-muted/60 focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {hasBaseUrlField && (
        <div>
          <label htmlFor={`llm-edit-base-url-${role}`} className="block text-xs font-medium text-text-muted mb-1">Base URL</label>
          <input
            id={`llm-edit-base-url-${role}`}
            value={baseUrl}
            onChange={e => setBaseUrl(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-border-default bg-bg-surface text-text-primary text-sm focus:outline-none focus:border-accent"
          />
        </div>
      )}
      {error && <p className="text-danger text-xs">{error}</p>}
      <div className="flex items-center justify-end gap-2">
        <button onClick={onCancel} disabled={saving} className="px-3 py-1.5 rounded-lg text-xs text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50">
          Annuler
        </button>
        <button onClick={handleSubmit} disabled={saving} className="px-3 py-1.5 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent/90 disabled:opacity-50 transition-colors">
          {saving ? 'Saving…' : 'Enregistrer'}
        </button>
      </div>
    </div>
  )
}

export default function LLMConfigPanel() {
  const [configs, setConfigs] = useState<LLMConfigOut[] | null>(null)
  const [providers, setProviders] = useState<ProviderDescriptor[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editingRole, setEditingRole] = useState<Role | null>(null)
  const [testingRole, setTestingRole] = useState<Role | null>(null)
  const [testResults, setTestResults] = useState<Partial<Record<Role, TestResult>>>({})

  const refresh = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [cfgs, provs] = await Promise.all([getLLMConfigs(), listProviders()])
      setConfigs(cfgs)
      setProviders(provs)
    } catch {
      setError('Could not load LLM configuration')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const configFor = (role: Role) => configs?.find(c => c.role === role) ?? null

  const handleDelete = async (role: Role) => {
    try {
      await deleteLLMConfig(role)
      await refresh()
    } catch {
      setError(`Failed to delete ${role} config`)
    }
  }

  const handleTest = async (role: Role, provider: string, baseUrl: string | null) => {
    setTestingRole(role)
    try {
      const result = await verifyLLMConfig({ provider, base_url: baseUrl || undefined })
      setTestResults(prev => ({ ...prev, [role]: result }))
    } catch {
      setTestResults(prev => ({ ...prev, [role]: { ok: false, error: 'Network error' } }))
    } finally {
      setTestingRole(null)
    }
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-3">
        <div className="h-16 bg-gray-200 rounded-lg" />
        <div className="h-16 bg-gray-200 rounded-lg" />
        <div className="h-16 bg-gray-200 rounded-lg" />
        <div className="h-16 bg-gray-200 rounded-lg" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {error && <p className="text-danger text-xs">{error}</p>}
      {ROLES.map(role => {
        const cfg = configFor(role)
        const meta = ROLE_META[role]
        const testResult = testResults[role]
        return (
          <div key={role}>
            <h3 className="text-sm font-semibold text-text-primary mb-2">
              {meta.label} <span className="text-text-muted font-normal">({meta.description})</span>
            </h3>
            {editingRole === role ? (
              <LLMConfigEditForm
                role={role}
                providers={providers}
                initial={cfg}
                onCancel={() => setEditingRole(null)}
                onSaved={async () => { setEditingRole(null); await refresh() }}
              />
            ) : (
              <div className="flex items-center justify-between border border-border-subtle rounded-xl p-3 gap-3">
                <div className="text-sm text-text-primary min-w-0">
                  {cfg ? (
                    <div>
                      <span className="font-medium">{cfg.provider}</span> · {cfg.model} ·{' '}
                      <span className="text-green-600 font-medium">✓ Actif</span>
                    </div>
                  ) : (
                    <div>
                      <span className="font-medium">{meta.fallbackLabel}</span> ·{' '}
                      <span className="text-text-muted font-medium">⬡ Fallback</span>
                    </div>
                  )}
                  {testResult && (
                    <div className="text-xs mt-1">
                      {testResult.ok
                        ? <span className="text-green-600">✓ Connexion OK</span>
                        : <span className="text-danger">✗ {testResult.error || 'Connexion échouée'}</span>}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {cfg && (
                    <button
                      onClick={() => handleTest(role, cfg.provider, cfg.base_url)}
                      disabled={testingRole === role}
                      className="px-3 py-1.5 rounded-lg border border-border-default text-xs font-medium text-text-primary hover:border-border-hover disabled:opacity-50 transition-colors"
                    >
                      {testingRole === role ? 'Testing…' : 'Tester'}
                    </button>
                  )}
                  <button
                    onClick={() => setEditingRole(role)}
                    className="px-3 py-1.5 rounded-lg border border-border-default text-xs font-medium text-text-primary hover:border-border-hover transition-colors"
                  >
                    {cfg ? 'Modifier' : 'Configurer'}
                  </button>
                  {cfg && (
                    <button
                      onClick={() => handleDelete(role)}
                      className="px-3 py-1.5 rounded-lg border border-border-default text-xs font-medium text-danger hover:border-danger transition-colors"
                    >
                      Supprimer
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
