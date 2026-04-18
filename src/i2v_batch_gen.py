#!/usr/bin/env python3
"""
ComfyUI WAN 2.2 I2V バッチ動画生成ツール

D:/upload/20260304 の全画像を5秒動画に変換する。
既存の20260304i2v.jsonワークフローをベースに、高速化設定で生成。

使い方:
  py -3 i2v-batch-gen.py                          # デフォルト実行
  py -3 i2v-batch-gen.py --steps 20 --fps 16      # 高速モード
  py -3 i2v-batch-gen.py --dry-run                 # 確認のみ
"""

import argparse
import base64
import json
import os
import random
import shutil
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# --- 設定 ---
COMFYUI_URL = "http://127.0.0.1:8188"
COMFYUI_INPUT = Path("D:/ComfyUI/input")
COMFYUI_OUTPUT_VIDEO = Path("D:/ComfyUI/output/video")
SOURCE_DIR = Path("D:/upload/20260304")
OUTPUT_DIR = Path("D:/upload")

# 動画生成パラメータ（品質+速度バランス）
DEFAULT_STEPS = 35
DEFAULT_FPS = 16
DEFAULT_DURATION = 5  # 秒

# モデル設定（既存ワークフローから）
CLIP_NAME = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE_NAME = "wan_2.1_vae.safetensors"
CLIP_VISION = "clip_vision_h.safetensors"
GGUF_HIGH = "Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf"
GGUF_LOW = "Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf"

# LoRA設定
LORAS = [
    {"name": "NSFW-22-H-e8.safetensors", "strength": 0.75, "noise": "high"},
    {"name": "NSFW-22-L-e8.safetensors", "strength": 0.75, "noise": "low"},
    {"name": "smoothxxxanimation.j6bQ.safetensors", "strength": 0.2, "noise": "both"},
    {"name": "wan22I2VHighLSDasiwa.4ctl.safetensors", "strength": 0.2, "noise": "both"},
]

DEFAULT_POSITIVE = "High Quality, Professional"
NEGATIVE_PROMPT = "bad quality, bad anatomy, low quality"

# Qwen設定
OLLAMA_URL = "http://127.0.0.1:11434"
QWEN_MODEL = "qwen3:latest"
QWEN_PROMPT = """Analyze this anime/illustration image and generate a short motion description for image-to-video generation.
Focus on: character movement, hair/clothing physics, background atmosphere, camera motion.
Keep it concise (1-2 sentences). Output ONLY the motion description in English, no explanation.
Example: "gentle hair and clothing sway in breeze, soft ambient light shifts, slight camera zoom in"
"""
WIDTH = 832
HEIGHT = 1216
SHIFT = 5       # 低めでキャラ崩れ防止（元8）
CFG = 3.5       # 高めでキャラ構造維持（元2.5）

# EasyCache設定（速度向上・品質維持）
EASYCACHE_THRESHOLD = 0.2
EASYCACHE_START = 0.15
EASYCACHE_END = 0.95


def calc_frames(duration: float, fps: float) -> int:
    """WAN互換フレーム数を計算 (4n+1)"""
    raw = int(duration * fps)
    n = (raw - 1) // 4
    return 4 * n + 1


