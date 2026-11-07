/**
 * Inkpick — Hand-Drawn Discovery Hub
 * Consolidated & Stabilized
 */

let currentTab = 'movies';
let currentGenre = 'All';
const TMDB_POSTER = 'https://image.tmdb.org/t/p/w500';
const cache = {};
const CACHE_MAX = 500; // O6: Memory cap
let discoveryOffset = 0;
const DISCOVERY_LIMIT = 24;
let searchSeq = 0;   // Guards against out-of-order search responses
let similarSeq = 0;  // Guards against out-of-order "More like this" responses

// Escape untrusted text before interpolating into HTML (titles come from datasets/APIs)
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── Elements (Resolved in init) ──────────────────────
let grid, input, detailView, genrePills, spotlightContainer;

function resolveElements() {
    grid = document.getElementById('discovery-results');
    input = document.getElementById('query-input');
    detailView = document.getElementById('detail-view');
    genrePills = document.getElementById('genre-pills');
    spotlightContainer = document.getElementById('spotlight-container');
    
    if (!grid) console.warn("⚠️ Warning: 'discovery-results' grid element not found.");
}

const CATEGORIES = {
    movies: ['All', 'Bollywood', 'Action', 'Sci-Fi', 'Horror', 'Romance', 'Comedy', 'Drama'],
    songs: ['All', 'Bollywood', 'Pop', 'Rock', 'Electronic', 'Jazz', 'Chill', 'Dance'],
    courses: ['All', 'YouTube', 'Web Dev', 'Design', 'Business', 'Music']
};

// Course fallback images by category (O7: No more Microlink)
const COURSE_FALLBACKS = {
    'web dev': 'https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=500&q=80',
    'design': 'https://images.unsplash.com/photo-1558655146-9f40138edfeb?w=500&q=80',
    'business': 'https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=500&q=80',
    'music': 'https://images.unsplash.com/photo-1511379938547-c1f69419868d?w=500&q=80',
    'default': 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=500&q=80'
};

// ── B1 FIX: Single DOMContentLoaded handler ──────────
window.addEventListener('DOMContentLoaded', () => {
    console.log("🎨 Inkpick Hub: DOM Content Loaded. Initializing...");
    try {
        resolveElements();
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const query = input.value.trim();
                    handleSearch(query);
                }
            });
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
        initRouter();
        initMascot();
        initShortcuts();
        
        // Safety: Ensure visibility of main content
        const main = document.getElementById('main-content');
        if (main) main.style.opacity = '1';

        console.log("✅ Inkpick Hub initialized successfully.");
    } catch (err) {
        console.error("❌ Critical Hub Init Error:", err);
        // Show visible error if the core crashes
        const errGrid = document.getElementById('discovery-results');
        if (errGrid) {
            errGrid.innerHTML = `
                <div class="empty-state" style="color:var(--accent);">
                    <h3>⚠️ Hub initialization failure</h3>
                    <p>${escapeHtml(err.message)}</p>
                    <button onclick="location.reload()">Reload Hub</button>
                </div>`;
        }
    }
});

window.addEventListener('hashchange', initRouter);

function initRouter() {
    const hash = window.location.hash || '#/movies';
    const route = hash.replace('#/', '');
    const validRoutes = ['movies', 'songs', 'courses'];
    const tab = validRoutes.includes(route) ? route : 'movies';
    const navLink = document.querySelector(`.nav-link[data-route="${tab}"]`);
    internalSwitchTab(tab, navLink);
}

function internalSwitchTab(tab, el) {
    currentTab = tab;
    currentGenre = 'All';
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    if (el) el.classList.add('active');

    // Paper clip
    movePaperClip(el);

    const titles = {
        movies: "Inkpick: Cinema Log 🎬",
        songs: "Inkpick: Playlist Scribbles 🎧",
        courses: "Inkpick: Learning Scribbles 📚"
    };
    document.title = titles[tab] || "Inkpick: Sketchbook";

    // Update placeholder
    if (input) {
        const ph = { movies: 'Sketch a movie title...', songs: 'Sketch a song or artist...', courses: 'Sketch a course topic...' };
        input.placeholder = ph[tab] || 'Search...';
    }

    if (detailView) detailView.style.display = 'none';
    similarSeq++;
    discoveryOffset = 0; // Reset offset on tab switch
    renderPills();
    fetchDiscovery();

    // Mascot commentary
    const mascotConfig = {
        movies: { quote: "Cinema Log activated! 🍿", anim: "ThumbsUp" },
        songs: { quote: "Tuning into Playlist Scribbles! 🎸", anim: "Dance" },
        courses: { quote: "Learning mode: ON! 📚", anim: "Yes" }
    };
    const config = mascotConfig[tab] || { quote: "Sketching something fresh! 🖋️", anim: "Wave" };
    triggerSketchy3D(config.quote, config.anim);
}

