/**
 * Inkpick — Hand-Drawn Discovery Hub
 * Features: discovery, live search suggestions, "More like this" with match
 * reasons, saved sketchbook + "Because you saved", shareable deep links,
 * song mood mixer, movie trailers, chalkboard dark mode, 3D mascot.
 */

const DOMAINS = ['movies', 'songs', 'courses'];
const TABS = [...DOMAINS, 'saved'];
const DISCOVERY_LIMIT = 24;
const POSTER_SM = 'https://image.tmdb.org/t/p/w342';
const POSTER_LG = 'https://image.tmdb.org/t/p/w500';
const CACHE_MAX = 500;
const SAVED_KEY = 'inkpick:saved:v1';
const THEME_KEY = 'inkpick:theme';
const MASCOT_SRC = '/static/vendor/model-viewer-4.3.1.min.js';

const CATEGORIES = {
    movies: ['All', 'Action', 'Sci-Fi', 'Horror', 'Romance', 'Comedy', 'Drama', 'Animation', 'Thriller'],
    songs: ['All', 'Bollywood', 'Pop', 'Rock', 'Electronic', 'Jazz', 'Chill', 'Dance'],
    courses: ['All', 'YouTube', 'Web Dev', 'Design', 'Business', 'Music'],
};

const COURSE_FALLBACKS = {
    'web dev': 'https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=500&q=70',
    'design': 'https://images.unsplash.com/photo-1558655146-9f40138edfeb?w=500&q=70',
    'business': 'https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=500&q=70',
    'music': 'https://images.unsplash.com/photo-1511379938547-c1f69419868d?w=500&q=70',
    'default': 'https://images.unsplash.com/photo-1516321318423-f06f85e504b3?w=500&q=70',
};

const MOOD_PRESETS = {
    chill: { energy: 0.3, dance: 0.5, tempo: 85 },
    focus: { energy: 0.4, dance: 0.4, tempo: 100 },
    workout: { energy: 0.9, dance: 0.7, tempo: 140 },
    party: { energy: 0.85, dance: 0.9, tempo: 124 },
};

// ── State ────────────────────────────────────────────
let currentTab = null;
let currentGenre = 'All';
let discoveryOffset = 0;
let lastHash = null;
let searchSeq = 0;
let similarSeq = 0;
let detailSeq = 0;
let suggestSeq = 0;
let becauseSeq = 0;
let currentDetail = null;               // { domain, item }
const metaCache = {};                   // tmdbId -> slim TMDB metadata
const pageCache = new Map();            // `${tab}:${offset}` -> items
const itemsById = new Map();            // `${domain}:${id}` -> item

let grid, input, detailView, genrePills, spotlightContainer, gridHeader, loadMoreWrap, moodMixer;

// ── Helpers ──────────────────────────────────────────
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function domainOf(item) {
    if (item.tmdbId === -2) return 'courses';
    if (item.spotifyId) return 'songs';
    return 'movies';
}

function idOf(item) {
    return String(item.movieId ?? item.spotifyId);
}

function keyOf(domain, id) {
    return `${domain}:${id}`;
}

function rememberItem(item) {
    if (itemsById.size > 1500) itemsById.clear();
    itemsById.set(keyOf(domainOf(item), idOf(item)), item);
    if (item.cached && item.tmdbId > 0) metaCache[item.tmdbId] = item.cached;
}

function pruneCache() {
    const keys = Object.keys(metaCache);
    if (keys.length > CACHE_MAX) keys.slice(0, keys.length - CACHE_MAX).forEach(k => delete metaCache[k]);
}

async function getJSON(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
        const err = new Error(`Request failed (${res.status})`);
        err.status = res.status;
        throw err;
    }
    return res.json();
}

function debounce(fn, ms) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// ── Saved sketchbook (localStorage) ──────────────────
const Saved = {
    items: [],
    load() {
        try { this.items = JSON.parse(localStorage.getItem(SAVED_KEY)) || []; }
        catch { this.items = []; }
    },
    persist() {
        try { localStorage.setItem(SAVED_KEY, JSON.stringify(this.items)); } catch { /* private mode */ }
        updateSavedCount();
    },
    has(domain, id) {
        return this.items.some(s => s.domain === domain && s.id === id);
    },
    toggle(item) {
        const domain = domainOf(item);
        const id = idOf(item);
        if (this.has(domain, id)) {
            this.items = this.items.filter(s => !(s.domain === domain && s.id === id));
            this.persist();
            return false;
        }
        const { reasons, similarity, ...rest } = item;
        const meta = item.tmdbId > 0 ? metaCache[item.tmdbId] : null;
        if (meta) rest.cached = { poster_path: meta.poster_path, overview: meta.overview, vote_average: meta.vote_average };
        this.items.unshift({ domain, id, item: rest, savedAt: Date.now() });
        this.persist();
        return true;
    },
};

function updateSavedCount() {
    const badge = document.getElementById('saved-count');
    if (!badge) return;
    badge.textContent = Saved.items.length;
    badge.hidden = Saved.items.length === 0;
}

function syncSaveButtons(domain, id) {
    const saved = Saved.has(domain, id);
    document.querySelectorAll(`.save-btn[data-key="${CSS.escape(keyOf(domain, id))}"]`).forEach(btn => {
        btn.setAttribute('aria-pressed', String(saved));
        btn.textContent = saved ? '♥' : '♡';
        btn.title = saved ? 'Remove from sketchbook' : 'Save to sketchbook';
    });
    const detBtn = document.getElementById('det-save');
    if (detBtn && currentDetail && currentDetail.domain === domain && idOf(currentDetail.item) === id) {
        detBtn.setAttribute('aria-pressed', String(saved));
        detBtn.textContent = saved ? '♥ Saved' : '♡ Save';
    }
}

