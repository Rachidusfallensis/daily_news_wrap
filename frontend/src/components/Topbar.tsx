import { Search, PanelLeftClose, PanelLeftOpen, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useArticlesStore } from '../store/articles'

interface TopbarProps {
  breadcrumb: string
  sidebarOpen: boolean
  onToggleSidebar: () => void
}

export function Topbar({ breadcrumb, sidebarOpen, onToggleSidebar }: TopbarProps) {
  const { searchQuery, setSearchQuery, searchArticles, clearSearch } = useArticlesStore()
  
  const searchInputRef = useRef<HTMLInputElement>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (!searchQuery.trim()) {
      clearSearch()
      return
    }
    searchTimer.current = setTimeout(() => searchArticles(searchQuery.trim()), 300)
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current) }
  }, [searchQuery, searchArticles, clearSearch])

  // `/` key opens search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === '/') {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  return (
    <div className="h-[48px] min-h-[48px] border-b border-border-subtle flex items-center px-5 gap-3 bg-bg-base">
      <button 
        onClick={onToggleSidebar}
        className="text-text-muted hover:text-text-primary transition-colors flex-shrink-0"
        title={sidebarOpen ? "Hide sidebar [" : "Show sidebar ["}
      >
        {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
      </button>

      <div className="flex items-center gap-1.5 text-[13px] text-text-muted">
        <span>Baṣīra</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
        <b className="text-text-primary font-medium">{breadcrumb}</b>
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <div className="flex items-center gap-2 bg-bg-surface border border-border-default rounded-md px-3 py-1 text-[13px] text-text-primary focus-within:ring-1 focus-within:ring-accent-blue focus-within:border-accent-blue transition-all w-[250px] relative">
          <Search size={14} className="text-text-muted flex-shrink-0" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Rechercher…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="bg-transparent border-none outline-none flex-1 placeholder:text-text-muted min-w-0"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} className="text-text-muted hover:text-text-primary">
              <X size={14} />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
