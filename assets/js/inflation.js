/* Box Office Jedi — Inflation Adjust tool
 * -----------------------------------------
 * Adds a "🖨 Print | Adjust this page for inflation ...>>>" bar to any
 * chart page that includes this script, and an <div id="page-tools">
 * placeholder element near the top of its main content.
 *
 * Chart pages register themselves with InflationTool.mount({...}) after
 * their data is ready. The config spells out how to read each movie's
 * year + original gross and how to re-render the chart with adjusted
 * values.
 *
 * Usage pattern:
 *
 *     InflationTool.mount({
 *       container: document.getElementById('page-tools'),
 *       defaultYear: 2026,          // optional page-wide release year
 *       getMovies:    () => CHART,  // return the original data array
 *       renderMovies: (movies, isAdjusted) => {
 *         // render the chart with this array; movies are sorted.
 *       },
 *       adjust: (movie, tool) => {
 *         // return {year, gross} for a given movie
 *         return { year: movie.y, gross: movie.g };
 *       },
 *       applyAdjusted: (movie, adjustedGross, rank) => {
 *         // return a copy with adjusted numbers for rendering
 *         return Object.assign({}, movie, { g: adjustedGross, r: rank });
 *       },
 *     });
 */
(function () {
  'use strict';

  const PRICES_URL = 'data/ticket_prices.json';

  let pricesReady = null;        // Promise resolving to { year: price } map
  let priceMap    = null;        // int year -> float price (filled from file)
  let sortedYears = null;        // sorted list of known years
  let referenceYear = null;      // year whose price we adjust TO

  function loadPrices() {
    if (pricesReady) return pricesReady;
    pricesReady = fetch(PRICES_URL, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('no data')))
      .then(d => {
        priceMap = {};
        Object.keys(d.prices || {}).forEach(k => { priceMap[+k] = +d.prices[k]; });
        sortedYears = Object.keys(priceMap).map(Number).sort((a, b) => a - b);
        referenceYear = d.current_reference_year || new Date().getFullYear();
        return priceMap;
      });
    return pricesReady;
  }

  // Return the average ticket price for a given year. Linearly interpolate
  // between known points; clamp to the nearest known year outside the range.
  function priceFor(year) {
    if (!sortedYears || !sortedYears.length) return null;
    if (priceMap[year] !== undefined) return priceMap[year];
    // Clamp
    if (year <= sortedYears[0])  return priceMap[sortedYears[0]];
    if (year >= sortedYears[sortedYears.length - 1]) return priceMap[sortedYears[sortedYears.length - 1]];
    // Linear interpolate between the two bracketing known years
    let lo = sortedYears[0], hi = sortedYears[sortedYears.length - 1];
    for (let i = 0; i < sortedYears.length - 1; i++) {
      if (sortedYears[i] <= year && sortedYears[i + 1] >= year) {
        lo = sortedYears[i]; hi = sortedYears[i + 1]; break;
      }
    }
    const t = (year - lo) / (hi - lo);
    return priceMap[lo] + t * (priceMap[hi] - priceMap[lo]);
  }

  function adjustGross(originalGross, fromYear, toYear) {
    const p1 = priceFor(fromYear);
    const p2 = priceFor(toYear);
    if (!p1 || !p2) return originalGross;
    return Math.round(originalGross * (p2 / p1));
  }

  // ── Toolbar UI ─────────────────────────────────────────────────────────
  const TOOLBAR_HTML = (
    '<div class="page-tools-inner">' +
      '<a class="pt-print" href="#" data-pt-action="print" title="Print this page">' +
        // Simple filled-body printer silhouette — reads clearly at small size
        '<svg class="pt-print-icon" width="20" height="16" viewBox="0 0 20 16" aria-hidden="true">' +
          '<rect x="5" y="1.5" width="10" height="4" fill="#7F170E"/>' +
          '<path d="M2.5 6 H17.5 Q19 6 19 7.5 V11 Q19 12 18 12 H15 V10 H5 V12 H2 Q1 12 1 11 V7.5 Q1 6 2.5 6 Z" fill="#7F170E"/>' +
          '<rect x="5" y="10" width="10" height="5" fill="#ffffff" stroke="#7F170E" stroke-width="1"/>' +
          '<line x1="7" y1="12" x2="13" y2="12" stroke="#7F170E" stroke-width="1"/>' +
          '<line x1="7" y1="13.5" x2="13" y2="13.5" stroke="#7F170E" stroke-width="1"/>' +
          '<circle cx="16.5" cy="8" r="0.7" fill="#ffffff"/>' +
        '</svg>' +
        '<span class="pt-label">Print</span>' +
      '</a>' +
      '<span class="pt-sep">|</span>' +
      '<a class="pt-inflation" href="#" data-pt-action="inflation">' +
        '<span class="pt-inflation-label">Adjust this page for inflation&nbsp;...&gt;&gt;&gt;</span>' +
      '</a>' +
    '</div>'
  );

  function injectStylesOnce() {
    if (document.getElementById('inflation-tool-styles')) return;
    const css = document.createElement('style');
    css.id = 'inflation-tool-styles';
    css.textContent =
      '.page-tools{padding:6px 14px 4px;background:#fff;}' +
      '.page-tools-inner{display:flex;justify-content:flex-end;align-items:center;' +
      '  font-family:Verdana,Geneva,sans-serif;font-size:13px;font-weight:bold;gap:8px;}' +
      '.page-tools a{color:#00239C;text-decoration:none;display:inline-flex;align-items:center;gap:4px;}' +
      '.page-tools a:hover{text-decoration:underline;}' +
      '.page-tools .pt-sep{color:#7F170E;font-weight:bold;}' +
      '.page-tools .pt-print-icon{vertical-align:middle;}' +
      '.page-tools.is-adjusted .pt-inflation-label::before{content:"\\2713 ";color:#006600;}' +
      '.page-tools.is-adjusted .pt-inflation-label{color:#006600;}' +
      '.infl-banner{font-family:Verdana,Geneva,sans-serif;font-size:11px;color:#7F170E;' +
      '  background:#FFF6E0;border:1px solid #EFD7A0;padding:4px 10px;margin:0 14px 8px;' +
      '  display:none;text-align:center;}' +
      '.page-tools.is-adjusted ~ .infl-banner{display:block;}';
    document.head.appendChild(css);
  }

  // Public API ──────────────────────────────────────────────────────────
  const API = {
    /** Mount the Print + Adjust toolbar into a container and wire the toggle. */
    async mount(opts) {
      injectStylesOnce();
      const container = opts.container;
      if (!container) return;
      container.classList.add('page-tools');
      container.innerHTML = TOOLBAR_HTML;

      // Print handler
      container.querySelector('[data-pt-action="print"]').addEventListener('click', e => {
        e.preventDefault();
        window.print();
      });

      const inflationLink  = container.querySelector('[data-pt-action="inflation"]');
      const labelEl        = inflationLink.querySelector('.pt-inflation-label');

      // Disable until prices load
      inflationLink.style.opacity = '0.5';
      inflationLink.style.pointerEvents = 'none';
      try {
        await loadPrices();
      } catch (e) {
        labelEl.textContent = 'Inflation data unavailable';
        return;
      }
      inflationLink.style.opacity = '';
      inflationLink.style.pointerEvents = '';

      let adjusted = false;
      const adjustedLabel = 'View original grosses&nbsp;...&gt;&gt;&gt;';
      const originalLabel = 'Adjust this page for inflation&nbsp;...&gt;&gt;&gt;';

      inflationLink.addEventListener('click', (e) => {
        e.preventDefault();
        adjusted = !adjusted;
        if (adjusted) {
          container.classList.add('is-adjusted');
          labelEl.innerHTML = adjustedLabel;
          API.applyTo(opts, /*adjust=*/true);
        } else {
          container.classList.remove('is-adjusted');
          labelEl.innerHTML = originalLabel;
          API.applyTo(opts, /*adjust=*/false);
        }
      });
    },

    /** Core transform: reads the original movies, produces a (sorted,
     *  rank-renumbered) adjusted copy, and hands it to the page's renderer. */
    applyTo(opts, adjust) {
      const movies = opts.getMovies();
      if (!movies || !movies.length) return;

      if (!adjust) {
        // Revert: hand back the original array (caller re-ranks if needed)
        opts.renderMovies(movies, false);
        return;
      }

      const target = opts.referenceYear || referenceYear;
      const adjustReader = opts.adjust || ((m) => ({
        year:  (opts.defaultYear || m.year || m.y),
        gross: (m.gross || m.g || m.total_gross),
      }));
      const applyAdjusted = opts.applyAdjusted || ((m, g, r) => Object.assign({}, m, { g: g, r: r }));

      // Compute adjusted gross per movie
      const adj = movies.map(m => {
        const {year, gross} = adjustReader(m);
        const newGross = adjustGross(gross || 0, year || target, target);
        return { m, year, origGross: gross, adjGross: newGross };
      });

      // Sort by adjusted gross desc
      adj.sort((a, b) => b.adjGross - a.adjGross);

      // Re-rank and build the final movie list
      const result = adj.map((e, i) => applyAdjusted(e.m, e.adjGross, i + 1));
      opts.renderMovies(result, true);
    },

    /** Expose helpers so pages can reuse the math directly if needed. */
    priceFor,
    adjustGross,
    loadPrices,
    get referenceYear() { return referenceYear; },
  };

  window.InflationTool = API;
})();
