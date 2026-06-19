# Notices and attributions

## Mascot artwork
Serenity's mascot poses were generated with Google's Gemini image model
("nano banana 2") and then post-processed by the author with a custom cyberpunk effect
pipeline (hologram, chromatic aberration, scanlines, glow, posterize).

IP note (informational, not legal advice): purely AI-generated images may not be
eligible for copyright protection in some jurisdictions (for example the current
U.S. Copyright Office position on works lacking human authorship). The author's
effect post-processing adds human authorship to the final assets. Gemini outputs
carry Google's SynthID watermark. Before any commercial release, verify Google's
current Gemini / generative-AI terms for commercial use of generated images.

## Copyright holder
This project is published under the handle **BeMuCa**. For an enforceable commercial
license you may wish to substitute your full legal name or company in LICENSE,
COMMERCIAL-LICENSE.md, and this file.

## Third-party software (runtime)
- **PySide6 / Qt** - LGPLv3. Serenity uses PySide6 as a normally pip-installed,
  dynamically linked dependency, which is compatible with distributing a proprietary
  or commercially licensed application. If you ship a frozen build (e.g. PyInstaller),
  keep the Qt libraries replaceable and include the LGPL notice. See
  <https://www.qt.io/licensing> and <https://doc.qt.io/qtforpython/licenses.html>.
- **dateparser** - BSD-3-Clause.
- **PyYAML** - MIT.
- **SQLite** - public domain.

## Phase-2 model stack (added later, commercial-friendly)
- **Qwen3-4B-Instruct** - Apache-2.0.
- **multilingual-e5-base** - MIT.
- **Piper** - MIT. **Kokoro** - Apache-2.0.

Deliberately avoided for commercial use: non-commercial-licensed models such as
jina-embeddings-v3 (CC-BY-NC) and XTTS (non-commercial).
