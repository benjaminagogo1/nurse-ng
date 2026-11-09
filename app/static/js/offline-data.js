(() => {
  'use strict';
  const app = window.NurseOffline, store = app.store;
  const recordsHost = document.querySelector('[data-offline-records]');
  const operationsHost = document.querySelector('[data-offline-operations]');
  const editor = document.querySelector('[data-offline-editor]');
  let rendering = 0;
  let revalidating = false;
  const initialProfileForm = document.querySelector('[data-offline-profile]')?.closest('form');
  const initialProfileValues = initialProfileForm ? valuesFrom(initialProfileForm) : null;
  function node(tag, text, cls) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  }
  function button(label, action) {
    const element = node('button', label, 'btn btn-secondary'); element.type = 'button';
    element.addEventListener('click', () => Promise.resolve().then(action).catch(error => app.notice(error.message, 'warning')));
    return element;
  }
  function count(kind, value) {
    document.querySelectorAll('[data-offline-count="' + kind + '"]').forEach(element => {
      element.textContent = value === null ? '—' : String(value);
    });
  }
  function emptyState(kind, title, description, path, label) {
    const state = document.querySelector('#offline-empty-' + kind).content.firstElementChild.cloneNode(true);
    state.querySelector('h3').textContent = title;
    state.querySelector('p').textContent = description;
    if (path) { const link = node('a', label, 'text-link'); link.href = path; state.append(link); }
    return state;
  }
  async function refresh(path, explicit = false) {
    if (!store.available || !navigator.onLine) return;
    const owner = store.scope;
    const response = await app.fetch('/offline/data?path=' + encodeURIComponent(path));
    if (response.status === 401) { await store.clear(); return; }
    if (response.status === 404) {
      for (const row of await store.list('record')) if (row.value.path === path) await store.remove('record', row.id);
      return;
    }
    if (!response.ok) throw new Error('Saved information could not be refreshed.');
    const body = await response.json();
    if (body.scope !== owner || owner !== store.scope) return;
    // Replace the notification snapshot so revoked/removed sources do not linger.
    if (path === '/notifications') {
      for (const row of await store.list('record')) if (row.value.kind === 'notification') await store.remove('record', row.id);
    }
    for (const record of body.records) {
      if (record.kind === 'unavailable') await store.remove('record', record.key);
      else if (record.kind !== 'learning' || explicit) await store.put('record', record.key, record);
    }
    const records = await store.list('record');
    for (const row of records.sort((a, b) => b.saved - a.saved).slice(200)) await store.remove('record', row.id);
    if (explicit) app.notice('Downloaded to this browser for offline reading. Available for 24 hours.');
  }
  async function revalidate() {
    if (revalidating || !store.available || !navigator.onLine) return;
    revalidating = true;
    try {
      const records = await store.list('record');
      if (!records.length) return;
      await app.session();
      const paths = [...new Set(records.filter(row => row.value.kind !== 'learning')
        .map(row => row.value.kind === 'notification' ? '/notifications' : row.value.path))];
      for (const path of paths) {
        if (!store.available || !navigator.onLine) break;
        await refresh(path);
      }
    } catch { /* Keep last-known data on transport failure; session rejection clears it. */ }
    finally { revalidating = false; }
  }
  function valuesFrom(form) {
    const data = new FormData(form), values = {};
    for (const name of ['display_name', 'professional_status', 'headline', 'location', 'bio', 'qualification', 'years_experience', 'skills']) values[name] = data.get(name) || '';
    values.interests = data.getAll('interests').join(', ');
    return values;
  }
  async function saveProfile(form, base) {
    await app.queue('profile', 'profile:self', 'Professional profile', {base, values: valuesFrom(form)});
  }
  function editProfile(record, values = record.data.values, previous) {
    if (!editor) return;
    editor.replaceChildren(document.querySelector('#offline-profile-template').content.cloneNode(true));
    editor.hidden = false;
    const form = editor.querySelector('form');
    for (const control of form.elements) {
      if (control.name === 'interests') control.checked = (values.interests || '').split(', ').includes(control.value);
      else if (control.name in values) control.value = values[control.name] ?? '';
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      try {
        if (previous) await app.dismiss(previous.id);
        await saveProfile(form, record.data); editor.hidden = true;
      } catch (error) { app.notice(error.message, 'warning'); }
    });
    editor.scrollIntoView({block: 'start'}); form.querySelector('input')?.focus();
  }
  function describe(record, card) {
    const data = record.data;
    const actions = node('div', undefined, 'offline-card-actions');
    const details = node('details', undefined, 'offline-record-details');
    details.append(node('summary', record.kind === 'learning' ? 'Read saved guide' : 'View saved details'));
    if (record.kind === 'profile') {
      card.append(node('p', [data.values.display_name, data.values.headline, data.values.location].filter(Boolean).join(' · ')));
      actions.append(button('Edit saved profile', () => editProfile(record)));
    } else if (record.kind === 'public-profile') {
      for (const [name, value] of Object.entries(data)) if (value) details.append(node('p', name.replaceAll('_', ' ') + ': ' + value));
      card.append(details);
      actions.append(button('Queue connection request', () => app.queue('connection', record.key, 'Connection request', {profile_id: record.path.split('/').pop()})));
    } else if (record.kind === 'job') {
      card.append(node('p', [data.organization, data.location, data.salary].filter(Boolean).join(' · ')));
      details.append(node('p', data.description), node('p', 'Reconnect to check availability and deadlines.'));
      card.append(details);
      actions.append(button(data.bookmark.saved ? 'Remove saved job' : 'Save job', () => app.queue('bookmark', record.key, record.title,
        {job_id: data.id, base: data.bookmark, saved: !data.bookmark.saved, remind: false})));
    } else if (record.kind === 'learning') { details.append(node('p', data.text, 'offline-text')); card.append(details); }
    else if (record.kind === 'notification') card.append(node('p', data.description));
    const link = node('a', 'Open current page', 'btn btn-secondary'); link.href = record.path;
    actions.append(link); card.append(actions);
  }
  function review(op) {
    const details = node('details'); details.append(node('summary', 'Review saved changes'));
    if (op.kind === 'profile') {
      const labels = {display_name: 'Display name', professional_status: 'Career stage', headline: 'Headline',
        location: 'Location', bio: 'About you', qualification: 'Qualification', years_experience: 'Years of experience',
        skills: 'Skills', interests: 'Professional interests'};
      for (const [field, value] of Object.entries(op.payload.values)) {
        if (String(value ?? '') === String(op.payload.base.values[field] ?? '')) continue;
        details.append(node('h4', labels[field] || field), node('p', 'Your change: ' + (value || 'Empty')));
        if (op.current?.values) details.append(node('p', 'Current value: ' + (op.current.values[field] || 'Empty')));
      }
    } else if (op.kind === 'bookmark') {
      const choice = value => value.saved ? 'Save this opportunity' + (value.remind ? ' with a deadline reminder' : '') : 'Remove this saved opportunity';
      details.append(node('p', 'Your choice: ' + choice(op.payload)));
      if (op.current) details.append(node('p', 'Current choice: ' + choice(op.current)));
      details.append(node('p', 'Dismiss this change, then refresh the saved opportunity before choosing again.'));
    } else if (op.payload.body || op.payload.cover_note) {
      details.append(node('p', op.payload.body || op.payload.cover_note, 'offline-text'));
      details.append(node('p', 'Open the local draft to review and edit it before sending again.'));
    } else details.append(node('p', 'Reopen the current page while connected to review this action.'));
    return details;
  }
  async function render() {
    const version = ++rendering;
    if (!store.available) {
      count('records', null); count('pending', null);
      app.setSyncState?.(0, 0, false);
      recordsHost?.replaceChildren(emptyState('records', 'Your library is private', 'Sign in while connected to access saved information.', '/auth/login', 'Sign in'));
      operationsHost?.replaceChildren(emptyState('changes', 'No workspace open', 'Sign in while connected to check your saved changes.'));
      if (editor) { editor.hidden = true; editor.replaceChildren(); }
      return;
    }
    const [records, operations] = await Promise.all([store.list('record'), store.list('operation')]);
    if (version !== rendering || !store.available) return;
    const active = operations.filter(row => row.value.status !== 'dismissed');
    const pending = active.filter(row => ['pending', 'syncing'].includes(row.value.status));
    const failures = active.filter(row => ['failed', 'conflict'].includes(row.value.status));
    count('records', records.length); count('pending', pending.length);
    app.setSyncState?.(pending.length, failures.length, active.some(row => row.value.status === 'syncing'));
    if (operationsHost) {
      operationsHost.replaceChildren();
      for (const {value: op} of active.sort((a, b) => b.saved - a.saved)) {
        const card = node('article', undefined, 'offline-card'); card.dataset.operationStatus = op.status;
        const actions = node('div', undefined, 'offline-card-actions');
        card.append(node('h3', op.title), node('p', ({pending: 'Waiting to sync', syncing: 'Syncing', confirmed: 'Synced', failed: 'Failed — try again', conflict: 'Needs your review'})[op.status], 'offline-state'), node('p', op.message));
        if (op.status === 'failed') actions.append(button('Retry this change', () => app.retry(op.id)));
        if (['failed', 'conflict'].includes(op.status)) {
          card.append(review(op));
          if (op.kind === 'profile' && op.current?.values) actions.append(button('Review profile and save again', () => editProfile(
            {data: op.current}, {...op.current.values, ...Object.fromEntries(Object.entries(op.payload.values)
              .filter(([key, value]) => String(value ?? '') !== String(op.payload.base.values[key] ?? '')))}, op)));
        }
        if (op.status === 'confirmed' && /^\/(?!\/)/.test(op.result?.path || '')) {
          const link = node('a', op.kind === 'reel' ? 'View upload status' : 'View confirmed result', 'btn btn-secondary');
          link.href = op.result.path; actions.append(link);
        }
        if (['confirmed', 'failed', 'conflict'].includes(op.status)) actions.append(button('Dismiss this change', () => app.dismiss(op.id)));
        if (actions.childElementCount) card.append(actions);
        operationsHost.append(card);
      }
      if (!active.length) operationsHost.append(emptyState('changes', 'Nothing waiting to sync', 'Queued changes and their results will appear here. You’re all caught up.'));
    }
    if (recordsHost) {
      const search = (document.querySelector('#offline-search')?.value || '').toLocaleLowerCase();
      const expanded = new Set([...recordsHost.querySelectorAll('[data-record-key]')]
        .filter(card => card.querySelector('.offline-record-details')?.open).map(card => card.dataset.recordKey));
      recordsHost.replaceChildren();
      for (const {value: record} of records.sort((a, b) => b.saved - a.saved)) {
        if (search && !JSON.stringify(record).toLocaleLowerCase().includes(search)) continue;
        const card = node('article', undefined, 'offline-card'); card.dataset.recordKey = record.key;
        const kind = {profile: 'YOUR PROFILE', 'public-profile': 'COLLEAGUE', job: 'OPPORTUNITY', learning: 'LEARNING', notification: 'NOTIFICATION'}[record.kind] || 'SAVED ITEM';
        card.append(node('span', kind, 'offline-record-type'), node('h3', record.title), node('p', 'Last saved: ' + new Date(record.retrieved_at).toLocaleString(), 'offline-meta'));
        describe(record, card);
        if (expanded.has(record.key) && card.querySelector('.offline-record-details')) card.querySelector('.offline-record-details').open = true;
        recordsHost.append(card);
      }
      if (!recordsHost.childElementCount) recordsHost.append(search
        ? emptyState('records', 'No matching saved items', 'Try a different search or clear it to see everything in your library.')
        : emptyState('records', 'A little preparation goes a long way', 'Visit profiles, jobs and notifications while connected to keep a copy here. Download a learning guide to read it offline.', '/jobs', 'Explore opportunities'));
    }
  }
  const repaint = () => render().catch(() => {});
  document.addEventListener('nurse:offline-change', repaint);
  document.addEventListener('nurse:sync-request', () => revalidate());
  document.querySelector('#offline-search')?.addEventListener('input', repaint);
  document.addEventListener('nurse:operation-confirmed', event => {
    const op = event.detail;
    const path = op.kind === 'bookmark' && op.payload ? '/jobs/' + op.payload.job_id : op.result.path;
    refresh(path).catch(() => {});
  });
  document.querySelector('[data-offline-download]')?.addEventListener('click', () => refresh(location.pathname, true).catch(error => app.notice(error.message, 'warning')));
  document.querySelector('[data-offline-profile]')?.addEventListener('click', async event => {
    try {
      const record = await store.get('record', 'profile:self');
      if (!record) throw new Error('Wait for the connected profile to be saved before editing offline.');
      await saveProfile(event.target.closest('form'), {...record.data, values: initialProfileValues});
    } catch (error) { app.notice(error.message, 'warning'); }
  });
  Object.assign(app, {refresh, render, node, button, count, emptyState});
  app.ready.then(async enabled => {
    if (!enabled) { repaint(); return; }
    repaint();
    if (!app.shell && location.pathname === '/offline') revalidate();
    if (!app.shell && /^\/(profile(?:\/edit)?|p\/[a-f0-9-]+|jobs(?:\/saved|\/[a-f0-9-]+)?|notifications)$/.test(location.pathname)) {
      try { await refresh(location.pathname); } catch { /* Retain the last successful snapshot. */ }
    }
  });
})();
