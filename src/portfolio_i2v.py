#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_i2v.py — SFW Portfolio I2V Generator
===============================================
WAN 2.2 GGUF Q5_K_M による Image-to-Video 生成。
ポートフォリオ用 SFW サンプル動画を drafts/ フォルダから一括生成する。

使い方:
  py -3 portfolio_i2v.py                        # drafts/ の全画像を変換
  py -3 portfolio_i2v.py --input path/to/img.png # 1枚指定
  py -3 portfolio_i2v.py --dry-run               # 確認のみ（送信しない）

出力先:
  D:/portfolio/anime-pipeline/examples/
    ├── videos/  ← 生成動画 (mp4)
    └── stills/  ← ソース画像コピー

モデル構成:
  UNET   : Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf  (GGUF, VRAM ~7GB)
  CLIP   : umt5-xxl-encoder-Q5_K_M.gguf            (GGUF, VRAM ~1.5GB)
  Vision : wan21NSFWClipVisionH_v10.safetensors
  VAE    : wan2.2_vae.safetensors

  ※ Lightning LoRA (fp16) は GGUF Q5 アーキテクチャと patch_embedding チャネル数
    (36 vs 64) が不一致のため使用不可。20-step euler に変更。

生成設定 (20-step):
  Steps : 20   Sampler: euler   Scheduler: simple
  CFG   : 1.0  Shift: 5.0
  Size  : 832×1216  Duration: 3s @ 16fps = 49 frames
"""

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ─── パス設定 ─────────────────────────────────────────────────────────────────
COMFYUI_URL   = "http://127.0.0.1:8188"
COMFYUI_INPUT = Path("D:/ComfyUI/input")
SOURCE_DIRS   = [
    Path("D:/ai-studio/01-pixiv-studio/drafts"),
    Path("D:/upload/20260304"),
]
EXAMPLES_DIR  = Path("D:/portfolio/anime-pipeline/examples")
COMFYUI_OUT   = Path("D:/ComfyUI/output")

# ─── モデル設定 ────────────────────────────────────────────────────────────────
UNET_HIGH  = "Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf"   # Q5 = VRAM ~7GB, Q8 = ~10GB
CLIP_GGUF  = "umt5-xxl-encoder-Q5_K_M.gguf"
CLIP_VIS   = "wan21NSFWClipVisionH_v10.safetensors"
VAE_NAME   = "wan_2.1_vae.safetensors"   # GGUF is WAN2.1 architecture (36-ch patch_embed)
# ─── 生成設定 (20-step, no LoRA) ─────────────────────────────────────────────
# Lightning LoRA fp16 は GGUF Q5_K_M と patch_embedding チャネル数不一致のため除外
STEPS    = 20
CFG      = 1.0
SHIFT    = 5.0
WIDTH    = 832
HEIGHT   = 1216
FPS      = 16
DURATION = 3   # 秒 (Q5 でも安定動作する短め設定)
FRAMES   = int(DURATION * FPS)   # 48 → WAN互換 4n+1 で 49

POSITIVE = (
    "masterpiece, best quality, ultra detailed, cinematic lighting, "
    "soft ambient light, futuristic atmosphere, anime style"
)
NEGATIVE = "bad quality, bad anatomy, low quality, blurry, worst quality"

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}


# ─── ComfyUI API ──────────────────────────────────────────────────────────────
def api_post(endpoint: str, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{COMFYUI_URL}{endpoint}",
        data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[HTTP {e.code}] {err_body[:1000]}")
        raise


def upload_image(path: Path) -> str:
    """ComfyUI の input/ にコピーして画像名を返す"""
    dest = COMFYUI_INPUT / path.name
    shutil.copy2(path, dest)
    return path.name


def queue_prompt(workflow: dict) -> str:
    result = api_post("/prompt", {"prompt": workflow})
    return result["prompt_id"]


def wait_for_completion(prompt_id: str, timeout: int = 600) -> bool:
    """プロンプトIDの完了を待つ"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10) as r:
                history = json.loads(r.read())
            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                if outputs:
                    return True
        except Exception:
            pass
        time.sleep(3)
    return False


def find_output_video(prompt_id: str) -> Path | None:
    """生成された動画ファイルを探す"""
    try:
        with urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10) as r:
            history = json.loads(r.read())
        outputs = history.get(prompt_id, {}).get("outputs", {})
        for node_outputs in outputs.values():
            for key in ("gifs", "videos"):
                for item in node_outputs.get(key, []):
                    vid_path = COMFYUI_OUT / item.get("subfolder", "") / item["filename"]
                    if vid_path.exists():
                        return vid_path
    except Exception:
        pass
    return None


