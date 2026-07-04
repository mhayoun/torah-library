import React, { useState } from 'react'
import { Play, Clock, Eye, Calendar, X, ExternalLink, BookOpen, Tag, FileText, Loader2, ChevronDown, ChevronUp } from 'lucide-react'

function formatDate(iso) {
  if (!iso) return null
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('he-IL', { year: 'numeric', month: 'long', day: 'numeric' })
  } catch { return null }
}

function formatViews(n) {
  if (n == null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`
  return String(n)
}

// Formats a position in seconds as m:ss (e.g. 137 -> "2:17"), for the
// jump-to-topic chips and the modal's topic list.
function formatTime(seconds) {
  if (seconds == null || isNaN(seconds)) return ''
  const total = Math.floor(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

// video.topics  — full list of {keyword, start} markers on this video
//                 (only present for הלכה יומית videos with transcript_status
//                 "done"), used to render the "jump within this lesson" list
//                 inside the modal.
// matchedTopics — the subset of those topics that matched the current
//                 search keyword (passed in from SearchPage/HomePage),
//                 rendered as chips on the card itself so the person can
//                 jump straight to that moment without opening the modal
//                 first.
export default function VideoCard({ video, matchedTopics = [] }) {
  const [modalOpen, setModalOpen] = useState(false)
  const [startAt, setStartAt] = useState(null) // seconds to start the embed at, or null = beginning

  // Transcript panel — fetched lazily from GET /api/transcript/{id} only
  // when the person actually clicks "show transcript" inside the modal,
  // never on page load. `transcript` holds { video_id, chunks, updated }
  // once loaded; `transcriptChecked` distinguishes "haven't tried yet"
  // from "tried and got nothing" so we don't refetch on every toggle.
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [transcript, setTranscript] = useState(null)
  const [transcriptLoading, setTranscriptLoading] = useState(false)
  const [transcriptError, setTranscriptError] = useState(null)
  const [transcriptChecked, setTranscriptChecked] = useState(false)

  const openAt = (seconds = null) => {
    setStartAt(seconds)
    setModalOpen(true)
  }

  const toggleTranscript = () => {
    const willOpen = !transcriptOpen
    setTranscriptOpen(willOpen)
    if (willOpen && !transcriptChecked && video.id) {
      setTranscriptLoading(true)
      setTranscriptError(null)
      fetch(`/api/transcript/${video.id}`)
        .then(r => {
          if (r.status === 404) { setTranscript(null); return null }
          if (!r.ok) throw new Error(`Erreur serveur : ${r.status}`)
          return r.json()
        })
        .then(data => { if (data) setTranscript(data) })
        .catch(e => setTranscriptError(e.message))
        .finally(() => {
          setTranscriptLoading(false)
          setTranscriptChecked(true)
        })
    }
  }

  const closeModal = () => {
    setModalOpen(false)
    setTranscriptOpen(false)
  }

  const thumb = video.thumbnail ||
    (video.id ? `https://img.youtube.com/vi/${video.id}/mqdefault.jpg` : null)

  const allTopics = Array.isArray(video.topics) ? video.topics : []

  return (
    <>
      <article style={styles.card} onClick={() => openAt(null)}>
        {/* Thumbnail */}
        <div style={styles.thumbWrap}>
          {thumb
            ? <img src={thumb} alt={video.title} style={styles.thumb} loading="lazy" />
            : <div style={styles.thumbPlaceholder}><BookOpen size={32} color="#B8860B" /></div>
          }
          <div style={styles.playOverlay}>
            <div style={styles.playBtn}><Play size={20} fill="#F5F0E8" color="#F5F0E8" /></div>
          </div>
          {video.duration && video.duration !== 'Unknown' && (
            <span style={styles.durationBadge}>{video.duration}</span>
          )}
        </div>

        {/* Meta */}
        <div style={styles.body}>
          <div style={styles.topRow}>
            <div style={styles.category}>{video.category}</div>
            {video.hebraic_year && (
              <span style={styles.yearBadge}>{video.hebraic_year}</span>
            )}
          </div>
          <h3 style={styles.title}>{video.title}</h3>
          <div style={styles.playlist}>{video.playlist}</div>

          <div style={styles.meta}>
            {video.upload_date && (
              <span style={styles.metaItem}>
                <Calendar size={11} style={{ marginLeft: 3 }} />
                {formatDate(video.upload_date)}
              </span>
            )}
            {video.view_count != null && (
              <span style={styles.metaItem}>
                <Eye size={11} style={{ marginLeft: 3 }} />
                {formatViews(video.view_count)} צפיות
              </span>
            )}
          </div>

          {/* Matched topic chips — clicking one jumps straight into the
              video, starting playback at that exact position. */}
          {matchedTopics.length > 0 && (
            <div style={styles.topicsRow} onClick={e => e.stopPropagation()}>
              {matchedTopics.map((t, i) => (
                <button
                  key={i}
                  style={styles.topicChip}
                  onClick={() => openAt(t.start)}
                  title="לחצו כדי לצפות מנקודה זו בשיעור"
                >
                  <Clock size={10} style={{ marginLeft: 4, flexShrink: 0 }} />
                  {formatTime(t.start)} · {t.keyword}
                </button>
              ))}
            </div>
          )}
        </div>
      </article>

      {/* Modal */}
      {modalOpen && (
        <div style={styles.backdrop} onClick={closeModal}>
          <div style={styles.modal} onClick={e => e.stopPropagation()}>
            <button style={styles.closeBtn} onClick={closeModal}>
              <X size={20} />
            </button>
            <h2 style={styles.modalTitle}>{video.title}</h2>
            <div style={styles.categoryTag}>{video.category}</div>

            {/* YouTube embed — starts at `startAt` seconds and autoplays
                when opened via a topic jump; starts from the beginning
                (paused, per YouTube's default) when opened normally. */}
            {video.id && (
              <div style={styles.embedWrap}>
                <iframe
                  key={startAt ?? 'start'}
                  src={
                    `https://www.youtube.com/embed/${video.id}?rel=0&hl=iw` +
                    (startAt ? `&start=${Math.floor(startAt)}&autoplay=1` : '')
                  }
                  title={video.title}
                  style={styles.embed}
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                  allowFullScreen
                />
              </div>
            )}

            {/* Full topic list for this lesson — lets the person jump
                around within the video even outside of a search. */}
            {allTopics.length > 0 && (
              <div style={styles.topicsSection}>
                <div style={styles.topicsSectionHeader}>
                  <Tag size={13} color="#B8860B" />
                  <span>נושאים בשיעור זה</span>
                </div>
                <div style={styles.topicsList}>
                  {allTopics.map((t, i) => (
                    <button
                      key={i}
                      style={{
                        ...styles.topicListItem,
                        ...(startAt === t.start ? styles.topicListItemActive : {}),
                      }}
                      onClick={() => setStartAt(t.start)}
                    >
                      <span style={styles.topicTime}>{formatTime(t.start)}</span>
                      <span>{t.keyword}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Transcript panel — lazy-loaded on demand from
                GET /api/transcript/{id} only when the person clicks
                this button; not fetched on page load or modal open. */}
            <div style={styles.transcriptSection}>
              <button style={styles.transcriptToggle} onClick={toggleTranscript}>
                <FileText size={14} color="#B8860B" />
                <span>תמלול השיעור</span>
                {transcriptOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>

              {transcriptOpen && (
                <div style={styles.transcriptBody}>
                  {transcriptLoading && (
                    <div style={styles.transcriptStatus}>
                      <Loader2 size={16} className="spin" />
                      <span>טוען תמלול…</span>
                    </div>
                  )}
                  {!transcriptLoading && transcriptError && (
                    <div style={styles.transcriptStatus}>שגיאה בטעינת התמלול: {transcriptError}</div>
                  )}
                  {!transcriptLoading && !transcriptError && transcriptChecked && !transcript && (
                    <div style={styles.transcriptStatus}>אין תמלול זמין לשיעור זה</div>
                  )}
                  {!transcriptLoading && transcript?.chunks?.length > 0 && (
                    <div style={styles.transcriptChunks}>
                      {transcript.chunks.map((c, i) => (
                        <div
                          key={i}
                          style={{
                            ...styles.transcriptChunk,
                            ...(startAt === c.start ? styles.transcriptChunkActive : {}),
                          }}
                        >
                          <button
                            style={styles.transcriptChunkHeader}
                            onClick={() => setStartAt(c.start)}
                            title="לחצו כדי לצפות מנקודה זו בשיעור"
                          >
                            <span style={styles.topicTime}>{formatTime(c.start)}</span>
                            <span>{c.keyword || 'פתיחה'}</span>
                          </button>
                          <p style={styles.transcriptChunkText}>{c.text}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={styles.modalMeta}>
              {video.hebraic_year && (
                <div style={styles.modalMetaItem}>
                  <BookOpen size={14} />
                  <span>{video.hebraic_year}</span>
                </div>
              )}
              {video.playlist && (
                <div style={styles.modalMetaItem}>
                  <BookOpen size={14} />
                  <span>{video.playlist}</span>
                </div>
              )}
              {video.upload_date && (
                <div style={styles.modalMetaItem}>
                  <Calendar size={14} />
                  <span>{formatDate(video.upload_date)}</span>
                </div>
              )}
              {video.duration && video.duration !== 'Unknown' && (
                <div style={styles.modalMetaItem}>
                  <Clock size={14} />
                  <span>{video.duration}</span>
                </div>
              )}
              {video.view_count != null && (
                <div style={styles.modalMetaItem}>
                  <Eye size={14} />
                  <span>{formatViews(video.view_count)} צפיות</span>
                </div>
              )}
            </div>

            <a
              href={startAt ? `${video.url}&t=${Math.floor(startAt)}s` : video.url}
              target="_blank"
              rel="noopener noreferrer"
              style={styles.ytLink}
            >
              <ExternalLink size={14} style={{ marginLeft: 6 }} />
              פתח ביוטיוב
            </a>
          </div>
        </div>
      )}
    </>
  )
}

const styles = {
  card: {
    background: '#FDFBF7',
    borderRadius: 10,
    overflow: 'hidden',
    boxShadow: '0 2px 12px rgba(28,22,16,.08)',
    border: '1px solid rgba(184,134,11,.15)',
    cursor: 'pointer',
    transition: 'transform .2s, box-shadow .2s',
    display: 'flex',
    flexDirection: 'column',
  },
  topicsRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 8,
  },
  topicChip: {
    display: 'inline-flex',
    alignItems: 'center',
    background: 'rgba(184,134,11,.12)',
    border: '1px solid rgba(184,134,11,.35)',
    color: '#8B6500',
    fontSize: '.7rem',
    fontFamily: "'Heebo', sans-serif",
    fontWeight: 600,
    padding: '4px 9px',
    borderRadius: 20,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    maxWidth: '100%',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  topicsSection: {
    marginBottom: 20,
    background: '#F5F0E8',
    border: '1px solid rgba(184,134,11,.15)',
    borderRadius: 8,
    padding: '12px 14px',
  },
  topicsSectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: '.8rem',
    fontWeight: 600,
    color: '#1C1610',
    fontFamily: "'Heebo', sans-serif",
    marginBottom: 10,
  },
  topicsList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  topicListItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    background: 'transparent',
    border: 'none',
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: '.82rem',
    fontFamily: "'Heebo', sans-serif",
    color: '#3D3323',
    textAlign: 'right',
    cursor: 'pointer',
    transition: 'background .15s',
  },
  topicListItemActive: {
    background: 'rgba(184,134,11,.18)',
    color: '#8B6500',
    fontWeight: 600,
  },
  topicTime: {
    fontFamily: "'Heebo', sans-serif",
    fontVariantNumeric: 'tabular-nums',
    color: '#1A3A5C',
    fontWeight: 700,
    fontSize: '.78rem',
    flexShrink: 0,
    minWidth: 36,
  },
  transcriptSection: {
    marginBottom: 20,
    border: '1px solid rgba(184,134,11,.15)',
    borderRadius: 8,
    overflow: 'hidden',
  },
  transcriptToggle: {
    width: '100%',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: '#F5F0E8',
    border: 'none',
    padding: '10px 14px',
    fontSize: '.82rem',
    fontWeight: 600,
    color: '#1C1610',
    fontFamily: "'Heebo', sans-serif",
    cursor: 'pointer',
  },
  transcriptBody: {
    padding: '12px 14px',
    background: '#FDFBF7',
    maxHeight: 320,
    overflowY: 'auto',
  },
  transcriptStatus: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: '.8rem',
    color: '#6B5E47',
    fontFamily: "'Heebo', sans-serif",
    padding: '4px 2px',
  },
  transcriptChunks: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  transcriptChunk: {
    borderRadius: 6,
    padding: '6px 8px',
    transition: 'background .15s',
  },
  transcriptChunkActive: {
    background: 'rgba(184,134,11,.1)',
  },
  transcriptChunkHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    background: 'transparent',
    border: 'none',
    padding: '2px 0 4px',
    fontSize: '.8rem',
    fontWeight: 600,
    color: '#8B6500',
    fontFamily: "'Heebo', sans-serif",
    cursor: 'pointer',
    textAlign: 'right',
    width: '100%',
  },
  transcriptChunkText: {
    margin: 0,
    fontSize: '.82rem',
    lineHeight: 1.7,
    color: '#3D3323',
    fontFamily: "'Heebo', sans-serif",
  },
  thumbWrap: {
    position: 'relative',
    aspectRatio: '16/9',
    background: '#EAE2D0',
    overflow: 'hidden',
  },
  thumb: {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    display: 'block',
  },
  thumbPlaceholder: {
    width: '100%',
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#EAE2D0',
  },
  playOverlay: {
    position: 'absolute',
    inset: 0,
    background: 'rgba(14,36,64,.4)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    opacity: 0,
    transition: 'opacity .2s',
  },
  playBtn: {
    width: 48,
    height: 48,
    borderRadius: '50%',
    background: 'rgba(184,134,11,.9)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 2px 12px rgba(0,0,0,.4)',
  },
  durationBadge: {
    position: 'absolute',
    bottom: 8,
    left: 8,
    background: 'rgba(14,36,64,.85)',
    color: '#F5F0E8',
    fontSize: '.72rem',
    padding: '2px 6px',
    borderRadius: 4,
    fontFamily: "'Heebo', sans-serif",
  },
  body: {
    padding: '14px 16px 16px',
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  topRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  category: {
    fontSize: '.68rem',
    fontWeight: 600,
    color: '#B8860B',
    letterSpacing: '.05em',
    textTransform: 'uppercase',
  },
  yearBadge: {
    fontSize: '.7rem',
    fontWeight: 600,
    color: '#1A3A5C',
    background: 'rgba(26,58,92,.1)',
    padding: '2px 8px',
    borderRadius: 20,
    whiteSpace: 'nowrap',
    flexShrink: 0,
  },
  title: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '.95rem',
    fontWeight: 600,
    color: '#1C1610',
    lineHeight: 1.4,
    flex: 1,
  },
  playlist: {
    fontSize: '.75rem',
    color: '#6B5E47',
  },
  meta: {
    display: 'flex',
    gap: 12,
    flexWrap: 'wrap',
    marginTop: 4,
  },
  metaItem: {
    display: 'flex',
    alignItems: 'center',
    fontSize: '.7rem',
    color: '#6B5E47',
  },
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(14,36,64,.75)',
    backdropFilter: 'blur(4px)',
    zIndex: 999,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  modal: {
    background: '#FDFBF7',
    borderRadius: 16,
    padding: 28,
    maxWidth: 760,
    width: '100%',
    maxHeight: '90vh',
    overflowY: 'auto',
    position: 'relative',
    border: '1px solid rgba(184,134,11,.3)',
    boxShadow: '0 20px 60px rgba(0,0,0,.4)',
  },
  closeBtn: {
    position: 'absolute',
    top: 16,
    left: 16,
    background: 'rgba(184,134,11,.1)',
    border: '1px solid rgba(184,134,11,.3)',
    borderRadius: '50%',
    width: 36,
    height: 36,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#1C1610',
    cursor: 'pointer',
  },
  modalTitle: {
    fontFamily: "'Frank Ruhl Libre', serif",
    fontSize: '1.25rem',
    fontWeight: 700,
    color: '#1C1610',
    marginBottom: 8,
    paddingLeft: 44,
  },
  categoryTag: {
    display: 'inline-block',
    background: 'rgba(184,134,11,.15)',
    color: '#8B6500',
    fontSize: '.72rem',
    fontWeight: 600,
    padding: '3px 10px',
    borderRadius: 20,
    marginBottom: 16,
  },
  embedWrap: {
    position: 'relative',
    paddingBottom: '56.25%',
    height: 0,
    borderRadius: 10,
    overflow: 'hidden',
    marginBottom: 20,
    background: '#000',
  },
  embed: {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
    border: 'none',
  },
  modalMeta: {
    display: 'flex',
    gap: 20,
    flexWrap: 'wrap',
    marginBottom: 20,
    padding: '14px 16px',
    background: '#F5F0E8',
    borderRadius: 8,
    border: '1px solid rgba(184,134,11,.15)',
  },
  modalMetaItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: '.8rem',
    color: '#3D3323',
  },
  ytLink: {
    display: 'inline-flex',
    alignItems: 'center',
    background: '#1A3A5C',
    color: '#F5F0E8',
    padding: '9px 20px',
    borderRadius: 6,
    fontSize: '.85rem',
    fontWeight: 500,
    fontFamily: "'Heebo', sans-serif",
    transition: 'background .15s',
  },
}