function movePaperClip(el) {
    const clip = document.getElementById('nav-paper-clip');
    if (!clip || !el) return;
    const rect = el.getBoundingClientRect();
    const parentRect = el.parentElement.getBoundingClientRect();
    const left = rect.left - parentRect.left + (rect.width / 2);
    clip.style.left = `${left}px`;
    clip.style.transform = `translateX(-50%) rotate(${Math.random() * 20 - 10}deg)`;
}

function pruneCache() {
    const keys = Object.keys(cache);
    if (keys.length > CACHE_MAX) {
        // Remove oldest half
        keys.slice(0, Math.floor(CACHE_MAX / 2)).forEach(k => delete cache[k]);
    }
}

function initShortcuts() {
    window.addEventListener('keydown', (e) => {
        if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
            e.preventDefault();
            if (input) input.focus();
        }
    });
}

function showSkeletons(count = 12) {
    if (!grid) return;
    
    let html = '';
    for (let i = 0; i < count; i++) {
        const rot = (Math.random() * 4 - 2).toFixed(1);
        html += `
            <div class="skeleton" style="transform: rotate(${rot}deg); animation-delay: ${i * 0.05}s;">
                <div class="skel-card">
                    <div class="skel-img"></div>
                    <div class="skel-title"></div>
                    <div class="skel-text"></div>
                </div>
            </div>`;
    }
    grid.innerHTML = html;
    grid.style.opacity = '1';
}


/**
 * FETCH LOGIC
 */
async function fetchDiscovery(append = false) {
    const loadMoreWrap = document.getElementById('load-more-wrap');
    if (!append) {
        discoveryOffset = 0;
        showSkeletons(12);
        if (loadMoreWrap) loadMoreWrap.style.display = 'none';
    } else {
        discoveryOffset += DISCOVERY_LIMIT;
    }

    try {
        const limit = DISCOVERY_LIMIT;
        const res = await fetch(`/api/v1/discover/${currentTab}?limit=${limit}&offset=${discoveryOffset}`);
        if (!res.ok) throw new Error("Server was having trouble sketching...");
        const data = await res.json();
        const items = data.results || [];

        if (!append && items.length === 0) {
            grid.innerHTML = `
                <div class="empty-state">
                    <h3>✍️ No sketches found in this wing.</h3>
                    <p>Try switching categories or check back later!</p>
                </div>`;
            return;
        }

        // Cache management for movies
        if (currentTab === 'movies') {
            items.forEach(item => {
                if (item.cached && item.tmdbId > 0) cache[item.tmdbId] = item.cached;
            });
            pruneCache();
        }

        if (!append) {
            triggerSketchy3D();
            grid.innerHTML = '';
            if (items.length > 0) renderSpotlight(items[0]);
            renderItems(items.slice(1), false);
        } else {
            renderItems(items, true);
        }

        // Show "Load More" if we got a full page
        if (loadMoreWrap) loadMoreWrap.style.display = items.length >= limit ? 'flex' : 'none';

        if (currentTab === 'movies') {
            const uncached = items.filter(i => i.tmdbId > 0 && !cache[i.tmdbId]).map(i => i.tmdbId);
            if (uncached.length > 0) batchFetchMeta(uncached);
        }
    } catch (err) {
        console.error("Discovery error:", err);
        if (append) {
            discoveryOffset = Math.max(0, discoveryOffset - DISCOVERY_LIMIT);
            triggerSketchy3D("Couldn't sketch more right now. Try again! ✏️", "Wave");
        } else {
            grid.innerHTML = `<div class="empty-state" style="color:var(--accent);">⚠️ Pencil broke: ${escapeHtml(err.message)}</div>`;
        }
    }
}