# ─── ワークフロー構築 ─────────────────────────────────────────────────────────
def build_sfw_i2v_workflow(image_name: str, seed: int = -1) -> dict:
    """
    SFW WAN 2.2 I2V ワークフロー (20-step, GGUF, LoRA なし)

    ノード構成:
      10: UnetLoaderGGUF      (HighNoise Q5_K_M GGUF)
      13: ModelSamplingSD3    (shift=5.0)
      20: CLIPLoaderGGUF      (UMT5 GGUF)
      21: VAELoader
      22: CLIPVisionLoader
      30: LoadImage
      31: CLIPVisionEncode
      40: CLIPTextEncode      (positive)
      41: CLIPTextEncode      (negative)
      50: WanImageToVideo
      60: KSamplerSelect
      61: BasicScheduler
      62: SamplerCustomAdvanced
      63: RandomNoise
      64: CFGGuider
      70: VAEDecodeTiled
      80: VHS_VideoCombine
    """
    import random
    if seed < 0:
        seed = random.randint(0, 2**32 - 1)

    # frames → WAN互換 (4n+1)
    n = (FRAMES - 1) // 4
    frames = 4 * n + 1  # 81

    return {
        # ── モデルローダ ─────────────────────────────────
        "10": {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": UNET_HIGH},
        },
        "13": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"shift": SHIFT, "model": ["10", 0]},
        },
        # ── CLIP / VAE / Vision ──────────────────────────
        "20": {
            "class_type": "CLIPLoaderGGUF",
            "inputs": {"clip_name": CLIP_GGUF, "type": "wan"},
        },
        "21": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": VAE_NAME},
        },
        "22": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": CLIP_VIS},
        },
        # ── 入力画像 ─────────────────────────────────────
        "30": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name, "upload": "image"},
        },
        "31": {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "clip_vision": ["22", 0],
                "image": ["30", 0],
                "crop": "center",
            },
        },
        # ── プロンプト ───────────────────────────────────
        "40": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": POSITIVE, "clip": ["20", 0]},
        },
        "41": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE, "clip": ["20", 0]},
        },
        # ── I2V ─────────────────────────────────────────
        "50": {
            "class_type": "WanImageToVideo",
            "inputs": {
                "positive": ["40", 0],
                "negative": ["41", 0],
                "vae": ["21", 0],
                "width": WIDTH,
                "height": HEIGHT,
                "length": frames,
                "batch_size": 1,
                "clip_vision_output": ["31", 0],
                "start_image": ["30", 0],
            },
        },
        # ── サンプラー (Lightning 4-step) ─────────────────
        "60": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": "euler"},
        },
        "61": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["13", 0],
                "scheduler": "simple",
                "steps": STEPS,
                "denoise": 1.0,
            },
        },
        "62": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["63", 0],
                "guider": ["64", 0],
                "sampler": ["60", 0],
                "sigmas": ["61", 0],
                "latent_image": ["50", 2],   # WanImageToVideo output[2] = LATENT
            },
        },
        "63": {
            "class_type": "RandomNoise",
            "inputs": {"noise_seed": seed},
        },
        "64": {
            "class_type": "CFGGuider",
            "inputs": {
                "model": ["13", 0],
                # WanImageToVideo embeds image into CONDITIONING outputs
                "positive": ["50", 0],   # output[0] = positive CONDITIONING (with image)
                "negative": ["50", 1],   # output[1] = negative CONDITIONING
                "cfg": CFG,
            },
        },
        # ── デコード & 出力 ───────────────────────────────
        "70": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["62", 0],
                "vae": ["21", 0],
                "tile_size": 256,
                "overlap": 64,
                "temporal_size": 64,
                "temporal_overlap": 8,
            },
        },
        "80": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["70", 0],
                "frame_rate": FPS,
                "loop_count": 0,
                "filename_prefix": "portfolio_i2v",
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
            },
        },
    }


# ─── メイン処理 ───────────────────────────────────────────────────────────────
def collect_source_images(args_input: str | None) -> list[Path]:
    if args_input:
        p = Path(args_input)
        if p.is_file():
            return [p]
        if p.is_dir():
            return sorted(p.glob("*.png")) + sorted(p.glob("*.jpg"))

    images = []
    for d in SOURCE_DIRS:
        if d.exists():
            for ext in SUPPORTED:
                images.extend(sorted(d.glob(f"*{ext}")))
    return images[:5]   # ポートフォリオ用は最大5枚


def main():
    parser = argparse.ArgumentParser(description="SFW Portfolio I2V Generator")
    parser.add_argument("--input",   help="入力画像 or フォルダ")
    parser.add_argument("--dry-run", action="store_true", help="確認のみ")
    parser.add_argument("--steps",   type=int, default=STEPS)
    args = parser.parse_args()

    # 出力ディレクトリ準備
    (EXAMPLES_DIR / "videos").mkdir(parents=True, exist_ok=True)
    (EXAMPLES_DIR / "stills").mkdir(parents=True, exist_ok=True)

    images = collect_source_images(args.input)
    if not images:
        print("[ERROR] 入力画像が見つかりません")
        sys.exit(1)

    print(f"[INFO] {len(images)} 枚の画像を処理します")
    print(f"[INFO] モデル: WAN2.2 GGUF Q5_K_M ({args.steps}-step, LoRA なし)")
    print(f"[INFO] 出力: {EXAMPLES_DIR}/videos/\n")

    for i, img_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img_path.name}")

        if args.dry_run:
            print("  → [DRY RUN] スキップ")
            continue

        # ComfyUI にアップロード
        img_name = upload_image(img_path)
        print(f"  → Upload: {img_name}")

        # ワークフロー送信
        workflow = build_sfw_i2v_workflow(img_name)
        prompt_id = queue_prompt(workflow)
        print(f"  → Queue: {prompt_id[:8]}... ({STEPS}-step euler, 約2-5分)")

        # 完了待ち
        ok = wait_for_completion(prompt_id, timeout=600)   # Q5: ~2-3min per clip
        if not ok:
            print(f"  → [WARN] タイムアウト: {img_path.name}")
            continue

        # 出力ファイルを examples/ に移動
        vid = find_output_video(prompt_id)
        if vid and vid.exists():
            dest = EXAMPLES_DIR / "videos" / f"portfolio_{img_path.stem}.mp4"
            shutil.copy2(vid, dest)
            shutil.copy2(img_path, EXAMPLES_DIR / "stills" / img_path.name)
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"  → Saved: {dest.name} ({size_mb:.1f} MB)")
        else:
            print(f"  → [WARN] 出力動画が見つかりません: {img_path.name}")

    print("\n[DONE] I2V 生成完了")
    print(f"出力先: {EXAMPLES_DIR}/videos/")


if __name__ == "__main__":
    main()
