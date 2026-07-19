import React, {useState} from 'react'
import Header from './components/Header.jsx'
import HomePage from './pages/HomePage.jsx'
import CategoryPage from './pages/CategoryPage.jsx'
import SearchPage from './pages/SearchPage.jsx'
import {useVideos} from './hooks/useVideos.js'
import {useKeywords} from './hooks/useKeywords.js'
import {dlog} from './utils/debug.js'

export default function App() {
    const {
        catalog, allVideos, categories, years,
        loading, error, lastSync, total, newCount,
        fetchMs, fetchSource,
    } = useVideos()

    const {keywords} = useKeywords()

    const [activeTab, setActiveTab] = useState('כל הקטגוריות')
    const [searchInit, setSearchInit] = useState(null)

    // Called from the HomePage quick-search bar — hands the chosen params off
    // to SearchPage and switches tabs.
    const handleHomeSearch = (params) => {
        dlog('App', 'handing off search from HomePage', params)
        setSearchInit(params)
        setActiveTab('__search__')
    }

    const renderContent = () => {
        if (loading) return (
            <div style={s.center}>
                <div style={s.spinner}/>
                <p style={s.loadingText}>טוען את מאגר השיעורים…</p>
            </div>
        )

        if (error) return (
            <div style={s.center}>
                <p style={s.errorText}>שגיאה: {error}</p>
                <p style={s.errorSub}>ודאו שה-backend פועל ושנתיב /api/cours זמין</p>
            </div>
        )

        if (!catalog) return null

        if (activeTab === '__search__')
            return (
                <SearchPage
                    allVideos={allVideos}
                    categories={categories}
                    years={years}
                    keywords={keywords}
                    initialParams={searchInit}
                />
            )

        if (activeTab === 'כל הקטגוריות')
            return (
                <HomePage
                    catalog={catalog}
                    allVideos={allVideos}
                    categories={categories}
                    years={years}
                    keywords={keywords}
                    onCategorySelect={setActiveTab}
                    onSearch={handleHomeSearch}
                    lastSync={lastSync}
                    total={total}
                    newCount={newCount}
                    fetchMs={fetchMs}
                    fetchSource={fetchSource}
                />
            )

        const videos = catalog[activeTab]
        if (!videos) return (
            <div style={s.center}><p style={s.errorText}>קטגוריה לא נמצאה</p></div>
        )
        return <CategoryPage category={activeTab} playlists={videos} years={years} keywords={keywords}/>
    }

    return (
        <div>
            <Header activeTab={activeTab} onTabChange={setActiveTab}/>
            <main style={s.main}>
                <div style={s.container}>{renderContent()}</div>
            </main>
            <footer style={s.footer}>
                <div style={s.footerInner}>
                    <span>הרב אהרון בוטבול שליט"א</span>
                    <span style={s.dot}>•</span>
                    <span>כל הזכויות שמורות</span>
                    <span style={s.dot}>•</span> {/* Optionnel : ajoute un point de séparation visuel */}
                    <div className="copyright" style={{display: 'inline-block'}}>
                        © <a href="https://yelotag.vercel.app/" target="_blank" rel="noopener noreferrer">yelotag.com</a>
                    </div>
                </div>
            </footer>
        </div>
    )
}

const s = {
    main: {minHeight: 'calc(100vh - 68px - 56px)'},
    container: {maxWidth: 1200, margin: '0 auto', padding: '0 24px'},
    center: {
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', minHeight: 400, gap: 12, textAlign: 'center',
    },
    spinner: {
        width: 44, height: 44,
        border: '3px solid rgba(184,134,11,.2)',
        borderTop: '3px solid #B8860B',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
    },
    loadingText: {fontFamily: "'Frank Ruhl Libre', serif", fontSize: '1rem', color: '#6B5E47'},
    errorText: {fontFamily: "'Frank Ruhl Libre', serif", fontSize: '1.1rem', color: '#8B1A1A'},
    errorSub: {fontSize: '.85rem', color: '#6B5E47'},
    footer: {background: '#1C1610', padding: '16px 24px', marginTop: 40},
    footerInner: {
        maxWidth: 1200, margin: '0 auto', display: 'flex', gap: 12,
        justifyContent: 'center', color: 'rgba(245,240,232,.4)',
        fontSize: '.78rem', fontFamily: "'Heebo', sans-serif",
    },
    dot: {opacity: .3},
}
