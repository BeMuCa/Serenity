# Serenity voices - sweet, free, local-first TTS

Curated for ProjectSerenity: a privacy-first, bilingual (German + English) desktop
secretary with a sweet cyberpunk pixel-girl mascot. She already shows speech bubbles;
this is the shortlist for reading them aloud. The lens throughout is privacy-first:
**local/offline is strongly preferred; cloud is an opt-in caveat, never the default.**

Researched and verified June 2026. Licenses and "sweetness" should be re-checked by
ear before any commercial ship - see the honest-uncertainties note at the end.

## TL;DR recommendation

- **Default (sweet + local + DE/EN): Piper.** It is the only fully-offline,
  permissively-licensed engine here with genuinely sweet female voices in **both**
  German and English. Ship two voices:
  - **English -> `en_US-amy` (medium)** - soft, warm, friendly young-adult female; the
    community's go-to "pleasant assistant" voice.
  - **German -> `de_DE-kerstin` (low)** - warm, friendly conversational German female,
    and CC0 (the cleanest possible license).
- **Backup (cleanest license, English only): Kokoro-82M `af_heart`** - Apache-2.0, tiny,
  very natural flagship female. No German, so it cannot be the bilingual default.
- **Zero-download offline fallback: Windows SAPI5** (Zira EN / Katja-Hedda DE) - free and
  offline, but sounds dated/robotic. A "basic" tier, not the sweet default.
- **edge-tts (Ana, Jenny, Katja): do NOT use as default.** It is a cloud call to
  Microsoft, breaks the offline/privacy guarantee, and sits in a ToS gray area. Offer
  only behind an explicit opt-in "online HD voice" toggle.

The single decisive finding: **Kokoro and MeloTTS have no German.** That alone makes
**Piper the only engine that satisfies sweet + local + bilingual DE/EN** - which is why
it is the app default and the voices we actually sampled (see `voices.html`).

## Comparison table

| Voice | Engine | License + catch | Language(s) | Local/Cloud | Size + RAM | Sweetness / character | Where to get |
|---|---|---|---|---|---|---|---|
| **en_US-amy** (medium) | Piper | Mimic3 dataset, broadly permissive - verify specific terms for commercial | EN-US | Local | ~63 MB / <~100 MB RAM | Soft, warm, friendly young-adult female | HF rhasspy/piper-voices (URLs below) |
| **en_GB-jenny_dioco** (medium) | Piper | Custom "Jenny (Dioco)" - commercial OK but you must call it "Jenny (Dioco)" | EN-GB | Local | ~63 MB / <~100 MB | Warm, gentle, expressive British female; arguably sweetest EN | HF (URLs below) |
| **en_US-ljspeech** (high) / **en_US-kristin** (medium) | Piper | Public domain (LJ Speech) - zero strings | EN-US | Local | high ~110 MB / medium ~63 MB | Clear, neutral-friendly clean narrator female | HF |
| **en_US-hfc_female** (medium) | Piper | CC BY-NC-SA 4.0 - NON-COMMERCIAL | EN-US | Local | ~63 MB | Clean, studio-quality female (great, but NC) | HF (avoid for product) |
| **de_DE-kerstin** (low) | Piper | CC0 (public domain) - no strings | DE | Local | ~63 MB / <~100 MB | Warm, natural, friendly conversational German female | HF (URLs below) |
| **de_DE-eva_k** (x_low) | Piper | M-AILABS (BSD-style) - commercial OK with attribution | DE | Local | ~21 MB | Soft, gentle, audiobook tone; sweet but low fidelity (x_low) | HF (URLs below) |
| **de_DE-ramona** (low) | Piper | M-AILABS (BSD-style) - attribution | DE | Local | ~21 MB | Pleasant audiobook narration female | HF |
| **de_DE-thorsten** | Piper | CC0 | DE | Local | up to high | Excellent quality but MALE | HF (not a fit) |
| **af_heart** | Kokoro-82M | Apache-2.0 - clean, commercial OK | EN (US/GB) + 7 langs, NO German | Local | fp32 ~326 MB / q8 ~80 MB | Flagship grade-A warm female (sweetest by reputation) | HF hexgrad/Kokoro-82M |
| **af_bella** | Kokoro-82M | Apache-2.0 | EN + above, no German | Local | as above | Grade A-, most training data; warm female | HF |
| EN-US / EN-BR etc. | MeloTTS | MIT - clean | EN (US/UK/IN/AU) + 5 langs, NO German | Local (CPU real-time) | not published | Neutral/clear; gender and sweetness undocumented | GitHub myshell-ai/MeloTTS |
| **Zira** (EN-US) / **Katja**, **Hedda** (DE) | Windows SAPI5 | Free with Windows; cannot redistribute voices | EN-US, EN-GB, DE | Local | OS built-in | Dated/robotic - fallback only | Built into Windows (pyttsx3) |
| Katja Natural (DE), Aria/Jenny (EN) | Windows Narrator "Natural" | Free with Windows | DE, EN | Local after download | OS | Genuinely sweet/warm - but NOT exposed to apps | Walled inside Narrator |
| **en-US-AnaNeural** | edge-tts | Code GPL-3.0; Microsoft service ToS - personal use only | EN-US | CLOUD | n/a (server-side) | Cute, child-like, sweetest | pip install edge-tts |
| **en-US-JennyNeural** | edge-tts | same ToS caveat | EN-US | CLOUD | n/a | Warm, caring adult female | edge-tts |
| **de-DE-KatjaNeural / AmalaNeural** | edge-tts | same ToS caveat | DE | CLOUD | n/a | Friendly, positive German female | edge-tts |
| XTTS-v2 | Coqui (idiap fork) | Weights CPML - NON-COMMERCIAL (code MPL-2.0) | DE+EN (17 langs) | Local | ~1.8 GB | High quality, voice cloning | idiap/coqui-ai-TTS |
| Parler-TTS Mini Multilingual | Parler | Apache-2.0 | DE+EN (8 EU langs) | Local | medium | Prompt-described voice (no fixed identity) | huggingface/parler-tts |
| Chatterbox Multilingual | Resemble AI | MIT (auto-watermarks output) | DE+EN (20+) | Local | medium-large | Cloning + emotion control | resemble-ai/chatterbox |

