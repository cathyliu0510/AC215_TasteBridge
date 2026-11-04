import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const generated = resolve(root, '.prototype-build');
const bundle = spawnSync(process.execPath, [resolve(root, 'tools/build-standalone.mjs'), resolve(root, 'src'), generated], { stdio: 'pipe', encoding: 'utf8' });
if (bundle.status !== 0) { process.stderr.write(bundle.stderr || bundle.stdout); process.exit(bundle.status || 1); }
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const releases = [];
for (const version of ['A', 'B']) {
  let html = readFileSync(resolve(generated, `TasteBridge-Prototype-${version}.html`), 'utf8');
  html = html.replaceAll('TasteBridge-Prototype-A.html', '/a/').replaceAll('TasteBridge-Prototype-B.html', '/b/');
  const target = resolve(root, `dist/${version.toLowerCase()}/index.html`);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, html);
  if (version === 'A') writeFileSync(resolve(root, 'dist/index.html'), html);
  const metadata = JSON.parse(/<script type="application\/json" id="prototype-metadata">([\s\S]*?)<\/script>/.exec(html)[1]);
  releases.push({ version, release: metadata.sourceRelease, sha256: hash(html) });
}
let project = readFileSync(resolve(root, 'pages/project.html'), 'utf8');
for (const [placeholder, file, mime] of [
  ['FONT_GEIST', 'shared/fonts/Geist.woff2', 'font/woff2'],
  ['FONT_SERIF', 'shared/fonts/InstrumentSerif-Regular.ttf', 'font/ttf'],
  ['COVER_MISTBORN', 'shared/covers/mistborn.svg', 'image/svg+xml'],
  ['COVER_LOCKE', 'shared/covers/locke.svg', 'image/svg+xml'],
  ['COVER_GONE_GIRL', 'shared/covers/gone-girl.svg', 'image/svg+xml']
]) project = project.replaceAll(placeholder, `data:${mime};base64,${readFileSync(resolve(root, 'src/a', file)).toString('base64')}`);
mkdirSync(resolve(root, 'dist/project'), { recursive: true });
writeFileSync(resolve(root, 'dist/project/index.html'), project);
writeFileSync(resolve(root, 'release.json'), JSON.stringify({ preferred: 'A', release: releases.find(item => item.version === 'A').release, routes: ['/', '/a/', '/b/', '/project/'], versions: releases, project_sha256: hash(project) }, null, 2) + '\n');
console.log('Built A, B, and the project scope page from editable source.');
