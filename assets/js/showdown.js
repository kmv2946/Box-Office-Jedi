/* Box Office Jedi — Showdown Renderer (data-driven)
 * --------------------------------------------------
 * Each showdown page provides:
 *
 *   <script>
 *     window.SHOWDOWN_CONFIG = {
 *       title: 'SUMMER STARTERS',
 *       breadcrumb: 'SUMMER STARTERS',
 *       films: [
 *         { slug: 'twister',                title: 'Twister'           },
 *         { slug: 'themummy-1999',          title: 'The Mummy'         },
 *         ...
 *       ],
 *     };
 *   </script>
 *   <div id="showdown-root"></div>
 *
 * This script:
 *   - Renders the page header + tabs (Summary, Weekend)
 *   - Fetches each film's meta from data/movies_meta_shards/{letter}.json
 *   - Fetches each film's weekends from data/movie_weekends_shards/{letter}.json
 *   - Fetches data/movie_totals.json for authoritative domestic totals
 *   - Builds the Summary table (Genre, Studio, Release Date, Opening Weekend,
 *     Domestic Gross, Production Budget, Running Time, MPAA Rating)
 *   - Builds the Weekend table — one row per weekend (1..N where N is the
 *     longest run across the included films), plus footer rows
 *     (Total, Budget, Theaters, Release Date, Yearly Rank). Films with shorter
 *     runs get an em-dash in any rows past their last weekend.
 *   - Bolds the leader value in each row.
 */
