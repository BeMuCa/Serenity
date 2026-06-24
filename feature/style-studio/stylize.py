"""
============================================================
Author:  Berk
Created: 2026-06-24
Purpose: One-command wrapper that runs the full render->encode style pipeline
         (render_frames.js -> encode_webp.py) per input PNG.
Role:    Dev/build-time entry point for the style-studio asset tool (NOT shipped
         in the app). Turns a source PNG (or a directory of PNGs) into the
         holographic-glitch animated WebP poses Serenity consumes. Stages temp
         256px frames per image, encodes at quality 90, then cleans them up.

Functions:
- stylize_one(png, out_dir, tmp) -- render frames + encode one PNG to a WebP
- main() -- resolve input PNG/dir, run stylize_one per image
============================================================
"""
import sys
import os
import glob
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER_JS = os.path.join(HERE, "render_frames.js")
ENCODE_PY = os.path.join(HERE, "encode_webp.py")
QUALITY = 90  # established value


def stylize_one(png, out_dir, tmp):
    """Render frames for one PNG then encode them to <name>.webp in out_dir."""
    name = os.path.splitext(os.path.basename(png))[0]
    frames_dir = os.path.join(tmp, name)
    out_webp = os.path.join(out_dir, name + ".webp")
    if os.path.isdir(frames_dir):
        shutil.rmtree(frames_dir)
    try:
        subprocess.run(["node", RENDER_JS, png, frames_dir], cwd=HERE, check=True)
        subprocess.run([sys.executable, ENCODE_PY, frames_dir, out_webp, str(QUALITY)], check=True)
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
    return out_webp


def main():
    if len(sys.argv) != 3:
        print("usage: python stylize.py <input.png|inputDir> <outDir>")
        sys.exit(1)
    # Resolve to absolute up front: render_frames.js runs with cwd=HERE, so a relative
    # input/output (e.g. "img/foo.png" from the repo root) must not be re-resolved there.
    inp, out_dir = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(HERE, "frames")
    if os.path.isdir(inp):
        pngs = sorted(glob.glob(os.path.join(inp, "*.png")))
    else:
        pngs = [inp]
    if not pngs:
        print(f"no PNG input found at {inp}")
        sys.exit(1)
    for png in pngs:
        print(stylize_one(png, out_dir, tmp))
    shutil.rmtree(tmp, ignore_errors=True)  # drop the now-empty temp frames root


if __name__ == "__main__":
    main()