(Disk sizes above for the Piper voices we downloaded: amy medium 63 MB, kerstin low 63 MB,
jenny_dioco medium 63 MB, eva_k x_low 21 MB. RAM at synth time stays under ~100 MB.)

## Per-engine notes

### 1. Piper - the recommended core (local, sweet, bilingual)

- **Engine moved:** active development is now `OHF-Voice/piper1-gpl` (old `rhasspy/piper`
  is archived). The new engine is GPL-3.0; the old one was MIT - matters for how you link
  or distribute the engine, not the voices. Install: `pip install piper-tts` (imports as
  `piper`). This is exactly what `requirements-voice.txt` pins.
- **Voices still live at** `https://huggingface.co/rhasspy/piper-voices`. Per-voice
  licenses vary independently of the engine - this is the key gotcha. A voice's terms are
  in its `MODEL_CARD` file (verified: `de_DE-kerstin` says "License: CC0"; `en_US-amy`
  points to the Mimic3 repo for terms, treated as permissive but confirm before commercial
  ship).
- **Runtime:** CPU-only, under ~100 MB RAM, near real-time even on a Raspberry Pi.
  Quality levels: x_low (~10-21 MB), low (~21-63 MB), medium (~63 MB), high (~110 MB).
- **sherpa-onnx (Apache-2.0) can also run Piper voices** - a good cross-platform / embedded
  runtime if the GPL engine is awkward to distribute: https://k2-fsa.github.io/sherpa/onnx/tts/piper.html
- **Sweetest DE female -> `de_DE-kerstin`** (warm + CC0). **Sweetest EN female ->
  `en_US-amy`** (warm, permissive) or `en_GB-jenny_dioco` (sweetest overall, attribution
  catch). **Avoid for a product:** `en_US-hfc_female` and `de_DE-pavoque` are CC BY-NC-SA
  (non-commercial); pavoque is also male.

Exact download URLs (pattern: `.../resolve/main/<lang2>/<locale>/<name>/<quality>/<locale>-<name>-<quality>.onnx` plus the matching `.onnx.json`):