function toggleSave(item) {
    const saved = Saved.toggle(item);
    syncSaveButtons(domainOf(item), idOf(item));
    talk(saved ? 'Pinned to your sketchbook! 📌' : 'Erased from your sketchbook. ✏️', saved ? 'ThumbsUp' : 'No');
    if (currentTab === 'saved') renderSaved();
    else if (!document.getElementById('because').hidden || saved) renderBecauseIfBrowsing();
}

function renderBecauseIfBrowsing() {
    // Only refresh on the plain discovery view (not search/mood results)
    if (gridHeader.textContent === 'Trending Sketches') renderBecause();
}

// ── Init ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    grid = document.getElementById('discovery-results');
    input = document.getElementById('query-input');
    detailView = document.getElementById('detail-view');
    genrePills = document.getElementById('genre-pills');
    spotlightContainer = document.getElementById('spotlight-container');
    gridHeader = document.getElementById('grid-header');
    loadMoreWrap = document.getElementById('load-more-wrap');
    moodMixer = document.getElementById('mood-mixer');

    Saved.load();
    updateSavedCount();

    initSuggestions();
    initTheme();
    document.getElementById('btn-load-more')?.addEventListener('click', () => fetchDiscovery(true));
    document.getElementById('btn-surprise')?.addEventListener('click', surpriseMe);
    document.getElementById('det-close')?.addEventListener('click', closeDetail);
    document.getElementById('det-save')?.addEventListener('click', () => currentDetail && toggleSave(currentDetail.item));
    document.getElementById('det-share')?.addEventListener('click', shareCurrent);
    document.getElementById('det-trailer')?.addEventListener('click', playTrailer);
    window.addEventListener('keydown', (e) => {
        if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
            e.preventDefault();
            input?.focus();
        } else if (e.key === 'Escape' && document.activeElement !== input && !detailView.hidden) {
            closeDetail();
        }
    });

    initMoodMixer();
    window.addEventListener('hashchange', handleRoute);
    window.addEventListener('popstate', handleRoute);
    handleRoute();
    initMascot();
});

// ── Router: #/movies, #/movies/<id>, #/saved, #/saved/<domain>/<id> ──
function parseHash(hash) {
    const parts = (hash || '').replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
    const tab = TABS.includes(parts[0]) ? parts[0] : 'movies';
    if (tab === 'saved') {
        return { tab, domain: DOMAINS.includes(parts[1]) ? parts[1] : null, id: parts[2] || null };
    }
    return { tab, domain: tab, id: parts[1] || null };
}

function itemHash(tab, domain, id) {
    const enc = encodeURIComponent(id);
    return tab === 'saved' ? `#/saved/${domain}/${enc}` : `#/${domain}/${enc}`;
}

function handleRoute() {
    const hash = window.location.hash || '#/movies';
    if (hash === lastHash) return;
    lastHash = hash;
    const { tab, domain, id } = parseHash(hash);
    if (tab !== currentTab) switchTab(tab);
    if (id && domain) openItemById(domain, id);
    else hideDetail();
}

function navigate(hash) {
    if (hash === window.location.hash) return;
    history.pushState(null, '', hash);
    lastHash = hash;
}

function switchTab(tab) {
    currentTab = tab;
    currentGenre = 'All';
    discoveryOffset = 0;
    document.querySelectorAll('.nav-link').forEach(l => l.classList.toggle('active', l.dataset.route === tab));

    const titles = {
        movies: 'Inkpick: Cinema Log 🎬',
        songs: 'Inkpick: Playlist Scribbles 🎧',
        courses: 'Inkpick: Learning Scribbles 📚',
        saved: 'Inkpick: My Sketchbook 📒',
    };
    document.title = titles[tab];
    if (input) {
        const ph = { movies: 'Sketch a movie title...', songs: 'Sketch a song or artist...', courses: 'Sketch a course topic...', saved: 'Search your sketchbook...' };
        input.placeholder = ph[tab];
        input.value = '';
    }

    const isSaved = tab === 'saved';
    hideBecause();
    closeSuggestions();
    document.getElementById('pill-bar').hidden = isSaved;
    document.getElementById('spotlight-section').hidden = isSaved;
    moodMixer.hidden = tab !== 'songs';
    hideDetail();

    if (isSaved) {
        renderSaved();
    } else {
        renderPills();
        fetchDiscovery();
    }

    const mascotConfig = {
        movies: ['Cinema Log activated! 🍿', 'ThumbsUp'],
        songs: ['Tuning into Playlist Scribbles! 🎸 Try the mood mixer.', 'Dance'],
        courses: ['Learning mode: ON! 📚', 'Yes'],
        saved: ['Your personal sketchbook 📒', 'Wave'],
    };
    talk(...mascotConfig[tab]);
}

// ── Skeletons ────────────────────────────────────────
function showSkeletons(count = 12) {
    if (!grid) return;
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `<div class="skeleton" style="animation-delay:${i * 0.04}s"><div class="skel-card"><div class="skel-img"></div><div class="skel-title"></div><div class="skel-text"></div></div></div>`;
    }
    grid.innerHTML = html;
}

// ── Discovery ────────────────────────────────────────
async function fetchDiscovery(append = false) {
    const tab = currentTab;
    if (!append) {
        discoveryOffset = 0;
        gridHeader.textContent = 'Trending Sketches';
    } else {
        discoveryOffset += DISCOVERY_LIMIT;
    }
    const offset = discoveryOffset;
    const cacheKey = `${tab}:${offset}`;

    if (!append && !pageCache.has(cacheKey)) showSkeletons(12);
    if (!append) loadMoreWrap.hidden = true;

    try {
        let items = pageCache.get(cacheKey);
        if (!items) {
            const data = await getJSON(`/api/v1/discover/${tab}?limit=${DISCOVERY_LIMIT}&offset=${offset}`);
            items = data.results || [];
            pageCache.set(cacheKey, items);
        }
        if (tab !== currentTab) return;   // user switched tabs meanwhile
        items.forEach(rememberItem);
        pruneCache();

        if (!append && items.length === 0) {
            grid.innerHTML = emptyState('✍️ No sketches found in this wing.', 'Try switching categories or check back later!');
            return;
        }
        if (!append) {
            renderSpotlight(items[0]);
            renderItems(items.slice(1));
            renderBecause();
        } else {
            renderItems(items, true);
        }
        loadMoreWrap.hidden = items.length < DISCOVERY_LIMIT;
        fetchMissingMeta(items);
    } catch (err) {
        console.error('Discovery error:', err);
        if (append) {
            discoveryOffset = Math.max(0, discoveryOffset - DISCOVERY_LIMIT);
            talk("Couldn't sketch more right now. Try again! ✏️", 'No');
        } else {
            grid.innerHTML = emptyState('⚠️ Pencil broke.', 'The server had trouble sketching. Reload to try again.');
        }
    }
}

