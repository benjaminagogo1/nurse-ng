import assert from 'node:assert/strict';
import test from 'node:test';
import { configure, serverURL } from '../scripts/configure.mjs';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

test('preview can be built before hosting without pretending to have a server', () => {
  assert.equal(serverURL(''), null);
  assert.throws(() => serverURL('', true), /hosted HTTPS/);
});
test('a release uses only its explicitly configured public HTTPS origin', () => {
  assert.equal(serverURL('https://nurse.example/', true), 'https://nurse.example');
  for (const input of ['http://nurse.example', 'https://localhost', 'http://10.0.2.2:8000',
    'https://user:password@nurse.example', 'https://nurse.example/path',
    'https://nurse.example/?token=private', 'https://nurse.example/#private']) {
    assert.throws(() => serverURL(input, true));
  }
});
test('local device and emulator previews can connect to development', () => {
  assert.equal(serverURL('http://10.0.2.2:8000'), 'http://10.0.2.2:8000');
  assert.equal(serverURL('http://192.168.1.10:8000'), 'http://192.168.1.10:8000');
  assert.throws(() => serverURL('http://public.example'));
  assert.throws(() => serverURL('javascript:alert(1)'));
});

test('native builds bundle the workspace without moving member storage to an error origin', async t => {
  const output = await mkdtemp(join(tmpdir(), 'nurse-native-bundle-'));
  t.after(() => rm(output, { recursive: true, force: true }));
  await configure({ release: true, value: 'https://nurse.example', output });
  const config = JSON.parse(await readFile(join(output, 'capacitor.config.json'), 'utf8'));
  assert.equal(config.server.url, 'https://nurse.example');
  assert.equal(config.server.errorPath, undefined);
  assert.equal(config.android.webContentsDebuggingEnabled, false);
  assert.equal(config.ios.webContentsDebuggingEnabled, false);
  const bundle = await readFile(join(output, 'www/offline.html'), 'utf8');
  assert.match(bundle, /data-offline-shell="true"/);
  assert.match(bundle, /data-draft-scope=""/);
  assert.match(bundle, /window.NurseNativeOffline = true/);
  assert.doesNotMatch(bundle, /<script[^>]+src=/);
  assert.doesNotMatch(bundle, /name="csrf_token"/);
  await configure({ value: '', output });
  const preview = JSON.parse(await readFile(join(output, 'capacitor.config.json'), 'utf8'));
  assert.equal(preview.server, undefined);
  assert.match(await readFile(join(output, 'www/index.html'), 'utf8'), /Open offline workspace/);
});
