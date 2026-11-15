import { spawnSync } from 'node:child_process';
import { copyFile, mkdir, readdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { configure, root } from './configure.mjs';

const release = process.argv.includes('--release');
const env = { ...process.env };
try {
  if (release) {
    for (const name of ['NURSE_NG_KEYSTORE_PATH', 'NURSE_NG_KEYSTORE_PASSWORD',
      'NURSE_NG_KEY_ALIAS', 'NURSE_NG_KEY_PASSWORD']) {
      if (!env[name]) throw new Error(`Supply ${name} through your private build environment.`);
    }
  }
  await configure({ release });
  const local = resolve(root, '../.local-tools/mobile');
  if (!env.JAVA_HOME) {
    const jdk = (await readdir(local).catch(() => [])).find(name => name.startsWith('jdk-'));
    if (jdk) env.JAVA_HOME = join(local, jdk);
  }
  env.ANDROID_HOME ||= join(local, 'android-sdk');
  env.GRADLE_USER_HOME ||= join(root, '.gradle');
  env.ANDROID_USER_HOME ||= join(root, '.android');
  if (env.JAVA_HOME) env.PATH = join(env.JAVA_HOME, 'bin') + ':' + env.PATH;
  const run = (command, args, cwd) => {
    const result = spawnSync(command, args, { cwd, env, stdio: 'inherit' });
    if (result.error) throw result.error;
    if (result.status !== 0) throw new Error(`${command} failed (${result.status}).`);
  };
  run(process.execPath, [join(root, 'node_modules/@capacitor/cli/bin/capacitor'), 'sync', 'android'], root);
  run('./gradlew', ['--no-daemon', '--max-workers=1', release ? 'assembleRelease' : 'assembleDebug'], join(root, 'android'));
  const variant = release ? 'release' : 'debug';
  const output = join(root, 'dist', release ? 'nurse-ng.apk' : 'nurse-ng-preview.apk');
  await mkdir(join(root, 'dist'), { recursive: true });
  await copyFile(join(root, `android/app/build/outputs/apk/${variant}/app-${variant}.apk`), output);
  console.log(`Built ${output}${release ? '' : ' (development preview, not a public release)'}`);
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
