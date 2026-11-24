/** Validate the target origin and generate Capacitor configuration plus the neutral offline bundle. See mobile/README.md. */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isIP } from 'node:net';
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';

export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function serverURL(value, release = false) {
  if (!value) {
    if (release) throw new Error('Set NURSE_NG_MOBILE_URL to the hosted HTTPS site before a release.');
    return null;
  }
  if (typeof value !== 'string' || /[\s\\]/.test(value)) {
    throw new Error('Use a site origin without whitespace or backslashes.');
  }
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('Use the site origin without credentials, paths, queries or fragments.');
  }
  const host = url.hostname.toLowerCase().replace(/\.$/, '');
  const local = host === 'localhost'
    || ['.localhost', '.local', '.localdomain', '.internal', '.lan', '.home.arpa']
      .some(suffix => host.endsWith(suffix))
    || /^127\./.test(host) || /^10\./.test(host) || /^192\.168\./.test(host)
    || /^172\.(1[6-9]|2\d|3[01])\./.test(host) || host === '[::1]';
  if (!['https:', 'http:'].includes(url.protocol)
      || (url.protocol === 'http:' && (!local || release))
      || (release && (local || isIP(host.replace(/^\[|\]$/g, '')) || !host.includes('.')))) {
    throw new Error('Release apps require a public HTTPS origin; HTTP is only for local previews.');
  }
  return url.origin;
}

export async function configure({ release = false, value = process.env.NURSE_NG_MOBILE_URL,
  output = root } = {}) {
  const origin = serverURL(value, release);
  const config = {
    appId: 'com.nurseng.app', appName: 'Nurse.ng', webDir: 'www',
    backgroundColor: '#073c40',
    android: { allowMixedContent: false, webContentsDebuggingEnabled: !release },
    ios: { contentInset: 'automatic', webContentsDebuggingEnabled: !release },
  };
  if (origin) {
    // Native hosts load the bundled workspace at this same origin on failure.
    // A local errorPath would separate it from the member's encrypted storage.
    config.server = { url: origin, cleartext: origin.startsWith('http:') };
  }
  await mkdir(resolve(output, 'www'), { recursive: true });
  const template = await readFile(resolve(root, 'resources/shell.html'), 'utf8');
  const icon = await readFile(resolve(root, '../app/static/img/favicon.svg'), 'utf8');
  const page = (title, body, action) => template
    .replace('{{ICON}}', icon).replace('{{TITLE}}', title)
    .replace('{{BODY}}', body).replace('{{ACTION}}', action);
  await writeFile(resolve(output, 'www/index.html'), page(
    origin ? 'Nurse.ng' : 'Nurse.ng mobile preview',
    origin ? 'Open your community or continue saved work offline.'
      : 'The Android and iPhone app projects are ready. Nurse.ng is not online yet, so this preview cannot sign in or load opportunities.',
    (origin ? `<a class="button" href="${origin}">Open Nurse.ng</a>`
      : '<p class="note">This is a development preview, not a public release.</p>')
      + '<a class="button" href="offline.html">Open offline workspace</a>',
  ));
  const localPython = resolve(root, '../venv/bin/python');
  const python = process.env.NURSE_NG_BUILD_PYTHON || (existsSync(localPython) ? localPython : 'python3');
  const bundled = spawnSync(python, [resolve(root, 'scripts/bundle-offline.py'),
    resolve(output, 'www/offline.html')], { cwd: resolve(root, '..'), encoding: 'utf8' });
  if (bundled.error || bundled.status !== 0) {
    throw new Error('Could not bundle the offline workspace. Install the app’s Python dependencies '
      + 'and set NURSE_NG_BUILD_PYTHON if needed.\n' + (bundled.stderr || bundled.error?.message || ''));
  }
  await writeFile(resolve(output, 'capacitor.config.json'), JSON.stringify(config, null, 2) + '\n');
  return { origin, release };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await configure({ release: process.argv.includes('--release') });
    console.log(result.origin ? `Mobile app connects to ${result.origin}` : 'Configured an offline development preview.');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
