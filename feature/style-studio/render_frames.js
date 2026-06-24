/*
 * Serenity animated-effect frame renderer.
 * Faithful CommonJS port of the render() pipeline from
 * Serenity_Mockups/serenity-effects.html, driven per-frame to produce a
 * 4.2s seamless 63-frame / 15fps loop. Emits raw 256x256 RGBA frame PNGs;
 * Python (encode_webp.py) upscales 256->320 NN and encodes animated WebP.
 *
 * Usage: node render_frames.js <input.png> <outDir>
 */
const { createCanvas, loadImage } = require("@napi-rs/canvas");
const fs = require("fs");
const path = require("path");

// ---- exact settings from the task (everything else OFF / DEFAULTS) ----
const S = {
  pixel: 1,
  cyber: 0,
  holo: 64,
  noise: 36,
  scanSpace: 2, scanInt: 15,
  aberr: 0,
  aberrOsc: true,
  aberrMin: 0,
  aberrMax: 5,
  aberrPeriod: 42,          // 0.1s units => 4.2s
  glowThresh: 175, glowInt: 21,
  posterize: 16,
  bright: -4, contrast: 0, sat: 100,
  vignette: 0,
  dither: false,
  glitch: 12,
};

const FRAMES = 63;
const PERIOD_S = 4.2;
const FRAME_MS = (PERIOD_S * 1000) / FRAMES;   // 66.666... ms/frame -> seamless loop

let flickerPhase = 0;
let animTime = 0;

// canvases (256 working res, matching the tool)
const work = createCanvas(256, 256);
const wctx = work.getContext("2d");
const src = createCanvas(256, 256);
const sctx = src.getContext("2d");

const clamp = (v) => (v < 0 ? 0 : v > 255 ? 255 : v);

const bayer = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];

function fitSource(img) {
  sctx.clearRect(0, 0, 256, 256);
  const iw = img.width, ih = img.height;
  const sc = Math.min(256 / iw, 256 / ih);
  const dw = iw * sc, dh = ih * sc;
  sctx.imageSmoothingEnabled = true;
  sctx.drawImage(img, (256 - dw) / 2, (256 - dh) / 2, dw, dh);
}

function perPixel(d) {
  const br = S.bright * 2.55;
  const cF = (259 * (S.contrast + 255)) / (255 * (259 - S.contrast));
  const satF = 1 + S.sat / 100;
  const cyber = S.cyber / 100;
  const post = S.posterize;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 0) continue;
    let r = d[i], g = d[i + 1], b = d[i + 2];
    r += br; g += br; b += br;
    r = cF * (r - 128) + 128; g = cF * (g - 128) + 128; b = cF * (b - 128) + 128;
    if (satF !== 1) { const lum = 0.299 * r + 0.587 * g + 0.114 * b; r = lum + (r - lum) * satF; g = lum + (g - lum) * satF; b = lum + (b - lum) * satF; }
    if (post >= 2) {
      const px = (i >> 2) % 256, py = (i >> 2) / 256 | 0;
      const step = 255 / (post - 1);
      const t = S.dither ? (bayer[py & 3][px & 3] / 16 - 0.5) * step : 0;
      r = Math.round((r + t) / step) * step; g = Math.round((g + t) / step) * step; b = Math.round((b + t) / step) * step;
    }
    if (cyber > 0) {
      const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
      const tR = 40 + lum * 215;
      const tB = 60 + (1 - lum) * 170 + lum * 120;
      const tG = 30 + lum * 90 + (1 - lum) * 90;
      r = r + (tR - r) * cyber * 0.6;
      g = g + (tG - g) * cyber * 0.6;
      b = b + (tB - b) * cyber * 0.6;
      if (cyber > 0.5) { const q = 64; r = Math.round(r / q) * q; g = Math.round(g / q) * q; b = Math.round(b / q) * q; }
    }
    d[i] = clamp(r); d[i + 1] = clamp(g); d[i + 2] = clamp(b);
  }
}

function overlays(d) {
  const scan = S.scanInt / 100, holo = S.holo / 100, noise = S.noise / 100, vig = S.vignette / 100;
  const sp = S.scanSpace;
  const cx = 128, cy = 128, maxD = Math.hypot(128, 128);
  const flick = 1 - holo * 0.10 * (0.5 + 0.5 * Math.sin(flickerPhase));
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 0) continue;
    let r = d[i], g = d[i + 1], b = d[i + 2];
    const idx = i >> 2, x = idx % 256, y = idx / 256 | 0;
    if (scan > 0 && (y % sp) === 0) { r *= (1 - scan * 0.7); g *= (1 - scan * 0.7); b *= (1 - scan * 0.7); }
    if (holo > 0) {
      r = r + (90 - r) * holo * 0.35;
      b = b + (210 - b) * holo * 0.45;
      g = g + (200 - g) * holo * 0.30;
      if ((y % 3) === 0) { const band = 1 + holo * 0.25; r *= band; g *= band; b *= band; }
      r *= flick; g *= flick; b *= flick;
    }
    if (noise > 0) { const n = (Math.random() - 0.5) * 255 * noise * 0.5; r += n; g += n; b += n; }
    if (vig > 0) { const f = 1 - vig * Math.pow(Math.hypot(x - cx, y - cy) / maxD, 2.2); r *= f; g *= f; b *= f; }
    d[i] = clamp(r); d[i + 1] = clamp(g); d[i + 2] = clamp(b);
    if (holo > 0) d[i + 3] = clamp(d[i + 3] * (1 - holo * 0.12));
  }
}

