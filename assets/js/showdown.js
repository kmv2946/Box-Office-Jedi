/* Box Office Jedi — Showdown weekend-data connector
 * ---------------------------------------------------
 * On any showdown page, this script finds the #panel-weekend table,
 * reads each column's movie title, and fetches per-movie weekend data
 * from data/movie_weekends/<normalized-key>.json. It then fills the
 * Weekend-1..Weekend-5 rows with actual grosses, replacing the
 * "Data pending" placeholders.
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

  async function fetchMovie(key) {
    try {
      const r = await fetch('data/movie_weekends/' + key + '.json', { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  function fillColumn(panel, colIdx, movie) {
    // For each weekend row in the tbody, find the cell for this column
    // and drop in the gross (or em-dash).
    const rows = panel.querySelectorAll('tbody tr');
    rows.forEach((tr) => {
      const label = tr.querySelector('.sd-wknd-label');
      if (!label) return;
      const n = parseInt(label.textContent.trim(), 10);
      if (!n) return;
      const cell = tr.querySelector('.sd-wknd-cell.sd-col-' + colIdx);
      if (!cell) return;
      if (!movie) {
        cell.innerHTML = '<span class="wpend">\u2014</span>';
        return;
      }
      const w = movie.weekends.find((x) => x.n === n);
      if (!w || !w.gross) {
        cell.innerHTML = '<span>\u2014</span>';
      } else {
        cell.setAttribute('data-val', String(w.gross));
        cell.textContent = fmtMoney(w.gross);
      }
    });
  }

  async function init() {
    const panel = document.getElementById('panel-weekend');
    if (!panel) return;

    // Gather each column's title in order (sd-col-1, sd-col-2, ...)
    const heads = panel.querySelectorAll('thead .sd-head-cell');
    if (!heads.length) return;

    const work = [];
    heads.forEach((th) => {
      // Column index comes from the sd-col-N class on the <th>
      let colIdx = null;
      th.classList.forEach((c) => {
        const m = /^sd-col-(\d+)$/.exec(c);
        if (m) colIdx = parseInt(m[1], 10);
      });
      if (!colIdx) return;
      const link = th.querySelector('.sd-movie-title-link');
      const title = link ? link.textContent.trim() : '';
      if (!title) return;
      work.push({ colIdx: colIdx, title: title, key: normTitle(title) });
    });

    // Fetch all needed movies in parallel
    const results = await Promise.all(work.map((w) => fetchMovie(w.key)));

    work.forEach((w, i) => fillColumn(panel, w.colIdx, results[i]));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