function emptyState(title, body) {
    return `<div class="empty-state"><h3>${title}</h3><p>${body}</p></div>`;
}

// ── Search ───────────────────────────────────────────
async function handleSearch(q) {
    if (currentTab === 'saved') {
        renderSaved(q);
        return;
    }
    if (q.length < 2) return;
    const seq = ++searchSeq;
    const tab = currentTab;
    closeSuggestions();
    hideBecause();
    talk('Pencil at the ready... 🖋️', 'Walking');
    try {
        const data = await getJSON(`/api/v1/search/${tab}?q=${encodeURIComponent(q)}&limit=24`);
        if (seq !== searchSeq || tab !== currentTab) return;
        const items = data.results || [];
        items.forEach(rememberItem);
        loadMoreWrap.hidden = true;
        gridHeader.textContent = `Sketches for “${q}”`;

        if (items.length === 0) {
            pendingSuggestion = data.suggestion || null;
            grid.innerHTML = emptyState(
                `✍️ No sketches match “${escapeHtml(q)}”.`,
                data.suggestion
                    ? `Did you mean <a href="#" onclick="applySuggestion(); return false;">${escapeHtml(data.suggestion)}</a>?`
                    : 'Try a different word or hit 🎲 Surprise me.'
            );
            if (data.suggestion) talk(`Did you mean “${escapeHtml(data.suggestion)}”?`, 'Wave', true);
            return;
        }
        renderItems(items);
        fetchMissingMeta(items);
    } catch (err) {
        console.error('Search error:', err);
        if (seq === searchSeq) talk('Search hit a snag. Try again! ✏️', 'No');
    }
}

let pendingSuggestion = null;
function applySuggestion(text = pendingSuggestion) {
    if (input && text) {
        input.value = text;
        handleSearch(text);
    }
}
window.applySuggestion = applySuggestion;

// ── Surprise Me ──────────────────────────────────────
async function surpriseMe() {
    talk('Rolling the dice... 🎲', 'Jump');
    try {
        const { result } = await getJSON(`/api/v1/surprise/${currentTab}`);
        if (!result) return;
        rememberItem(result);
        selectItem(result);
    } catch (err) {
        console.error('Surprise error:', err);
        talk('My dice rolled under the couch. Try again! 🙈', 'No');
    }
}

// ── Mood mixer (songs) ───────────────────────────────
function initMoodMixer() {
    const energy = document.getElementById('mood-energy');
    const dance = document.getElementById('mood-dance');
    const tempo = document.getElementById('mood-tempo');
    if (!energy || !dance || !tempo) return;

    const syncOutputs = () => {
        document.getElementById('mood-energy-out').textContent = Number(energy.value).toFixed(2);
        document.getElementById('mood-dance-out').textContent = Number(dance.value).toFixed(2);
        document.getElementById('mood-tempo-out').textContent = tempo.value;
    };
    const run = debounce(() => fetchMood(energy.value, dance.value, tempo.value), 250);

    [energy, dance, tempo].forEach(el => el.addEventListener('input', () => {
        syncOutputs();
        moodMixer.querySelectorAll('[data-preset]').forEach(b => b.classList.remove('active'));
        run();
    }));
    moodMixer.querySelectorAll('[data-preset]').forEach(btn => btn.addEventListener('click', () => {
        const p = MOOD_PRESETS[btn.dataset.preset];
        energy.value = p.energy; dance.value = p.dance; tempo.value = p.tempo;
        syncOutputs();
        moodMixer.querySelectorAll('[data-preset]').forEach(b => b.classList.toggle('active', b === btn));
        fetchMood(p.energy, p.dance, p.tempo, btn.textContent.trim());
    }));
}

async function fetchMood(energy, dance, tempo, label = null) {
    const seq = ++searchSeq;
    hideBecause();
    try {
        const qs = new URLSearchParams({ energy, danceability: dance, tempo, limit: 24 });
        const data = await getJSON(`/api/v1/songs/mood?${qs}`);
        if (seq !== searchSeq || currentTab !== 'songs') return;
        const items = data.results || [];
        items.forEach(rememberItem);
        loadMoreWrap.hidden = true;
        gridHeader.textContent = label ? `Mood mix: ${label}` : `Mood mix · ${Math.round(tempo)} BPM`;
        renderItems(items);
        if (label) talk(`${label} mix coming right up! 🎧`, 'Dance');
    } catch (err) {
        console.error('Mood error:', err);
        talk("The mixer jammed. Try again! 🎚️", 'No');
    }
}

// ── Rendering ────────────────────────────────────────
function renderPills() {
    if (!genrePills) return;
    genrePills.innerHTML = '';
    CATEGORIES[currentTab].forEach(cat => {
        const p = document.createElement('button');
        p.type = 'button';
        p.className = `pill ${currentGenre === cat ? 'active' : ''}`;
        p.textContent = cat;
        p.onclick = () => {
            currentGenre = cat;
            genrePills.querySelectorAll('.pill').forEach(btn => btn.classList.toggle('active', btn === p));
            if (cat === 'All') fetchDiscovery();
            else handleSearch(cat);
        };
        genrePills.appendChild(p);
    });
}

