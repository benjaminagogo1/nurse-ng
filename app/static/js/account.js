(() => {
  'use strict';
  const tokenInput = document.querySelector('[data-account-token]');
  if (tokenInput) {
    const token = new URLSearchParams(location.hash.slice(1)).get('token');
    if (token && /^[A-Za-z0-9_-]{43}$/.test(token)) tokenInput.value = token;
    if (tokenInput.value) {
      tokenInput.type = 'hidden';
      document.querySelector('[data-token-field]').hidden = true;
    }
    if (location.hash) history.replaceState(null, '', location.pathname + location.search);
  }
  const input = document.querySelector('[data-photo-input]');
  const preview = document.querySelector('[data-photo-preview]');
  const previewCard = document.querySelector('[data-photo-preview-card]');
  let previewUrl;
  input?.addEventListener('change', () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = input.files[0];
    preview.hidden = !file;
    if (previewCard) previewCard.hidden = !file;
    const filename = document.querySelector('[data-photo-filename]');
    if (filename) filename.textContent = file?.name || '';
    if (file) {
      previewUrl = URL.createObjectURL(file);
      preview.src = previewUrl;
    } else preview.removeAttribute('src');
  });
})();
