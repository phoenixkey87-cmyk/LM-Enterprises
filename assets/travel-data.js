/* Phoenix Travel: renders pre-fetched fares, explore, cheapest dates and featured stays.
   Reads only static files in /data (written by the scheduled GitHub Action).
   Nothing here calls SerpApi and no API key is present in the browser. */
(function () {
  'use strict';

  var EMAIL = 'key.phoeniixtravel@gmail.com';
  var STALE_MS = 72 * 60 * 60 * 1000; // overridden by data.stale_hours (from data/config.json)
  var ORIGIN = 'STL';
  var travelers = 1;
  var mailInfo = new WeakMap();

  /* ---------- helpers ---------- */
  function h(tag, props, kids) {
    var el = document.createElement(tag);
    props = props || {};
    Object.keys(props).forEach(function (k) {
      var v = props[k];
      if (v === undefined || v === null || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else el.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }
  function $(id) { return document.getElementById(id); }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function isNum(n) { return typeof n === 'number' && isFinite(n) && n > 0; }
  function money(n) { return '$' + Math.round(n).toLocaleString('en-US'); }
  function safeUrl(u) { return typeof u === 'string' && /^https:\/\//i.test(u) ? u : null; }
  function staleLabel() {\n    var hrs = Math.round(STALE_MS / 3600000);\n    return hrs % 24 === 0 ? (hrs / 24) + ' days' : hrs + ' hours';\n  }\n  function useStale(data) {\n    if (data && typeof data.stale_hours === 'number' && data.stale_hours > 0) STALE_MS = data.stale_hours * 3600000;\n  }\n  function isStale(ts) {
    var t = Date.parse(ts);
    return !isFinite(t) || Date.now() - t > STALE_MS;
  }
  function parseDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
    return m ? new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])) : null;
  }
  function fmtDay(iso, withYear) {
    var d = parseDay(iso);
    if (!d) return null;
    var o = { month: 'short', day: 'numeric', timeZone: 'UTC' };
    if (withYear) o.year = 'numeric';
    return d.toLocaleDateString('en-US', o);
  }
  function fmtRange(a, b) {
    var x = fmtDay(a, false), y = fmtDay(b, true);
    if (x && y) return x + ' \u2013 ' + y;
    if (x) return fmtDay(a, true);
    return null;
  }
  function fmtUpdated(ts) {
    var t = Date.parse(ts);
    return isFinite(t) ? new Date(t).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : null;
  }
  function stopsText(n) { return n === 0 ? 'Nonstop' : n === 1 ? '1 stop' : isNum(n) ? n + ' stops' : null; }
  function notVerified(extra) { return h('span', { class: 'nv', text: 'Not verified' + (extra ? ' ' + extra : '') }); }

  function mailHref(subject, lines) {
    return 'mailto:' + EMAIL + '?subject=' + encodeURIComponent(subject) +
      '&body=' + encodeURIComponent(lines.filter(function (l) { return l !== null && l !== undefined; }).join('\n'));
  }
  function ctaLink(label, build) {
    var a = h('a', { class: 'btn btn-primary cta', 'data-mail': '1', text: label });
    mailInfo.set(a, build);
    a.href = build(travelers);
    return a;
  }
  function estText(el) {
    var unit = +el.getAttribute('data-unit'), kind = el.getAttribute('data-kind');
    if (!(unit > 0) || travelers < 2) { el.textContent = ''; return; }
    var rooms = Math.ceil(travelers / 2);
    var total = kind === 'room' ? unit * rooms : unit * travelers;
    el.textContent = kind === 'room'
      ? travelers + ' travelers, ' + rooms + ' room' + (rooms > 1 ? 's' : '') + ' \u2248 ' + money(total) + ' per night (estimate, not a quote)'
      : 'Group of ' + travelers + ' \u2248 ' + money(total) + ' (estimate, not a quote)';
  }
  function est(unit, kind) {
    var el = h('div', { class: 'est', 'data-est': '1', 'data-unit': String(unit), 'data-kind': kind, 'aria-live': 'polite' });
    estText(el);
    return el;
  }
  function refreshEstimates() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-est]'), estText);
    Array.prototype.forEach.call(document.querySelectorAll('a[data-mail]'), function (a) {
      var build = mailInfo.get(a);
      if (build) a.href = build(travelers);
    });
  }
  function travelersLine() { return travelers > 1 ? 'Travelers: ' + travelers : null; }

  function loadJSON(name) {
    return fetch('data/' + name + '.json', { cache: 'no-cache' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .catch(function () { return null; });
  }
  function setState(box, kind, msg) {
    clear(box);
    box.removeAttribute('aria-busy');
    box.appendChild(h('div', { class: 'td-state' + (kind === 'error' ? ' error' : ''), role: kind === 'error' ? 'alert' : null, text: msg }));
  }
  function updatedNote(id, ts) {
    var el = $(id);
    if (!el) return;
    var s = fmtUpdated(ts);
    el.textContent = s ? 'Last updated ' + s + (isStale(ts) ? ' \u2022 older than ' + staleLabel() + ', so prices are not shown as current' : '') : 'Last updated: not verified';
  }
  var ERR = "This data isn't available right now. Message Phoenix and I'll check current options by hand.";

  /* ---------- Fare Deals ---------- */
  function renderFares(data) {
    var box = $('td-fares-body');
    if (!data || !Array.isArray(data.deals)) return setState(box, 'error', ERR);
    if (!data.deals.length) return setState(box, 'empty', 'No fare deals found in the latest update. Check back tomorrow.');
    var stale = isStale(data.updated_at);
    updatedNote('td-fares-updated', data.updated_at);
    var grid = h('div', { class: 'td-grid' });
    data.deals.forEach(function (d) {
      var priced = isNum(d.price) && !stale;
      var dates = fmtRange(d.start_date, d.end_date);
      var code = d.arrival_airport_code || '';
      var card = h('article', { class: 'td-card' + (stale ? ' is-stale' : '') });
      if (isNum(d.discount_percentage) && !stale) card.appendChild(h('span', { class: 'td-badge deal', text: Math.round(d.discount_percentage) + '% below typical' }));
      card.appendChild(h('h4', { text: d.destination }));
      card.appendChild(h('div', { class: 'route', text: ORIGIN + ' \u2192 ' + (code || d.destination) + ' \u2022 round trip' }));
      card.appendChild(h('div', { class: 'price' }, [
        h('small', { text: 'Starting from, per person' }),
        priced ? document.createTextNode(money(d.price)) : notVerified(stale ? '(older than ' + staleLabel() + ')' : '')
      ]));
      card.appendChild(h('div', { class: 'meta' }, [
        dates ? dates : notVerified('dates'), h('br'),
        [d.airline, stopsText(d.stops)].filter(Boolean).join(' \u2022 ') || ''
      ]));
      if (priced) card.appendChild(est(d.price, 'flight')); else card.appendChild(h('div', { class: 'est' }));
      card.appendChild(ctaLink('Plan this trip with Phoenix', function (n) {
        return mailHref('Trip inquiry: ' + d.destination + ' from ' + ORIGIN, [
          'Hi Phoenix Travel,', '',
          "I'd like help planning a trip.",
          'Destination: ' + d.destination + (d.country ? ', ' + d.country : ''),
          'Dates: ' + (dates || 'flexible'),
          'Fare shown: ' + (priced ? 'starting from ' + money(d.price) + ' per person (Google Flights via SerpApi, updated ' + fmtUpdated(data.updated_at) + ', subject to change)' : 'not verified'),
          n > 1 ? 'Travelers: ' + n : null, '',
          'I understand planning fees apply and that Phoenix does not sell fares directly.'
        ]);
      }));
      grid.appendChild(card);
    });
    clear(box); box.removeAttribute('aria-busy'); box.appendChild(grid);
  }

  /* ---------- Explore ---------- */
  var explore = { data: null, shown: 12 };
  function renderExplore(data) {
    var box = $('td-explore-body');
    if (!data || !Array.isArray(data.destinations)) { $('td-explore-filters').hidden = true; return setState(box, 'error', ERR); }
    explore.data = data;
    updatedNote('td-explore-updated', data.updated_at);
    var months = {};
    data.destinations.forEach(function (d) { var x = parseDay(d.start_date); if (x) months[x.getUTCMonth()] = true; });
    var mSel = $('td-f-month');
    Object.keys(months).map(Number).sort(function (a, b) { return a - b; }).forEach(function (m) {
      mSel.appendChild(h('option', { value: String(m), text: new Date(Date.UTC(2000, m, 1)).toLocaleString('en-US', { month: 'long', timeZone: 'UTC' }) }));
    });
    var iSel = $('td-f-interest');
    (data.interests || []).forEach(function (i) { iSel.appendChild(h('option', { value: i.key, text: i.label })); });
    $('td-explore-filters').hidden = false;
    drawExplore();
  }
  function drawExplore() {
    var data = explore.data, box = $('td-explore-body');
    if (!data) return;
    var budget = +$('td-f-budget').value, month = $('td-f-month').value, interest = $('td-f-interest').value;
    var nonstop = $('td-f-nonstop').checked, plannedOnly = $('td-f-planned').checked;
    var stale = isStale(data.updated_at);
    var list = data.destinations.filter(function (d) {
      if (budget && !(isNum(d.price) && d.price <= budget)) return false;
      if (month !== '') { var x = parseDay(d.start_date); if (!x || x.getUTCMonth() !== +month) return false; }
      if (interest && (d.interests || []).indexOf(interest) < 0) return false;
      if (nonstop && d.stops !== 0) return false;
      if (plannedOnly && !d.planned) return false;
      return true;
    }).sort(function (a, b) {
      if (!!b.planned !== !!a.planned) return b.planned ? 1 : -1;
      return (isNum(a.price) ? a.price : 1e9) - (isNum(b.price) ? b.price : 1e9);
    });
    var status = $('td-explore-count');
    status.textContent = list.length + ' destination' + (list.length === 1 ? '' : 's') + ' match your filters';
    clear(box); box.removeAttribute('aria-busy');
    if (!list.length) { box.appendChild(h('div', { class: 'td-state', text: 'No destinations match these filters. Try widening your budget or month.' })); return; }
    var grid = h('div', { class: 'td-grid' });
    list.slice(0, explore.shown).forEach(function (d) {
      var priced = isNum(d.price) && !stale;
      var dates = fmtRange(d.start_date, d.end_date);
      var card = h('article', { class: 'td-card' + (d.planned ? ' planned' : '') + (stale ? ' is-stale' : '') });
      if (d.planned) card.appendChild(h('span', { class: 'td-badge', text: 'Phoenix has planned trips here' }));
      card.appendChild(h('h4', { text: d.name }));
      card.appendChild(h('div', { class: 'route', text: ORIGIN + ' \u2192 ' + (d.airport || d.name) + (d.country ? ' \u2022 ' + d.country : '') }));
      card.appendChild(h('div', { class: 'price' }, [
        h('small', { text: 'Starting from, per person' }),
        priced ? document.createTextNode(money(d.price)) : notVerified(stale ? '(older than ' + staleLabel() + ')' : '')
      ]));
      card.appendChild(h('div', { class: 'meta' }, [
        dates ? 'Example dates: ' + dates : notVerified('dates'), h('br'),
        [d.airline, stopsText(d.stops)].filter(Boolean).join(' \u2022 ')
      ]));
      if (priced) card.appendChild(est(d.price, 'flight')); else card.appendChild(h('div', { class: 'est' }));
      card.appendChild(ctaLink('Plan this trip with Phoenix', function (n) {
        return mailHref('Trip inquiry: ' + d.name + ' from ' + ORIGIN, [
          'Hi Phoenix Travel,', '', "I'd like help planning a trip.",
          'Destination: ' + d.name + (d.country ? ', ' + d.country : ''),
          'Dates: ' + (dates || 'flexible'),
          'Fare shown: ' + (priced ? 'starting from ' + money(d.price) + ' per person (Google Travel Explore via SerpApi, updated ' + fmtUpdated(data.updated_at) + ', subject to change)' : 'not verified'),
          n > 1 ? 'Travelers: ' + n : null, '',
          'I understand planning fees apply and that Phoenix does not sell fares directly.'
        ]);
      }));
      grid.appendChild(card);
    });
    box.appendChild(grid);
    if (list.length > explore.shown) {
      var more = h('button', { type: 'button', class: 'btn btn-secondary td-more', text: 'Show more (' + (list.length - explore.shown) + ' left)' });
      more.addEventListener('click', function () { explore.shown += 12; drawExplore(); });
      box.appendChild(more);
    }
  }

  /* ---------- Heat-map calendar (used by flights and hotels) ---------- */
  // items: [{date:'YYYY-MM-DD', price:number, ...}]  opts: {onPick(item), label(item), initial}
  function buildHeat(items, opts) {
    var byDate = {};
    items.forEach(function (it) { if (isNum(it.price) && parseDay(it.date)) byDate[it.date] = it; });
    var dates = Object.keys(byDate).sort();
    if (!dates.length) return null;
    var prices = dates.map(function (d) { return byDate[d].price; }).sort(function (a, b) { return a - b; });
    function q(p) { return prices[Math.min(prices.length - 1, Math.floor(p * prices.length))]; }
    var cuts = [q(0.2), q(0.4), q(0.6), q(0.8)];
    function bucket(p) { for (var i = 0; i < cuts.length; i++) if (p <= cuts[i]) return i; return 4; }

    var first = parseDay(dates[0]), last = parseDay(dates[dates.length - 1]);
    var wrap = h('div', { class: 'td-months', role: 'group', 'aria-label': 'Price calendar. Use arrow keys to move between days, Enter to select.' });
    var cells = [], selected = null;

    function select(btn) {
      if (selected) selected.setAttribute('aria-pressed', 'false');
      selected = btn; btn.setAttribute('aria-pressed', 'true');
      if (opts.onPick) opts.onPick(byDate[btn.getAttribute('data-date')]);
    }
    function focusCell(i) {
      i = Math.max(0, Math.min(cells.length - 1, i));
      cells.forEach(function (c) { c.tabIndex = -1; });
      cells[i].tabIndex = 0; cells[i].focus();
    }

    var cur = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1));
    while (cur <= last) {
      var y = cur.getUTCFullYear(), m = cur.getUTCMonth();
      var daysIn = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
      var month = h('div', { class: 'td-month' });
      month.appendChild(h('h5', { text: cur.toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }) }));
      var dow = h('div', { class: 'td-dow', 'aria-hidden': 'true' });
      ['S', 'M', 'T', 'W', 'T', 'F', 'S'].forEach(function (d) { dow.appendChild(h('span', { text: d })); });
      month.appendChild(dow);
      var grid = h('div', { class: 'td-days' });
      for (var p = 0; p < cur.getUTCDay(); p++) grid.appendChild(h('span', { class: 'pad' }));
      for (var d = 1; d <= daysIn; d++) {
        var iso = y + '-' + String(m + 1).padStart(2, '0') + '-' + String(d).padStart(2, '0');
        var dt = parseDay(iso);
        if (dt < first || dt > last) { grid.appendChild(h('span', { class: 'pad' })); continue; }
        var it = byDate[iso];
        var btn = h('button', {
          type: 'button', 'data-date': iso, tabindex: '-1', 'aria-pressed': 'false',
          class: 'td-day ' + (it ? 'h' + bucket(it.price) : 'none'),
          'aria-disabled': it ? null : 'true',
          'aria-label': it ? opts.label(it) : fmtDay(iso, true) + ', no price data'
        }, [h('span', { class: 'n', text: String(d) }), h('span', { class: 'p', text: it ? money(it.price) : '\u2013' })]);
        btn.setAttribute('data-i', String(cells.length));
        cells.push(btn);
        grid.appendChild(btn);
      }
      month.appendChild(grid);
      wrap.appendChild(month);
      cur = new Date(Date.UTC(y, m + 1, 1));
    }
    cells[0].tabIndex = 0;
    wrap.addEventListener('click', function (e) {
      var b = e.target.closest ? e.target.closest('.td-day') : null;
      if (!b || b.getAttribute('aria-disabled') === 'true') return;
      cells.forEach(function (c) { c.tabIndex = -1; }); b.tabIndex = 0;
      select(b);
    });
    wrap.addEventListener('keydown', function (e) {
      var b = e.target.closest ? e.target.closest('.td-day') : null;
      if (!b) return;
      var i = +b.getAttribute('data-i'), step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
      if (step) { e.preventDefault(); focusCell(i + step); }
      else if (e.key === 'Home') { e.preventDefault(); focusCell(0); }
      else if (e.key === 'End') { e.preventDefault(); focusCell(cells.length - 1); }
    });

    var legend = h('div', { class: 'td-legend', 'aria-hidden': 'true' }, [
      h('span', null, [h('i', { class: 'sw h0' }), 'Lowest ']),
      h('span', null, [h('i', { class: 'sw h2' }), 'Mid ']),
      h('span', null, [h('i', { class: 'sw h4' }), 'Highest ']),
      h('span', null, [h('i', { class: 'sw none' }), 'No price data'])
    ]);
    var cheapest = dates.slice().sort(function (a, b) { return byDate[a].price - byDate[b].price || (a < b ? -1 : 1); }).slice(0, 3);
    return {
      el: wrap, legend: legend, cheapest: cheapest.map(function (d) { return byDate[d]; }),
      pick: function (iso) { var b = wrap.querySelector('[data-date="' + iso + '"]'); if (b) { cells.forEach(function (c) { c.tabIndex = -1; }); b.tabIndex = 0; select(b); } }
    };
  }

  /* ---------- Cheapest Dates (flights) ---------- */
  function renderCalendar(data) {
    var box = $('td-cal-body'), sel = $('td-route');
    if (!data || !Array.isArray(data.routes)) { $('td-route-field').hidden = true; return setState(box, 'error', ERR); }
    if (!data.routes.length) { $('td-route-field').hidden = true; return setState(box, 'empty', 'No route calendars in the latest update.'); }
    updatedNote('td-cal-updated', data.updated_at);
    data.routes.forEach(function (r, i) { sel.appendChild(h('option', { value: String(i), text: ORIGIN + ' \u2192 ' + r.name + ' (' + r.arrival + ')' })); });
    $('td-route-field').hidden = false;
    function draw() {
      var r = data.routes[+sel.value], stale = isStale(r.updated_at);
      clear(box); box.removeAttribute('aria-busy');
      var wrap = h('div', { class: 'td-cal-wrap' + (stale ? ' is-stale' : '') });
      if (stale) wrap.appendChild(h('p', { class: 'td-state', text: 'Prices for this route are older than ' + staleLabel() + ' and are not verified. Message Phoenix for a current check.' }));
      var heat = buildHeat(r.prices || [], {
        label: function (it) { return fmtDay(it.outbound_date || it.date, true) + ', round trip from ' + money(it.price) + ' per person'; },
        onPick: function (it) {
          clear(pickEl);
          var dep = fmtDay(it.outbound_date, true), ret = it.return_date ? fmtDay(it.return_date, true) : null;
          pickEl.appendChild(h('div', null, [
            h('strong', { text: 'Depart ' + dep + (ret ? ', return ' + ret : '') }), ' \u2022 from ' + money(it.price) + ' per person',
            est(it.price, 'flight')
          ]));
          pickEl.appendChild(ctaLink('Plan this trip with Phoenix', function (n) {
            return mailHref('Trip inquiry: ' + r.name + ' from ' + ORIGIN, [
              'Hi Phoenix Travel,', '', "I'd like help planning a trip.",
              'Destination: ' + r.name + ' (' + r.arrival + ')',
              'Dates: depart ' + dep + (ret ? ', return ' + ret : ''),
              'Fare shown: starting from ' + money(it.price) + ' per person round trip (Google Flights via SerpApi, updated ' + fmtUpdated(r.updated_at) + ', subject to change)',
              n > 1 ? 'Travelers: ' + n : null, '',
              'I understand planning fees apply and that Phoenix does not sell fares directly.'
            ]);
          }));
        }
      });
      var pickEl = h('div', { class: 'td-pick', 'aria-live': 'polite' });
      if (!heat) { wrap.appendChild(h('div', { class: 'td-state', text: 'No fares were returned for this route. Not verified.' })); box.appendChild(wrap); return; }
      var chips = h('div', { class: 'td-cheapest' }, [h('span', { text: 'Cheapest departures:' })]);
      heat.cheapest.forEach(function (it) {
        chips.appendChild(h('span', { class: 'chip', text: fmtDay(it.outbound_date, false) + ' \u2022 ' + money(it.price) }));
      });
      chips.appendChild(h('span', { text: '(' + r.round_trip_days + '-day trips, starting from, subject to change)' }));
      wrap.appendChild(chips);
      wrap.appendChild(heat.el);
      wrap.appendChild(heat.legend);
      wrap.appendChild(pickEl);
      box.appendChild(wrap);
      if (!stale) heat.pick(heat.cheapest[0].outbound_date || heat.cheapest[0].date);
      else pickEl.appendChild(notVerified('(data older than ' + staleLabel() + ')'));
    }
    // heat items need a "date" for lookup; calendar rows use outbound_date
    data.routes.forEach(function (r) { (r.prices || []).forEach(function (p) { if (!p.date) p.date = p.outbound_date; }); });
    sel.addEventListener('change', draw);
    draw();
  }

  /* ---------- Featured Stays ---------- */
  function renderStays(data) {
    var box = $('td-stays-body');
    if (!data || !Array.isArray(data.destinations)) return setState(box, 'error', ERR);
    if (!data.destinations.length) return setState(box, 'empty', 'No featured stays in the latest update.');
    updatedNote('td-stays-updated', data.updated_at);
    clear(box); box.removeAttribute('aria-busy');
    data.destinations.forEach(function (dest) {
      if (!Array.isArray(dest.hotels) || !dest.hotels.length) return;
      box.appendChild(h('h4', { class: 'td-stay-dest', text: dest.name }));
      var grid = h('div', { class: 'td-stays' });
      dest.hotels.forEach(function (hotel) { grid.appendChild(stayCard(dest, hotel)); });
      box.appendChild(grid);
    });
  }
  function stayCard(dest, hotel) {
    var stale = isStale(hotel.price_updated_at);
    var photos = (hotel.photos || []).filter(function (p) { return safeUrl(p.url) || safeUrl(p.thumb); });
    var card = h('article', { class: 'td-stay' + (stale ? ' is-stale' : '') });
    if (photos.length) {
      var heroBtn = h('button', { type: 'button', class: 'td-hero', 'aria-label': 'Open ' + photos.length + ' photos of ' + hotel.name }, [
        h('img', { src: safeUrl(photos[0].thumb) || safeUrl(photos[0].url), alt: photos[0].alt || hotel.name + ' photo', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer' }),
        h('span', { class: 'count', text: photos.length + ' photos' })
      ]);
      heroBtn.addEventListener('click', function () { openLightbox(photos, 0, hotel.name, heroBtn); });
      card.appendChild(heroBtn);
    } else {
      card.appendChild(h('div', { class: 'td-nophoto', text: 'Photos not verified' }));
    }
    var body = h('div', { class: 'body' });
    body.appendChild(h('h5', { text: hotel.name }));
    body.appendChild(h('div', { class: 'rating' }, isNum(hotel.rating)
      ? ['\u2605 ' + hotel.rating.toFixed(1) + ' ', h('span', { text: isNum(hotel.review_count) ? '(' + Math.round(hotel.review_count).toLocaleString('en-US') + ' Google reviews)' : '(Google)' })]
      : [notVerified('rating')]));

    var rate = h('div', { class: 'rate-block' });
    var stay = fmtRange(hotel.rate_check_in, hotel.rate_check_out);
    if (isNum(hotel.nightly_rate) && !stale) {
      rate.appendChild(h('div', { class: 'price' }, [h('small', { text: 'Starting from, per night, 1 room (2 adults)' }), document.createTextNode(money(hotel.nightly_rate))]));
      rate.appendChild(h('div', { class: 'meta', text: (stay ? 'Rate checked for ' + stay + '. ' : '') + 'Subject to change.' }));
      rate.appendChild(est(hotel.nightly_rate, 'room'));
    } else {
      rate.appendChild(h('div', { class: 'price' }, [h('small', { text: 'Nightly rate' }), notVerified(stale ? '(older than ' + staleLabel() + ')' : '')]));
    }
    body.appendChild(rate);

    (hotel.reviews || []).slice(0, 2).forEach(function (rv) {
      if (!rv || !rv.text) return;
      var who = [rv.author, (rv.source || 'Google') + ' review', rv.date].filter(Boolean).join(', ');
      body.appendChild(h('blockquote', null, ['\u201C' + rv.text + '\u201D', h('cite', { text: '\u2014 ' + who + (isNum(rv.rating) ? ' \u2022 ' + rv.rating + '/5' : '') })]));
    });

    if (Array.isArray(hotel.calendar) && hotel.calendar.length) {
      var det = h('details', null, [h('summary', { text: 'Cheapest dates' })]);
      var built = false;
      det.addEventListener('toggle', function () {
        if (!det.open || built) return;
        built = true;
        var hstale = isStale(hotel.price_updated_at);
        var line = h('p', { class: 'meta', 'aria-live': 'polite', text: hstale ? 'Prices older than ' + staleLabel() + ': not verified.' : 'Pick a date to see its nightly rate.' });
        var heat = buildHeat(hotel.calendar, {
          label: function (it) { return fmtDay(it.date, true) + ', from ' + money(it.price) + ' per night'; },
          onPick: function (it) {
            line.textContent = fmtDay(it.date, true) + ': from ' + money(it.price) + ' per night (1 night, 2 adults, subject to change)';
          }
        });
        if (!heat) { det.appendChild(h('p', { class: 'meta' }, [notVerified('(no calendar prices returned)')])); return; }
        var holder = h('div', { class: hstale ? 'td-cal-wrap is-stale' : '' }, [heat.el, heat.legend]);
        det.appendChild(holder); det.appendChild(line);
      });
      body.appendChild(det);
    }

    var linkUrl = safeUrl(hotel.link);
    body.appendChild(ctaLink('Plan this trip with Phoenix', function (n) {
      return mailHref('Trip inquiry: ' + hotel.name + ', ' + dest.name, [
        'Hi Phoenix Travel,', '', "I'd like help planning a stay.",
        'Destination: ' + dest.name,
        'Hotel shown: ' + hotel.name,
        'Dates: ' + (stay || 'flexible'),
        'Rate shown: ' + (isNum(hotel.nightly_rate) && !stale ? 'starting from ' + money(hotel.nightly_rate) + ' per night (Google Hotels via SerpApi, updated ' + fmtUpdated(hotel.price_updated_at) + ', subject to change)' : 'not verified'),
        n > 1 ? 'Travelers: ' + n : null, '',
        'I understand planning fees apply and that Phoenix does not sell rooms directly.'
      ]);
    }));
    if (linkUrl) body.appendChild(h('a', { class: 'td-sub', href: linkUrl, target: '_blank', rel: 'noopener noreferrer', text: 'Hotel website' }));
    card.appendChild(body);
    return card;
  }

  /* ---------- Lightbox ---------- */
  var lb = { photos: [], i: 0, opener: null };
  function lbShow() {
    var p = lb.photos[lb.i];
    var img = $('td-lb-img'), cap = $('td-lb-cap');
    img.onerror = function () { cap.textContent = 'This photo could not be loaded.'; };
    img.alt = p.alt || lb.title + ' photo ' + (lb.i + 1);
    img.referrerPolicy = 'no-referrer';
    img.src = safeUrl(p.url) || safeUrl(p.thumb);
    cap.textContent = lb.title + ' \u2022 photo ' + (lb.i + 1) + ' of ' + lb.photos.length + (p.alt ? ' \u2022 ' + p.alt : '');
  }
  function openLightbox(photos, i, title, opener) {
    var dlg = $('td-lb');
    if (!dlg || typeof dlg.showModal !== 'function') { var u = safeUrl(photos[i].url); if (u) window.open(u, '_blank', 'noopener'); return; }
    lb = { photos: photos, i: i, title: title, opener: opener };
    lbShow();
    dlg.showModal();
    $('td-lb-close').focus();
  }
  function initLightbox() {
    var dlg = $('td-lb');
    if (!dlg) return;
    function step(d) { lb.i = (lb.i + d + lb.photos.length) % lb.photos.length; lbShow(); }
    $('td-lb-prev').addEventListener('click', function () { step(-1); });
    $('td-lb-next').addEventListener('click', function () { step(1); });
    $('td-lb-close').addEventListener('click', function () { dlg.close(); });
    dlg.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    });
    dlg.addEventListener('click', function (e) { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener('close', function () { if (lb.opener && lb.opener.focus) lb.opener.focus(); });
  }

  /* ---------- init ---------- */
  function safely(fn, data, boxId) {
    try { fn(data); } catch (e) { var b = $(boxId); if (b) setState(b, 'error', ERR); }
  }
  function init() {
    if (!$('travel-data')) return;
    var t = $('td-travelers');
    t.addEventListener('input', function () {
      var n = Math.floor(+t.value);
      travelers = n >= 1 && n <= 50 ? n : 1;
      refreshEstimates();
    });
    ['td-f-budget', 'td-f-month', 'td-f-interest', 'td-f-nonstop', 'td-f-planned'].forEach(function (id) {
      $(id).addEventListener('change', function () { explore.shown = 12; drawExplore(); });
    });
    initLightbox();
    Promise.all([loadJSON('fares'), loadJSON('explore'), loadJSON('calendar'), loadJSON('stays')]).then(function (r) {
      r.forEach(useStale);
      safely(renderFares, r[0], 'td-fares-body');
      safely(renderExplore, r[1], 'td-explore-body');
      safely(renderCalendar, r[2], 'td-cal-body');
      safely(renderStays, r[3], 'td-stays-body');
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
