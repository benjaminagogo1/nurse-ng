/* Only explicit, server-idempotent operations enter this queue. */
(() => {
  'use strict';
  const app = window.NurseOffline, store = app.store, TTL = 30 * 86400000;
  let running = false, timer;
  const persist = (op, fence) => store.put('operation', op.id, op, {ttl: TTL}, fence);
  async function session() {
    const response = await app.fetch('/offline/session');
    if (response.status === 401 || response.status === 403) {
      await store.clear(); throw new Error('Sign in again. Access to this session’s offline data has been cleared.');
    }
    if (!response.ok) throw new Error('Your session could not be checked. Try again when connected.');
    const identity = await response.json();
    if (identity.scope !== store.scope) {
      await store.clear(); throw new Error('The signed-in account changed. Offline access has been cleared.');
    }
    return identity;
  }
  async function queue(kind, target, title, payload, metadata = {}, draft) {
    if (!await app.ready || !store.available) throw new Error('Sign in while connected to enable local saving.');
    return store.withLock('changes', fence => enqueue(kind, target, title, payload, metadata, draft, fence));
  }
  async function enqueue(kind, target, title, payload, metadata, draft, fence) {
    const existing = await store.list('operation');
    if (existing.some(row => row.value.target === target && !['confirmed', 'dismissed'].includes(row.value.status))) {
      throw new Error('Review the existing change for this item in Offline & sync before making another.');
    }
    const op = {id: crypto.randomUUID(), kind, target, title, payload, status: 'pending',
      attempts: 0, next: 0, created: Date.now(), message: 'Saved locally · pending synchronization', metadata};
    if (draft) {
      const current = await store.get('draft', draft.id);
      if (current?.version !== draft.version) throw new Error('This draft changed in another tab. Open the latest draft in Offline & sync before sending.');
      // The publication intent and the draft's pending state must survive together.
      await store.putMany([
        {kind: 'operation', id: op.id, value: op, options: {ttl: TTL}},
        {kind: 'draft', id: draft.id, value: {...draft, operation: op.id}, options: {ttl: 7 * 86400000}},
      ], fence);
    } else await persist(op, fence);
    app.notice('Saved locally. The server has not confirmed this change yet.');
    navigator.serviceWorker?.ready.then(reg => reg.sync?.register('nurse-offline-sync')).catch(() => {});
    schedule(1000);
    return op;
  }
  function schedule(delay = 30000) { clearTimeout(timer); timer = setTimeout(() => sync().catch(() => {}), delay); }
  async function sync(manual = false) {
    if (running || !store.available || !navigator.onLine) return;
    running = true; clearTimeout(timer);
    try {
      await store.withLock('sync', async fence => {
        const pending = (await store.list('operation')).map(row => row.value)
          .filter(op => ['pending', 'syncing'].includes(op.status) && (manual || op.next <= Date.now()));
        if (!pending.length) return;
        const identity = await session();
        for (const op of pending.sort((a, b) => a.created - b.created)) {
          if (!store.available) break;
          op.status = 'syncing'; op.attempts++; op.message = 'Synchronizing…'; await persist(op, fence);
          let response, body;
          try {
            if (op.kind === 'reel') await app.transferReel(op, identity, async message => {
              op.message = message; await persist(op, fence);
            }, fence);
            await fence.check();
            response = await app.fetch('/offline/operations', {method: 'POST',
              headers: {'Content-Type': 'application/json', 'X-CSRF-Token': identity.csrf, 'X-Offline-Scope': identity.scope},
              body: JSON.stringify({operation_id: op.id, kind: op.kind, payload: op.payload})});
            body = await response.json();
          } catch (error) {
            response = error.response; body = error.body;
            // A lost response is an unknown outcome; retain this exact UUID/payload.
          }
          if (!store.available) break;
          if (response?.ok && body?.status === 'confirmed') {
            op.status = 'confirmed'; op.message = body.result.message; op.result = body.result;
            await persist({...op, payload: null}, fence);
            document.dispatchEvent(new CustomEvent('nurse:operation-confirmed', {detail: op}));
            store.announce('confirmed', {id: op.id});
          } else if (!response || !body || response.status >= 500 || [408, 425, 429].includes(response.status)) {
            op.status = 'pending';
            const retryAfter = Number(response?.headers.get('Retry-After')) || 0;
            op.next = Date.now() + Math.max(retryAfter * 1000, Math.min(300000, 2000 * 2 ** Math.min(op.attempts, 7)) * (0.8 + Math.random() * 0.4));
            op.message = 'Awaiting server confirmation. Will retry when connected.'; await persist(op, fence);
            break;
          } else if (response.status === 401) {
            await store.clear(); app.notice('Your sign-in session changed. Reconnect and sign in again.', 'warning'); break;
          } else {
            op.status = response.status === 409 ? 'conflict' : 'failed';
            op.message = body.message || body.detail || 'This change was rejected. Review it before trying again.';
            op.current = body.current; await persist(op, fence);
          }
        }
      }, {ifAvailable: true});
    } catch (error) { if (manual) app.notice(error.message, 'warning'); }
    finally { running = false; if (store.available) schedule(); }
  }
  async function retry(id) {
    await store.withLock('changes', async fence => {
      const op = await store.get('operation', id);
      if (!op || op.status !== 'failed') return;
      op.status = 'pending'; op.next = 0; await persist(op, fence);
    });
    await sync(true);
  }
  async function dismiss(id, fence) {
    const action = async lease => {
      const op = await store.get('operation', id);
      if (!op || !['failed', 'conflict', 'confirmed'].includes(op.status)) return;
      op.status = 'dismissed'; op.payload = null; await persist(op, lease);
    };
    return fence ? action(fence) : store.withLock('changes', action);
  }
  Object.assign(app, {queue, sync, session, retry, dismiss});
  document.addEventListener('nurse:sync-request', () => sync(true).catch(() => {}));
  document.querySelector('[data-offline-sync]')?.addEventListener('click', () => sync(true).catch(() => {}));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) sync().catch(() => {}); });
  app.ready.then(enabled => { if (enabled) schedule(1500); });
  window.addEventListener('pagehide', () => clearTimeout(timer));
})();
