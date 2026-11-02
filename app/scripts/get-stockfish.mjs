// Downloads the official Stockfish release for this computer (or for
// --platform/--arch) into app/stockfish/, where the app and the installer look.
//
//   node scripts/get-stockfish.mjs
//   node scripts/get-stockfish.mjs --platform darwin --arch x64

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const VERSION = 'sf_18';
const ASSETS = {
  'darwin-arm64': 'stockfish-macos-m1-apple-silicon.tar',
  'darwin-x64': 'stockfish-macos-x86-64-avx2.tar',
  'win32-x64': 'stockfish-windows-x86-64-avx2.zip',
  'linux-x64': 'stockfish-ubuntu-x86-64-avx2.tar',
};

const arg = name => { const i = process.argv.indexOf(`--${name}`); return i > 0 ? process.argv[i + 1] : null; };
const target = `${arg('platform') || process.platform}-${arg('arch') || process.arch}`;
const asset = ASSETS[target];
if (!asset) throw new Error(`No Stockfish build for ${target}. Known: ${Object.keys(ASSETS).join(', ')}`);

const outDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'stockfish');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'stockfish-'));
const archive = path.join(tmp, asset);
const url = `https://github.com/official-stockfish/Stockfish/releases/download/${VERSION}/${asset}`;

console.log(`Downloading ${url}`);
const resp = await fetch(url);
if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
fs.writeFileSync(archive, Buffer.from(await resp.arrayBuffer()));
execFileSync('tar', ['-xf', archive, '-C', tmp]); // bsdtar on macOS and Windows reads .zip too

const src = path.join(tmp, 'stockfish');
const binary = fs.readdirSync(src).find(f => f.startsWith('stockfish-'));
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });
const exe = target.startsWith('win32') ? 'stockfish.exe' : 'stockfish';
fs.copyFileSync(path.join(src, binary), path.join(outDir, exe));
fs.chmodSync(path.join(outDir, exe), 0o755);
fs.copyFileSync(path.join(src, 'Copying.txt'), path.join(outDir, 'COPYING.txt'));
fs.rmSync(tmp, { recursive: true, force: true });
console.log(`Stockfish ${VERSION.slice(3)} for ${target} -> ${path.join(outDir, exe)}`);