// Bind Load More
document.getElementById('btn-load-more')?.addEventListener('click', () => fetchDiscovery(true));
document.getElementById('btn-surprise')?.addEventListener('click', surpriseMe);

// ✨ Surprise Me: open a random pick from the current tab
async function surpriseMe() {
    triggerSketchy3D("Rolling the dice... 🎲", "Jump");
    try {
        const res = await fetch(`/api/v1/surprise/${currentTab}`);
        if (!res.ok) throw new Error('No surprise available');
        const { result } = await res.json();
        if (!result) return;
        if (result.cached && result.tmdbId > 0) cache[result.tmdbId] = result.cached;
        featuredItems.set(String(result.movieId || result.spotifyId), result);
        selectItem(result);
    } catch (err) {
        console.error('Surprise error:', err);
        triggerSketchy3D("My dice rolled under the couch. Try again! 🙈", "Wave");
    }
}


async function handleSearch(q) {
    if (q.length < 2) return;
    const seq = ++searchSeq;
    const tab = currentTab;
    triggerSketchy3D("Pencil at the ready... 🖋️", "Walking");
    try {
        const res = await fetch(`/api/v1/search/${tab}?q=${encodeURIComponent(q)}&limit=24`);
        if (!res.ok) throw new Error("Search API failed");
        const data = await res.json();
        // Ignore stale responses (user typed again or switched tabs)
        if (seq !== searchSeq || tab !== currentTab) return;
        const items = data.results || [];

        items.forEach(item => {
            if (item.cached && item.tmdbId > 0) cache[item.tmdbId] = item.cached;
        });
        renderItems(items);
        const loadMoreWrap = document.getElementById('load-more-wrap');
        if (loadMoreWrap) loadMoreWrap.style.display = 'none';

        if (items.length === 0) {
            if (data.suggestion) {
                pendingSuggestion = data.suggestion;
                triggerSketchy3D(`Did you mean <span style="text-decoration:underline; cursor:pointer; color:var(--secondary);" onclick="applySuggestion()">${escapeHtml(data.suggestion)}</span>?`, "Wave");
            }
            grid.innerHTML = `
                <div class="empty-state">
                    <h3>✍️ No sketches match "${escapeHtml(q)}".</h3>
                    <p>${data.suggestion ? `Did you mean <a href="#" onclick="applySuggestion(); return false;">${escapeHtml(data.suggestion)}</a>?` : 'Try a different word or hit 🎲 Surprise me.'}</p>
                </div>`;
        } else if (tab === 'movies') {
            const uncached = items.filter(i => i.tmdbId > 0 && !cache[i.tmdbId]).map(i => i.tmdbId);
            if (uncached.length > 0) batchFetchMeta(uncached);
        }
    } catch (err) {
        console.error("Search error:", err);
        if (seq === searchSeq) triggerSketchy3D("Search hit a snag. Try again! ✏️", "Wave");
    }
}

let pendingSuggestion = null;
function applySuggestion(text = pendingSuggestion) {
    if (input && text) {
        input.value = text;
        triggerSketchy3D("Excellent choice!", "Jump");
        handleSearch(text);
    }
}

/**
 * RENDERING LOGIC
 */
function renderPills() {
    if (!genrePills) return;
    genrePills.innerHTML = '';
    CATEGORIES[currentTab].forEach(cat => {
        const p = document.createElement('button');
        p.className = `pill ${currentGenre === cat ? 'active' : ''}`;
        p.textContent = cat;
        p.onclick = () => {
            currentGenre = cat;
            document.querySelectorAll('.pill').forEach(btn => btn.classList.remove('active'));
            p.classList.add('active');
            handleGenreClick(cat);
        };
        genrePills.appendChild(p);
    });
}

function handleGenreClick(genre) {
    if (genre === 'All') fetchDiscovery();
    else if (genre === 'YouTube') handleSearch('YouTube');
    else handleSearch(genre);
}

const featuredItems = new Map();

