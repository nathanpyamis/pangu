/*
 * Field agent data layer: auth, photo compression, outbox queue, sync engine.
 * No UI code here. The UI listens for the `outbox-changed` and `sync-state`
 * events on window.
 */
(function () {
  'use strict';

  const { store, getMeta, setMeta, delMeta } = window.AgentDB;

  const CONFIG = {
    batchSize: 5,
    requestTimeoutMs: 60000,     // generous: rural 3G/EDGE
    autoSyncIntervalMs: 90000,
    photo: { size: 300, targetBytes: 35 * 1024, startQuality: 0.75, minQuality: 0.4 },
    keepSyncedDays: 30,
    maxBackoffMs: 30 * 60 * 1000,
  };

  const API = {
    token: '/api/auth/token/',
    refresh: '/api/auth/token/refresh/',
    lookup: '/api/geo/electorates/',
    sync: '/api/members/sync/',
    history: '/api/members/sync/history/',
  };

  const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }));

  // -------------------------------------------------------------------------
  // Utilities
  // -------------------------------------------------------------------------

  function uuid4() {
    if (crypto.randomUUID) return crypto.randomUUID();
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('');
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }

  async function fetchWithTimeout(url, opts = {}, ms = CONFIG.requestTimeoutMs) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal, cache: 'no-store' });
    } finally {
      clearTimeout(t);
    }
  }

  // Ask the browser not to evict our IndexedDB when the phone runs low on
  // space; unsynced registrations live only here.
  async function requestPersistentStorage() {
    try {
      if (navigator.storage && navigator.storage.persist) {
        return await navigator.storage.persist();
      }
    } catch (_) { /* not fatal */ }
    return false;
  }

  // -------------------------------------------------------------------------
  // Auth (SimpleJWT). Login needs signal once; the 30-day refresh token then
  // lets the agent sync for a month without re-entering a password.
  // -------------------------------------------------------------------------

  // -------------------------------------------------------------------------
  // Session. Nothing in the app is visible without a login, and each officer
  // only ever sees and sends their own registrations.
  // -------------------------------------------------------------------------

  async function currentUser() {
    return (await getMeta('tokens')) ? getMeta('username') : null;
  }

  // Forget the session and everything about the previous officer except their
  // unsent registrations (kept, hidden, and sent only after they log in again).
  async function lockSession(reason) {
    await delMeta('tokens');
    await delMeta('username');
    await delMeta('last_sync_at');
    await store.del('lookup', 'geo');
    await setMeta('locked_reason', reason || '');
    emit('locked', { reason: reason || '' });
  }

  async function login(username, password) {
    const res = await fetchWithTimeout(API.token, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (res.status === 401) throw new Error('Wrong username or password.');
    if (res.status === 403 || res.status === 429) {
      // 403: account disabled, card suspended or no electorate; 429: too many attempts
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || (res.status === 429
        ? 'Too many attempts. Wait a minute and try again.'
        : 'Your access to member registration has been stopped.'));
    }
    if (!res.ok) throw new Error(`Login failed (${res.status}).`);
    const { access, refresh } = await res.json();
    const previous = await getMeta('username');
    if (previous && previous !== username) await store.del('lookup', 'geo');
    await setMeta('tokens', { access, refresh, refreshed_at: Date.now() });
    await setMeta('username', username);
    await setMeta('needs_login', false);
    await delMeta('locked_reason');
    // Records saved by an older version of the app have no owner: give them to this officer.
    const orphans = (await store.all('outbox')).filter((r) => !r.agent).map((r) => r.id);
    if (orphans.length) await store.updateMany('outbox', orphans, { agent: username });
    await refreshLookup();
    return true;
  }

  async function logout() {
    // Unsynced records are kept (they belong to the party), but hidden until
    // the same officer logs in again.
    await lockSession('');
  }

  async function refreshAccessToken() {
    const tokens = await getMeta('tokens');
    if (!tokens || !tokens.refresh) return null;
    const res = await fetchWithTimeout(API.refresh, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh: tokens.refresh }),
    }, 30000);
    if (res.status === 401) {
      // Expired after 30 days, or access withdrawn by an administrator.
      const body = await res.json().catch(() => ({}));
      await lockSession(body.detail && /stopped/i.test(body.detail)
        ? body.detail : 'Your session has ended. Log in again to continue.');
      return null;
    }
    if (!res.ok) throw new Error(`Token refresh failed (${res.status})`);
    const data = await res.json();
    const updated = { ...tokens, access: data.access, refreshed_at: Date.now() };
    if (data.refresh) updated.refresh = data.refresh;  // if rotation is ever enabled
    await setMeta('tokens', updated);
    return updated.access;
  }

  class AuthRequired extends Error {}

  async function authFetch(url, opts = {}) {
    let tokens = await getMeta('tokens');
    if (!tokens) throw new AuthRequired('Please log in.');
    const call = (access) => fetchWithTimeout(url, {
      ...opts,
      headers: { ...(opts.headers || {}), Authorization: `Bearer ${access}` },
    });
    let res = await call(tokens.access);
    if (res.status === 401) {
      const access = await refreshAccessToken();
      if (!access) throw new AuthRequired('Session expired. Log in again to sync.');
      res = await call(access);
    }
    return res;
  }

  async function refreshLookup() {
    const res = await authFetch(API.lookup);
    if (res.status === 403) {
      const body = await res.json().catch(() => ({}));
      const reason = body.detail || 'Your access to member registration has been stopped.';
      await lockSession(reason);
      throw new AuthRequired(reason);
    }
    if (!res.ok) throw new Error('Could not download electorate list.');
    const data = await res.json();
    await store.put('lookup', { key: 'geo', value: data, fetched_at: Date.now() });
    emit('lookup-changed');
    return data;
  }

  async function getLookup() {
    const row = await store.get('lookup', 'geo');
    return row ? row.value : null;
  }

  // -------------------------------------------------------------------------
  // Photo compression: centre-crop square -> 300x300 JPEG, ~30 KB.
  // Pure <canvas>; no third-party library to vendor or cache.
  // -------------------------------------------------------------------------

  async function loadBitmap(file) {
    if ('createImageBitmap' in window) {
      try {
        // Applies EXIF orientation so portrait phone shots aren't sideways
        return await createImageBitmap(file, { imageOrientation: 'from-image' });
      } catch (_) { /* fall through (older Safari) */ }
    }
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read photo.')); };
      img.src = url;
    });
  }

  function canvasToBlob(canvas, type, quality) {
    return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
  }

  async function compressPhoto(file) {
    const { size, targetBytes, startQuality, minQuality } = CONFIG.photo;
    const src = await loadBitmap(file);
    const w = src.width, h = src.height;
    const side = Math.min(w, h);
    // Bias crop slightly upward: faces sit in the upper part of portrait shots
    const sx = (w - side) / 2;
    const sy = h > w ? Math.max(0, (h - side) * 0.35) : 0;

    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, size, size);
    ctx.drawImage(src, sx, sy, side, side, 0, 0, size, size);
    if (src.close) src.close();

    let q = startQuality;
    let blob = await canvasToBlob(canvas, 'image/jpeg', q);
    while (blob && blob.size > targetBytes && q > minQuality) {
      q = Math.max(minQuality, q - 0.1);
      blob = await canvasToBlob(canvas, 'image/jpeg', q);
    }
    if (!blob) throw new Error('Photo compression failed.');
    return blob;
  }

  // -------------------------------------------------------------------------
  // Outbox
  // -------------------------------------------------------------------------

  /**
   * Save a registration locally. Works with zero signal.
   * `existingId` re-queues a rejected record after the agent fixes it
   * (same UUID, so the server still sees one person).
   */
  async function queueMember(fields, photoBlob, existingId = null) {
    const me = await currentUser();
    if (!me) throw new Error('Log in first.');
    const id = existingId || uuid4();
    const prev = existingId ? await store.get('outbox', existingId) : null;
    if (prev && prev.agent && prev.agent !== me) throw new Error('That record belongs to another officer.');
    const data = {
      ...fields,
      id,
      client_created_at: prev ? prev.data.client_created_at : new Date().toISOString(),
    };
    await store.put('outbox', {
      id,
      data,
      photo: photoBlob || (prev && prev.photo) || null,
      status: 'pending',
      attempts: 0,
      next_attempt_at: 0,
      errors: null,
      created_at: prev ? prev.created_at : Date.now(),
      agent: me,
    });
    emit('outbox-changed');
    // Opportunistic: if there happens to be signal right now, send it.
    if (navigator.onLine) setTimeout(() => syncNow({ reason: 'queued' }), 500);
    return id;
  }

  async function myRows() {
    const me = await currentUser();
    if (!me) return [];
    return (await store.all('outbox')).filter((r) => r.agent === me);
  }

  // Unsent work saved by other officers on this phone: a count only, never details.
  async function othersWaiting() {
    const me = await currentUser();
    return (await store.all('outbox'))
      .filter((r) => r.agent && r.agent !== me && r.status !== 'synced').length;
  }

  async function counts() {
    const rows = await myRows();
    const n = (st) => rows.filter((r) => st.includes(r.status)).length;
    return { waiting: n(['pending', 'syncing', 'failed']), rejected: n(['rejected']), synced: n(['synced']) };
  }

  async function listOutbox() {
    return (await myRows()).sort((a, b) => b.created_at - a.created_at);
  }

  // -------------------------------------------------------------------------
  // Sync engine
  // -------------------------------------------------------------------------

  let syncing = false;

  function backoffMs(attempts) {
    // 30 s, 1 min, 2 min, 4 min ... capped at 30 min, with jitter
    const base = Math.min(CONFIG.maxBackoffMs, 30000 * 2 ** Math.max(0, attempts - 1));
    return base * (0.75 + Math.random() * 0.5);
  }

  async function nextBatch(force) {
    const now = Date.now();
    const me = await currentUser();
    const rows = (await store.byStatus(['pending', 'failed']))
      .filter((r) => r.agent === me)
      .sort((a, b) => a.created_at - b.created_at);
    return rows
      .filter((r) => force || !r.next_attempt_at || r.next_attempt_at <= now)
      .slice(0, CONFIG.batchSize);
  }

  function buildForm(batch) {
    const form = new FormData();
    form.append('records', JSON.stringify(batch.map((r) => r.data)));
    for (const r of batch) {
      if (r.photo) form.append(`photo_${r.id}`, r.photo, `${r.id}.jpg`);
    }
    return form;
  }

  // Strip personal data from the phone once the server has the record.
  function syncedStub(row, result) {
    return {
      id: row.id,
      data: {
        id: row.id,
        full_name: row.data.full_name,
        electorate: row.data.electorate,
        client_created_at: row.data.client_created_at,
      },
      photo: null,
      status: 'synced',
      server_status: result.status,
      flag_message: result.message || null,
      synced_at: Date.now(),
      created_at: row.created_at,
      attempts: row.attempts,
      next_attempt_at: 0,
      agent: row.agent,
    };
  }

  async function applyResults(batch, results) {
    const byId = new Map(results.map((r) => [String(r.id), r]));
    const updated = batch.map((row) => {
      const r = byId.get(row.id);
      if (!r) {
        // Server didn't mention it (shouldn't happen): retry later
        return { ...row, status: 'failed', next_attempt_at: Date.now() + 60000 };
      }
      if (r.status === 'rejected') return { ...row, status: 'rejected', errors: r.errors || {} };
      // created | already_synced | flagged -> server owns it now
      return syncedStub(row, r);
    });
    await store.putMany('outbox', updated);  // one atomic write
  }

  async function markBatchFailed(batch, message) {
    await store.updateMany('outbox', batch.map((r) => r.id), (row) => {
      const attempts = (row.attempts || 0) + 1;
      return { status: 'failed', attempts, last_error: message, next_attempt_at: Date.now() + backoffMs(attempts) };
    });
  }

  /**
   * Upload the outbox in small batches. Stops at the first network failure
   * (no point hammering a dead link); everything already sent stays sent.
   * `force` ignores backoff (manual "Sync Now" button).
   */
  async function syncNow({ force = false, reason = 'auto' } = {}) {
    if (syncing) return { skipped: 'already-running' };
    syncing = true;  // claim the lock BEFORE any await, or two triggers can both pass
    if (!(await getMeta('tokens'))) { syncing = false; return { needsLogin: true }; }
    emit('sync-state', { running: true, reason });

    const summary = { sent: 0, rejected: 0, error: null, needsLogin: false };
    try {
      for (;;) {
        const batch = await nextBatch(force);
        if (!batch.length) break;

        await store.updateMany('outbox', batch.map((r) => r.id), { status: 'syncing' });
        emit('outbox-changed');

        let res;
        try {
          res = await authFetch(API.sync, { method: 'POST', body: buildForm(batch) });
        } catch (err) {
          if (err instanceof AuthRequired) {
            await store.updateMany('outbox', batch.map((r) => r.id), { status: 'pending' });
            summary.needsLogin = true;
            summary.error = (await getMeta('locked_reason')) || err.message;
          } else {
            await markBatchFailed(batch, err.name === 'AbortError' ? 'Timed out' : 'No connection');
            summary.error = 'Connection lost. Will retry automatically.';
          }
          break;
        }

        if (res.status === 403) {
          // Access withdrawn (login disabled or card suspended). Keep every
          // record on the phone, untouched, and ask for a fresh login.
          const body = await res.json().catch(() => ({}));
          await store.updateMany('outbox', batch.map((r) => r.id), { status: 'pending' });
          summary.needsLogin = true;
          summary.error = body.detail || 'Your access to member registration has been stopped.';
          await lockSession(summary.error);
          break;
        }

        if (res.status === 200) {
          const body = await res.json();
          await applyResults(batch, body.results || []);
          summary.sent += (body.summary && (body.summary.created + body.summary.already_synced + body.summary.flagged)) || 0;
          summary.rejected += (body.summary && body.summary.rejected) || 0;
          await setMeta('last_sync_at', Date.now());
          summary.ok = true;
        } else if (res.status === 400 || res.status === 413) {
          // Whole batch refused (e.g. too large). Retry one-by-one next time.
          CONFIG.batchSize = 1;
          await markBatchFailed(batch, `Server refused batch (${res.status})`);
          summary.error = 'Server refused a batch; retrying smaller.';
          break;
        } else {
          await markBatchFailed(batch, `Server error ${res.status}`);
          summary.error = `Server error ${res.status}. Will retry.`;
          break;
        }
        emit('outbox-changed');
      }
    } finally {
      syncing = false;
      if ((summary.ok || reason === 'manual') && reason !== 'login') refreshLookupQuietly();
      emit('outbox-changed');
      emit('sync-state', { running: false, summary });
    }
    return summary;
  }

  // Called on start and after each sync, so a changed assignment (or a list
  // saved by an older version of the app) is replaced while there is signal.
  async function refreshLookupQuietly() {
    if (!navigator.onLine || !(await currentUser())) return;
    try {
      await refreshLookup();
    } catch (err) {
      if (err instanceof AuthRequired) return;   // lockSession already ran
    }
  }

  async function fetchHistory() {
    const res = await authFetch(API.history);
    if (!res.ok) throw new Error('Could not load history.');
    return res.json();
  }

  async function purgeOldSynced() {
    const cutoff = Date.now() - CONFIG.keepSyncedDays * 86400000;
    const old = (await store.byStatus(['synced']))
      .filter((r) => (r.synced_at || 0) < cutoff).map((r) => r.id);
    if (old.length) await store.delMany('outbox', old);
  }

  // A sync interrupted by closing the app leaves rows stuck in `syncing`.
  async function recoverStuck() {
    const stuck = (await store.byStatus(['syncing'])).map((r) => r.id);
    if (stuck.length) await store.updateMany('outbox', stuck, { status: 'pending' });
  }

  // -------------------------------------------------------------------------
  // Triggers
  // -------------------------------------------------------------------------

  async function start() {
    await recoverStuck();
    await purgeOldSynced();
    requestPersistentStorage();

    window.addEventListener('online', () => syncNow({ reason: 'online' }));
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && navigator.onLine) syncNow({ reason: 'resume' });
    });
    // navigator.onLine is unreliable (true on captive Wi-Fi / no-data SIMs),
    // so keep trying on an interval; backoff limits the cost.
    setInterval(() => { if (navigator.onLine) syncNow({ reason: 'interval' }); }, CONFIG.autoSyncIntervalMs);
    if (navigator.onLine) {
      await refreshLookupQuietly();
      syncNow({ reason: 'startup' });
    }
  }

  window.AgentSync = {
    start, login, logout, syncNow, queueMember, compressPhoto,
    counts, listOutbox, getLookup, refreshLookup, fetchHistory,
    currentUser, othersWaiting,
    isSyncing: () => syncing,
    getMeta,
  };
})();
