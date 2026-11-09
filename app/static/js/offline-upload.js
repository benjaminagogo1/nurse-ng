(() => {
  'use strict';
  const app = window.NurseOffline, store = app.store;
  async function rejected(response) {
    const body = await response.json().catch(() => ({message: 'The upload could not be verified.'}));
    const error = new Error(body.message); error.response = response; error.body = body; throw error;
  }
  app.transferReel = async (op, identity, report, fence) => {
    const path = '/offline/uploads/' + encodeURIComponent(op.payload.file_id);
    const headers = {'X-CSRF-Token': identity.csrf, 'X-Offline-Scope': identity.scope};
    await fence.check();
    const start = await app.fetch(path, {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'},
      body: JSON.stringify({size: op.payload.file_size})});
    if (!start.ok) await rejected(start);
    let state = await start.json();
    if (state.complete) return;
    for (let offset = state.received; offset < state.size; offset = state.received) {
      const bytes = await store.get('file-chunk', op.payload.file_id + ':' + offset);
      if (!bytes) await rejected(new Response(JSON.stringify({message: 'The saved video expired or was cleared. Save a new Reel draft.'}), {status: 410}));
      await report('Uploading saved video · ' + Math.floor(offset / state.size * 100) + '% received');
      const response = await app.fetch(path + '?offset=' + offset, {method: 'PUT', headers, body: bytes}, 60000);
      if (!response.ok) await rejected(response);
      state = await response.json();
      if (state.received <= offset) throw new Error('The upload has not advanced.');
    }
    await report('Video transferred. Awaiting server validation and confirmation.');
  };
  app.discardUpload = async id => {
    if (!navigator.onLine) return;
    const identity = await app.session();
    const response = await app.fetch('/offline/uploads/' + encodeURIComponent(id), {method: 'DELETE',
      headers: {'X-CSRF-Token': identity.csrf, 'X-Offline-Scope': identity.scope}});
    if (!response.ok) await rejected(response);
  };
})();
