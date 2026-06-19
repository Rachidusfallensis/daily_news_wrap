import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'

interface NoteListItem {
  id: number
  filename: string
  title: string | null
  bibtex_key: string | null
  theme: string | null
  cluster: string | null
  last_modified: string
}

interface NoteDetail extends NoteListItem {
  content_md: string
}

export default function NotesView() {
  const [notes, setNotes] = useState<NoteListItem[]>([])
  const [selectedNoteId, setSelectedNoteId] = useState<number | null>(null)
  const [noteContent, setNoteContent] = useState<NoteDetail | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    fetch('/api/notes', { credentials: 'include' })
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setNotes(data)
        }
      })
      .catch(console.error)
  }, [])

  useEffect(() => {
    if (selectedNoteId) {
      setNoteContent(null)
      fetch(`/api/notes/${selectedNoteId}`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => setNoteContent(data))
        .catch(console.error)
    } else {
      setNoteContent(null)
    }
  }, [selectedNoteId])

  const filteredNotes = notes.filter(n => {
    const q = search.toLowerCase()
    return (
      (n.title && n.title.toLowerCase().includes(q)) ||
      (n.theme && n.theme.toLowerCase().includes(q)) ||
      (n.bibtex_key && n.bibtex_key.toLowerCase().includes(q)) ||
      (n.cluster && n.cluster.toLowerCase().includes(q)) ||
      n.filename.toLowerCase().includes(q)
    )
  })

  const groupedNotes = filteredNotes.reduce((acc, note) => {
    const cluster = note.cluster || 'Unclustered'
    if (!acc[cluster]) acc[cluster] = []
    acc[cluster].push(note)
    return acc
  }, {} as Record<string, NoteListItem[]>)

  const sortedClusters = Object.keys(groupedNotes).sort((a, b) => {
    if (a === 'Unclustered') return 1
    if (b === 'Unclustered') return -1
    return a.localeCompare(b)
  })

  return (
    <div className="flex w-full h-full">
      {/* Left Sidebar List */}
      <div className="w-[300px] border-r border-border-subtle flex flex-col h-full bg-bg-surface flex-shrink-0">
        <div className="p-3 border-b border-border-subtle">
          <input
            type="text"
            placeholder="Search notes..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-bg-base border border-border-default rounded px-3 py-1.5 text-sm outline-none focus:border-brand-primary transition-colors text-text-primary"
          />
        </div>
        <div className="flex-1 overflow-y-auto">
          {sortedClusters.map(cluster => (
            <div key={cluster}>
              <div className="px-3 py-1.5 text-[11px] font-bold text-text-muted uppercase tracking-wider bg-bg-base border-b border-border-subtle sticky top-0 z-10 shadow-sm">
                {cluster}
              </div>
              {groupedNotes[cluster].map(n => (
                <div
                  key={n.id}
                  onClick={() => setSelectedNoteId(n.id)}
                  className={`p-3 border-b border-border-subtle cursor-pointer transition-colors ${
                    selectedNoteId === n.id ? 'bg-bg-elevated border-l-2 border-l-accent-blue' : 'hover:bg-bg-hover border-l-2 border-l-transparent'
                  }`}
                >
                  <div className="text-sm font-semibold text-text-primary leading-tight line-clamp-2">
                    {n.title || n.filename}
                  </div>
                  <div className="text-[11px] text-text-muted mt-2 flex flex-wrap gap-1">
                    {n.theme && <span className="px-1.5 py-0.5 bg-accent-blue/10 text-accent-blue rounded">{n.theme}</span>}
                    {n.bibtex_key && <span className="px-1.5 py-0.5 bg-bg-base border border-border-default rounded font-mono">{n.bibtex_key}</span>}
                  </div>
                </div>
              ))}
            </div>
          ))}
          {filteredNotes.length === 0 && (
            <div className="p-4 text-center text-sm text-text-muted">No notes found.</div>
          )}
        </div>
      </div>

      {/* Right Content */}
      <div className="flex-1 overflow-y-auto bg-bg-base p-8">
        {noteContent ? (
          <div className="max-w-4xl mx-auto reader-content">
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
            >
              {noteContent.content_md}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-text-muted">
            {selectedNoteId ? 'Loading...' : 'Select a note to read'}
          </div>
        )}
      </div>
    </div>
  )
}