(function () {
  'use strict';

  // ── Helpers ──────────────────────────────────────────────────────────
  function $(sel, root) { return (root || document).querySelector(sel); }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; });
  }
  function normKey(s) {
    return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  }
  function shardLetter(k) {
    if (!k) return null;
    var c = (k[0] || '').toLowerCase();
    return (c >= 'a' && c <= 'z') ? c : '_';
  }
  function fmtMoney(n) {
    if (n === null || n === undefined || n === 0) return '—';
    return '$' + Number(n).toLocaleString('en-US');
  }
  function fmtMoneyMillions(n) {
    if (!n) return '—';
    if (n >= 1e6) return '$' + (n / 1e6).toFixed(n % 1e6 === 0 ? 0 : 1) + ' million';
    return fmtMoney(n);
  }
  function fmtInt(n) {
    if (!n) return '—';
    return Number(n).toLocaleString('en-US');
  }
  function fmtRuntime(m) {
    if (!m) return '—';
    var h = Math.floor(m / 60), r = m % 60;
    return h + ' hr. ' + (r < 10 ? '0' + r : r) + ' min.';
  }
  function fmtRelease(iso) {
    if (!iso) return '—';
    var p = iso.split('-').map(function(x){ return parseInt(x, 10); });
    var MO = ['January','February','March','April','May','June',
              'July','August','September','October','November','December'];
    return MO[p[1]-1] + ' ' + p[2] + ', ' + p[0];
  }
  function fmtReleaseShort(iso) {
    if (!iso) return '—';
    var p = iso.split('-');
    return p[1] + '/' + p[2] + '/' + p[0].slice(-2);
  }
  function fmtSunDate(isoFri) {
    if (!isoFri) return '—';
    var p = isoFri.split('-').map(function(x){ return parseInt(x, 10); });
    var dt = new Date(Date.UTC(p[0], p[1] - 1, p[2] + 2));
    var mm = dt.getUTCMonth() + 1, dd = dt.getUTCDate();
    var yy = String(dt.getUTCFullYear()).slice(-2);
    return mm + '-' + dd + '-' + yy;
  }
  function fmtChange(curr, prev) {
    if (!prev || !curr) return '—';
    var p = (curr - prev) / prev * 100;
    if (!isFinite(p)) return '—';
    var sign = p >= 0 ? '+' : '−';
    return sign + Math.abs(p).toFixed(1) + '%';
  }

  // ── Shard cache: each shard fetched at most once per page ────────────
  var _SHARDS = {};
  async function loadShard(dir, letter) {
    if (!letter) return null;
    var k = dir + '/' + letter;
    if (k in _SHARDS) return _SHARDS[k];
    try {
      var r = await fetch('data/' + dir + '/' + letter + '.json',
                          { cache: 'no-store' });
      _SHARDS[k] = r.ok ? (await r.json()).entries || {} : null;
    } catch (e) { _SHARDS[k] = null; }
    return _SHARDS[k];
  }
  async function lookup(dir, key) {
    if (!key) return null;
    var sh = await loadShard(dir, shardLetter(key));
    return (sh && sh[key]) || null;
  }

  // Movie totals index — fetched once, cached
  var _TOTALS = null;
  async function loadTotals() {
    if (_TOTALS !== null) return _TOTALS;
    try {
      var r = await fetch('data/movie_totals.json', { cache: 'no-store' });
      _TOTALS = r.ok ? await r.json() : {};
    } catch (e) { _TOTALS = {}; }
    return _TOTALS;
  }

  // ── Per-film data fetch ──────────────────────────────────────────────
  async function fetchFilm(film) {
    // film: {slug, title}
    // Try slug first, then fall back to title-keyed lookup so old configs
    // that don't include the year still resolve.
    var keys = [];
    if (film.slug) keys.push(film.slug);
    var tk = normKey(film.title);
    if (tk && keys.indexOf(tk) === -1) keys.push(tk);

    var meta = null, weekends = null;
    for (var i = 0; i < keys.length && !meta; i++)
      meta = await lookup('movies_meta_shards', keys[i]);
    for (var i = 0; i < keys.length && !weekends; i++)
      weekends = await lookup('movie_weekends_shards', keys[i]);

    // Fall back to / merge with movie_meta_overrides.json so manually-
    // curated entries (posters, distributors, runtime for upcoming or
    // recent films that haven't been TMDB-enriched yet) flow through to
    // the showdown. Without this, films like Obsession (added by hand
    // before TMDB has them) show "No poster" even though the override
    // file carries the curated poster_url. Overrides win on conflicts —
    // same precedence rule the movie profile page uses.
    var overrides = null;
    try {
      var rO = await fetch('data/movie_meta_overrides.json', { cache: 'no-store' });
      if (rO.ok) overrides = await rO.json();
    } catch (e) { /* fall through */ }
    if (overrides) {
      var ovr = null;
      for (var i = 0; i < keys.length && !ovr; i++) {
        if (keys[i] && !keys[i].startsWith('_')) ovr = overrides[keys[i]];
      }
      // Title-prefix fallback: if no direct slug hit, try matching a
      // bare title (no year) against any override slug that starts with
      // it. Mirrors the movie profile page's behavior. Most recent year
      // wins on ambiguity.
      if (!ovr) {
        var bareKey = normKey(film.title);
        if (bareKey && !bareKey.includes('-')) {
          var matched = Object.keys(overrides)
            .filter(function(k){ return !k.startsWith('_') && k.startsWith(bareKey + '-'); })
            .sort()
            .pop();
          if (matched) ovr = overrides[matched];
        }
      }
      if (ovr) {
        meta = Object.assign({}, meta || {}, ovr);
      }
    }

    var totals = await loadTotals();
    var totalEntry = null;
    if (totals && totals.by_slug) {
      for (var i = 0; i < keys.length && !totalEntry; i++)
        totalEntry = totals.by_slug[keys[i]];
    }
    if (!totalEntry && totals && totals.by_title) {
      for (var i = 0; i < keys.length && !totalEntry; i++)
        totalEntry = totals.by_title[keys[i]];
    }

    return {
      film:     film,
      meta:     meta || {},
      weekends: weekends || null,
      total:    totalEntry || null,
    };
  }

  // ── Header cell builder (poster + title link, no year line) ─────────
  function headerCell(f, n) {
    var poster = (f.meta && f.meta.poster_url)
      ? '<img class="sd-poster" src="' + escapeHtml(f.meta.poster_url) +
        '" alt="' + escapeHtml(f.film.title) + '">'
      : '<div class="sd-poster-placeholder">No poster</div>';
    var slugParam = '?slug=' + encodeURIComponent(f.film.slug);
    return '<th class="sd-head-cell sd-col-' + n + '">' +
      poster +
      '<a class="sd-movie-title-link" href="movie.html' + slugParam + '">' +
        escapeHtml(f.film.title) + '</a>' +
    '</th>';
  }

  // ── Render: Summary table ────────────────────────────────────────────
  function renderSummary(films) {
    var rows = [
      { label: 'Genre',             pick: function(f){ return (f.meta.genres||[]).slice(0,2).join(' / ') || '—'; } },
      { label: 'Studio',            pick: function(f){ return f.meta.distributor || '—'; } },
      { label: 'Release Date',      pick: function(f){ return fmtRelease(f.meta.release_date); } },
      { label: 'Opening Weekend',   pick: function(f){
          var w = f.weekends && f.weekends.weekends && f.weekends.weekends[0];
          return w ? fmtMoney(w.gross) : '—';
        }, val: function(f){
          var w = f.weekends && f.weekends.weekends && f.weekends.weekends[0];
          return w && w.gross ? w.gross : 0;
        } },
      { label: 'Domestic Gross',    pick: function(f){
          var t = (f.total && f.total.total_gross) || 0;
          return t ? fmtMoney(t) : '—';
        }, val: function(f){ return (f.total && f.total.total_gross) || 0; } },
      { label: 'Production Budget', pick: function(f){ return fmtMoneyMillions(f.meta.budget); },
        val: function(f){ return f.meta.budget || 0; } },
      { label: 'Running Time',      pick: function(f){ return fmtRuntime(f.meta.runtime); } },
      { label: 'MPAA Rating',       pick: function(f){ return f.meta.mpaa || '—'; } },
    ];

    var html = '<table class="sd-table"><thead><tr>';
    html += '<th class="sd-corner"></th>';
    films.forEach(function(f, i) { html += headerCell(f, i + 1); });
    html += '</tr></thead><tbody>';

    rows.forEach(function(r) {
      html += '<tr><td class="sd-label">' + r.label + '</td>';
      var vals = films.map(function(f) {
        return r.val ? (r.val(f) || 0) : null;
      });
      var max = vals.some(function(v){ return v != null; })
        ? Math.max.apply(null, vals.map(function(v){ return v || 0; })) : 0;
      films.forEach(function(f, i) {
        var n = i + 1;
        var txt = r.pick(f);
        var isBest = (max > 0 && vals[i] === max);
        html += '<td class="sd-movie sd-col-' + n + (isBest ? ' best' : '') + '">' +
                escapeHtml(txt) + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  // ── Render: Weekend table ────────────────────────────────────────────
  function renderWeekend(films) {
    // Determine the longest run across all films so every row is filled
    // (or em-dashed for films that didn't reach that weekend).
    var maxWeeks = 0;
    films.forEach(function(f) {
      var ws = f.weekends && f.weekends.weekends;
      if (ws && ws.length > maxWeeks) maxWeeks = ws.length;
    });

    var html = '<table class="sd-table"><thead><tr>';
    html += '<th class="sd-corner-wknd"></th>';
    films.forEach(function(f, i) { html += headerCell(f, i + 1); });
    html += '</tr></thead><tbody>';

    // Weekend rows
    for (var n = 1; n <= maxWeeks; n++) {
      html += '<tr><td class="sd-wknd-label">' + n + '</td>';
      var grosses = films.map(function(f) {
        var ws = f.weekends && f.weekends.weekends;
        var w = ws ? ws[n - 1] : null;
        return w ? (w.gross || 0) : 0;
      });
      var max = grosses.length ? Math.max.apply(null, grosses) : 0;
      films.forEach(function(f, i) {
        var col = i + 1;
        var ws = f.weekends && f.weekends.weekends;
        var w = ws ? ws[n - 1] : null;
        var prev = (ws && n > 1) ? ws[n - 2] : null;
        if (!w) {
          html += '<td class="sd-wknd-cell sd-col-' + col +
                  '"><span class="wpend">—</span></td>';
          return;
        }
        var isBest = (max > 0 && (w.gross || 0) === max);
        var totalToDate = w.total_gross || 0;
        // Fall back to running sum when total_gross is missing in archive.
        if (!totalToDate && ws) {
          var run = 0;
          for (var k = 0; k < n; k++) run += (ws[k].gross || 0);
          totalToDate = run;
        }
        // Weekend-over-weekend pct change — color the cell content by
        // sign. Up = blue (#002AF5), down = red (#F23620). A flat 0% or
        // a missing prior week stays default text color.
        var chTxt = prev ? fmtChange(w.gross, prev.gross) : '—';
        var chCls = '';
        if (prev && w.gross && w.gross > prev.gross) chCls = ' wch-up';
        else if (prev && w.gross && w.gross < prev.gross) chCls = ' wch-down';
        html += '<td class="sd-wknd-cell sd-col-' + col + '" data-val="' + (w.gross || 0) + '">' +
          '<span class="wg' + (isBest ? ' best' : '') + '">' + fmtMoney(w.gross) + '</span>' +
          '<span class="wm">' + fmtSunDate(w.date) + ' / <b>' + (w.rank || '—') + '</b></span>' +
          '<span class="wth">' + ((w.theaters || 0) ? Number(w.theaters).toLocaleString('en-US') + ' / $' + (Math.floor((w.gross||0)/(w.theaters||1))).toLocaleString('en-US') : '—') + '</span>' +
          '<span class="wch' + chCls + '">' + chTxt + '</span>' +
          '<span class="wgt">' + fmtMoney(totalToDate) + '</span>' +
        '</td>';
      });
      html += '</tr>';
    }

    // ── Footer rows: Total, Budget, Theaters, Release Date, Yearly Rank
    var footerRows = [
      {
        label: 'Total',
        pick: function(f) { return fmtMoney((f.total && f.total.total_gross) || 0); },
        val:  function(f) { return (f.total && f.total.total_gross) || 0; },
      },
      {
        label: 'Budget',
        pick: function(f) { return fmtMoneyMillions(f.meta.budget); },
        val:  function(f) { return f.meta.budget || 0; },
      },
      {
        label: 'Theaters',
        pick: function(f) {
          var ws = f.weekends && f.weekends.weekends;
          if (!ws || !ws.length) return '—';
          var widest = 0;
          ws.forEach(function(w){ if ((w.theaters || 0) > widest) widest = w.theaters; });
          return widest ? fmtInt(widest) : '—';
        },
        val: function(f) {
          var ws = f.weekends && f.weekends.weekends;
          if (!ws || !ws.length) return 0;
          var widest = 0;
          ws.forEach(function(w){ if ((w.theaters || 0) > widest) widest = w.theaters; });
          return widest;
        },
      },
      {
        label: 'Release Date',
        pick: function(f) { return fmtReleaseShort(f.meta.release_date); },
      },
      {
        label: 'Yearly Rank',
        pick: function(f) {
          var r = (f.total && f.total.rank) || 0;
          return r ? String(r) : '—';
        },
        // Lower rank is better — invert for "best" highlighting
        val: function(f) {
          var r = (f.total && f.total.rank) || 9999;
          return -r;
        },
      },
    ];

    footerRows.forEach(function(r) {
      html += '<tr class="sd-footer-row"><td class="sd-label">' + r.label + '</td>';
      var vals = films.map(function(f) { return r.val ? r.val(f) : null; });
      var max = vals.some(function(v){ return v != null && v !== 0; })
        ? Math.max.apply(null, vals.map(function(v){ return v == null ? -Infinity : v; })) : null;
      films.forEach(function(f, i) {
        var col = i + 1;
        var txt = r.pick(f);
        var isBest = (max != null && vals[i] === max && vals[i] !== 0 && vals[i] !== -Infinity);
        html += '<td class="sd-movie sd-col-' + col + (isBest ? ' best' : '') + '">' +
                escapeHtml(txt) + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  // ── Page header / tab scaffolding ────────────────────────────────────
  function renderHeader(cfg) {
    return (
      '<div class="sd-page-header">' +
        '<a href="showdowns.html">SHOWDOWNS</a>' +
        '<span> &gt; ' + escapeHtml(cfg.breadcrumb || cfg.title || '') + '</span>' +
      '</div>' +
      '<div class="sd-section-bar"></div>' +
      '<div class="sd-title">' + escapeHtml(cfg.title || '') + '</div>' +
      // "Compare:" label sits just left of the tabs in Times Regular
      '<div class="sd-tabstrip">' +
        '<span class="sd-compare-label">Compare:</span>' +
        '<div class="sd-tabs">' +
          '<a class="sd-tab active" href="#" data-panel="summary">Summary Stats</a>' +
          '<a class="sd-tab" href="#" data-panel="weekend">Weekend Box Office</a>' +
        '</div>' +
      '</div>' +
      // Per-tab legend that explains the dense weekend-cell layout. Shown
      // only when the Weekend Box Office tab is active.
      '<div class="sd-tab-legend sd-tab-legend-weekend" id="sd-tab-legend-weekend">' +
        '(Weekend Gross / Weekend Date / Weekend Rank / Theaters / Theater Avg. / % Last Wknd / Gross-to-Date)' +
      '</div>'
    );
  }

  function attachTabHandlers(root) {
    var legendEl = root.querySelector('#sd-tab-legend-weekend');
    function syncLegend() {
      // Show the legend only when the Weekend Box Office tab is active
      if (!legendEl) return;
      var weekendActive = root.querySelector('.sd-tab[data-panel="weekend"].active');
      legendEl.style.display = weekendActive ? '' : 'none';
    }
    syncLegend();
    root.querySelectorAll('.sd-tab').forEach(function(tab) {
      tab.addEventListener('click', function(e) {
        e.preventDefault();
        root.querySelectorAll('.sd-tab').forEach(function(t){ t.classList.remove('active'); });
        tab.classList.add('active');
        root.querySelectorAll('.sd-panel').forEach(function(p){ p.classList.remove('active'); });
        var panel = root.querySelector('#panel-' + tab.dataset.panel);
        if (panel) panel.classList.add('active');
        syncLegend();
      });
    });
  }

  // ── Main ─────────────────────────────────────────────────────────────
  async function init() {
    var cfg = window.SHOWDOWN_CONFIG;
    if (!cfg || !cfg.films || !cfg.films.length) return;
    var root = document.getElementById('showdown-root');
    if (!root) return;

    document.title = (cfg.title || 'Showdown') + ' — Box Office Jedi';

    root.innerHTML = renderHeader(cfg) +
      '<div class="sd-panel active" id="panel-summary"><div class="sd-wrap">' +
        '<div class="sd-empty">Loading…</div>' +
      '</div></div>' +
      '<div class="sd-panel" id="panel-weekend"><div class="sd-wrap">' +
        '<div class="sd-empty">Loading…</div>' +
      '</div></div>';
    attachTabHandlers(root);

    var films = await Promise.all(cfg.films.map(fetchFilm));

    root.querySelector('#panel-summary .sd-wrap').innerHTML = renderSummary(films);
    root.querySelector('#panel-weekend .sd-wrap').innerHTML = renderWeekend(films);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