def qwen_describe_image(image_path: Path) -> str | None:
    """Qwen VLで画像を分析し、動画用モーションプロンプトを生成"""
    try:
        img_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        payload = {
            "model": QWEN_MODEL,
            "prompt": QWEN_PROMPT,
            "images": [img_data],
            "stream": False,
            "options": {"num_predict": 100, "temperature": 0.7},
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            result = json.loads(r.read())
        response = result.get("response", "").strip()
        # 余計な思考タグを除去
        if "<think>" in response:
            response = response.split("</think>")[-1].strip()
        return response if response else None
    except Exception as e:
        print(f"    [WARN] Qwen failed: {e}")
        return None


def check_ollama() -> bool:
    """Ollamaが起動しているか確認"""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as r:
            data = json.loads(r.read())
            models = [m["name"] for m in data.get("models", [])]
            return any("qwen" in m for m in models)
    except Exception:
        return False


def clear_comfyui_queue():
    """ComfyUIの待機キューをクリア"""
    try:
        api_post("/queue", {"clear": True})
        print("  Queue cleared.")
    except Exception as e:
        print(f"  [WARN] Failed to clear queue: {e}")


def build_i2v_workflow(image_name: str, seed: int, steps: int, fps: float, frames: int, positive_prompt: str = DEFAULT_POSITIVE) -> dict:
    """WAN 2.2 I2V ワークフロー（デュアルパス）をAPI形式で構築"""
    split_step = steps * 2 // 5  # 40%でハイ→ロー切替

    return {
        # CLIP Loader
        "84": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP_NAME, "type": "wan", "device": "cpu"},
        },
        # VAE Loader
        "90": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": VAE_NAME},
        },
        # Load Image
        "97": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        # Positive prompt
        "93": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["84", 0]},
        },
        # Negative prompt
        "89": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE_PROMPT, "clip": ["84", 0]},
        },
        # WAN Image to Video
        "98": {
            "class_type": "WanImageToVideo",
            "inputs": {
                "width": WIDTH, "height": HEIGHT,
                "length": frames, "batch_size": 1,
                "positive": ["93", 0], "negative": ["89", 0],
                "vae": ["90", 0], "start_image": ["97", 0],
            },
        },
        # HighNoise GGUF model
        "132": {
            "class_type": "LoaderGGUF",
            "inputs": {"gguf_name": GGUF_HIGH},
        },
        # LowNoise GGUF model
        "131": {
            "class_type": "LoaderGGUF",
            "inputs": {"gguf_name": GGUF_LOW},
        },
        # LoRA chain - HighNoise path: 132 -> 117 (NSFW-H) -> 134 (smooth) -> 141 (dasiwa)
        "117": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "NSFW-22-H-e8.safetensors", "strength_model": 0.75, "model": ["132", 0]},
        },
        "134": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "smoothxxxanimation.j6bQ.safetensors", "strength_model": 0.2, "model": ["117", 0]},
        },
        "141": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "wan22I2VHighLSDasiwa.4ctl.safetensors", "strength_model": 0.2, "model": ["134", 0]},
        },
        # LoRA chain - LowNoise path: 131 -> 119 (NSFW-L) -> 136 (smooth) -> 138 (dasiwa)
        "119": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "NSFW-22-L-e8.safetensors", "strength_model": 0.75, "model": ["131", 0]},
        },
        "136": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "smoothxxxanimation.j6bQ.safetensors", "strength_model": 0.2, "model": ["119", 0]},
        },
        "138": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"lora_name": "wan22I2VHighLSDasiwa.4ctl.safetensors", "strength_model": 0.2, "model": ["136", 0]},
        },
        # ModelSamplingSD3 - HighNoise
        "122": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"shift": SHIFT, "model": ["141", 0]},
        },
        # EasyCache - HighNoise (速度向上)
        "150": {
            "class_type": "EasyCache",
            "inputs": {
                "model": ["122", 0],
                "reuse_threshold": EASYCACHE_THRESHOLD,
                "start_percent": EASYCACHE_START,
                "end_percent": EASYCACHE_END,
                "verbose": False,
            },
        },
        # ModelSamplingSD3 - LowNoise
        "140": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"shift": SHIFT, "model": ["138", 0]},
        },
        # EasyCache - LowNoise (速度向上)
        "151": {
            "class_type": "EasyCache",
            "inputs": {
                "model": ["140", 0],
                "reuse_threshold": EASYCACHE_THRESHOLD,
                "start_percent": EASYCACHE_START,
                "end_percent": EASYCACHE_END,
                "verbose": False,
            },
        },
        # KSampler Pass 1 (HighNoise: step 0 -> split_step)
        "123": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "add_noise": "enable",
                "noise_seed": seed,
                "steps": steps,
                "cfg": CFG,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": 0,
                "end_at_step": split_step,
                "return_with_leftover_noise": "enable",
                "model": ["150", 0],
                "positive": ["98", 0],
                "negative": ["98", 1],
                "latent_image": ["98", 2],
            },
        },
        # KSampler Pass 2 (LowNoise: split_step -> end)
        "85": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "add_noise": "disable",
                "noise_seed": 0,
                "steps": steps,
                "cfg": CFG,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": split_step,
                "end_at_step": 10000,
                "return_with_leftover_noise": "disable",
                "model": ["151", 0],
                "positive": ["98", 0],
                "negative": ["98", 1],
                "latent_image": ["123", 0],
            },
        },
        # VAE Decode
        "87": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["85", 0], "vae": ["90", 0]},
        },
        # Create Video
        "94": {
            "class_type": "CreateVideo",
            "inputs": {"fps": fps, "images": ["87", 0]},
        },
        # Save Video
        "108": {
            "class_type": "SaveVideo",
            "inputs": {
                "filename_prefix": "video/i2v_batch",
                "format": "auto",
                "codec": "auto",
                "video": ["94", 0],
            },
        },
    }


