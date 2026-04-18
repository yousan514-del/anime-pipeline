# anime-pipeline 🎨⚡

**Automated AI illustration & video generation pipeline for anime-style content.**  
ComfyUI × Qwen VL × WAN 2.2 Lightning — from theme prompt to upload-ready package.

> セミリアルアニメ調のAIイラスト・動画を、テーマ入力から投稿パッケージまで自動化するパイプライン。

---

## Overview / 概要

```
[1] Theme (Japanese)
    ↓  prompt_gen.py  (Qwen 2.5 → ComfyUI English prompt)
[2] ComfyUI t2i / I2V
    ↓  comfyui_batch_gen.py / i2v_batch_gen.py
[3] Quality Filter
    ↓  quality_eval.py  (PIL fast-score + Qwen VL visual judge)
[4] Sync & Package
    ↓  comfyui_sync.py → prepare_upload.py
[5] Upload-ready folder (pixiv / FANBOX)
```

---

## Features / 機能

| Script | Description |
|--------|-------------|
| `prompt_gen.py` | Japanese theme → ComfyUI English prompt via **Qwen 2.5** (Ollama) |
| `comfyui_batch_gen.py` | Batch queue 20+ images to **ComfyUI API** (t2i / LoRA) |
| `i2v_batch_gen.py` | Image-to-Video via **WAN 2.2 Lightning** (4-step LoRA, ~10s/clip) |
| `quality_eval.py` | **2-stage QA**: PIL pixel metrics → Qwen VL composition judge |
| `comfyui_sync.py` | Auto-rename & sync ComfyUI output → project structure |
| `prepare_upload.py` | Mosaic/blur processing + pixiv & FANBOX metadata generation |
| `llm_client.py` | Shared Ollama client with auto-start & multimodal support |

---

## Setup / セットアップ

### Prerequisites

- Python 3.10+
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) running at `http://127.0.0.1:8188`
- [Ollama](https://ollama.ai/) with `qwen2.5-vl:7b` pulled
- GPU: RTX 4070+ recommended (12GB VRAM)

### Install

```bash
git clone https://github.com/yousan514-del/anime-pipeline.git
cd anime-pipeline
pip install -r requirements.txt
```

### Qwen setup (first time only)

```bash
# Windows
setup-qwen.bat

# Manual
ollama pull qwen2.5-vl:7b
```

---

## Usage / 使い方

### Full pipeline (recommended)

```bash
# 1. Generate prompts from theme
py -3 src/prompt_gen.py --theme "メタバース大学の図書館、夕暮れ" --count 10

# 2. Batch generate images
py -3 src/comfyui_batch_gen.py --from-llm --count 20

# 3. Quality evaluation (PIL + Qwen VL)
py -3 src/quality_eval.py --folder drafts/ --llm --auto-reject 60

# 4. Sync to project
py -3 src/comfyui_sync.py --since 2026-01-01

# 5. Prepare for upload
py -3 src/prepare_upload.py --folder drafts/
```

### Image-to-Video (WAN 2.2 Lightning)

```bash
# Convert still images to 5-second anime clips
py -3 src/i2v_batch_gen.py --input-folder drafts/ --steps 4 --fps 24
```

### Single image caption + tags (Qwen VL)

```bash
py -3 src/prompt_gen.py --caption drafts/my_image.png   # pixiv caption
py -3 src/prompt_gen.py --tags   drafts/my_image.png    # pixiv tags (JSON)
```

---

## Workflows / ComfyUIワークフロー

The `workflows/` directory contains 6 ready-to-use ComfyUI JSON workflows:

| Workflow | Description |
|----------|-------------|
| `t2i_illustrious.json` | Text-to-Image (waiIllustrous XL) |
| `t2i_illustrious_lora.json` | Text-to-Image + LoRA stack |
| `i2v_wan22_lightning.json` | Image-to-Video 4-step Lightning |
| `qwen35_theme2prompt.json` | Japanese theme → English prompt (in-ComfyUI) |
| `qwen35_image2caption.json` | Image → pixiv caption |
| `qwen35_quality_eval.json` | Visual quality evaluation |

---

## LoRA Stack / 使用LoRA

| LoRA | Purpose |
|------|---------|
| `Anime_artistic_2` | Anime style enhancer |
| `DetailedEyes_V3` | Eye detail boost |
| `Hyperrealistic_illustrious` | Semi-realistic texture |
| `Smooth_Booster_v4` | Smooth animation |
| `Wan2.2-Lightning_I2V` | Fast I2V (4-step) |
| `ComfyUI_trained_lora_640_steps` | Custom character LoRA |

---

## Quality Score System

```
Stage 1 — PIL fast score (instant)
  Resolution × 0.30 + Sharpness × 0.25 + Contrast × 0.20
  + Brightness × 0.15 + Saturation × 0.10

Stage 2 — Qwen VL judge (optional, ~5s/image)
  Composition / World consistency / Post suitability
  → S/A/B/C/D grade

Auto-reject threshold: configurable (default: 60/100)
```

---

## Tech Stack

- **Python 3.11** — automation & pipeline
- **ComfyUI** — image/video generation backend
- **Qwen 2.5-VL 7B** — prompt gen, captioning, quality judge (Ollama)
- **WAN 2.2 Lightning** — fast I2V (4-step LoRA)
- **waiIllustrous XL** — base checkpoint (anime/semi-real)
- **Pillow / NumPy** — pixel-level quality metrics

---

## License

MIT — see [LICENSE](LICENSE)

---

*Built for AI anime content production · pixiv / FANBOX / Booth pipeline*
