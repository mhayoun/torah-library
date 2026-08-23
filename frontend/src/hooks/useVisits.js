import { useState, useEffect, useRef } from 'react'

const API_URL     = '/api/visits'
const VISITOR_KEY  = 'tl_visitor_id'

function getVisitorId() {
  try {
    let id = localStorage.getItem(VISITOR_KEY)
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem(VISITOR_KEY, id)
    }
    return id
  } catch {
    return null // localStorage unavailable (private mode etc.) — still counts the page view
  }
}

// Records one page view (and this browser's unique visitor id) on mount,
// then exposes the running totals returned by the backend.
export function useVisits() {
  const [totalViews, setTotalViews]         = useState(null)
  const [uniqueVisitors, setUniqueVisitors] = useState(null)
  const sent = useRef(false)

  useEffect(() => {
    if (sent.current) return
    sent.current = true

    const visitorId = getVisitorId()
    const url = visitorId ? `${API_URL}?visitor_id=${encodeURIComponent(visitorId)}` : API_URL

    fetch(url, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.total_views != null) setTotalViews(data.total_views)
        if (data.unique_visitors != null) setUniqueVisitors(data.unique_visitors)
      })
      .catch(() => {})
  }, [])

  return { totalViews, uniqueVisitors }
}