def api_get(path: str) -> dict:
    url = f"{COMFYUI_URL}{path}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def api_post(path: str, data: dict) -> dict:
    url = f"{COMFYUI_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def check_running() -> bool:
    try:
        api_get("/system_stats")
        return True
    except Exception:
        return False


def queue_prompt(workflow: dict) -> str:
    result = api_post("/prompt", {"prompt": workflow})
    return result.get("prompt_id", "")


def get_queue_status() -> tuple:
    data = api_get("/queue")
    running = len(data.get("queue_running", []))
    pending = len(data.get("queue_pending", []))
    return running, pending


def wait_for_queue(total: int):
    """キューが空になるまで進捗表示"""
    completed = 0
    last_pending = total
    start = time.time()

    while True:
        try:
            running, pending = get_queue_status()
        except Exception:
            time.sleep(5)
            continue

        current = running + pending
        if current < last_pending:
            completed += last_pending - current
            last_pending = current

        elapsed = int(time.time() - start)
        bar_len = 30
        done = int(bar_len * completed / total) if total > 0 else 0
        bar = "#" * done + "-" * (bar_len - done)

        print(f"\r  [{bar}] {completed}/{total}  {elapsed//60:02d}:{elapsed%60:02d}  queue:{current}", end="", flush=True)

        if current == 0 and completed >= total:
            break
        time.sleep(5)

    total_time = int(time.time() - start)
    print(f"\n  Complete! {total_time//60}m{total_time%60}s")


def copy_images_to_input(images: list) -> list:
    """画像をComfyUI inputにコピー"""
    copied = []
    for img_path in images:
        dest = COMFYUI_INPUT / img_path.name
        if not dest.exists() or dest.stat().st_mtime < img_path.stat().st_mtime:
            shutil.copy2(img_path, dest)
        copied.append(img_path.name)
    return copied


def collect_existing_videos() -> set:
    """既存の動画ファイル名を収集"""
    if not COMFYUI_OUTPUT_VIDEO.exists():
        return set()
    return {f.name for f in COMFYUI_OUTPUT_VIDEO.glob("*.mp4")}


def move_new_videos(before_set: set, source_names: list):
    """新しく生成された動画をD:/uploadに移動"""
    if not COMFYUI_OUTPUT_VIDEO.exists():
        print("  [WARN] Video output directory not found")
        return

    current = {f.name for f in COMFYUI_OUTPUT_VIDEO.glob("i2v_batch*.mp4")}
    new_videos = sorted(current - before_set)

    if not new_videos:
        print("  No new videos found to move")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for i, vid_name in enumerate(new_videos):
        src = COMFYUI_OUTPUT_VIDEO / vid_name
        # 元の画像名に対応する名前で保存
        if i < len(source_names):
            base = Path(source_names[i]).stem
            dst = OUTPUT_DIR / f"{base}.mp4"
        else:
            dst = OUTPUT_DIR / vid_name

        shutil.copy2(src, dst)
        print(f"  {vid_name} -> {dst.name}")

    print(f"\n  {len(new_videos)} videos saved to {OUTPUT_DIR}")


