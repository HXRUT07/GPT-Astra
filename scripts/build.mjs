import { build } from 'esbuild';
import { mkdir, copyFile } from 'node:fs/promises';

await mkdir('dist', { recursive: true });
await build({
  entryPoints: ['src/content.js', 'src/background.js'],
  outdir: 'dist',
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: ['chrome120'],
  minify: true,
  legalComments: 'linked',
});
await copyFile('extension/manifest.json', 'dist/manifest.json');
await copyFile('THIRD_PARTY_NOTICES.txt', 'dist/THIRD_PARTY_NOTICES.txt');
console.log('Chrome extension built in dist/');
