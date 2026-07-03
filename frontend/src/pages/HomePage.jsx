import React, { useState, useMemo } from 'react'
import { BookOpen, ChevronLeft, Loader2, RefreshCw, Sparkles, Search, Filter } from 'lucide-react'
import VideoCard from '../components/VideoCard.jsx'
import { dlog } from '../utils/debug.js'

const CATEGORY_ICONS = {
  'דעת ותורה':     '📖',
  'הליכות עולם':   '🌍',
  'הלכה יומית':    '⚖️',
  'השיעור השבועי': '📅',
  'שיחת חולין':   '🎙️',
}

const ALL_LABEL = 'כל הקטגוריות'
const ALL_YEARS = 'כל השנים'
const WEEK_MS   = 7 * 24 * 60 * 60 * 1000

function formatSync(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString('he-IL', {
      day: 'numeric', month: 'long', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return null }
}

// Human-readable load time, e.g. "0.4 שנ'" or "3.2 שנ'".
// Cache hits are near-instant (just a sessionStorage read), so they're
// labelled separately rather than shown as "0.0 שנ'".
function formatDuration(ms, source) {
  if (ms == null) return null
  if (source === 'cache') return 'מיידי (מהזיכרון)'
  const seconds = ms / 1000
  return `${seconds.toFixed(1)} שנ'`
}

export default function HomePage({
  catalog, allVideos = [], categories = [], years = [], keywords = [],
  onCategorySelect, onSearch, lastSync, total, newCount,
  fetchMs, fetchSource,
}) {
  const entries       = Object.entries(catalog)
  const syncLabel      = formatSync(lastSync)
  const durationLabel  = formatDuration(fetchMs, fetchSource)
  const [loadingCat, setLoadingCat] = useState(null)

  // ── Quick search bar state ────────────────────────────────────────────
  const [query, setQuery]       = useState('')
  const [category, setCategory] = useState(ALL_LABEL)
  const [year, setYear]         = useState(ALL_YEARS)

  const handleSelect = (catName) => {
    if (loadingCat) return
    setLoadingCat(catName)
    setTimeout(() => onCategorySelect(catName), 350)
  }

  const handleSearch = () => {
    dlog('HomePage', 'search button clicked', { query, category, year, hasOnSearch: !!onSearch })
    onSearch?.({ query, category, year })
  }

  const handleSearchKey = (e) => { if (e.key === 'Enter') handleSearch() }

  // ── Last-week new videos ──────────────────────────────────────────────
  const recentVideos = useMemo(() => {
    if (!allVideos.length) return []
    const now = Date.now()
    return allVideos
      .filter(v => {
        if (!v.upload_date) return false
        const t = new Date(v.upload_date).getTime()
        return !isNaN(t) && now - t <= WEEK_MS
      })
      .sort((a, b) => new Date(b.upload_date) - new Date(a.upload_date))
  }, [allVideos])

  return (
    <div style={s.page}>

      {/* ── Quick search bar ─────────────────────────────────────────── */}
      <div style={s.searchPanel}>
        <div style={s.searchHeaderLabel}>
          <Search size={16} color="#B8860B" />
          <span>חיפוש שיעורים</span>
        </div>
        <div style={s.searchRow}>
          <div style={s.searchInputWrap}>
            <input
              type="text"
              placeholder="חיפוש לפי כותרת או לפי נושא בתוך השיעור…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={handleSearchKey}
              style={s.searchInput}
              dir="rtl"
              list="home-keyword-suggestions"
              autoComplete="off"
            />
            {/* Same keyword listbox as SearchPage, sourced from the
                backend's /api/keywords (see useKeywords.js). */}
            <datalist id="home-keyword-suggestions">
              {keywords.map(k => <option key={k} value={k} />)}
            </datalist>
          </div>
          <div style={s.searchSelectWrap}>
            <select value={category} onChange={e => setCategory(e.target.value)} style={s.searchSelect}>
              <option value={ALL_LABEL}>{ALL_LABEL}</option>
              {categories.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div style={s.searchSelectWrap}>
            <select value={year} onChange={e => setYear(e.target.value)} style={s.searchSelect}>
              <option value={ALL_YEARS}>{ALL_YEARS}</option>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <button style={s.searchBtn} onClick={handleSearch}>
            <Search size={15} style={{ marginLeft: 6 }} />
            חפש
          </button>
        </div>
      </div>

      {/* ── Last week's new video courses ────────────────────────────── */}
      {recentVideos.length > 0 && (
        <div style={s.section}>
          <div style={s.sectionHeader}>
            <Sparkles size={16} color="#B8860B" />
            <h2 style={s.sectionTitle}>שיעורים חדשים מהשבוע האחרון</h2>
          </div>
          <div style={s.grid}>
            {recentVideos.map(v => <VideoCard key={v.id} video={v} />)}
          </div>
        </div>
      )}

      {/* ── Category cards ────────────────────────────────────────────── */}
      <div style={s.section}>
        <div style={s.sectionHeader}>
          <BookOpen size={16} color="#B8860B" />
          <h2 style={s.sectionTitle}>קטגוריות</h2>
        </div>
        <div style={s.grid}>
          {entries.map(([catName, videos]) => {
            const isLoading = loadingCat === catName
            return (
              <button
                key={catName}
                style={{
                  ...s.card,
                  ...(isLoading ? s.cardLoading : {}),
                  ...(loadingCat && !isLoading ? s.cardDisabled : {}),
                }}
                onClick={() => handleSelect(catName)}
                disabled={!!loadingCat}
              >
                <div style={s.cardIcon}>{CATEGORY_ICONS[catName] || '📚'}</div>
                <div style={s.cardInfo}>
                  <h3 style={s.cardName}>{catName}</h3>
                  <p style={s.cardCount}>{videos.length} שיעורים</p>
                </div>
                {isLoading ? (
                  <Loader2 size={16} color="#B8860B" style={{ marginRight: 'auto', flexShrink: 0, animation: 'spin 0.8s linear infinite' }} />
                ) : (
                  <ChevronLeft size={16} color="#B8860B" style={{ marginRight: 'auto', flexShrink: 0 }} />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <div style={s.hero}>
        <div style={s.heroIcon}>
          <BookOpen size={40} color="#D4A017" strokeWidth={1.2} />
        </div>

        {/* Line 1: title + subtitle */}
        <h1 style={s.heroTitle}>הרב אהרון בוטבול שליט"א</h1>
        <p style={s.heroSub}>ספריית שיעורים מקוונת — לימוד תורה בכל זמן ובכל מקום</p>

        {/* Line 2: stats + last sync */}
        <div style={s.heroLine2}>
          <div style={s.statsRow}>
            <div style={s.statPill}>
              <span style={s.statNum}>{entries.length}</span>
              <span style={s.statLabel}>קטגוריות</span>
            </div>
            <div style={s.statDiv} />
            <div style={s.statPill}>
              <span style={s.statNum}>{total}</span>
              <span style={s.statLabel}>שיעורים</span>
            </div>
            {newCount > 0 && (
              <>
                <div style={s.statDiv} />
                <div style={{ ...s.statPill, ...s.statNew }}>
                  <Sparkles size={12} style={{ marginLeft: 4 }} />
                  <span style={s.statNum}>{newCount}</span>
                  <span style={s.statLabel}>חדשים</span>
                </div>
              </>
            )}
          </div>

          {syncLabel && (
            <div style={s.syncBadge}>
              <RefreshCw size={11} style={{ marginLeft: 5, flexShrink: 0 }} />
              עודכן לאחרונה: {syncLabel}
              {durationLabel && (
                <span style={s.syncDuration}> · זמן טעינה: {durationLabel}</span>
              )}
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

const s = {
  page: { padding: '32px 0 60px' },

  /* Quick search bar */
  searchPanel: {
    background: '#FDFBF7',
    border: '1px solid rgba(184,134,11,.2)',
    borderRadius: 12,
    padding: '16px 20px',
    marginBottom: 40,
    boxShadow: '0 2px 12px rgba(28,22,16,.07)',
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
  searchBtn: {
    background: 'linear-gradient(135deg, #1A3A5C, #0E2440)',
    color: '#F5F0E8',
    border: 'none',
    borderRadius: 8,
    padding: '10px 22px',
    fontFamily: "'Heebo', sans-serif",
    fontSize: '.88rem',
    fontWeight: 600,
    display: 'flex',
    alignItems: 'center',
    whiteSpace: 'nowrap',
    boxShadow: '0 2px 8px rgba(14,36,64,.3)',
    cursor: 'pointer',
    flexShrink: 0,
  },

  /* Sections */
  section: { marginBottom: 44 },
  sectionHeader: {
    display: 'flex', alignItems: 'center', gap: 8,
    marginBottom: 16,
  },
  sectionTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.15rem', fontWeight: 700, color: '#1C1610', margin: 0,
  },

  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 16,
  },
  card: {
    background: '#FDFBF7',
    border: '1.5px solid rgba(184,134,11,.18)',
    borderRadius: 12, padding: '18px 20px',
    cursor: 'pointer', display: 'flex', alignItems: 'center',
    gap: 14, textAlign: 'right', transition: 'all .2s',
    boxShadow: '0 2px 8px rgba(28,22,16,.06)',
  },
  cardIcon:  { fontSize: '1.8rem', flexShrink: 0 },
  cardInfo:  { flex: 1, minWidth: 0 },
  cardLoading: { opacity: 0.85, cursor: 'default' },
  cardDisabled: { opacity: 0.5, cursor: 'default' },
  cardName: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1rem', fontWeight: 700, color: '#1C1610', marginBottom: 4,
  },
  cardCount: { fontSize: '.75rem', color: '#6B5E47' },

  /* Hero (moved to bottom, 2-line layout) */
  hero: {
    textAlign: 'center',
    padding: '40px 20px',
    background: 'linear-gradient(135deg, rgba(26,58,92,.06) 0%, rgba(184,134,11,.06) 100%)',
    borderRadius: 16,
    border: '1px solid rgba(184,134,11,.15)',
  },
  heroIcon: {
    width: 72, height: 72, borderRadius: '50%',
    background: 'linear-gradient(135deg, #1A3A5C, #0E2440)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    margin: '0 auto 16px',
    boxShadow: '0 4px 20px rgba(26,58,92,.3)',
  },
  heroTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '2.2rem', fontWeight: 900, color: '#1C1610', marginBottom: 10,
  },
  heroSub: {
    fontSize: '.95rem', color: '#6B5E47',
    maxWidth: 440, margin: '0 auto 24px', lineHeight: 1.6,
  },

  heroLine2: {
    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16,
  },
  statsRow: {
    display: 'inline-flex', alignItems: 'center', gap: 20,
    background: 'rgba(184,134,11,.1)',
    border: '1px solid rgba(184,134,11,.25)',
    borderRadius: 50, padding: '10px 28px',
  },
  statPill: { textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center' },
  statNew:  { flexDirection: 'row', gap: 4, color: '#B8860B' },
  statNum: {
    display: 'block',
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.4rem', fontWeight: 700, color: '#1A3A5C',
  },
  statLabel: { fontSize: '.72rem', color: '#6B5E47' },
  statDiv:   { width: 1, height: 32, background: 'rgba(184,134,11,.3)' },

  syncBadge: {
    display: 'inline-flex', alignItems: 'center',
    fontSize: '.72rem', color: '#6B5E47',
    background: 'rgba(184,134,11,.08)',
    border: '1px solid rgba(184,134,11,.2)',
    borderRadius: 20, padding: '4px 12px',
  },
  syncDuration: {
    color: '#B8860B',
    fontWeight: 600,
  },
}