function renderSaved(filter = '') {
    gridHeader.textContent = 'My Sketchbook';
    loadMoreWrap.hidden = true;
    hideBecause();
    const q = filter.trim().toLowerCase();
    const entries = Saved.items.filter(s => !q || `${s.item.title} ${s.item.artist || ''}`.toLowerCase().includes(q));
    if (!Saved.items.length) {
        grid.innerHTML = emptyState('📒 Your sketchbook is empty.', 'Tap ♡ on any movie, song or course to keep it here.');
        return;
    }
    if (!entries.length) {
        grid.innerHTML = emptyState(`Nothing saved matches “${escapeHtml(filter)}”.`, 'Try another word.');
        return;
    }
    entries.forEach(s => rememberItem(s.item));
    renderItems(entries.map(s => s.item));
    if (!q) renderBecause();
    else hideBecause();
}

function posterUrl(meta, size = POSTER_SM) {
    return meta && meta.poster_path ? `${size}${meta.poster_path}` : null;
}

function renderSpotlight(item) {
    if (!spotlightContainer || !item) return;
    const domain = domainOf(item);
    const isMusic = domain === 'songs';
    const isCourse = domain === 'courses';
    const meta = domain === 'movies' ? metaCache[item.tmdbId] : null;
    const poster = posterUrl(meta, POSTER_LG);
    const image = isCourse ? generateCoursePoster(item, true)
        : isMusic ? generateMusicArt(item)
        : poster ? `<img src="${poster}" alt="" fetchpriority="high" decoding="async">` : generateMovieSketch(item);
    const desc = isCourse ? `A top-rated lesson from ${item.album}. Category: ${item.category}`
        : isMusic ? `A track from "${item.album || 'Unknown'}" by ${item.artist}.`
        : (meta && meta.overview) || 'A classic sketch in the vault...';

    spotlightContainer.innerHTML = `
        <div class="hero-card ${isCourse ? 'course-hero' : ''}" role="button" tabindex="0">
            <div class="masking-tape top-left"></div>
            <div class="masking-tape top-right"></div>
            <div class="hero-img">${image}</div>
            <div class="hero-content">
                <div class="hero-tag">PICK OF THE DAY</div>
                <h1 class="hero-title">${escapeHtml(item.title)}</h1>
                <p class="hero-desc">${escapeHtml(desc)}</p>
                <div class="detail-meta">
                    <span>${escapeHtml(item.releaseYear || '')}</span>
                    ${isMusic ? `<span class="acoustic-badge">${Math.round(item.tempo)} BPM</span>` : ''}
                    ${isCourse ? `<span class="rating">⭐ ${escapeHtml(item.rating)}</span>` : ''}
                </div>
            </div>
        </div>`;
    const card = spotlightContainer.firstElementChild;
    card.onclick = () => selectItem(item);
    card.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectItem(item); } };
}

function buildCard(item, i) {
    const domain = domainOf(item);
    const id = idOf(item);
    const isMusic = domain === 'songs';
    const isCourse = domain === 'courses';
    const meta = domain === 'movies' ? (metaCache[item.tmdbId] || item.cached) : null;
    const poster = posterUrl(meta);
    const saved = Saved.has(domain, id);

    const card = document.createElement('article');
    card.className = `card ${isCourse ? 'course-item' : ''}`;
    card.tabIndex = 0;
    if (item.tmdbId > 0) card.dataset.tmdbId = item.tmdbId;
    card.style.setProperty('--rand-rot', `${(Math.random() * 4 - 2).toFixed(1)}deg`);
    card.style.animationDelay = `${Math.min(i, 12) * 0.04}s`;

    const imageHtml = isCourse ? generateCoursePoster(item)
        : isMusic ? generateMusicArt(item)
        : poster ? `<img src="${poster}" class="loaded" alt="" loading="lazy" decoding="async">`
        : `<div class="skeleton-sketch">${generateMovieSketch(item)}</div>`;

    const labelText = isCourse ? (item.album || 'Course') : isMusic ? 'Track' : 'Film';
    const labelClass = String(labelText).toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const score = item.similarity > 0 ? `<span class="match-score">${Math.round(item.similarity * 100)}% match</span>` : '';
    const voteAvg = meta && meta.vote_average ? `<span class="rating">⭐ ${Number(meta.vote_average).toFixed(1)}</span>` : '';
    const why = Array.isArray(item.reasons) && item.reasons.length
        ? `<p class="card-why">✎ ${item.reasons.slice(0, 2).map(escapeHtml).join(' · ')}</p>` : '';

    card.innerHTML = `
        <div class="match-label label-${labelClass}">${escapeHtml(labelText)}</div>
        <div class="card-img">
            ${imageHtml}
            <button type="button" class="save-btn" data-key="${escapeHtml(keyOf(domain, id))}" aria-pressed="${saved}"
                title="${saved ? 'Remove from sketchbook' : 'Save to sketchbook'}">${saved ? '♥' : '♡'}</button>
        </div>
        <h3 class="card-title">${escapeHtml(item.title)}</h3>
        <div class="card-meta-line">
            <span>${escapeHtml(isCourse || isMusic ? item.artist : (item.releaseYear || ''))}</span>
            ${item.rating ? `<span class="rating">⭐ ${escapeHtml(item.rating)}</span>` : voteAvg}
            ${score}
        </div>
        ${why}`;

    card.querySelector('.save-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSave(item);
    });
    card.addEventListener('click', () => selectItem(item));
    card.addEventListener('keydown', (e) => {
        if (e.target === card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); selectItem(item); }
    });
    return card;
}

function renderItems(items, append = false, target = grid) {
    if (!target) return;
    const fragment = document.createDocumentFragment();
    items.forEach((item, i) => {
        rememberItem(item);
        fragment.appendChild(buildCard(item, i));
    });
    if (!append) target.replaceChildren(fragment);
    else target.appendChild(fragment);
}

