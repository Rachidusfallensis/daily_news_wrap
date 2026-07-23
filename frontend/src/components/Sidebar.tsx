import { Rss, Sparkles, BarChart2, Network, BookOpen, Settings, LogOut, Bookmark, AlertTriangle, Users, FileText, Calendar, Layers, BookMarked, Library, Sun, Moon } from 'lucide-react'
import { useCallback, useState } from 'react'
import { useTheme } from '../hooks/useTheme'
import type { NotificationCounts } from '../types'
import { useArticlesStore } from '../store/articles'
import type { Feed } from '../types'
import { usePolling } from '../hooks/usePolling'

export type AppView = 'feed' | 'digest' | 'stats' | 'research' | 'litreview' | 'threats' | 'authors' | 'write' | 'conferences' | 'highlights' | 'bibliography' | 'notes'

interface SidebarProps {
  currentView: AppView
  onViewChange: (v: AppView) => void
  feeds: Feed[]
  onOpenFeedManager: () => void
  onOpenProfile: () => void
  onLogout: () => void
}

const NO_NOTIFICATIONS: NotificationCounts = { new_threats: 0, urgent_deadlines: 0, new_author_papers: 0 }

function dismissNotification(type: 'threats' | 'conferences' | 'authors') {
  fetch('/api/research/notifications/dismiss', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type }),
  }).catch(() => {})
}

