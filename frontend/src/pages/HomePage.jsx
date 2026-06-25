import React from 'react'
import { BookOpen, ChevronLeft, RefreshCw, Sparkles } from 'lucide-react'

const CATEGORY_ICONS = {
  'דעת ותורה':     '📖',
  'הליכות עולם':   '🌍',
  'הלכה יומית':    '⚖️',
  'השיעור השבועי': '📅',
  'שיחת חולין':   '🎙️',
}

function formatSync(iso) {
  if (!iso) return null
  try {
    return new Date(iso).toLocaleString('he-IL', {
      day: 'numeric', month: 'long', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return null }
}

export default function HomePage({ catalog, onCategorySelect, lastSync, total, newCount }) {
  const entries   = Object.entries(catalog)
  const syncLabel = formatSync(lastSync)

  return (
    <div style={s.page}>

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <div style={s.hero}>
        <div style={s.heroIcon}>
          <BookOpen size={40} color="#D4A017" strokeWidth={1.2} />
        </div>
        <h1 style={s.heroTitle}>מאגר שיעורי תורה</h1>
        <p style={s.heroSub}>ספריית שיעורים מקוונת — לימוד תורה בכל זמן ובכל מקום</p>

        {/* Stats row */}
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

        {/* Last sync badge */}
        {syncLabel && (
          <div style={s.syncBadge}>
            <RefreshCw size={11} style={{ marginLeft: 5, flexShrink: 0 }} />
            עודכן לאחרונה: {syncLabel}
          </div>
        )}
      </div>

      {/* ── Category cards ────────────────────────────────────────── */}
      <div style={s.grid}>
        {entries.map(([catName, videos]) => (
          <button key={catName} style={s.card} onClick={() => onCategorySelect(catName)}>
            <div style={s.cardIcon}>{CATEGORY_ICONS[catName] || '📚'}</div>
            <div style={s.cardInfo}>
              <h3 style={s.cardName}>{catName}</h3>
              <p style={s.cardCount}>{videos.length} שיעורים</p>
            </div>
            <ChevronLeft size={16} color="#B8860B" style={{ marginRight: 'auto', flexShrink: 0 }} />
          </button>
        ))}
      </div>
    </div>
  )
}

const s = {
  page: { padding: '40px 0 60px' },

  hero: {
    textAlign: 'center',
    marginBottom: 48,
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
    marginTop: 16, fontSize: '.72rem', color: '#6B5E47',
    background: 'rgba(184,134,11,.08)',
    border: '1px solid rgba(184,134,11,.2)',
    borderRadius: 20, padding: '4px 12px',
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
  cardName: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1rem', fontWeight: 700, color: '#1C1610', marginBottom: 4,
  },
  cardCount: { fontSize: '.75rem', color: '#6B5E47' },
}