// ── Detail view ──────────────────────────────────────
async function openItemById(domain, id) {
    const known = itemsById.get(keyOf(domain, id));
    if (known) {
        selectItem(known, { push: false });
        return;
    }
    const seq = ++detailSeq;
    try {
        const { result } = await getJSON(`/api/v1/item/${domain}/${encodeURIComponent(id)}`);
        if (seq !== detailSeq) return;
        rememberItem(result);
        selectItem(result, { push: false });
    } catch (err) {
        console.error('Deep link error:', err);
        talk("Couldn't find that sketch. It may have been erased! 🧽", 'No');
    }
}

function hideDetail() {
    resetTrailer();
    if (detailView) detailView.hidden = true;
    currentDetail = null;
    similarSeq++;
    detailSeq++;
}

function closeDetail() {
    hideDetail();
    navigate(`#/${currentTab}`);
}

async function shareCurrent() {
    if (!currentDetail) return;
    // Canonical link always points at the item's own category
    const url = `${location.origin}${location.pathname}${itemHash(currentDetail.domain, currentDetail.domain, idOf(currentDetail.item))}`;
    try {
        if (navigator.share && matchMedia('(pointer: coarse)').matches) {
            await navigator.share({ title: currentDetail.item.title, url });
        } else {
            await navigator.clipboard.writeText(url);
            talk('Link copied! Share the sketch 🔗', 'ThumbsUp');
        }
    } catch {
        window.prompt('Copy this link:', url);
    }
}

async function selectItem(item, { push = true } = {}) {
    if (!detailView) return;
    const domain = domainOf(item);
    const id = idOf(item);
    const seq = ++detailSeq;
    currentDetail = { domain, item };
    if (push) navigate(itemHash(currentTab === 'saved' ? 'saved' : domain, domain, id));
    resetTrailer();

    detailView.hidden = false;
    document.getElementById('det-title').textContent = item.title;
    const isMusic = domain === 'songs';
    const isCourse = domain === 'courses';
    const imgContainer = document.getElementById('det-img-container');
    imgContainer.className = `detail-img ${isCourse ? 'course-detail' : ''}`;
    const tagline = document.getElementById('det-tagline');
    const desc = document.getElementById('det-desc');
    const metaEl = document.getElementById('det-meta');

    if (isMusic) {
        imgContainer.innerHTML = generateMusicArt(item);
        tagline.textContent = item.artist;
        desc.textContent = `Featured in "${item.album || 'Single'}".`;
        metaEl.innerHTML = `<span>${escapeHtml(item.releaseYear || '')}</span>
            <span class="acoustic-badge">${Math.round(item.tempo)} BPM</span>
            <span class="acoustic-badge">⚡ ${Math.round(item.energy * 100)}% energy</span>
            <span class="acoustic-badge">🕺 ${Math.round(item.danceability * 100)}% dance</span>`;
    } else if (isCourse) {
        imgContainer.innerHTML = generateCoursePoster(item, true);
        tagline.textContent = `Instructor: ${item.artist}`;
        desc.textContent = `A top-rated lesson from ${item.album}. Category: ${item.category}`;
        metaEl.innerHTML = `<span>Rating: ${escapeHtml(item.rating)} ★</span> <span class="acoustic-badge">${escapeHtml(item.category)}</span>`;
    } else {
        let meta = metaCache[item.tmdbId] || item.cached;
        if (!meta && item.tmdbId > 0) {
            imgContainer.innerHTML = generateMovieSketch(item);
            desc.textContent = 'Inkpick is sketching the details...';
            try {
                meta = await getJSON(`/api/v1/tmdb/movie/${item.tmdbId}`);
                metaCache[item.tmdbId] = meta;
                pruneCache();
            } catch (err) {
                console.error('Detail fetch error:', err);
            }
            if (seq !== detailSeq) return;
        }
        meta = meta || {};
        const poster = posterUrl(meta, POSTER_LG);
        imgContainer.innerHTML = poster ? `<img src="${poster}" alt="Poster for ${escapeHtml(item.title)}" decoding="async">` : generateMovieSketch(item);
        tagline.textContent = meta.tagline || '';
        desc.textContent = meta.overview || '';
        const genres = (item.genres || []).slice(0, 3).map(g => `<span class="acoustic-badge">${escapeHtml(g)}</span>`).join(' ');
        const year = (meta.release_date || '').split('-')[0] || item.releaseYear || '';
        metaEl.innerHTML = `<span>${escapeHtml(year)}</span> <span>${meta.runtime ? escapeHtml(meta.runtime) + 'm' : ''}</span> ${genres}`;
    }

    // "Why this pick?" when the item came from a recommendation list
    const whyEl = document.getElementById('det-why');
    if (Array.isArray(item.reasons) && item.reasons.length) {
        whyEl.innerHTML = `<li class="why-title">Why this pick?</li>` + item.reasons.map(r => `<li>✎ ${escapeHtml(r)}</li>`).join('');
        whyEl.hidden = false;
    } else {
        whyEl.hidden = true;
    }

    const playLink = document.getElementById('det-play-link');
    const playText = document.getElementById('det-play-text');
    if (isMusic && item.spotifyId) {
        playLink.href = `https://open.spotify.com/track/${encodeURIComponent(item.spotifyId)}`;
        playText.textContent = 'Play on Spotify';
        playLink.hidden = false;
    } else if (isCourse && /^https?:\/\//.test(item.url || '')) {
        playLink.href = item.url;
        playText.textContent = `Start on ${item.album}`;
        playLink.hidden = false;
    } else if (domain === 'movies' && item.tmdbId > 0) {
        playLink.href = `https://www.themoviedb.org/movie/${item.tmdbId}`;
        playText.textContent = 'Experience on TMDB';
        playLink.hidden = false;
    } else {
        playLink.hidden = true;
    }

    if (domain === 'movies') loadTrailerButton(item, seq);
    syncSaveButtons(domain, id);
    detailView.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    loadSimilar(item);
}