function renderSpotlight(item) {
    if (!spotlightContainer || !item) return;
    const itemId = item.movieId || item.spotifyId;
    featuredItems.set(String(itemId), item);

    const isMusic = !!item.artist && item.tmdbId === -1;
    const isCourse = item.tmdbId === -2;
    const meta = !isMusic && !isCourse && cache[item.tmdbId];
    const image = isCourse ? generateCoursePoster(item) :
        (isMusic ? generateMusicArt(item) :
            (meta && meta.poster_path ? `<img src="${TMDB_POSTER}${meta.poster_path}" alt="">` : generateMovieSketch(item)));

    spotlightContainer.innerHTML = `
        <div class="hero-card ${isCourse ? 'course-hero' : ''}" onclick="selectItemById('${escapeHtml(itemId)}')">
            <div class="masking-tape top-left"></div>
            <div class="masking-tape top-right"></div>
            <div class="hero-img">${image}</div>
            <div class="hero-content">
                <div class="hero-tag">PICK OF THE DAY</div>
                <h1 class="hero-title">${escapeHtml(item.title)}</h1>
                <p class="hero-desc">${escapeHtml(isCourse ? `A top-rated lesson from ${item.album}. Category: ${item.category}` : (!isMusic ? (meta && meta.overview ? meta.overview : 'A classic sketch in the vault...') : `A track from "${item.album || 'Unknown'}" by ${item.artist}.`))}</p>
                <div class="detail-meta">
                    <span>${escapeHtml(item.releaseYear || '')}</span>
                    ${isMusic ? `<span class="acoustic-badge">${Math.round(item.tempo)} BPM</span>` : ''}
                    ${isCourse ? `<span class="academic-badge">${escapeHtml(item.category)}</span> <span class="rating">⭐ ${escapeHtml(item.rating)}</span>` : ''}
                </div>
            </div>
        </div>
    `;
}

function renderItems(items, append = false, target = grid) {
    if (!target) return;
    if (!append) target.innerHTML = '';
    if (featuredItems.size > 300) featuredItems.clear();

    const fragment = document.createDocumentFragment();
    items.forEach((item, i) => {
        const isMusic = item.tmdbId === -1;
        const isCourse = item.tmdbId === -2;
        const itemId = item.movieId || item.spotifyId;
        featuredItems.set(String(itemId), item);

        const card = document.createElement('div');
        card.className = `card ${isCourse ? 'course-item' : ''}`;
        card.dataset.tmdbId = item.tmdbId > 0 ? item.tmdbId : '';
        const rot = (Math.random() * 4 - 2).toFixed(1);
        card.style.setProperty('--rand-rot', `${rot}deg`);
        card.style.animationDelay = `${Math.min(i, 12) * 0.05}s`;
        card.onclick = () => selectItemById(itemId);

        const meta = !isMusic && !isCourse && cache[item.tmdbId];

        let imageHtml = isCourse ? generateCoursePoster(item) :
            (isMusic ? generateMusicArt(item) :
                (meta && meta.poster_path ? `<img src="${TMDB_POSTER}${meta.poster_path}" class="loaded" loading="lazy" decoding="async">` :
                    (item.tmdbId > 0 ? `<div class="skeleton-sketch">${generateMovieSketch(item)}</div>` : generateMovieSketch(item))));

        const labelClass = String(isCourse ? (item.album || 'Course') : 'item').toLowerCase().replace(/[^a-z0-9]+/g, '-');
        const score = item.similarity > 0 ? `<span class="match-score">${Math.round(item.similarity * 100)}% match</span>` : '';
        const voteAvg = meta && meta.vote_average ? `<span class="rating">⭐ ${Number(meta.vote_average).toFixed(1)}</span>` : '';
        card.innerHTML = `
            <div class="match-label label-${labelClass}">${escapeHtml(isCourse ? (item.album || 'Course') : (isMusic ? 'Draft' : 'Picked'))}</div>
            <div class="card-img">${imageHtml}</div>
            <div class="card-title">${escapeHtml(item.title)}</div>
            <div class="card-meta-line">
                <span>${escapeHtml(isCourse || isMusic ? item.artist : (item.releaseYear || ''))}</span>
                ${item.rating ? `<span class="rating">⭐ ${escapeHtml(item.rating)}</span>` : voteAvg}
                ${score}
            </div>
        `;
        if (append) card.style.animationDelay = `${Math.min(i, 12) * 0.05}s`;
        fragment.appendChild(card);
    });
    target.appendChild(fragment);
}

