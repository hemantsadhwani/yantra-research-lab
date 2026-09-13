// Render every 0N-*.excalidraw in a folder to PNG with Excalidraw's own exporter, in a
// headless Chromium-family browser via Playwright. GitHub cannot display .excalidraw
// files, so these PNGs are what the READMEs embed.
//
//   PW_MODULE=playwright node architecture/diagrams/render/shoot.js architecture/diagrams architecture/diagrams/png
//
// PW_MODULE: path/name of a playwright package (default "playwright"); PW_CHANNEL: browser
// channel (default "msedge"; use "chrome" or unset for bundled chromium).
const pw = require(process.env.PW_MODULE || 'playwright');
const fs = require('fs'), path = require('path');
const [,, dir, outDir] = process.argv;
(async () => {
  const b = await pw.chromium.launch({ channel: process.env.PW_CHANNEL || 'msedge', headless: true });
  for (const f of fs.readdirSync(dir).filter(x => /^0\d-.*\.excalidraw$/.test(x))) {
    const scene = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
    const page = await b.newPage({ viewport: { width: 1600, height: 1000 } });
    page.on('pageerror', e => console.log('  pageerror', f, String(e).slice(0,120)));
    await page.goto('file:///' + path.resolve(__dirname, 'render.html').split(String.fromCharCode(92)).join('/'));
    await page.waitForFunction(() => window.ExcalidrawLib && window.renderScene);
    const dim = await page.evaluate(s => window.renderScene(s), scene);
    const scale = Math.min(1, 1900 / dim.w, 1900 / dim.h);
    await page.setViewportSize({ width: Math.ceil(dim.w*scale)+2, height: Math.ceil(dim.h*scale)+2 });
    await page.evaluate(sc => { document.body.style.zoom = String(sc); }, scale);
    await page.waitForTimeout(400);
    const out = path.join(outDir, f.replace('.excalidraw', '.png'));
    await page.screenshot({ path: out, fullPage: true });
    console.log(f, `${Math.round(dim.w)}x${Math.round(dim.h)}`, '->', out);
    await page.close();
  }
  await b.close();
})().catch(e => { console.error('FAILED', e); process.exit(1); });
