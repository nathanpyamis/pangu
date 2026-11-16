/*
 * MiniMap: a tiny tap-to-place map with no third-party library.
 * Used by the field agent app and the public Join form.
 *
 *   const map = MiniMap(document.getElementById('map'), {
 *     onChange: (pt) => { pt.lat, pt.lon, pt.source ('GPS' | 'MAP'), pt.accuracy }
 *   });
 *   map.setPoint(-6.73, 147.0, { zoom: 16, source: 'GPS', accuracy: 12 });
 *   map.clear();
 *
 * Map pictures come from OpenStreetMap and need signal. With no signal the
 * map says so, and a GPS point (which needs no signal) is still recorded.
 */
(function () {
  'use strict';

  const TILE = 256;
  const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const PNG_CENTRE = { lat: -6.4, lon: 147.2, zoom: 5 };
  const MIN_Z = 4, MAX_Z = 18;

  const worldX = (lon, z) => (lon + 180) / 360 * TILE * 2 ** z;
  const worldY = (lat, z) => {
    const r = lat * Math.PI / 180;
    return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * TILE * 2 ** z;
  };
  const lonOf = (x, z) => x / (TILE * 2 ** z) * 360 - 180;
  const latOf = (y, z) => {
    const n = Math.PI - 2 * Math.PI * y / (TILE * 2 ** z);
    return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  };

  function MiniMap(el, opts = {}) {
    el.classList.add('minimap');
    el.innerHTML =
      '<div class="mm-tiles"></div>' +
      '<div class="mm-pin" hidden></div>' +
      '<div class="mm-zoom"><button type="button" data-z="1" aria-label="Zoom in">+</button>' +
      '<button type="button" data-z="-1" aria-label="Zoom out">&minus;</button></div>' +
      '<div class="mm-msg" hidden></div>' +
      '<div class="mm-attr">&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a></div>';
    const tiles = el.querySelector('.mm-tiles');
    const pinEl = el.querySelector('.mm-pin');
    const msg = el.querySelector('.mm-msg');

    let z = PNG_CENTRE.zoom;
    let cx = worldX(PNG_CENTRE.lon, z), cy = worldY(PNG_CENTRE.lat, z);
    let pin = null;                 // { lat, lon, source, accuracy }
    const cache = new Map();        // "z/x/y" -> <img>
    let failed = 0, loaded = 0;

    function showMsg(text) { msg.textContent = text || ''; msg.hidden = !text; }

    function render() {
      const w = el.clientWidth, h = el.clientHeight;
      if (!w || !h) return;
      const left = cx - w / 2, top = cy - h / 2;
      const n = 2 ** z;
      const x0 = Math.floor(left / TILE), x1 = Math.floor((left + w) / TILE);
      const y0 = Math.max(0, Math.floor(top / TILE)), y1 = Math.min(n - 1, Math.floor((top + h) / TILE));
      const keep = new Set();
      for (let tx = x0; tx <= x1; tx++) {
        for (let ty = y0; ty <= y1; ty++) {
          const wx = ((tx % n) + n) % n;
          const key = `${z}/${wx}/${ty}/${tx}`;
          keep.add(key);
          let img = cache.get(key);
          if (!img) {
            img = new Image(TILE, TILE);
            img.alt = '';
            img.draggable = false;
            img.onload = () => { img.style.visibility = ''; loaded++; showMsg(''); };
            img.style.visibility = 'hidden';            // no broken-image icons while loading or offline
            img.onerror = () => {
              failed++;
              if (!loaded) showMsg('Map needs signal. A GPS point is still saved.');
            };
            img.src = TILE_URL.replace('{z}', z).replace('{x}', wx).replace('{y}', ty);
            cache.set(key, img);
            tiles.appendChild(img);
          }
          img.style.transform = `translate(${Math.round(tx * TILE - left)}px, ${Math.round(ty * TILE - top)}px)`;
        }
      }
      for (const [key, img] of cache) {
        if (!keep.has(key)) { img.remove(); cache.delete(key); }
      }
      if (pin) {
        pinEl.hidden = false;
        pinEl.style.transform = `translate(${Math.round(worldX(pin.lon, z) - left)}px, ${Math.round(worldY(pin.lat, z) - top)}px)`;
      } else {
        pinEl.hidden = true;
      }
    }

    function zoomTo(nz, ax, ay) {
      nz = Math.max(MIN_Z, Math.min(MAX_Z, nz));
      if (nz === z) return;
      // keep the point under (ax, ay) - default the centre - in place
      const w = el.clientWidth, h = el.clientHeight;
      ax = ax == null ? w / 2 : ax; ay = ay == null ? h / 2 : ay;
      const lon = lonOf(cx - w / 2 + ax, z), lat = latOf(cy - h / 2 + ay, z);
      z = nz;
      cx = worldX(lon, z) - ax + w / 2;
      cy = worldY(lat, z) - ay + h / 2;
      render();
    }

    function place(lat, lon, source, accuracy) {
      pin = { lat: +lat.toFixed(6), lon: +lon.toFixed(6), source, accuracy: accuracy == null ? null : Math.round(accuracy) };
      render();
      if (opts.onChange) opts.onChange({ ...pin });
    }

    // Drag to pan, tap to place the pin.
    let drag = null;
    el.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.mm-zoom, .mm-attr')) return;
      drag = { x: e.clientX, y: e.clientY, cx, cy, moved: false, id: e.pointerId };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener('pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 6) drag.moved = true;
      if (drag.moved) { cx = drag.cx - dx; cy = drag.cy - dy; render(); }
    });
    el.addEventListener('pointerup', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      if (!drag.moved) {
        const r = el.getBoundingClientRect();
        const px = cx - r.width / 2 + (e.clientX - r.left);
        const py = cy - r.height / 2 + (e.clientY - r.top);
        place(latOf(py, z), lonOf(px, z), 'MAP', null);
      }
      drag = null;
    });
    el.addEventListener('pointercancel', () => { drag = null; });
    el.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomTo(z + (e.deltaY < 0 ? 1 : -1), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    el.querySelectorAll('.mm-zoom button').forEach((b) =>
      b.addEventListener('click', () => zoomTo(z + Number(b.dataset.z))));

    if ('ResizeObserver' in window) new ResizeObserver(render).observe(el);
    else window.addEventListener('resize', render);
    setTimeout(render, 0);

    return {
      setPoint(lat, lon, o = {}) {
        if (lat == null || lon == null || lat === '' || lon === '') return;
        lat = Number(lat); lon = Number(lon);
        if (o.zoom) z = o.zoom;
        cx = worldX(lon, z); cy = worldY(lat, z);
        place(lat, lon, o.source || 'MAP', o.accuracy);
      },
      centreOn(lat, lon, zoom) {
        z = zoom || z; cx = worldX(lon, z); cy = worldY(lat, z); render();
      },
      clear() {
        pin = null;
        z = PNG_CENTRE.zoom; cx = worldX(PNG_CENTRE.lon, z); cy = worldY(PNG_CENTRE.lat, z);
        render();
        if (opts.onChange) opts.onChange(null);
      },
      getPoint() { return pin ? { ...pin } : null; },
      refresh: render,
    };
  }

  /**
   * One GPS reading. Works with no data signal (GPS is satellite-based), but
   * needs location turned on and the officer to allow it.
   */
  MiniMap.locate = function (timeoutMs = 20000) {
    return new Promise((resolve, reject) => {
      if (!('geolocation' in navigator)) { reject(new Error('This phone cannot share its location.')); return; }
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }),
        (err) => reject(new Error(err.code === 1
          ? 'Location permission was refused. Allow location for this app in the phone settings.'
          : 'Could not get a GPS fix. Step outside, wait a moment and try again.')),
        { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 60000 });
    });
  };

  window.MiniMap = MiniMap;
})();