function chromatic() {
  let off = S.aberr;
  if (S.aberrOsc) {
    const lo = Math.min(S.aberrMin, S.aberrMax), hi = Math.max(S.aberrMin, S.aberrMax);
    const period = Math.max(0.1, S.aberrPeriod / 10);
    const phase = 0.5 + 0.5 * Math.sin(2 * Math.PI * (animTime / 1000) / period);
    off = Math.round(lo + (hi - lo) * phase);
  }
  if (off <= 0) return;
  const base = wctx.getImageData(0, 0, 256, 256);
  const out = wctx.createImageData(256, 256);
  const s = base.data, o = out.data;
  for (let y = 0; y < 256; y++) { const row = y * 256; for (let x = 0; x < 256; x++) {
    const i = (row + x) * 4;
    const ri = (row + clamp(x - off)) * 4;
    const bi = (row + clamp(x + off)) * 4;
    o[i] = s[ri]; o[i + 1] = s[i + 1]; o[i + 2] = s[bi + 2];
    o[i + 3] = Math.max(s[i + 3], s[ri + 3], s[bi + 3]);
  } }
  wctx.putImageData(out, 0, 0);
}

function glow() {
  const th = S.glowThresh, inten = S.glowInt / 100;
  const base = wctx.getImageData(0, 0, 256, 256), s = base.data;
  const bright = createCanvas(256, 256);
  const bc = bright.getContext("2d");
  const bd = bc.createImageData(256, 256), b = bd.data;
  for (let i = 0; i < s.length; i += 4) {
    const lum = 0.299 * s[i] + 0.587 * s[i + 1] + 0.114 * s[i + 2];
    if (lum > th && s[i + 3] > 0) { b[i] = s[i]; b[i + 1] = s[i + 1]; b[i + 2] = s[i + 2]; b[i + 3] = 255; }
  }
  bc.putImageData(bd, 0, 0);
  const sm = createCanvas(32, 32);
  const smc = sm.getContext("2d"); smc.imageSmoothingEnabled = true;
  smc.drawImage(bright, 0, 0, 32, 32);
  wctx.save();
  wctx.globalCompositeOperation = "lighter";
  wctx.globalAlpha = inten;
  wctx.imageSmoothingEnabled = true;
  wctx.drawImage(sm, 0, 0, 32, 32, 0, 0, 256, 256);
  wctx.restore();
}

// glitch: reshuffle the random block pattern every frame (task requirement)
function genGlitchPattern() {
  const amt = S.glitch / 100;
  const n = Math.round(amt * 7);
  const blocks = [];
  for (let k = 0; k < n; k++) {
    const h = 2 + Math.floor(Math.random() * 10);
    const y = Math.floor(Math.random() * (256 - h));
    const dx = Math.round((Math.random() - 0.5) * amt * 40);
    blocks.push({ h, y, dx });
  }
  return blocks;
}
function glitchBlocks() {
  const blocks = genGlitchPattern();
  for (const blk of blocks) {
    const slice = wctx.getImageData(0, blk.y, 256, blk.h);
    wctx.clearRect(0, blk.y, 256, blk.h);
    wctx.putImageData(slice, blk.dx, blk.y);
  }
}

function render() {
  wctx.imageSmoothingEnabled = true;
  wctx.clearRect(0, 0, 256, 256);
  wctx.drawImage(src, 0, 0);

  if (S.pixel > 1) {
    const small = Math.max(1, Math.round(256 / S.pixel));
    const tmp = createCanvas(small, small);
    const tctx = tmp.getContext("2d");
    tctx.imageSmoothingEnabled = true;
    tctx.drawImage(work, 0, 0, small, small);
    wctx.imageSmoothingEnabled = false;
    wctx.clearRect(0, 0, 256, 256);
    wctx.drawImage(tmp, 0, 0, small, small, 0, 0, 256, 256);
    wctx.imageSmoothingEnabled = true;
  }

  let img = wctx.getImageData(0, 0, 256, 256);
  perPixel(img.data);
  wctx.putImageData(img, 0, 0);

  if (S.aberr > 0 || S.aberrOsc) chromatic();
  if (S.glowInt > 0) glow();
  if (S.glitch > 0) glitchBlocks();

  img = wctx.getImageData(0, 0, 256, 256);
  overlays(img.data);
  wctx.putImageData(img, 0, 0);
}

async function main() {
  const [, , inputPath, outDir] = process.argv;
  if (!inputPath || !outDir) { console.error("usage: node render_frames.js <input.png> <outDir>"); process.exit(1); }
  fs.mkdirSync(outDir, { recursive: true });
  const img = await loadImage(inputPath);
  fitSource(img);

  flickerPhase = 0;
  for (let f = 0; f < FRAMES; f++) {
    animTime = f * FRAME_MS;     // ms timestamp driving aberration sine
    flickerPhase += 0.18;        // matches tick(): advances before render
    render();
    const buf = work.toBuffer("image/png");
    const name = "frame_" + String(f).padStart(3, "0") + ".png";
    fs.writeFileSync(path.join(outDir, name), buf);
  }
  console.log("rendered " + FRAMES + " frames -> " + outDir);
}
main();