// ── "More like this" ─────────────────────────────────
async function loadSimilar(item) {
    const wrap = document.getElementById('similar-wrap');
    const target = document.getElementById('similar-results');
    if (!wrap || !target) return;
    const seq = ++similarSeq;
    const domain = domainOf(item);
    wrap.hidden = false;
    target.innerHTML = '<p class="similar-empty">Sketching similar picks... ✏️</p>';

    try {
        const data = await getJSON(`/api/v1/recommend/${domain}/${encodeURIComponent(idOf(item))}?limit=8`);
        if (seq !== similarSeq) return;
        const recs = data.recommendations || [];
        if (!recs.length) {
            target.innerHTML = '<p class="similar-empty">No similar sketches yet for this one.</p>';
            return;
        }
        renderItems(recs, false, target);
        fetchMissingMeta(recs);
    } catch (err) {
        if (seq !== similarSeq) return;
        target.innerHTML = err.status === 404
            ? '<p class="similar-empty">No similar sketches yet for this one.</p>'
            : '<p class="similar-empty">Couldn\'t load similar picks right now.</p>';
    }
}

// ── Theme (chalkboard dark mode) ─────────────────────
function currentTheme() {
    const forced = document.documentElement.dataset.theme;
    if (forced) return forced;
    return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyThemeUi() {
    const btn = document.getElementById('theme-toggle');
    const dark = currentTheme() === 'dark';
    if (btn) {
        btn.textContent = dark ? '☀️' : '🌙';
        btn.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#1e2420' : '#fdfbf7');
}

function initTheme() {
    applyThemeUi();
    matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', applyThemeUi);
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
        const next = currentTheme() === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        try { localStorage.setItem(THEME_KEY, next); } catch { /* private mode */ }
        applyThemeUi();
        talk(next === 'dark' ? 'Chalkboard mode! 🖍️' : 'Fresh paper! 📄', 'Yes');
    });
}

// ── Live search suggestions (combobox) ───────────────
let suggestItems = [];
let suggestActive = -1;

function initSuggestions() {
    const list = document.getElementById('suggest-list');
    if (!input || !list) return;
    const run = debounce(() => fetchSuggestions(input.value.trim()), 150);

    input.addEventListener('input', run);
    input.addEventListener('focus', () => { if (suggestItems.length) openSuggestions(); });
    input.addEventListener('keydown', (e) => {
        const open = !list.hidden;
        if (e.key === 'ArrowDown' && open) {
            e.preventDefault();
            setActiveSuggestion(Math.min(suggestActive + 1, suggestItems.length));
        } else if (e.key === 'ArrowUp' && open) {
            e.preventDefault();
            setActiveSuggestion(Math.max(suggestActive - 1, -1));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (open && suggestActive >= 0 && suggestActive < suggestItems.length) {
                chooseSuggestion(suggestItems[suggestActive]);
            } else {
                closeSuggestions();
                handleSearch(input.value.trim());
            }
        } else if (e.key === 'Escape') {
            if (open) { e.preventDefault(); closeSuggestions(); }
        }
    });
    // Option clicks: mousedown fires before the input blurs
    list.addEventListener('mousedown', (e) => {
        const li = e.target.closest('[data-index]');
        if (!li) return;
        e.preventDefault();
        const i = Number(li.dataset.index);
        if (i === suggestItems.length) {
            closeSuggestions();
            handleSearch(input.value.trim());
        } else {
            chooseSuggestion(suggestItems[i]);
        }
    });
    input.addEventListener('blur', () => setTimeout(closeSuggestions, 120));
}

async function fetchSuggestions(q) {
    const seq = ++suggestSeq;
    if (q.length < 2) { suggestItems = []; closeSuggestions(); return; }
    let items = [];
    if (currentTab === 'saved') {
        const lq = q.toLowerCase();
        items = Saved.items.map(s => s.item).filter(i => `${i.title} ${i.artist || ''}`.toLowerCase().includes(lq)).slice(0, 8);
    } else {
        try {
            const data = await getJSON(`/api/v1/suggest/${currentTab}?q=${encodeURIComponent(q)}&limit=8`);
            items = data.results || [];
        } catch { return; }
    }
    if (seq !== suggestSeq || input.value.trim() !== q) return;
    suggestItems = items;
    renderSuggestions(q);
}

function highlight(text, q) {
    const t = String(text ?? '');
    const i = t.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return escapeHtml(t);
    return escapeHtml(t.slice(0, i)) + `<mark>${escapeHtml(t.slice(i, i + q.length))}</mark>` + escapeHtml(t.slice(i + q.length));
}

function renderSuggestions(q) {
    const list = document.getElementById('suggest-list');
    if (!list) return;
    suggestActive = -1;
    const rows = suggestItems.map((item, i) => {
        const domain = domainOf(item);
        const sub = domain === 'movies' ? (item.releaseYear || '') : (item.artist || '');
        return `<li id="suggest-${i}" class="suggest-option" role="option" aria-selected="false" data-index="${i}">
            <span>${highlight(item.title, q)}</span><span class="suggest-sub">${escapeHtml(sub)}</span></li>`;
    });
    if (currentTab !== 'saved') {
        rows.push(`<li id="suggest-${suggestItems.length}" class="suggest-option suggest-all" role="option" aria-selected="false" data-index="${suggestItems.length}">🔍 Search all for “${escapeHtml(q)}”</li>`);
    }
    if (!rows.length) { closeSuggestions(); return; }
    list.innerHTML = rows.join('');
    openSuggestions();
}

function setActiveSuggestion(i) {
    const list = document.getElementById('suggest-list');
    suggestActive = i;
    list.querySelectorAll('.suggest-option').forEach((li, idx) => li.setAttribute('aria-selected', String(idx === i)));
    const active = document.getElementById(`suggest-${i}`);
    if (active) {
        input.setAttribute('aria-activedescendant', active.id);
        active.scrollIntoView({ block: 'nearest' });
    } else {
        input.removeAttribute('aria-activedescendant');
    }
}

