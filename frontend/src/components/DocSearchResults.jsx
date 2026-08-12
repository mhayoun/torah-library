import React from 'react'
import { FileText, ExternalLink } from 'lucide-react'

// Renders one hit from GET /api/search-docs: the matching line (3 lines
// of context above/below, highlighted) plus a direct link to the PDF/DOCX
// and to the video itself — deliberately compact (no embedded VideoCard/
// player here), since this is meant to sit above the regular video
// results as a fast "jump straight to the paragraph that matched" list.
function DocSearchHit({ result, video }) {
  const docLink = video.documents?.pdf || video.documents?.docx || null
  const lines = result.snippet.split('\n')

  let consumed = 0
  const renderedLines = lines.map((line, i) => {
    const lineStart = consumed
    const lineEnd = lineStart + line.length
    consumed = lineEnd + 1 // +1 for the '\n' separator consumed between lines

    const hasMatch = result.match_offset >= lineStart && result.match_offset < lineEnd
    if (!hasMatch) {
      return <span key={i}>{line}<br /></span>
    }
    const localOffset = result.match_offset - lineStart
    const before = line.slice(0, localOffset)
    const match = line.slice(localOffset, localOffset + result.match_len)
    const after = line.slice(localOffset + result.match_len)
    return (
      <span key={i}>
        {before}<mark style={styles.highlight}>{match}</mark>{after}<br />
      </span>
    )
  })

  return (
    <div style={styles.item}>
      <div style={styles.videoTitle}>{video.title}</div>
      <p style={styles.snippet} dir="rtl">{renderedLines}</p>
      <div style={styles.links}>
        {docLink && (
          <a href={docLink.view_url} target="_blank" rel="noopener noreferrer" style={styles.link}>
            <FileText size={13} style={{ marginLeft: 6 }} />
            פתח מסמך
          </a>
        )}
        <a href={video.url} target="_blank" rel="noopener noreferrer" style={styles.link}>
          <ExternalLink size={13} style={{ marginLeft: 6 }} />
          צפה בשיעור
        </a>
      </div>
    </div>
  )
}

export default function DocSearchResults({ results, loading, allVideos }) {
  if (loading) {
    return (
      <div style={styles.section}>
        <span style={styles.count}>מחפש בתוך המסמכים…</span>
      </div>
    )
  }

  if (!results || results.length === 0) return null

  const hits = results
    .map(r => ({ result: r, video: allVideos.find(v => v.id === r.video_id) }))
    .filter(h => h.video)

  if (hits.length === 0) return null

  return (
    <div style={styles.section}>
      <div style={styles.header}>
        <span style={styles.count}>{hits.length} תוצאות נמצאו בתוך מסמכי השיעור (PDF/Word)</span>
      </div>
      <div style={styles.list}>
        {hits.map(({ result, video }) => (
          <DocSearchHit key={result.video_id} result={result} video={video} />
        ))}
      </div>
    </div>
  )
}

const styles = {
  section: { marginBottom: 32 },
  header: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: 16,
    padding: '0 4px',
  },
  count: {
    fontSize: '.85rem',
    color: '#6B5E47',
    fontFamily: "'Heebo', sans-serif",
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 14,
  },
  item: {
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
    background: '#F5F0E8',
    border: '1px solid rgba(184,134,11,.15)',
    borderRadius: 10,
    padding: 14,
  },
  videoTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '.9rem',
    fontWeight: 700,
    color: '#1C1610',
    textAlign: 'right',
  },
  snippet: {
    margin: 0,
    fontSize: '.83rem',
    lineHeight: 1.8,
    color: '#3D3323',
    fontFamily: "'Heebo', sans-serif",
  },
  highlight: {
    background: '#FFE066',
    color: '#1C1610',
    padding: '1px 3px',
    borderRadius: 3,
    fontWeight: 600,
  },
  links: {
    display: 'flex',
    gap: 10,
  },
  link: {
    display: 'inline-flex',
    alignItems: 'center',
    background: 'rgba(184,134,11,.12)',
    border: '1px solid rgba(184,134,11,.35)',
    color: '#8B6500',
    fontSize: '.78rem',
    fontWeight: 600,
    fontFamily: "'Heebo', sans-serif",
    padding: '5px 12px',
    borderRadius: 6,
  },
}
