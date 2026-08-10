# Style Studio (dev/build-time asset tool)

**This is NOT part of the shipped PySide6 app.** It is an offline, build-time
asset pipeline that turns a source PNG into the animated holographic-glitch WebP
used as Serenity's mascot poses. The app only ever consumes the output WebPs; no
app code imports anything in this folder.

## Effect preset (hardcoded)

The exact, locked effect parameters applied per frame:

- holo `64`, noise `36`
- scanSpace `2`, scanInt `15`
- chromatic aberration oscillating `0`→`5`, period `42` (0.1s units = 4.2s)
- glowThresh `175`, glowInt `21`
- posterize `16`
- bright `-4`, sat `100`
- glitch `12` (block pattern reshuffled every frame)

Output: 63 frames at 15fps = a 4.2s seamless loop.

## Two stages

1. **`render_frames.js`** (node + `@napi-rs/canvas`) — applies the preset above,
   emitting 63 RGBA 256×256 frame PNGs.
   `node render_frames.js <input.png> <framesDir>`
2. **`encode_webp.py`** (Pillow) — upscales each frame 256→320 nearest-neighbour
   and encodes a single seamless 15fps animated WebP.
   `python encode_webp.py <framesDir> <out.webp> <quality>` (quality `90`)

## One-command usage

`stylize.py` runs both stages end-to-end per image and cleans temp frames after
each. Input may be a single PNG or a directory of PNGs:

```bash
# single image
python stylize.py img.png outDir/

# whole directory of PNGs
python stylize.py inputDir/ outDir/
```

It always encodes at quality `90`.

## Setup

`node_modules/` is gitignored, so a fresh clone won't have it. Install deps
before first use:

```bash
npm ci   # or: npm install
```

## Outputs

Finished poses are staged in the repo's `current_Imgs/` directory (not here);
temp `frames/` and `*.webp`/`*.png` working files are gitignored.
