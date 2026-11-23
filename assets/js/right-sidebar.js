/* ============================================================
   BOX OFFICE JEDI — Shared right-sidebar populate script
   ------------------------------------------------------------
   Pages that include this script and have the #rs-widget-body
   element will auto-fill the Release Schedule widget with the
   next upcoming Friday's releases from data/releases.json.

   Pages without #rs-widget-body simply no-op; safe to include
   anywhere.
   ============================================================ */
(function () {
  function escapeHtmlBasic(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  async function fetchJSON(url) {
    try {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) { return null; }
  }

  async function loadReleaseScheduleWidget() {
    const tbody  = document.getElementById('rs-widget-body');
    const dateEl = document.getElementById('rs-widget-date');
    if (!tbody) return;   // page doesn't have the widget — silently bail

    const data = await fetchJSON('data/releases.json');
    if (!data || !data.months) {
      tbody.innerHTML = '<tr><td colspan="2" class="rs-widget-empty">No schedule data.</td></tr>';
      return;
    }

    // Find the Friday to show: upcoming Friday Sun–Thu, but keep showing
    // that same Friday's slate through Sat (it's still the "current"
    // releases for the weekend) — only flip to the next Friday on Sunday.
    const today = new Date();
    const dow = today.getDay();                   // 0 Sun ... 5 Fri, 6 Sat
    const daysUntilFri = 5 - dow;                  // Sun..Thu: 5..1, Fri: 0, Sat: -1
    const fri = new Date(today.getFullYear(), today.getMonth(), today.getDate() + daysUntilFri);
    const friIso = fri.getFullYear() + '-' +
      String(fri.getMonth() + 1).padStart(2, '0') + '-' +
      String(fri.getDate()).padStart(2, '0');
    // A release "week" is keyed by the date its first films open. That is
    // usually the Friday, but holiday weeks (Thanksgiving, Christmas) open on
    // Wednesday, so a week dated Wed 11/25 belongs to the weekend that starts
    // Fri 11/27. Map every week to the Friday of its release weekend, then
    // show the target Friday's slate (merging a Wed slate and a Fri slate if
    // both exist), falling back to the next weekend that has releases.
    function weekendFriday(iso) {
      const p = iso.split('-').map(Number);
      const d = new Date(p[0], p[1] - 1, p[2]);
      d.setDate(d.getDate() + ((5 - d.getDay() + 7) % 7));   // Fri stays Fri; Wed -> Fri
      return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }
    const allWeeks = [];
    Object.keys(data.months).forEach(function (mk) {
      ((data.months[mk] || {}).weeks || []).forEach(function (w) {
        if (w && w.date && (w.releases || []).length) allWeeks.push({ week: w, fri: weekendFriday(w.date) });
      });
    });
    allWeeks.sort(function (a, b) { return a.week.date < b.week.date ? -1 : 1; });
    const targetFri = allWeeks.map(function (x) { return x.fri; }).find(function (f) { return f >= friIso; });
    if (!targetFri) {
      tbody.innerHTML = '<tr><td colspan="2" class="rs-widget-empty">No releases scheduled.</td></tr>';
      return;
    }
    const group = allWeeks.filter(function (x) { return x.fri === targetFri; });
    const week = {
      date: group[0].week.date,   // earliest opening date in the group (e.g. the Wednesday)
      releases: [].concat.apply([], group.map(function (x) { return x.week.releases; }))
    };

    // Header label (e.g. "May 1")
    const monNames = ['Jan.','Feb.','Mar.','Apr.','May','June','July','Aug.','Sept.','Oct.','Nov.','Dec.'];
    const wp = week.date.split('-').map(Number);
    if (dateEl) dateEl.textContent = monNames[wp[1] - 1] + ' ' + wp[2];

    // Skip placeholder rows (e.g. "[Movie Title]")
    const realReleases = (week.releases || []).filter(r => r.title && !/^\[/.test(r.title));
    if (!realReleases.length) {
      tbody.innerHTML = '<tr><td colspan="2" class="rs-widget-empty">No releases scheduled.</td></tr>';
      return;
    }

    // Sort by theater count descending — wide releases first (headliner
    // at the top), then by theaters. Limited / null-theater films sink
    // to the bottom. Without this, the order is whatever was hand-typed
    // into releases.json, which doesn't always put the biggest film first.
    realReleases.sort((a, b) => {
      const aw = a.is_wide ? 1 : 0;
      const bw = b.is_wide ? 1 : 0;
      if (aw !== bw) return bw - aw;
      const at = a.theaters || 0;
      const bt = b.theaters || 0;
      return bt - at;
    });

    // Year derived from the week's Friday date — passed to movie.html so
    // same-titled films across years (Moana 2016 vs 2026, etc.) resolve
    // to the right profile.
    const weekYear = (week.date || '').slice(0, 4);
    tbody.innerHTML = realReleases.map(r => {
      const release = r.theaters
        ? r.theaters.toLocaleString('en-US') + (r.theaters_plus ? '+' : '')
        : (r.release || 'TBD');
      const yPart = weekYear ? '&year=' + weekYear : '';
      const titleHref = 'movie.html?title=' + encodeURIComponent(r.title) + yPart;
      return (
        '<tr>' +
          '<td class="rs-widget-title"><a href="' + titleHref + '">' +
            escapeHtmlBasic(r.title) + '</a></td>' +
          '<td class="rs-widget-theaters">' + escapeHtmlBasic(release) + '</td>' +
        '</tr>'
      );
    }).join('');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadReleaseScheduleWidget);
  } else {
    loadReleaseScheduleWidget();
  }
})();