function selectItemById(id) {
    const item = featuredItems.get(String(id));
    if (item) selectItem(item);
}

async function selectItem(item) {
    if (!detailView) return;
    detailView.style.display = 'block';
    window.scrollTo({ top: 0, behavior: 'smooth' });
    document.getElementById('det-title').textContent = item.title;
    const isMusic = item.tmdbId === -1;
    const isCourse = item.tmdbId === -2;
    const imgContainer = document.getElementById('det-img-container');
    imgContainer.className = `detail-img ${isCourse ? 'course-detail' : ''}`;

    if (isMusic) {
        imgContainer.innerHTML = generateMusicArt(item);
        document.getElementById('det-tagline').textContent = item.artist;
        document.getElementById('det-desc').textContent = `Featured in "${item.album || 'Single'}".`;
        document.getElementById('det-meta').innerHTML = `<span>${escapeHtml(item.releaseYear || '')}</span> <span class="acoustic-badge">${Math.round(item.tempo)} BPM</span>`;
    } else if (isCourse) {
        imgContainer.innerHTML = generateCoursePoster(item);
        document.getElementById('det-tagline').textContent = `Instructor: ${item.artist}`;
        document.getElementById('det-desc').textContent = `A top-rated lesson from ${item.album}. Category: ${item.category}`;
        document.getElementById('det-meta').innerHTML = `<span>Rating: ${escapeHtml(item.rating)} ★</span> <span class="acoustic-badge">${escapeHtml(item.category)}</span>`;
    } else {
        let meta = cache[item.tmdbId];
        if (!meta && item.tmdbId > 0) {
            // Show placeholder while fetching
            imgContainer.classList.add('skeleton');
            document.getElementById('det-desc').textContent = "Inkpick is sketching the details...";
            try {
                const res = await fetch(`/api/v1/tmdb/movie/${item.tmdbId}`);
                if (res.ok) {
                    meta = await res.json();
                    cache[item.tmdbId] = meta;
                    pruneCache();
                }
            } catch (err) {
                console.error("Detail fetch error:", err);
            }
            imgContainer.classList.remove('skeleton');
        }
        meta = meta || {};
        imgContainer.innerHTML = meta.poster_path ? `<img src="${TMDB_POSTER + meta.poster_path}">` : generateMovieSketch(item);
        document.getElementById('det-tagline').textContent = meta.tagline || "";
        document.getElementById('det-desc').textContent = meta.overview || "";
        const genres = (item.genres || []).slice(0, 3).map(g => `<span class="acoustic-badge">${escapeHtml(g)}</span>`).join(' ');
        document.getElementById('det-meta').innerHTML = `<span>${escapeHtml(meta.release_date?.split('-')[0] || item.releaseYear || '')}</span> <span>${meta.runtime ? escapeHtml(meta.runtime) + 'm' : ''}</span> ${genres}`;
    }

    const playLink = document.getElementById('det-play-link');
    const playText = document.getElementById('det-play-text');
    if (playLink && playText) {
        if (isMusic && item.spotifyId) {
            playLink.href = `https://open.spotify.com/track/${item.spotifyId}`;
            playText.textContent = "Play on Spotify";
            playLink.style.display = "inline-flex";
        } else if (isCourse && item.url) {
            playLink.href = item.url;
            playText.textContent = `Start on ${item.album}`;
            playLink.style.display = "inline-flex";
        } else if (!isMusic && !isCourse && item.tmdbId > 0) {
            playLink.href = `https://www.themoviedb.org/movie/${item.tmdbId}`;
            playText.textContent = "Experience on TMDB";
            playLink.style.display = "inline-flex";
        } else {
            playLink.style.display = "none";
        }
    }

    if (typeof lucide !== 'undefined') lucide.createIcons();
    detailView.scrollIntoView({ behavior: 'smooth' });
    loadSimilar(item);
}