function openSuggestions() {
    const list = document.getElementById('suggest-list');
    if (!list || !list.children.length) return;
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
}

function closeSuggestions() {
    const list = document.getElementById('suggest-list');
    if (list) list.hidden = true;
    input?.setAttribute('aria-expanded', 'false');
    input?.removeAttribute('aria-activedescendant');
    suggestActive = -1;
}

function chooseSuggestion(item) {
    closeSuggestions();
    rememberItem(item);
    selectItem(item);
}

// ── "Because you saved …" ────────────────────────────
function hideBecause() {
    becauseSeq++;
    const row = document.getElementById('because');
    if (row) row.hidden = true;
}

async function renderBecause() {
    const row = document.getElementById('because');
    const target = document.getElementById('because-results');
    if (!row || !target) return;
    const seq = ++becauseSeq;
    const tab = currentTab;
    // Most recent save in this category (or any category on the Sketchbook tab)
    const seed = Saved.items.find(s => tab === 'saved' || s.domain === tab);
    if (!seed) { row.hidden = true; return; }

    try {
        const data = await getJSON(`/api/v1/recommend/${seed.domain}/${encodeURIComponent(seed.id)}?limit=10`);
        if (seq !== becauseSeq || tab !== currentTab) return;
        const recs = (data.recommendations || []).filter(r => !Saved.has(domainOf(r), idOf(r))).slice(0, 6);
        if (!recs.length) { row.hidden = true; return; }
        document.getElementById('because-title').textContent = `Because you saved “${seed.item.title}”`;
        renderItems(recs, false, target);
        fetchMissingMeta(recs);
        row.hidden = false;
    } catch {
        if (seq === becauseSeq) row.hidden = true;
    }
}

// ── Trailers ─────────────────────────────────────────
let pendingTrailer = null;

function resetTrailer() {
    pendingTrailer = null;
    const btn = document.getElementById('det-trailer');
    const wrap = document.getElementById('trailer-wrap');
    if (btn) btn.hidden = true;
    if (wrap) { wrap.hidden = true; wrap.innerHTML = ''; }   // stops playback
}

async function loadTrailerButton(item, seq) {
    const btn = document.getElementById('det-trailer');
    if (!btn) return;
    const query = encodeURIComponent(`${item.title} official trailer`);
    const searchUrl = `https://www.youtube.com/results?search_query=${query}`;
    let trailer = null;
    if (item.tmdbId > 0) {
        try {
            trailer = (await getJSON(`/api/v1/movies/${item.tmdbId}/trailer`)).trailer;
        } catch { /* fall back to search */ }
    }
    if (seq !== detailSeq) return;
    pendingTrailer = trailer ? { key: trailer.key } : { searchUrl };
    btn.textContent = trailer ? '🎞️ Watch trailer' : '🎞️ Find trailer';
    btn.hidden = false;
}

function playTrailer() {
    if (!pendingTrailer) return;
    if (pendingTrailer.searchUrl) {
        window.open(pendingTrailer.searchUrl, '_blank', 'noopener');
        return;
    }
    const wrap = document.getElementById('trailer-wrap');
    const key = encodeURIComponent(pendingTrailer.key);
    wrap.innerHTML = `<div class="trailer-frame"><iframe src="https://www.youtube-nocookie.com/embed/${key}?autoplay=1&rel=0"
        title="Trailer for ${escapeHtml(currentDetail?.item.title || 'movie')}" loading="lazy"
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe></div>`;
    wrap.hidden = false;
    wrap.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
    talk('Popcorn time! 🍿', 'Dance');
}

// ── TMDB metadata backfill ───────────────────────────
function fetchMissingMeta(items) {
    const ids = [...new Set(items.filter(i => i.tmdbId > 0 && !metaCache[i.tmdbId]).map(i => i.tmdbId))];
    if (ids.length) batchFetchMeta(ids.slice(0, 50));
}

async function batchFetchMeta(tmdbIds) {
    try {
        const data = await getJSON('/api/v1/tmdb/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids: tmdbIds }),
        });
        for (const [tid, meta] of Object.entries(data.results || {})) {
            metaCache[tid] = meta;
            document.querySelectorAll(`.card[data-tmdb-id="${CSS.escape(tid)}"]`).forEach(card => updateCard(card, meta));
        }
        pruneCache();
    } catch { /* posters are optional */ }
}

function updateCard(cardEl, meta) {
    const container = cardEl.querySelector('.skeleton-sketch');
    const poster = posterUrl(meta);
    if (container && poster) {
        container.outerHTML = `<img src="${poster}" class="loaded" alt="" loading="lazy" decoding="async">`;
    }
}

// ── Sketch engine (generated covers) ─────────────────
function seedRandom(seed) {
    let s = 0;
    for (let i = 0; i < seed.length; i++) s = (seed.charCodeAt(i) + ((s << 5) - s)) | 0;
    s = Math.abs(s) || 1;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
}

function generateScribblePath(rng, w, h) {
    const pts = [];
    for (let i = 0; i < 5; i++) pts.push(`${Math.floor(rng() * w)},${Math.floor(rng() * h)}`);
    return `M ${pts.join(' L ')} Z`;
}

function generateMasterpieceSketch(item, mode) {
    const rng = seedRandom((item.title || 'Unknown') + (item.artist || item.releaseYear || ''));
    const paperType = rng() > 0.5 ? 'dot-paper' : 'graph-paper';
    const p1 = generateScribblePath(rng, 300, 450);
    const p2 = generateScribblePath(rng, 300, 450);
    const subText = mode === 'music' ? (item.artist || '') : (item.releaseYear || 'Cinema');
    return `<div class="sketch-canvas ${paperType}"><svg class="sketch-svg" viewBox="0 0 300 450" aria-hidden="true"><path d="${p1}" stroke-width="1.5" opacity="0.1"/><path d="${p2}" stroke-width="1" opacity="0.05"/></svg><div class="sketch-hero-text">${escapeHtml(item.title)}</div><div class="sketch-sub-text">${escapeHtml(subText)}</div></div>`;
}