export function Sidebar({
  currentView,
  onViewChange,
  feeds,
  onOpenFeedManager,
  onOpenProfile,
  onLogout
}: SidebarProps) {
  const { filter, setFilter, articles } = useArticlesStore()
  const [notifications, setNotifications] = useState<NotificationCounts>(NO_NOTIFICATIONS)
  const { theme, toggleTheme } = useTheme()

  const fetchNotifications = useCallback(() => {
    if (currentView === 'conferences' || currentView === 'threats' || currentView === 'authors') return
    fetch('/api/research/notifications', { credentials: 'include' })
      .then(r => r.ok ? r.json() : NO_NOTIFICATIONS)
      .then(data => setNotifications(data))
      .catch(() => {})
  }, [currentView])

  usePolling(fetchNotifications, 60_000)

  const handleNavClick = useCallback((view: AppView, dismissType?: 'threats' | 'conferences' | 'authors') => {
    if (dismissType) {
      const next = { ...notifications }
      if (dismissType === 'threats') next.new_threats = 0
      else if (dismissType === 'conferences') next.urgent_deadlines = 0
      else if (dismissType === 'authors') next.new_author_papers = 0
      setNotifications(next)
      dismissNotification(dismissType)
    }
    onViewChange(view)
  }, [notifications, onViewChange])

  const categories = ['All', ...Array.from(new Set(feeds.map(f => f.category))).sort()]
  const activeCategory = filter.bookmarked ? 'Bookmarks' : (filter.category ?? 'All')

  const feedNameToCategory = new Map(feeds.map(f => [f.name, f.category]))
  const categoryCounts = new Map<string, number>()
  let bookmarkCount = 0
  for (const a of articles) {
    if (filter.status === 'read') continue
    if (a.bookmarked) bookmarkCount++
    const cat = feedNameToCategory.get(a.feed_name)
    if (cat) categoryCounts.set(cat, (categoryCounts.get(cat) ?? 0) + 1)
  }
  const totalCount = [...categoryCounts.values()].reduce((s, n) => s + n, 0)

  const handleCategoryClick = (cat: string) => {
    onViewChange('feed')
    if (cat === 'Bookmarks') {
      setFilter({ bookmarked: true, category: null })
    } else if (cat === 'All') {
      setFilter({ bookmarked: false, category: null })
    } else {
      setFilter({ bookmarked: false, category: cat })
    }
  }

  const NavItem = ({ icon: Icon, label, active, count, dot, onClick }: any) => (
    <div
      onClick={onClick}
      className={`group flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-all duration-200 text-[13.5px] select-none mb-0.5
        ${active ? 'bg-bg-elevated text-text-primary font-medium' : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'}`}
    >
      <div className={`flex items-center justify-center flex-shrink-0 w-4 h-4 transition-colors ${active ? 'text-text-primary' : 'text-text-muted group-hover:text-text-secondary'}`}>
        <Icon size={16} strokeWidth={2} />
      </div>
      <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis">{label}</span>
      {dot && (
        <span className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0" />
      )}
      {count !== undefined && count > 0 && (
        <span className="text-[11px] text-text-muted bg-bg-elevated rounded-full px-2 py-[1px] font-medium font-mono">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </div>
  )

  const CatItem = ({ colorClass, label, active, count, onClick }: any) => (
    <div
      onClick={onClick}
      className={`group flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-all duration-200 text-[13.5px] select-none mb-0.5
        ${active ? 'bg-bg-elevated text-text-primary font-medium' : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'}`}
    >
      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${colorClass}`} />
      <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis">{label}</span>
      {count !== undefined && count > 0 && (
        <span className="text-[11px] text-text-muted bg-bg-elevated rounded-full px-2 py-[1px] font-medium font-mono">
          {count > 99 ? '99+' : count}
        </span>
      )}
    </div>
  )

  const colors = ['bg-[#2F6FED]', 'bg-[#0F7B6C]', 'bg-[#B45309]', 'bg-[#6B4FBB]', 'bg-[#9B9B9B]']

  return (
    <aside style={{ backgroundColor: 'var(--sidebar-bg)' }} className="w-[260px] min-w-[260px] border-r border-border-subtle flex flex-col h-screen overflow-y-auto overflow-x-hidden z-10">
      <div className="h-14 px-4 flex items-center gap-2.5 border-b border-border-subtle flex-shrink-0">
        <img src="/logo.png" alt="Logo" className="w-6 h-6 rounded-md object-cover flex-shrink-0 shadow-sm" />
        <span className="text-sm font-semibold tracking-tight text-text-primary">Baṣīra</span>
      </div>

      <div className="px-3 pt-5 pb-2">
        <div className="text-[11px] font-semibold text-text-muted tracking-widest uppercase px-3 pb-2.5">Principal</div>
        <NavItem icon={Rss} label="Feed" active={currentView === 'feed' && activeCategory === 'All'} count={totalCount} onClick={() => handleCategoryClick('All')} />
        <NavItem icon={Bookmark} label="Bookmarks" active={currentView === 'feed' && activeCategory === 'Bookmarks'} count={bookmarkCount} onClick={() => handleCategoryClick('Bookmarks')} />
        <NavItem icon={Sparkles} label="Digest" active={currentView === 'digest'} onClick={() => onViewChange('digest')} />
        <NavItem icon={BookOpen} label="Lit Review" active={currentView === 'litreview'} onClick={() => onViewChange('litreview')} />
        <NavItem icon={Network} label="Clusters" active={currentView === 'research'} onClick={() => onViewChange('research')} />
        <NavItem icon={Layers} label="Highlights" active={currentView === 'highlights'} onClick={() => onViewChange('highlights')} />
        <NavItem icon={Users} label="Authors" active={currentView === 'authors'} count={notifications.new_author_papers} onClick={() => handleNavClick('authors', 'authors')} />
        <NavItem icon={AlertTriangle} label="Threats" active={currentView === 'threats'} count={notifications.new_threats} onClick={() => handleNavClick('threats', 'threats')} />
        <NavItem icon={FileText} label="Writing" active={currentView === 'write'} onClick={() => onViewChange('write')} />
        <NavItem icon={Calendar} label="Conferences" active={currentView === 'conferences'} count={notifications.urgent_deadlines} onClick={() => handleNavClick('conferences', 'conferences')} />
        <NavItem icon={BookMarked} label="Bibliography" active={currentView === 'bibliography'} onClick={() => onViewChange('bibliography')} />
        <NavItem icon={Library} label="Local Notes" active={currentView === 'notes'} onClick={() => onViewChange('notes')} />
        <NavItem icon={BarChart2} label="Stats" active={currentView === 'stats'} onClick={() => onViewChange('stats')} />
      </div>

      <div className="h-px bg-border-subtle mx-5 my-3" />

      <div className="px-3 pt-2 pb-2">
        <div className="text-[11px] font-semibold text-text-muted tracking-widest uppercase px-3 pb-2.5">Feeds</div>
        {categories.filter(c => c !== 'All').map((cat, i) => {
          const count = categoryCounts.get(cat) ?? 0
          return (
            <CatItem
              key={cat}
              colorClass={colors[i % colors.length]}
              label={cat}
              active={currentView === 'feed' && activeCategory === cat}
              count={count}
              onClick={() => handleCategoryClick(cat)}
            />
          )
        })}
      </div>

      <div className="mt-auto p-4 border-t border-border-subtle space-y-1">
        <div onClick={onOpenProfile} className="flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-colors hover:bg-bg-hover group">
          <div className="w-8 h-8 rounded-full bg-text-primary text-bg-base flex items-center justify-center text-xs font-semibold flex-shrink-0 tracking-wide shadow-sm">
            AF
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-text-primary leading-tight truncate">Arona</div>
            <div className="text-xs text-text-muted leading-tight mt-0.5 truncate">Admin</div>
          </div>
          <div className="flex items-center gap-1">
            <div onClick={(e) => { e.stopPropagation(); toggleTheme() }} className="p-1.5 hover:bg-bg-elevated rounded-md text-text-muted hover:text-text-primary transition-all" title="Toggle Theme">
              {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            </div>
            <div onClick={(e) => { e.stopPropagation(); onLogout() }} className="p-1.5 hover:bg-bg-elevated rounded-md text-text-muted hover:text-danger transition-all" title="Logout">
              <LogOut size={15} />
            </div>
          </div>
        </div>
        <div onClick={onOpenFeedManager} className="flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-pointer transition-colors hover:bg-bg-hover">
          <div className="w-8 h-8 rounded-full bg-bg-surface border border-border-strong text-text-primary flex items-center justify-center flex-shrink-0 shadow-sm">
            <Settings size={16} />
          </div>
          <div>
            <div className="text-sm font-medium text-text-primary leading-tight">Feed Manager</div>
            <div className="text-xs text-text-muted leading-tight mt-0.5">Manage sources</div>
          </div>
        </div>
      </div>
    </aside>
  )
}
