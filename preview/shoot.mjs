// Real-engine preview: runs the live Voxels client in headless Chrome and swaps
// the generated content into parcels 1297 + 1342 at the network layer, so what
// we see is exactly what Voxels renders. Nothing is written anywhere.
//
//   node preview/shoot.mjs [viewName ...]        (default: every view)
//
// Assets referenced as https://assets.backrooms.test/<file> are served from
// out/assets/ (with CORS, like a CDN would).

import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire('/Users/nategeier/anchor.js');
const { chromium } = require('playwright-core');

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const outDir = path.join(root, 'shots');
fs.mkdirSync(outDir, { recursive: true });

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const ASSET_HOST = 'https://assets.backrooms.test/';

const content = {
  1297: JSON.parse(fs.readFileSync(path.join(root, 'out/1297.json'), 'utf8')).content,
  1342: JSON.parse(fs.readFileSync(path.join(root, 'out/1342.json'), 'utf8')).content,
};

// world coords of combined voxel (i, k): x = -343.5 + 0.5i, z = 110.5 + 0.5k
export const VIEWS = {
  street: { coords: 'N@335W,107.2N', wait: 22000 },
  'street-corner': { coords: 'NE@346W,107N,3U', pitch: 0.12, wait: 22000 },
  lobby: { coords: 'NW@332.5W,111.7N', wait: 22000 },
  crack: { coords: 'N@332.4W,113N', wait: 22000 },
  h2: { coords: 'W@330W,117N', wait: 22000 },
  hallway: { coords: 'N@342.3W,117N', wait: 22000 },
  s2: { coords: 'NW@329W,121N', wait: 22000 },
  pillars: { coords: 'N@334W,127N', wait: 22000 },
  'pillars-diag': { coords: 'NE@340W,127N', wait: 22000 },
  north: { coords: 'E@339W,139.5N', wait: 22000 },
  w1: { coords: 'W@339.5W,113N', wait: 22000 },
  dark: { coords: 'E@331.5W,139N', wait: 22000 },
  stair: { coords: 'N@328.4W,111.6N', wait: 22000 },
  aerial: { coords: 'N@335W,95N,22U', pitch: 0.75, wait: 26000 },
};

function patchRecord(rec) {
  const c = content[rec.id];
  if (!c) return rec;
  return {
    ...rec,
    voxels: c.voxels,
    palette: c.palette,
    tileset: c.tileset,
    features: c.features,
    brightness: c.brightness,
    scripting: c.scripting,
    hash: (rec.hash || '') + '-preview',
  };
}

async function installRoutes(context, log) {
  await context.route('**/grid/parcels/**', async (route) => {
    const url = route.request().url();
    const m = url.match(/\/grid\/parcels\/(\d+)(?:$|\?)/);
    const isPack = url.endsWith('.pack');
    if (!isPack && !m) return route.continue();
    let res;
    try {
      res = await route.fetch({ timeout: 45000 });
    } catch (e) {
      log.push('fetch-failed ' + url.slice(-40));
      return route.abort().catch(() => {});
    }
    let body;
    try {
      body = await res.json();
    } catch {
      return route.fulfill({ response: res });
    }
    let touched = false;
    if (isPack && Array.isArray(body.parcels)) {
      body.parcels = body.parcels.map((r) => {
        if (content[r.id]) touched = true;
        return patchRecord(r);
      });
    } else if (body && body.parcel && content[body.parcel.id]) {
      body.parcel = patchRecord(body.parcel);
      touched = true;
    }
    if (touched) log.push('patched ' + url.slice(-60));
    return route.fulfill({ response: res, json: body });
  });
  await context.route(ASSET_HOST + '**', async (route) => {
    const rel = route.request().url().slice(ASSET_HOST.length).split('?')[0];
    const file = path.join(root, 'out/assets', rel);
    if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: 'missing' });
    const ext = path.extname(file).toLowerCase();
    const type = { '.png': 'image/png', '.jpg': 'image/jpeg', '.mp3': 'audio/mpeg', '.webp': 'image/webp' }[ext] || 'application/octet-stream';
    log.push('asset ' + rel);
    return route.fulfill({ status: 200, body: fs.readFileSync(file), headers: { 'content-type': type, 'access-control-allow-origin': '*' } });
  });
}

async function shoot(browser, name, view) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
  const log = [];
  await installRoutes(context, log);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)));
  await page.goto(`https://www.voxels.com/play?coords=${encodeURIComponent(view.coords)}&ui=off`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(view.wait || 20000);
  if (view.pitch !== undefined) {
    await page.evaluate((pitch) => {
      const cam = window.scene?.activeCamera;
      if (cam && cam.rotation) cam.rotation.x = pitch;
      if (window.persona?.rotation) window.persona.rotation.x = pitch;
    }, view.pitch);
    await page.waitForTimeout(2500);
  }
  // clean frame: hide every DOM overlay that isn't on the canvas's ancestor
  // chain (the site nav, hints). Display-only, for the screenshot.
  await page.evaluate(() => {
    const canvas = document.getElementById('renderCanvas');
    for (let el = canvas; el && el !== document.documentElement; el = el.parentElement) {
      for (const sib of el.parentElement ? [...el.parentElement.children] : []) {
        if (sib !== el && !(sib instanceof HTMLScriptElement)) sib.style.setProperty('display', 'none', 'important');
      }
    }
  });
  await page.waitForTimeout(600);
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file });
  const patched = log.filter((l) => l.startsWith('patched')).length;
  const assets = log.filter((l) => l.startsWith('asset')).length;
  console.log(`${name}: ${file}  patched=${patched} assets=${assets}${errors.length ? '  errors=' + errors.slice(0, 2).join(' | ') : ''}`);
  await context.unrouteAll({ behavior: 'ignoreErrors' });
  await context.close();
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-gpu'] });
const wanted = process.argv.slice(2);
const names = wanted.length ? wanted : Object.keys(VIEWS);
for (const n of names) {
  if (!VIEWS[n]) { console.log('unknown view', n); continue; }
  await shoot(browser, n, VIEWS[n]);
}
await browser.close();