function generateMusicArt(item) { return generateMasterpieceSketch(item, 'music'); }
function generateMovieSketch(item) { return generateMasterpieceSketch(item, 'movie'); }

function generateCoursePoster(item, eager = false) {
    const cat = (item.category || 'default').toLowerCase();
    const fallback = COURSE_FALLBACKS[cat] || COURSE_FALLBACKS.default;
    const lazy = eager ? '' : 'loading="lazy"';
    const yt = String(item.url || '').match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{6,})/);
    if (yt) {
        // hqdefault always exists and is ~4x lighter than maxresdefault
        return `<img src="https://i.ytimg.com/vi/${yt[1]}/hqdefault.jpg" class="loaded course-poster" alt="" ${lazy} decoding="async">`;
    }
    const udemyImg = `https://img-c.udemycdn.com/course/480x270/${encodeURIComponent(item.movieId)}.jpg`;
    return `<img src="${udemyImg}" class="loaded course-poster" alt="" ${lazy} decoding="async" onerror="this.onerror=null;this.src='${fallback}'">`;
}

/**
 * MASCOT — "Sketchy" the 3D robot
 * The 3D viewer (~290 KB gz) + model (~130 KB gz) load only after the page
 * is idle, so they never delay the first paint or the content fetches.
 */
const sketchyQuotes = [
    'Searching for a masterpiece? 🖋️',
    'Tip: press / to search instantly!',
    'Tap ♡ to save picks to your sketchbook 📒',
    'Open anything to see “More like this” ✨',
    'Try the 🎚️ mood mixer on Playlist Scribbles!',
    'Stuck? Hit 🎲 Surprise me!',
    'Every pick has a shareable link 🔗',
];
const MASCOT_SPOTS = ['at-left', 'at-right'];    // page-margin spots, left → right
const prefersReducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const isCompact = () => matchMedia('(max-width: 768px)').matches;
let mascotState = 'at-left';
let mascotTalkTimer = null;
let mascotIdleTimer = null;
let mascotArrivalTimer = null;

function initMascot() {
    const mascot = document.getElementById('sketchy-mascot');
    const model = document.getElementById('sketchy-3d');
    if (!mascot || !model) return;

    const load = () => {
        if (customElements.get('model-viewer')) return activate();
        const s = document.createElement('script');
        s.type = 'module';
        s.src = MASCOT_SRC;
        s.onload = activate;
        document.head.appendChild(s);
    };
    const activate = () => {
        model.addEventListener('load', () => mascot.classList.add('ready'), { once: true });
        model.setAttribute('src', model.dataset.src);
    };
    // Defer heavy 3D work until the page has finished loading and is idle
    const whenIdle = (cb) => ('requestIdleCallback' in window ? requestIdleCallback(cb, { timeout: 3000 }) : setTimeout(cb, 1200));
    if (document.readyState === 'complete') whenIdle(load);
    else window.addEventListener('load', () => whenIdle(load), { once: true });

    mascot.addEventListener('click', () => {
        talk(sketchyQuotes[Math.floor(Math.random() * sketchyQuotes.length)], 'Jump');
    });

    setInterval(() => {
        if (document.hidden || mascot.classList.contains('active') || isCompact() || prefersReducedMotion()) return;
        const options = MASCOT_SPOTS.filter(s => s !== mascotState);
        moveMascotTo(options[Math.floor(Math.random() * options.length)]);
    }, 40000);
}

function playAnim(name, idleAfterMs = 0) {
    const model = document.getElementById('sketchy-3d');
    if (!model) return;
    clearTimeout(mascotIdleTimer);
    model.setAttribute('animation-name', name);
    // One-shot gestures return to a natural idle pose
    if (idleAfterMs) mascotIdleTimer = setTimeout(() => model.setAttribute('animation-name', 'Idle'), idleAfterMs);
}

function faceDirection(dir) {
    // Turn the camera instead of mirroring the mesh — keeps lighting & shadows correct
    const model = document.getElementById('sketchy-3d');
    if (!model) return;
    const theta = dir === 'right' ? '-65deg' : dir === 'left' ? '65deg' : '0deg';
    model.setAttribute('camera-orbit', `${theta} 78deg auto`);
}

function moveMascotTo(state) {
    const mascot = document.getElementById('sketchy-mascot');
    if (!mascot || state === mascotState) return;
    const dir = MASCOT_SPOTS.indexOf(state) > MASCOT_SPOTS.indexOf(mascotState) ? 'right' : 'left';
    mascot.classList.remove(mascotState);
    mascot.classList.add(state);
    mascotState = state;

    if (prefersReducedMotion() || isCompact()) return;
    faceDirection(dir);
    playAnim('Walking');

    const onArrival = (e) => {
        if (e && (e.target !== mascot || e.propertyName !== 'left')) return;
        mascot.removeEventListener('transitionend', onArrival);
        clearTimeout(mascotArrivalTimer);
        faceDirection('front');
        playAnim('Wave', 2600);
    };
    mascot.addEventListener('transitionend', onArrival);
    mascotArrivalTimer = setTimeout(onArrival, 3200);  // safety if no transition fires
}

function talk(message, anim = 'Wave', isHtml = false) {
    const mascot = document.getElementById('sketchy-mascot');
    const text = document.getElementById('sketchy-text');
    if (!mascot || !text) return;
    if (isHtml) text.innerHTML = message;
    else text.textContent = message;
    mascot.classList.add('active');
    const loops = anim === 'Walking' || anim === 'Dance';
    playAnim(anim, loops ? 3500 : 2200);
    clearTimeout(mascotTalkTimer);
    mascotTalkTimer = setTimeout(() => mascot.classList.remove('active'), 4500);
}
