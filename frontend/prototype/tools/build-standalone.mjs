import { readFile, writeFile, readdir, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { dirname, resolve, relative, posix } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Script } from 'node:vm';

// Package the independent A/B checkouts without changing their source files.
const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lab = resolve(process.argv[2] || resolve(repo, '../prototype-lab'));
const destination = resolve(process.argv[3] || resolve(repo, '../prototype-share'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const mime = { svg: 'image/svg+xml', png: 'image/png', woff2: 'font/woff2', ttf: 'font/ttf' };
const importPattern = () => /^\s*import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"];?\s*$/gm;
const names = bindings => bindings.split(',').map(part => part.trim()).filter(Boolean).map(part => {
  const match = /^([\w$]+)(?:\s+as\s+([\w$]+))?$/.exec(part);
  if (!match) throw Error(`Unsupported module binding: ${part}`);
  return { original: match[1], local: match[2] || match[1] };
});
const dependencyPath = (filename, specifier) => {
  if (!specifier.startsWith('./') && !specifier.startsWith('../')) throw Error(`External import: ${specifier}`);
  const path = posix.normalize(posix.join(posix.dirname(filename), specifier.split(/[?#]/)[0]));
  if (path.startsWith('../') && path !== '../api/client.mjs') throw Error(`Dependency escapes the checkout: ${path}`);
  return path;
};

await mkdir(destination, { recursive: true });
const artifacts = [];
for (const version of ['A', 'B']) {
  const root = resolve(lab, version.toLowerCase());
  const inputs = {};
  const assets = new Map();
  const read = async path => {
    const bytes = await readFile(resolve(root, path));
    inputs[path] = { bytes: bytes.length, sha256: hash(bytes) };
    return bytes.toString('utf8');
  };
  const embed = async path => {
    if (assets.has(path)) return assets.get(path).data;
    const bytes = await readFile(resolve(root, path));
    const type = mime[path.split('.').at(-1)];
    if (!type) throw Error(`Unsupported asset type: ${path}`);
    const data = `data:${type};base64,${bytes.toString('base64')}`;
    assets.set(path, { path, mime: type, bytes: bytes.length, sha256: hash(bytes), dataSha256: hash(data), data });
    return data;
  };
  const covers = {};
  for (const filename of (await readdir(resolve(root, 'shared/covers'))).filter(name => name.endsWith('.svg')).sort()) {
    covers[filename.replace(/\.svg$/, '')] = await embed(`shared/covers/${filename}`);
  }

  const moduleOrder = [];
  const sources = new Map();
  const visiting = new Set();
  async function visit(filename) {
    if (sources.has(filename)) return;
    if (visiting.has(filename)) throw Error(`Circular dependency: ${filename}`);
    visiting.add(filename);
    const source = await read(filename);
    for (const match of source.matchAll(importPattern())) await visit(dependencyPath(filename, match[2]));
    visiting.delete(filename);
    sources.set(filename, source);
    moduleOrder.push(filename);
  }
  await visit('app.mjs');
  const earlier = new Set();
  let script = `(() => {\n'use strict';\nconst __modules = Object.create(null);\nconst __covers = ${JSON.stringify(covers)};\n`;
  for (const filename of moduleOrder) {
    const exported = new Map();
    let source = sources.get(filename);
    if (filename === 'shared/ui.mjs') {
      const assetLookup = "const coverArt=new URL(`./covers/${book.id}.svg`,import.meta.url).href;";
      if (!source.includes(assetLookup)) throw Error('The cover lookup changed; review standalone asset binding.');
      source = source.replace(assetLookup, 'const coverArt=__covers[book.id];');
    }
    if (filename === 'app.mjs') {
      source = source.replaceAll('../a/', 'TasteBridge-Prototype-A.html').replaceAll('../b/', 'TasteBridge-Prototype-B.html');
      source = source.replaceAll('href="./?', `href="TasteBridge-Prototype-${version}.html?`);
    }
    source = source.replace(importPattern(), (_, bindings, specifier) => {
      const dependency = dependencyPath(filename, specifier);
      if (!earlier.has(dependency)) throw Error(`Out-of-order dependency: ${filename} -> ${dependency}`);
      return `const { ${names(bindings).map(({ original, local }) => original === local ? original : `${original}: ${local}`).join(', ')} } = __modules[${JSON.stringify(dependency)}];\n`;
    });
    source = source.replace(/^\s*export\s*\{([^}]+)\};?\s*$/gm, (_, bindings) => {
      for (const { original, local } of names(bindings)) exported.set(local, original);
      return '';
    });
    source = source.replace(/^([ \t]*)export\s+(?=(?:const|let|var|function|class)\s+([\w$]+))/gm, (_, indent, name) => {
      exported.set(name, name);
      return indent;
    });
    if (/^\s*(?:import|export)\b/m.test(source) || /import\.meta/.test(source)) throw Error(`Unresolved module syntax: ${filename}`);
    script += `\n// Source: ${filename}\n__modules[${JSON.stringify(filename)}] = (() => {\n${source}\nreturn { ${[...exported].map(([name, local]) => `${JSON.stringify(name)}: ${local}`).join(', ')} };\n})();\n`;
    earlier.add(filename);
  }
  script += '\n})();\n';
  new Script(script, { filename: `TasteBridge-Prototype-${version}.embedded.js` });

  let css = '';
  for (const filename of ['shared/base.css', 'style.css', ...(version === 'A' ? ['desk-refinement.css', 'desk-galaxy.css'] : [])]) {
    let part = await read(filename);
    for (const match of [...part.matchAll(/url\(\s*(['"]?)([^)'"\s]+)\1\s*\)/g)]) {
      const value = match[2];
      if (/^(?:data:|#)/.test(value)) continue;
      if (/^(?:https?:|\/\/)/.test(value)) throw Error(`External CSS asset: ${value}`);
      const path = posix.normalize(posix.join(posix.dirname(filename), value.split(/[?#]/)[0]));
      part = part.replace(match[0], `url('${await embed(path)}')`);
    }
    css += `\n/* Source: ${filename} */\n${part}\n`;
  }
  let html = await read('index.html');
  const sourceRelease = /\?v=([\d.]+)/.exec(html)?.[1];
  if (!sourceRelease) throw Error(`Version ${version} is missing a source release stamp`);
  const styles = /<link\b(?=[^>]*\brel=["']stylesheet["'])[^>]*>/gi;
  const app = /<script\b(?=[^>]*\btype=["']module["'])(?=[^>]*\bsrc=["']\.\/app\.mjs[^"']*["'])[^>]*>\s*<\/script>/i;
  if ([...html.matchAll(styles)].length !== (version === 'A' ? 4 : 2) || !app.test(html)) throw Error('Unexpected entry markup');
  html = html.replace(styles, '').replace(/<link\b(?=[^>]*\brel=["']preload["'])[^>]*>/gi, '');
  html = html.replace(app, () => `<script>${script.replace(/<\/script/gi, '<\\/script')}</script>`);
  html = html.replace(/<title>[^<]+<\/title>/, `<title>TasteBridge Prototype ${version} · ${version === 'A' ? 'Reading Desk' : 'Book Journey'}</title>`);
  const licenses = [];
  for (const filename of ['shared/fonts/Geist-OFL.txt', 'shared/fonts/Instrument-Serif-OFL.txt']) licenses.push(await read(filename));
  const metadata = { project: 'TasteBridge', kind: 'Frontend prototype', version, direction: version === 'A' ? 'Preferred: Reading Desk' : 'Comparison: Book Journey', sourceRelease, data: '23 sample books; deterministic local recommendations', offline: true, ...(version === 'A' ? { optionalApiMode: '?api=1, with a same-origin /api proxy' } : {}) };
  html = html.replace('</head>', () => `<style>${css}</style>\n<script type="application/json" id="prototype-metadata">${JSON.stringify(metadata).replaceAll('<', '\\u003c')}</script>\n<!-- Embedded typefaces: Geist and Instrument Serif. SIL Open Font Licenses:\n${licenses.join('\n\n').replaceAll('--', '- -')}\n-->\n</head>`);
  const path = resolve(destination, `TasteBridge-Prototype-${version}.html`);
  await writeFile(path, html);
  const manifest = { version, sourceRelease, preferred: version === 'A', sourceRoot: relative(destination, root), moduleOrder, sourceInputs: inputs, embeddedAssets: [...assets.values()].map(({ data, ...asset }) => asset), artifact: { file: `TasteBridge-Prototype-${version}.html`, bytes: Buffer.byteLength(html), sha256: hash(html) } };
  await writeFile(resolve(destination, `manifest-${version}.json`), JSON.stringify(manifest, null, 2) + '\n');
  artifacts.push({ version, path, modules: moduleOrder.length, assets: assets.size, ...manifest.artifact });
}
console.log(JSON.stringify({ artifacts }, null, 2));
