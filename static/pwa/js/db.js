/*
 * Tiny promise wrapper over IndexedDB. Replaces Dexie so the agent app has
 * zero third-party files to download.
 *
 * Stores: outbox (key: id, index: status), meta (key: key), lookup (key: key)
 */
(function () {
  'use strict';

  const DB_NAME = 'pngp_agent';
  const DB_VERSION = 1;
  let conn = null;

  function open() {
    if (conn) return conn;
    conn = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('outbox')) {
          db.createObjectStore('outbox', { keyPath: 'id' }).createIndex('status', 'status');
        }
        if (!db.objectStoreNames.contains('meta')) db.createObjectStore('meta', { keyPath: 'key' });
        if (!db.objectStoreNames.contains('lookup')) db.createObjectStore('lookup', { keyPath: 'key' });
      };
      req.onsuccess = () => {
        const db = req.result;
        db.onversionchange = () => { db.close(); conn = null; };
        resolve(db);
      };
      req.onerror = () => { conn = null; reject(req.error); };
    });
    return conn;
  }

  // Run `work(store)` in one transaction. `work` must issue its requests
  // synchronously and may return an IDBRequest whose result is resolved.
  async function run(storeName, mode, work) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);
      let req;
      try { req = work(store); } catch (e) { tx.abort(); reject(e); return; }
      tx.oncomplete = () => resolve(req && 'result' in req ? req.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error('Transaction aborted'));
    });
  }

  const store = {
    get: (s, key) => run(s, 'readonly', (st) => st.get(key)),
    all: (s) => run(s, 'readonly', (st) => st.getAll()),
    byStatus: (statuses) => run('outbox', 'readonly', (st) => st.getAll())
      .then((rows) => rows.filter((r) => statuses.includes(r.status))),
    put: (s, value) => run(s, 'readwrite', (st) => st.put(value)),
    putMany: (s, values) => run(s, 'readwrite', (st) => { values.forEach((v) => st.put(v)); }),
    del: (s, key) => run(s, 'readwrite', (st) => st.delete(key)),
    delMany: (s, keys) => run(s, 'readwrite', (st) => { keys.forEach((k) => st.delete(k)); }),
    // Merge `changes` (object, or function(row) -> object) into each key, atomically.
    updateMany: (s, keys, changes) => run(s, 'readwrite', (st) => {
      keys.forEach((k) => {
        const r = st.get(k);
        r.onsuccess = () => {
          if (!r.result) return;
          const c = typeof changes === 'function' ? changes(r.result) : changes;
          st.put({ ...r.result, ...c });
        };
      });
    }),
  };
  store.update = (s, key, changes) => store.updateMany(s, [key], changes);

  async function getMeta(key, fallback = null) {
    const row = await store.get('meta', key);
    return row ? row.value : fallback;
  }
  const setMeta = (key, value) => store.put('meta', { key, value });
  const delMeta = (key) => store.del('meta', key);

  window.AgentDB = { store, getMeta, setMeta, delMeta };
})();