EN - amy (medium), the app default:
```
https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx
https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json
```
EN - jenny_dioco (medium), backup:
```
https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx
https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium.onnx.json
```
EN - ljspeech (high, public domain):
```
https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx
https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/high/en_US-ljspeech-high.onnx.json
```
DE - kerstin (low, CC0), the app default:
```
https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/kerstin/low/de_DE-kerstin-low.onnx
https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/kerstin/low/de_DE-kerstin-low.onnx.json
```
DE - eva_k (x_low, M-AILABS attribution), backup:
```
https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/eva_k/x_low/de_DE-eva_k-x_low.onnx
https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/eva_k/x_low/de_DE-eva_k-x_low.onnx.json
```
(View a voice's `MODEL_CARD` by swapping `resolve` for `blob` in its folder URL.)

**How Serenity uses them:** drop the `.onnx` (and optional `.onnx.json`) into the per-user
voices folder (`%APPDATA%/Serenity/voices` on Windows, `~/.config/serenity/voices`
otherwise), set the voice id in Settings (e.g. `de_DE-kerstin-low`, `en_US-amy-medium`),
and `core.tts.PiperEngine` loads them by id.

### 2. Kokoro-82M - best single English voice, but no German

- **License: Apache-2.0** - genuinely clean for commercial use. Fully local. 82M params;
  ONNX fp32 ~326 MB, q8 ~80 MB. Near real-time on CPU.
- **`af_heart`** is the highest-graded voice (the flagship heart voice); `af_bella` is A-.
  These are the standard warm/natural female picks. Sweetness is by grade/reputation - the
  docs do not describe tone in prose, so audition at the demo Space.
- **German: NO.** Official language codes are exactly nine: en-US, en-GB, es, fr, hi, it,
  ja, pt-BR, zh. Unofficial German community fine-tunes exist (`semidark/kokoro-deutsch`,
  `Thomcle/kokoro_german`) but are not official and carry quality/maintenance risk.
- Get it: `pip install kokoro` (or `kokoro-onnx`); model `https://huggingface.co/hexgrad/Kokoro-82M`.

### 3. MeloTTS - clean license, but no German and undocumented voice character

- **License: MIT.** Fully local, advertised CPU real-time. Languages: EN (US/UK/Indian/
  Australian/Default), es, fr, zh, ja, ko.
- **German: NO** - the "German Language support" GitHub issue is still open/unimplemented;
  `language='DE'` throws file-not-found.
- Voice gender/sweetness is not documented, so you cannot pick a named sweet-female mascot
  the way Kokoro lets you. Size/RAM not published.
- Get it: `https://github.com/myshell-ai/MeloTTS`, models at `https://huggingface.co/myshell-ai`.

### 4. Windows SAPI / WinRT - the offline baseline (but the good voices are walled off)

Three generations, not equally reachable by apps:
- **SAPI5 classic** (Zira EN-US female; Hazel/Susan EN-GB female; Katja/Hedda DE female):
  fully offline, free, but robotic/dated. Reachable via **pyttsx3** (drives SAPI5 COM).
  This is the only truly zero-dependency path, and what `core.tts.Sapi5Engine` uses.
- **OneCore "Mobile" voices**: a modest quality bump, still offline; reachable from SAPI5
  via `SpObjectTokenCategory` pointed at the OneCore hive.
- **Narrator "Natural" neural voices** (de-DE Katja, en-US Aria/Jenny, en-GB Sonia):
  genuinely sweet/warm, run local after a one-time download, German available - BUT they
  are private to Narrator and NOT exposed to SAPI5 or WinRT `AllVoices`. A normal app
  cannot use them without the third-party `NaturalVoiceSAPIAdapter` bridge (unsupported,
  fragile, also bridges online voices - careful to keep it offline).
- **Python access:** pyttsx3 -> SAPI5 (simplest). WinRT via PyWinRT packages
  (`winrt-runtime`, `winrt-Windows.Media.SpeechSynthesis`) -> `SpeechSynthesizer.all_voices`,
  a cleaner async/SSML API but the same default voice set as SAPI5 (no Natural voices).
- **License:** built into Windows, free to consume on the user's machine; you may not
  redistribute the voice files.
- Verdict: a fine always-available fallback tier (label it "basic"), not the sweet default.

### 5. edge-tts - sweet voices, but CLOUD - privacy red flag

- **NOT local.** Every synthesis sends your text over the internet to Microsoft's Edge
  "Read Aloud" service; there is no offline fallback. This breaks Serenity's offline/privacy
  guarantee and means private text leaves the device. Use only as an explicit, consented
  opt-in "online HD voice."
- **License/ToS:** the package is GPL-3.0 (copyleft). Separately, the Microsoft service ToS
  is the real issue: the maintainer says it is "meant for personal use" and advises against
  commercial use; a Microsoft moderator confirmed programmatic/commercial use without an
  Azure subscription "could be a violation of our terms of service." A genuine gray area.
- **Sweetest voices** (if used at all): EN -> `en-US-AnaNeural` (cute/child-like),
  `en-US-JennyNeural` (warm adult, best for a mature secretary); DE -> `de-DE-KatjaNeural` /
  `de-DE-AmalaNeural`. One bilingual option: `de-DE-SeraphinaMultilingualNeural` (verify it
  is in your `edge-tts --list-voices`).
- Get it: `pip install edge-tts` - `https://github.com/rany2/edge-tts`.

### Other contenders (brief, honest)

- **Coqui XTTS-v2** - Coqui shut down Jan 2024. Local, DE+EN (17 langs), voice cloning,
  ~1.8 GB. Weights are CPML = NON-COMMERCIAL even though the maintained fork's code is
  MPL-2.0. Two-license trap: permissive code does not make the weights usable. Blocker.
- **Parler-TTS** - Apache-2.0 (code + checkpoints), local, DE+EN via Mini Multilingual.
  Voice is described by a text prompt (no fixed identity), quality a notch below Kokoro.
  The most license-clean DE+EN option if a fixed mascot voice is not required.
- **Chatterbox Multilingual** (Resemble AI) - MIT, local, DE+EN (20+), cloning + emotion
  control; auto-watermarks every output (disclose for a privacy product).
- **StyleTTS2** - MIT, human-level quality, but English-only released models -> poor DE fit.
- **F5-TTS** - code MIT but weights CC-BY-NC (non-commercial). Blocker for product.
- **sherpa-onnx** - Apache-2.0 runtime, not voices. Runs Piper/VITS/Kokoro ONNX models
  fully offline on desktop/mobile/embedded. A natural pairing with local Piper DE/EN voices.

## Recommendation (privacy-first lens)

1. **Default (sweet + local + DE/EN): Piper**, shipping `en_US-amy` (medium) for English
   and `de_DE-kerstin` (low) for German. Both run fully offline (under ~100 MB RAM); kerstin
   is CC0 and amy is permissive - clean privacy and licensing. These are the values baked
   into `Settings.tts_voice_en` / `tts_voice_de`.
   - Sweeter-tone alternatives with mild terms: `en_GB-jenny_dioco` (credit "Jenny (Dioco)")
     and `de_DE-eva_k` (attribution, x_low fidelity).
   - Bulletproof no-attribution English: `en_US-ljspeech` (high) or `en_US-kristin` (medium),
     both public domain (more "clean narrator" than "sweet").
2. **English-only backup: Kokoro-82M `af_heart`** (Apache-2.0, very natural). Cannot cover
   German, so secondary.
3. **Zero-download fallback tier: Windows SAPI5** (Zira / Katja). Offline and free, but flag
   it as "basic" because it is robotic. This is `core.tts.Sapi5Engine`.
4. **Opt-in online HD only: edge-tts** (Jenny / Ana / Katja) behind an explicit consent
   toggle - never the default, because it sends text to Microsoft and is a ToS gray area.
   (Not implemented in the app; left as a documented future opt-in.)

Do NOT use for a shipped product: XTTS-v2 (CPML-NC), F5-TTS weights (CC-BY-NC), Fish Speech
(research license), Piper `hfc_female` and `pavoque` (CC BY-NC-SA).

## Listen first - official sample/demo pages

- Piper voices (official samples, same paragraph per voice for easy A/B):
  `https://rhasspy.github.io/piper-samples/` - interactive: `https://rhasspy.github.io/piper-samples/demo.html`
- Kokoro (official HF Space demo, audition af_heart vs af_bella):
  `https://huggingface.co/spaces/hexgrad/Kokoro-TTS`
- MeloTTS: demo linked from `https://github.com/myshell-ai/MeloTTS`.
- edge-tts voice browser (listen to Ana/Jenny/Katja): `https://tts.travisvn.com/` -
  canonical voice list: `https://gist.github.com/BettyJJ/17cbaa1de96235a7f5773b8690a20462`

Local samples we synthesized for this project (Serenity's own greeting + a slot-fill
question, DE and EN) are in `Serenity_Mockups/voices/` with a player page at
`Serenity_Mockups/voices.html`.

## Honest uncertainties

- "Sweetness" of `af_heart` vs `af_bella`, and of specific Piper voices, is best confirmed
  by ear - grades and descriptions only go so far. The local samples exist for exactly this.
- `en_US-amy`'s license is treated as permissive but its `MODEL_CARD` points to the Mimic3
  repo rather than a clean SPDX tag - verify the specific terms before commercial use.
- `de-DE-SeraphinaMultilingualNeural` is the correct identifier (not `SeraphinaNeural`);
  confirm it appears in your installed `edge-tts --list-voices`.
- The two-license trap (XTTS-v2, F5-TTS): permissive code does not make the weights
  commercially usable. Always check the weights' license separately.