// ✨ "More like this": fetch recommendations for the selected item
async function loadSimilar(item) {
    const wrap = document.getElementById('similar-wrap');
    const target = document.getElementById('similar-results');
    if (!wrap || !target) return;
    const seq = ++similarSeq;
    const tab = currentTab;
    const itemId = item.movieId || item.spotifyId;
    wrap.style.display = 'block';
    target.innerHTML = '<p class="similar-empty">Sketching similar picks... ✏️</p>';

    try {
        const res = await fetch(`/api/v1/recommend/${tab}/${encodeURIComponent(itemId)}?limit=8`);
        if (seq !== similarSeq) return;
        if (!res.ok) {
            target.innerHTML = '<p class="similar-empty">No similar sketches yet for this one.</p>';
            return;
        }
        const data = await res.json();
        if (seq !== similarSeq) return;
        const recs = data.recommendations || [];
        recs.forEach(r => { if (r.cached && r.tmdbId > 0) cache[r.tmdbId] = r.cached; });
        renderItems(recs, false, target);
        if (tab === 'movies') {
            const uncached = recs.filter(r => r.tmdbId > 0 && !cache[r.tmdbId]).map(r => r.tmdbId);
            if (uncached.length) batchFetchMeta(uncached);
        }
    } catch (err) {
        console.error("Similar error:", err);
        if (seq === similarSeq) target.innerHTML = '<p class="similar-empty">Couldn\'t load similar picks right now.</p>';
    }
}

async function batchFetchMeta(tmdbIds) {
    try {
        const res = await fetch('/api/v1/tmdb/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: tmdbIds })
        });
        const data = await res.json();
        const results = data.results || {};
        for (const [tid, meta] of Object.entries(results)) {
            cache[parseInt(tid)] = meta;
            document.querySelectorAll(`.card[data-tmdb-id="${tid}"]`)
                .forEach(card => updateCard(parseInt(tid), card, meta));
        }
        pruneCache();
    } catch (err) { }
}

function updateCard(tid, cardEl, data) {
    const container = cardEl.querySelector('.skeleton-sketch');
    if (container && data.poster_path) {
        container.innerHTML = `<img src="${TMDB_POSTER}${data.poster_path}" class="loaded" loading="lazy">`;
        container.classList.remove('skeleton-sketch');
    }
}

/**
 * SKETCH ENGINE
 */
function seedRandom(seed) {
    let s = 0;
    for (let i = 0; i < seed.length; i++) s = seed.charCodeAt(i) + ((s << 5) - s);
    return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
}
function generateScribblePath(rng, w, h) {
    const pts = [];
    for (let i = 0; i < 5; i++) pts.push(`${Math.floor(rng() * w)},${Math.floor(rng() * h)}`);
    return `M ${pts.join(' L ')} Z`;
}
function generateMasterpieceSketch(item, mode = 'music') {
    const seed = (item.title || 'Unknown') + (item.artist || item.releaseYear || '');
    const rng = seedRandom(seed);
    const paperType = rng() > 0.5 ? 'dot-paper' : 'graph-paper';
    const paths = [generateScribblePath(rng, 300, 450), generateScribblePath(rng, 300, 450)];
    const subText = mode === 'music' ? (item.artist || '') : (item.releaseYear || 'Cinema');
    return `<div class="sketch-canvas ${paperType}"><svg class="sketch-svg" viewBox="0 0 300 450"><path d="${paths[0]}" stroke-width="1.5" opacity="0.1" /><path d="${paths[1]}" stroke-width="1" opacity="0.05" /></svg><div class="sketch-hero-text">${escapeHtml(item.title)}</div><div class="sketch-sub-text">${escapeHtml(subText)}</div></div>`;
}

function generateMusicArt(item) { return generateMasterpieceSketch(item, 'music'); }
function generateMovieSketch(item) { return generateMasterpieceSketch(item, 'movie'); }

