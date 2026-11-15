/* Pangu Pati site behaviour. Progressive: every panel and form works without JS. */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const PANELS = ['about', 'policies', 'candidates', 'news', 'join', 'contact'];

  // ---- Navbar: solid on scroll, mobile menu -------------------------------
  const nav = $('#navbar');
  const onScroll = () => nav && nav.classList.toggle('scrolled', window.scrollY > 30);
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  const toggle = $('.nav-toggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      const open = !document.body.classList.contains('nav-open');
      document.body.classList.toggle('nav-open', open);
      toggle.setAttribute('aria-expanded', String(open));
    });
    $$('.nav-links a').forEach((a) => a.addEventListener('click', () => {
      document.body.classList.remove('nav-open');
      toggle.setAttribute('aria-expanded', 'false');
    }));
  }

  // ---- Panels (Kitzu-style lightboxes) ------------------------------------
  // CSS :target already shows them; JS adds scroll lock, Escape and the
  // server-opened state (after a form post with errors or success).
  function syncPanels() {
    const id = location.hash.replace('#', '');
    let anyOpen = false;
    PANELS.forEach((p) => {
      const el = document.getElementById(p);
      if (!el) return;
      const open = p === id;
      if (!open) el.classList.remove('is-open');
      if (open || el.classList.contains('is-open')) anyOpen = true;
    });
    document.body.classList.toggle('panel-open', anyOpen);
  }
  const serverOpen = $('.panel.is-open');
  if (serverOpen && location.hash !== '#' + serverOpen.id) {
    history.replaceState(null, '', '#' + serverOpen.id);
  }
  window.addEventListener('hashchange', syncPanels);
  syncPanels();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.body.classList.contains('panel-open')) location.hash = 'home';
  });

  // ---- Rotating headline (typed, like Kitzu) ------------------------------
  const rot = $('.rotator');
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (rot && !reduce) {
    const lines = (rot.dataset.lines || '').split('|').map((s) => s.trim()).filter(Boolean);
    if (lines.length > 1) {
      let i = 0, ch = lines[0].length, deleting = true;
      const tick = () => {
        const word = lines[i];
        if (deleting) {
          ch -= 1;
          if (ch <= 0) { deleting = false; i = (i + 1) % lines.length; }
        } else {
          ch += 1;
          if (ch >= lines[i].length) { deleting = true; rot.textContent = lines[i]; return setTimeout(tick, 2200); }
        }
        rot.textContent = (deleting ? word : lines[i]).slice(0, Math.max(ch, 0)) || ' ';
        setTimeout(tick, deleting ? 35 : 70);
      };
      setTimeout(tick, 2500);
    }
  }

  // ---- Election countdown -------------------------------------------------
  const cd = $('.countdown');
  if (cd && cd.dataset.date) {
    const target = new Date(cd.dataset.date + 'T08:00:00+10:00').getTime(); // Port Moresby time
    const set = (u, v) => { const el = $(`[data-unit="${u}"]`, cd); if (el) el.textContent = v; };
    const draw = () => {
      const ms = Math.max(0, target - Date.now());
      set('days', Math.floor(ms / 864e5));
      set('hours', Math.floor(ms / 36e5) % 24);
      set('minutes', Math.floor(ms / 6e4) % 60);
    };
    draw();
    setInterval(draw, 30000);
  }

  // ---- Join form: shrink the photo before upload (saves mobile data) ------
  const form = $('[data-join-form]');
  if (form) {
    const input = $('input[type="file"]', form);
    const preview = $('[data-photo-preview]', form);
    const status = $('[data-photo-status]', form);

    async function compress(file, size = 300) {
      let src;
      try { src = await createImageBitmap(file, { imageOrientation: 'from-image' }); }
      catch (_) {
        src = await new Promise((res, rej) => {
          const img = new Image(); img.onload = () => res(img); img.onerror = rej;
          img.src = URL.createObjectURL(file);
        });
      }
      const side = Math.min(src.width, src.height);
      const sx = (src.width - side) / 2;
      const sy = src.height > src.width ? (src.height - side) * 0.35 : 0;
      const c = document.createElement('canvas'); c.width = size; c.height = size;
      const ctx = c.getContext('2d'); ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(src, sx, sy, side, side, 0, 0, size, size);
      return new Promise((res) => c.toBlob(res, 'image/jpeg', 0.8));
    }

    if (input) input.addEventListener('change', async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      try {
        status.textContent = 'Preparing photo…';
        const blob = await compress(file);
        if (blob && window.DataTransfer) {
          const dt = new DataTransfer();
          dt.items.add(new File([blob], 'photo.jpg', { type: 'image/jpeg' }));
          input.files = dt.files;
        }
        preview.src = URL.createObjectURL(blob || file);
        preview.hidden = false;
        status.textContent = `Photo ready (${Math.round((blob || file).size / 1024)} KB)`;
      } catch (_) {
        status.textContent = ''; // keep the original file; the server will resize it
      }
    });

    form.addEventListener('submit', () => {
      const btn = $('button[type="submit"]', form);
      if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
    });
  }
})();

/* Login menu: close when clicking elsewhere. */
document.addEventListener('click', function (e) {
  document.querySelectorAll('details.login[open]').forEach(function (d) {
    if (!d.contains(e.target)) d.removeAttribute('open');
  });
});

/* Join form: residential location (map tap or phone GPS). */
(function () {
  const box = document.querySelector('[data-map]');
  if (!box || !window.MiniMap) return;
  const form = box.closest('form');
  const set = (name, v) => { form.elements[name].value = v == null ? '' : v; };
  const text = form.querySelector('[data-loc-text]');
  const map = MiniMap(box, {
    onChange(pt) {
      set('latitude', pt && pt.lat); set('longitude', pt && pt.lon);
      set('location_accuracy_m', pt && pt.accuracy); set('location_source', pt && pt.source);
      text.textContent = pt ? `Point saved: ${pt.lat.toFixed(5)}, ${pt.lon.toFixed(5)}` +
        (pt.accuracy ? ` (±${pt.accuracy} m)` : '') : 'No point yet';
    },
  });
  if (box.dataset.lat && box.dataset.lon) map.setPoint(box.dataset.lat, box.dataset.lon, { zoom: 16 });
  form.querySelector('[data-locate]').addEventListener('click', async (e) => {
    const b = e.currentTarget; b.disabled = true; text.textContent = 'Finding your location…';
    try {
      const p = await MiniMap.locate();
      map.setPoint(p.lat, p.lon, { zoom: 17, source: 'GPS', accuracy: p.accuracy });
    } catch (err) { text.textContent = err.message; }
    b.disabled = false;
  });
  form.querySelector('[data-loc-clear]').addEventListener('click', () => map.clear());
  // The Join panel starts hidden; redraw when it opens.
  window.addEventListener('hashchange', () => setTimeout(map.refresh, 350));
})();
