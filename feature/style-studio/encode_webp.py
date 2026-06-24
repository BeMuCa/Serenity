"""
============================================================
Author:  Berk
Created: 2026-06-19
Purpose: Encode a 256x256 RGBA frame sequence into a 320x320 animated WebP.
Role:    Final stage of the Serenity effect-render pipeline. render_frames.js
         emits full-color 256px frames straight from the JS effect pipeline;
         this upscales each 256->320 nearest-neighbour (matching the tool's
         NN blit) and encodes a single seamless looping animated WebP.

Functions:
- encode(frames_dir, out_path, quality) -- load NN-upscaled frames, save animated WebP
============================================================
"""
import sys
import glob
import os
from PIL import Image

FPS = 15
OUT = 320

def encode(frames_dir, out_path, quality):
    paths = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
    frames = []
    for p in paths:
        im = Image.open(p).convert("RGBA")
        im = im.resize((OUT, OUT), Image.NEAREST)  # 256 -> 320 nearest-neighbour (tool blit)
        frames.append(im)
    if not frames:
        sys.exit(f"no frame_*.png found in {frames_dir}")
    frames[0].save(
        out_path,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=round(1000 / FPS),
        loop=0,
        quality=quality,
        method=6,
    )
    return len(frames)

if __name__ == "__main__":
    frames_dir, out_path, quality = sys.argv[1], sys.argv[2], int(sys.argv[3])
    n = encode(frames_dir, out_path, quality)
    print(f"{out_path}\t{n} frames\t{os.path.getsize(out_path)} bytes\tq={quality}")
