/* Box Office Jedi — Showdown weekend-data connector
 * ---------------------------------------------------
 * On any showdown page, this script finds the #panel-weekend table,
 * reads each column's movie title, and fetches per-movie weekend data
 * from data/movie_weekends/<normalized-key>.json. It then fills the
 * Weekend-1..Weekend-5 rows with the rich 5-line cell format:
 *
 *   Line 1 (.wg)  — weekend gross (bold)
 *   Line 2 (.wm)  — "M-D-YY / <b>N</b>" (Sunday of weekend / weekend #)
 *   Line 3 (.wth) — "theaters / $avg"
 *   Line 4 (.wch) — % change vs last weekend ("—" for week 1)
 *   Line 5 (.wgt) — cumulative total gross
 *
 * The cell also gets data-val=<gross> so the existing applyBolding()
 * helper will highlight the winning film per row.
 *
 * Title matching is case- and punctuation-insensitive, so the archive's
 * "Everything Everywhere All At Once" still matches a showdown's
 * "Everything Everywhere All at Once".
 */
(function () {
  'use strict';

  function normTitle(s) {
    return (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  }

  function fmtMoney(n) {
    if (n === null || n === undefined || n === 0) return '\u2014';
    return '$' + n.toLocaleString('en-US');
  }

  // "1996-05-10" (Friday) -> "5-12-96" (Sunday of that weekend)
  function fmtSunDate(isoFri) {
    if (!isoFri) return '\u2014';
    var parts = isoFri.split('-').map(function (x) { return parseInt(x, 10); });
    if (parts.length !== 3 || !parts[0]) return '\u2014';
    // Build in UTC so the +2 days shift doesn't dance around a local DST boundary.
    var dt = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2] + 2));
    var mm = dt.getUTCMonth() + 1;
    var dd = dt.getUTCDate();
    var yy = String(dt.getUTCFullYear()).slice(-2);
    return mm + '-' + dd + '-' + yy;
  }

  function fmtTheatersAvg(theaters, gross) {
    if (!theaters || !gross) return '\u2014';
    var avg = Math.floor(gross / theaters);
    return theaters.toLocaleString('en-US') + ' / $' + avg.toLocaleString('en-US');
  }

  // Change vs previous weekend. Returns an HTML string so we can apply a
  // sign-aware modifier class (positive = green, negative = red, none = dash).
  function fmtChange(curr, prev) {
    if (prev === null || prev === undefined || prev === 0 || !curr) return '\u2014';
    var p = (curr - prev) / prev * 100;
    if (!isFinite(p)) return '\u2014';
    // Use the typographic minus (U+2212) to match the hand-filled cells.
    var sign = p >= 0 ? '+' : '\u2212';
    return sign + Math.abs(p).toFixed(1) + '%';
  }

  async function fetchMovie(key) {
    try {
      var r = await fetch('data/movie_weekends/' + key + '.json', { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  function renderCell(cell, movie, n) {
    if (!movie) {
      cell.innerHTML = '<span class="wpend">\u2014</span>';
      return;
    }
    var w = null;
    var prev = null;
    for (var i = 0; i < movie.weekends.length; i++) {
      if (movie.weekends[i].n === n)     w    = movie.weekends[i];
      if (movie.weekends[i].n === n - 1) prev = movie.weekends[i];
    }
    if (!w) {
      cell.innerHTML = '<span class="wpend">\u2014</span>';
      cell.removeAttribute('data-val');
      return;
    }
    var prevGross = prev ? prev.gross : null;
    if (w.gross) cell.setAttribute('data-val', String(w.gross));
    cell.innerHTML = (
      '<span class="wg">'  + fmtMoney(w.gross) + '</span>' +
      '<span class="wm">'  + fmtSunDate(w.date) + ' / <b>' + n + '</b></span>' +
      '<span class="wth">' + fmtTheatersAvg(w.theaters, w.gross) + '</span>' +
      '<span class="wch">' + fmtChange(w.gross, prevGross) + '</span>' +
      '<span class="wgt">' + fmtMoney(w.total_gross) + '</span>'
    );
  }

  function fillColumn(panel, colIdx, movie) {
    var rows = panel.querySelectorAll('tbody tr');
    rows.forEach(function (tr) {
      var label = tr.querySelector('.sd-wknd-label');
      if (!label) return;
      var n = parseInt(label.textContent.trim(), 10);
      if (!n) return;
      var cell = tr.querySelector('.sd-wknd-cell.sd-col-' + colIdx);
      if (!cell) return;
      // Only auto-fill cells still showing the "Data pending" placeholder.
      // Any cell with hand-filled content is left alone so the author can
      // override archive data (e.g. pre-2000 films where The Numbers'
      // weekend aggregation differs from traditional Fri–Sun reporting).
      if (!cell.querySelector('.wpend')) return;
      renderCell(cell, movie, n);
    });
  }

  async function init() {
    var panel = document.getElementById('panel-weekend');
    if (!panel) return;

    var heads = panel.querySelectorAll('thead .sd-head-cell');
    if (!heads.length) return;

    var work = [];
    heads.forEach(function (th) {
      var colIdx = null;
      th.classList.forEach(function (c) {
        var m = /^sd-col-(\d+)$/.exec(c);
        if (m) colIdx = parseInt(m[1], 10);
      });
      if (!colIdx) return;
      var link = th.querySelector('.sd-movie-title-link');
      var title = link ? link.textContent.trim() : '';
      if (!title) return;
      work.push({ colIdx: colIdx, title: title, key: normTitle(title) });
    });

    var results = await Promise.all(work.map(function (w) { return fetchMovie(w.key); }));
    work.forEach(function (w, i) { fillColumn(panel, w.colIdx, results[i]); });

    // Re-run the page's bolding helper so the leader per row becomes bold
    // once our data has populated the data-val attributes.
    if (typeof window.applyBolding === 'function') {
      try { window.applyBolding(); } catch (e) { /* ignore */ }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