def main():
    parser = argparse.ArgumentParser(description="ComfyUI WAN 2.2 I2V Batch Generator")
    parser.add_argument("--source", default=str(SOURCE_DIR), help="Source image directory")
    parser.add_argument("--output", default=str(OUTPUT_DIR), help="Output directory for videos")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS, help=f"Sampling steps (default: {DEFAULT_STEPS})")
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS, help=f"Video FPS (default: {DEFAULT_FPS})")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, help=f"Video duration in seconds (default: {DEFAULT_DURATION})")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't queue")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for completion")
    parser.add_argument("--use-qwen", action="store_true", help="Use Qwen VL to generate motion prompts per image")
    parser.add_argument("--clear-queue", action="store_true", help="Clear pending ComfyUI queue before starting")
    args = parser.parse_args()

    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"[ERROR] Source directory not found: {source_dir}")
        sys.exit(1)

    # 画像一覧取得
    images = sorted(source_dir.glob("*.png")) + sorted(source_dir.glob("*.jpg"))
    if not images:
        print(f"[ERROR] No images found in {source_dir}")
        sys.exit(1)

    frames = calc_frames(args.duration, args.fps)

    print(f"\n=== WAN 2.2 I2V Batch Generator ===")
    print(f"  Source:    {source_dir} ({len(images)} images)")
    print(f"  Output:    {args.output}")
    print(f"  Steps:     {args.steps}")
    print(f"  FPS:       {args.fps}")
    print(f"  Duration:  {args.duration}s ({frames} frames)")
    print(f"  Split:     step 0-{args.steps * 2 // 5} (High) / {args.steps * 2 // 5}-{args.steps} (Low)")
    print(f"  Size:      {WIDTH}x{HEIGHT}")
    print()

    for i, img in enumerate(images):
        print(f"  [{i+1:02d}] {img.name}")
    print()

    if not check_running():
        print("[ERROR] ComfyUI is not running at", COMFYUI_URL)
        print("  Start: cd D:/ComfyUI && python main.py --listen")
        sys.exit(1)
    print("ComfyUI connected.")

    # Qwen確認
    use_qwen = args.use_qwen
    if use_qwen:
        if check_ollama():
            print(f"Qwen VL connected ({QWEN_MODEL})")
        else:
            print("[WARN] Qwen not available. Falling back to default prompt.")
            use_qwen = False

    if args.dry_run:
        print("[dry-run] Skipping queue submission.")
        return

    # キュークリア
    if args.clear_queue:
        print("\nClearing ComfyUI queue...")
        clear_comfyui_queue()

    # 画像をComfyUI inputにコピー
    print("\nCopying images to ComfyUI input...")
    image_names = copy_images_to_input(images)
    print(f"  {len(image_names)} images copied.")

    # Qwenでプロンプト生成（ComfyUI生成前に全画像分）
    prompts = {}
    if use_qwen:
        print(f"\nGenerating motion prompts with Qwen...")
        for i, img in enumerate(images):
            print(f"  [{i+1:02d}/{len(images)}] Analyzing {img.name}...", end=" ", flush=True)
            desc = qwen_describe_image(img)
            if desc:
                prompts[img.name] = f"High Quality, Professional, {desc}"
                print(f"OK")
                print(f"    -> {desc[:80]}")
            else:
                prompts[img.name] = DEFAULT_POSITIVE
                print(f"fallback")
        print()

    # 既存動画を記録
    before_videos = collect_existing_videos()

    # キューに追加
    print(f"\nQueuing {len(images)} jobs...")
    prompt_ids = []
    for i, img_name in enumerate(image_names):
        seed = random.randint(1, 2**32 - 1)
        pos = prompts.get(img_name, DEFAULT_POSITIVE)
        workflow = build_i2v_workflow(img_name, seed, args.steps, args.fps, frames, pos)
        try:
            pid = queue_prompt(workflow)
            prompt_ids.append(pid)
            print(f"  [{i+1:02d}/{len(images)}] Queued: {img_name} (seed={seed})")
            if img_name in prompts and prompts[img_name] != DEFAULT_POSITIVE:
                print(f"    prompt: {prompts[img_name][:70]}...")
        except Exception as e:
            print(f"  [{i+1:02d}] [ERROR] {img_name}: {e}")

    print(f"\n{len(prompt_ids)} jobs queued.")

    if args.no_wait:
        print("Use --no-wait: not waiting for completion.")
        return

    # 完了待ち
    print("\nWaiting for generation... (Ctrl+C to skip)")
    try:
        wait_for_queue(len(prompt_ids))
    except KeyboardInterrupt:
        print("\n\nWait skipped.")

    # 動画を移動
    print("\nMoving videos to output...")
    move_new_videos(before_videos, image_names)


if __name__ == "__main__":
    main()