// ── O7: Category-based fallbacks, no Microlink ──────
function generateCoursePoster(item) {
    const cat = (item.category || 'default').toLowerCase();
    const fallback = COURSE_FALLBACKS[cat] || COURSE_FALLBACKS['default'];

    // 1. YouTube High-Res Thumbnail (IDs are validated to [A-Za-z0-9_-])
    const ytMatch = String(item.url || '').match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{6,})/);
    const videoId = ytMatch ? ytMatch[1] : '';
    if (videoId) {
        return `<img src="https://img.youtube.com/vi/${videoId}/maxresdefault.jpg" class="loaded course-poster" alt="YouTube" style="width:100%;height:100%;object-fit:cover;" onerror="this.src='https://img.youtube.com/vi/${videoId}/hqdefault.jpg'">`;
    }

    // 2. Predictive Udemy CDN pattern, falling back to a category image
    const udemyImg = `https://img-c.udemycdn.com/course/480x270/${encodeURIComponent(item.movieId)}.jpg`;

    return `<img src="${udemyImg}" class="loaded course-poster" loading="lazy" alt="Course" style="width:100%;height:100%;object-fit:cover;" onerror="this.src='${fallback}'">`;
}

/**
 * MASCOT ENGINE — 3D Robot Restoration
 */
const sketchyQuotes = [
    "Searching for a masterpiece? 🖋️",
    "Did you know? 'DDLJ' is the longest-running film! 🍿",
    "Listening to Bolly-beats today? 🎸",
    "I've sketched 180,000 items so far!",
    "That Hero Card looks stunning, doesn't it?",
    "Need a recommendation? Try 'Sci-Fi'!",
    "I'm feeling wobbly today! 🤖"
];

function initMascot() {
    const mascot = document.getElementById('sketchy-mascot');
    if (!mascot) return;

    setInterval(() => {
        if (!mascot.classList.contains('active')) {
            const text = document.getElementById('sketchy-text');
            if (text) text.textContent = sketchyQuotes[Math.floor(Math.random() * sketchyQuotes.length)];
        }
    }, 10000);

    setTimeout(() => moveMascotTo('at-logo'), 1000);

    setInterval(() => {
        if (!mascot.classList.contains('active')) {
            const spots = ['at-logo', 'at-navbar', 'at-hero'];
            moveMascotTo(spots[Math.floor(Math.random() * spots.length)]);
        }
    }, 45000);
}

function moveMascotTo(state) {
    const mascot = document.getElementById('sketchy-mascot');
    const model = document.getElementById('sketchy-3d');
    if (!mascot || !model) return;

    if (state === 'at-logo') mascot.classList.add('facing-left');
    else mascot.classList.remove('facing-left');

    model.setAttribute('animation-name', 'Walking');
    mascot.classList.add('walking-bob');

    const states = ['at-navbar', 'at-hero', 'at-logo'];
    states.forEach(s => mascot.classList.remove(s));
    mascot.classList.add(state);

    const onArrival = () => {
        mascot.classList.remove('walking-bob');
        model.setAttribute('animation-name', 'Wave');
        mascot.removeEventListener('transitionend', onArrival);
        setTimeout(() => {
            if (model.getAttribute('animation-name') === 'Wave') {
                model.setAttribute('animation-name', 'Idle');
            }
        }, 3000);
    };
    mascot.addEventListener('transitionend', onArrival);
}

function triggerSketchy3D(customMessage = null, customAnim = null) {
    const mascot = document.getElementById('sketchy-mascot');
    const model = document.getElementById('sketchy-3d');
    const text = document.getElementById('sketchy-text');
    if (!mascot || !model || !text) return;

    mascot.classList.add('active');

    let behavior;
    if (customMessage) {
        behavior = { anim: customAnim || "Wave", text: customMessage };
    } else {
        const behaviors = [
            { anim: "Jump", text: "Boing! Searching... 🚀" },
            { anim: "ThumbsUp", text: "Great choice! 👍" },
            { anim: "Dance", text: "Let's celebrate! 🕺" }
        ];
        behavior = behaviors[Math.floor(Math.random() * behaviors.length)];
    }

    model.setAttribute('animation-name', behavior.anim);
    text.innerHTML = behavior.text;

    const locations = ['at-navbar', 'at-hero', 'at-logo'];
    setTimeout(() => moveMascotTo(locations[Math.floor(Math.random() * locations.length)]), 1500);

    setTimeout(() => { mascot.classList.remove('active'); }, customMessage ? 6000 : 4000);
}
