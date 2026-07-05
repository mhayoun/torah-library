import React, { useState, useMemo } from 'react'
import { Search } from 'lucide-react'
import VideoCard from '../components/VideoCard.jsx'

const ALL_YEARS = 'כל השנים'
const TOPIC_CATEGORY = 'הלכה יומית'

export default function CategoryPage({ category, playlists: videos, years = [], keywords = [] }) {
  // "playlists" prop name kept for App.jsx compatibility — it now holds a flat video array

  // Only הלכה יומית videos go through the backend's transcript pipeline and
  // get a `topics` array — for every other category there's no "subject
  // inside the lesson" to search by, so we don't offer topic search or
  // show the keyword-suggestions dropdown there (both would be misleading).
  const hasTopics = category === TOPIC_CATEGORY

  // ── Search bar state (same idea as HomePage's quick-search, but scoped
  // to this category — no category selector needed since we're already
  // inside one) ────────────────────────────────────────────────────────
  const [query, setQuery] = useState('')
  const [year, setYear]   = useState(ALL_YEARS)

  const handleSearchKey = (e) => { if (e.key === 'Enter') e.preventDefault() }

  const filtered = useMemo(() => {
    const q = query.trim()
    if (!q && year === ALL_YEARS) return videos.map(v => ({ video: v, topicMatches: [] }))

    return videos
      .map(v => {
        // Topics (keyword + start position) only exist on הלכה יומית videos
        // that have been processed by the backend's transcript pipeline.
        const topicMatches = (q && hasTopics && Array.isArray(v.topics))
          ? v.topics.filter(t => t.keyword && t.keyword.includes(q))
          : []

        const matchQuery = !q ||
          v.title?.includes(q) ||
          v.playlist?.includes(q) ||
          topicMatches.length > 0
        const matchYear = year === ALL_YEARS || v.hebraic_year === year

        if (!matchQuery || !matchYear) return null
        return { video: v, topicMatches }
      })
      .filter(Boolean)
  }, [videos, query, year, hasTopics])

  const topicMatchCount = useMemo(
    () => filtered.filter(r => r.topicMatches.length > 0).length,
    [filtered]
  )

  return (
    <div style={styles.page}>
      <div style={styles.headerRow}>
        {/* Title block — plain style (no card), first in DOM so it lands
            on the right in RTL */}
        <div style={styles.titleBlock}>
          <h2 style={styles.catTitle}>{category}</h2>
          <span style={styles.catMeta}>{videos.length} שיעורים</span>
          <div style={styles.ornament} />
        </div>

        {/* ── Search bar ─────────────────────────────────────────────── */}
        <div style={styles.searchPanel}>
          <div style={styles.searchHeaderLabel}>
            <Search size={16} color="#B8860B" />
            <span>חיפוש בתוך {category}</span>
          </div>
          <div style={styles.searchRow}>
            <div style={styles.searchInputWrap}>
              <input
                type="text"
                placeholder={hasTopics
                  ? 'חיפוש לפי כותרת או לפי נושא בתוך השיעור…'
                  : 'חיפוש לפי כותרת…'}
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={handleSearchKey}
                style={styles.searchInput}
                dir="rtl"
                list={hasTopics ? `category-keyword-suggestions-${category}` : undefined}
                autoComplete="off"
              />
              {/* Same keyword listbox as Home/SearchPage, sourced from the
                  backend's /api/keywords (see useKeywords.js) — only
                  relevant for הלכה יומית, the sole category with per-topic
                  transcript keywords. */}
              {hasTopics && (
                <datalist id={`category-keyword-suggestions-${category}`}>
                  {keywords.map(k => <option key={k} value={k} />)}
                </datalist>
              )}
            </div>
            <div style={styles.searchSelectWrap}>
              <select value={year} onChange={e => setYear(e.target.value)} style={styles.searchSelect}>
                <option value={ALL_YEARS}>{ALL_YEARS}</option>
                {years.map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
          </div>
          {(query.trim() || year !== ALL_YEARS) && (
            <div style={styles.resultsSummary}>
              {filtered.length} שיעורים נמצאו
              {topicMatchCount > 0 && (
                <span style={styles.resultSub}> · {topicMatchCount} מתוכם לפי נושא בתוך השיעור</span>
              )}
            </div>
          )}
        </div>
      </div>

      {filtered.length === 0
        ? <p style={styles.empty}>
            {query.trim() || year !== ALL_YEARS
              ? 'לא נמצאו תוצאות. נסו מילות חיפוש אחרות.'
              : 'אין שיעורים בקטגוריה זו'}
          </p>
        : (
          <div style={styles.grid}>
            {filtered.map(({ video: v, topicMatches }) => (
              <VideoCard key={v.id} video={{ ...v, category }} matchedTopics={topicMatches} />
            ))}
          </div>
        )
      }
    </div>
  )
}

const styles = {
  page: { padding: '32px 0 60px' },

  /* Title block + search panel sit side by side. Title block is listed
     first in DOM, which — under dir="rtl" — places it on the right
     (inline-start), matching the target layout. flexWrap lets the title
     block drop to its own full-width row on narrow/mobile screens
     instead of squeezing the search bar. Row is center-aligned (not
     stretched) so the title block keeps its natural compact height
     instead of being stretched to match the taller search card, which
     would leave an awkward gap before the ornament line. */
  headerRow: {
    display: 'flex',
    gap: 16,
    marginBottom: 32,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  titleBlock: {
    display: 'flex',
    flexDirection: 'column',
    textAlign: 'right',
    flex: '0 0 auto',
    minWidth: 200,
  },
  catTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.5rem',
    fontWeight: 900,
    color: '#1C1610',
    marginBottom: 4,
    whiteSpace: 'nowrap',
  },
  catMeta: { fontSize: '.8rem', color: '#6B5E47' },
  ornament: {
    marginTop: 12,
    marginLeft: 'auto',
    marginRight: 0,
    width: '33%',
    minWidth: 160,
    height: 2,
    background: 'linear-gradient(to left, transparent, #B8860B 15%, #D4A017 50%, #B8860B 85%, transparent)',
    borderRadius: 2,
  },

  /* Search bar (mirrors HomePage's searchPanel) */
  searchPanel: {
    background: '#FDFBF7',
    border: '1px solid rgba(184,134,11,.2)',
    borderRadius: 12,
    padding: '16px 20px',
    boxShadow: '0 2px 12px rgba(28,22,16,.07)',
    flex: '1 1 320px',
  },
  searchHeaderLabel: {
    display: 'flex', alignItems: 'center', gap: 8,
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '.95rem', fontWeight: 600, color: '#1C1610',
    marginBottom: 12,
  },
  searchRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    flexWrap: 'wrap',
  },
  searchInputWrap: { flex: '2 1 220px' },
  searchInput: {
    width: '100%',
    padding: '10px 14px',
    border: '1.5px solid #D4C5A0',
    borderRadius: 8,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.88rem',
    background: '#FDFBF7',
    color: '#1C1610',
    outline: 'none',
    direction: 'rtl',
  },
  searchSelectWrap: { flex: '1 1 150px' },
  searchSelect: {
    width: '100%',
    padding: '10px 12px',
    border: '1.5px solid #D4C5A0',
    borderRadius: 8,
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.85rem',
    background: '#FDFBF7',
    color: '#1C1610',
    direction: 'rtl',
    cursor: 'pointer',
    outline: 'none',
  },
  resultsSummary: {
    marginTop: 12,
    fontSize: '.8rem',
    color: '#6B5E47',
    fontFamily: "'Heebo', sans-serif",
  },
  resultSub: {
    color: '#B8860B',
    fontWeight: 600,
  },

  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: 16,
  },
  empty: {
    padding: '40px 0',
    color: '#6B5E47',
    fontSize: '.9rem',
    fontFamily: "'Heebo', sans-serif",
  },
}
