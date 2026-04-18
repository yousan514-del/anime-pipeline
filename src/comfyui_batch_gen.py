#!/usr/bin/env python3
"""
ComfyUI バッチ生成ツール

pixivスタジオ用のテーマ別プロンプトを一括キューに追加し、
20枚のストックを自動生成する。

使い方:
  python comfyui-batch-gen.py                       # デフォルト20枚生成
  python comfyui-batch-gen.py --count 10            # 10枚生成
  python comfyui-batch-gen.py --theme metaverse     # テーマ指定
  python comfyui-batch-gen.py --theme all           # 全テーマを均等に
  python comfyui-batch-gen.py --day 1               # 7日間プランのDay指定
  python comfyui-batch-gen.py --list-themes         # テーマ一覧を表示
  python comfyui-batch-gen.py --dry-run             # キューに追加せず確認のみ

前提条件:
  ComfyUI が起動していること（http://127.0.0.1:8188）
  起動コマンド例: cd D:/ComfyUI && python main.py --listen
"""

import argparse
import json
import random
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# --- 設定 ---
COMFYUI_URL = "http://127.0.0.1:8188"
STUDIO_ROOT = Path("D:/ai-studio")

# ワークフローの固定設定（t2i.001-1 ベース）
MODEL     = "waiIllustriousSDXL_v160.safetensors"
LORA      = "test1-2.safetensors"
LORA_STR  = 0.9
STEPS     = 40
CFG       = 5
SAMPLER   = "dpmpp_2m_sde"
SCHEDULER = "karras"
WIDTH     = 1024
HEIGHT    = 1024
FILENAME_PREFIX = "NetaYume_Lumina_3.5"

# ネガティブプロンプト（共通）
NEGATIVE = "bad quality, bad anatomy, low quality, worst quality, low res, blurry"

# ベースプロンプト（スタイル固定部分）
BASE_PREFIX = "High Quality, masterpiece, best quality, ultra detailed"

# ===================================================================
# テーマ別プロンプト集（pixivスタジオ世界観）
# ===================================================================
THEMES = {
    # --- 7日間スタートアップ ---
    "day1_metaverse_classroom": {
        "label": "Day1: メタバース大学の教室",
        "prompts": [
            "holographic classroom, futuristic university, 2040s, glowing screens, students with AR headsets, cyberpunk aesthetic, blue neon lights, large windows, floating data, digital campus",
            "virtual lecture hall, metaverse academy, transparent walls, hologram teacher, students in VR, soft blue lighting, futuristic architecture, digital textbooks floating",
            "neon-lit study room, AI university 2050, holographic whiteboard, diverse students, cyberpunk school uniform, quantum computers on desk, magical data streams",
        ],
    },
    "day2_ai_researcher": {
        "label": "Day2: AI研究員（Future Researcher）",
        "prompts": [
            "female AI researcher, futuristic lab coat, holographic interface, glowing blue data, focused expression, high-tech laboratory, 2040s aesthetic, professional, elegant",
            "scientist woman, digital workspace, transparent monitors, neural network visualization, soft lab lighting, white coat, futuristic office, intense focus, data streams",
            "AI engineer girl, cyberpunk office, multiple holographic screens, coding, neon accents, professional attire, future technology, 2050 aesthetics",
        ],
    },
    "day3_future_city": {
        "label": "Day3: 2040年の街角",
        "prompts": [
            "futuristic city street 2040, flying vehicles, neon signs japanese, cyberpunk urban, people with AR glasses, holographic advertisements, rainy night, reflective puddles",
            "neo tokyo 2040, sunset cityscape, floating platforms, aerial walkways, tech fashion crowd, glowing storefronts, soft purple sky, advanced architecture",
            "future metropolis, daily life 2045, AI assistants visible, clean energy vehicles, digital street signs, multicultural crowd, warm golden hour lighting",
        ],
    },
    "day4_ai_employee_daily": {
        "label": "Day4: AI社員の研究風景",
        "prompts": [
            "AI employee at work, cozy futuristic office, multiple monitors, warm desk lighting, focused woman, coffee cup, holographic notes, professional but comfortable",
            "researcher morning routine, high-tech home office, AI assistant hologram, casual professional wear, natural light, plants and technology combined, peaceful productive",
            "digital artist workspace, glowing screens, future creative studio, woman designing, concept art on monitors, neon accents, comfortable chair, late night work",
        ],
    },
    "day5_setting_document": {
        "label": "Day5: 世界観設定資料（衣装・小物）",
        "prompts": [
            "futuristic fashion design, cyberpunk outfit, tech accessories, character sheet style, multiple angles, detailed costume, 2040s clothing, neon highlights",
            "sci-fi uniform concept art, AI company employee outfit, sleek design, digital badge, holographic elements, professional future fashion, clean lines",
            "character design sheet, metaverse avatar clothing, layered tech wear, smart fabric, minimalist futuristic, design reference, flat lighting",
        ],
    },
    "day6_emotional_scene": {
        "label": "Day6: 感情的なワンシーン",
        "prompts": [
            "girl looking at city lights, melancholic beauty, 2040s rooftop, emotional moment, neon reflection in eyes, quiet night, cinematic composition, soft focus background",
            "woman at holographic window, contemplating, rain outside, cozy interior, warm light contrast, emotional depth, futuristic apartment, solitary but peaceful",
            "AI research assistant, moment of discovery, glowing eyes, soft expression, data streams around, wonder and emotion, intimate portrait, future world",
        ],
    },
    # --- 5シリーズ ---
    "series_student_life": {
        "label": "未来の学生生活シリーズ",
        "prompts": [
            "future student dormitory 2040, shared holographic space, young woman studying, AR textbooks, glowing desk, cozy futuristic room, warm light",
            "metaverse university cafeteria, students chatting, digital food menus, diverse young people, bright airy space, 2040s daily life",
            "commuting to virtual campus, girl with AR headset, morning train, digital cityscape outside, casual future fashion, natural light",
            "campus library 2050, infinite digital archives, student browsing holograms, quiet studious atmosphere, soft blue glow",
            "student presenting hologram project, classroom audience, confident young woman, floating 3D model, applause, futuristic academia",
        ],
    },
    "series_ai_employee": {
        "label": "AI社員の研究風景シリーズ",
        "prompts": [
            "AI illustrator at digital canvas, painting with light, futuristic art studio, creative flow, holographic brushes, inspired expression",
            "future researcher presenting findings, conference room 2040, colleagues watching hologram, professional atmosphere, data visualization",
            "AI engineer debugging code, late night office, multiple screens, focused intensity, coffee, neon city outside window",
            "style director reviewing designs, mood board wall of holograms, creative director energy, minimalist future office",
            "team meeting of AI employees, round holographic table, diverse professionals, 2040s corporation, collaborative energy",
        ],
    },
    "series_metaverse_campus": {
        "label": "メタバース大学の教室シリーズ",
        "prompts": [
            "virtual reality lecture, student in VR pod, experiencing ancient history hologram, educational immersion, future learning",
            "metaverse graduation ceremony, digital caps and gowns, floating achievement badges, emotional celebration, virtual but meaningful",
            "online study group, four students in shared virtual room, each floating in own space, collaborative holographic notes",
            "VR laboratory class, students conducting digital experiments, safe futuristic learning, professor avatar explaining",
            "metaverse library at night, endless digital shelves, lone student reading, atmospheric blue glow, vast knowledge space",
        ],
    },
    "series_future_city": {
        "label": "2040年の街角シリーズ",
        "prompts": [
            "neon rain alley 2040, woman with umbrella, reflective streets, warm neon glow, atmospheric fog, cyberpunk romance",
            "future coffee shop, digital menu, barista with AR assistant, cozy high-tech cafe, customers with devices, morning atmosphere",
            "rooftop garden future city, urban farming, woman tending plants, city skyline background, green tech, peaceful contrast",
            "night market 2040, food vendors with holographic displays, diverse crowd, street food future, festive lights, community",
            "future park, people relaxing, autonomous vehicles passing, trees and screens coexisting, afternoon golden light, urban nature",
        ],
    },
    "series_memory_restorer": {
        "label": "記憶復元士の仕事場シリーズ",
        "prompts": [
            "memory restoration specialist at work, ethereal data streams, delicate interface, woman manipulating memories, mysterious blue light",
            "memory archive room, infinite crystalline storage, specialist navigating emotional data, quiet reverence, soft glow",
            "client session memory restoration, therapeutic tech room, specialist and patient, gentle professional atmosphere, healing light",
            "memory fragment reconstruction, broken data becoming whole, specialist with focused care, puzzle of the past, emotional weight",
            "memory restorer office desk, personal artifacts and digital tools, end of day reflection, melancholy beauty, warm lamp light",
        ],
    },
}

# 全テーマのフラットリスト
ALL_PROMPTS = []
for theme_key, theme_data in THEMES.items():
    for p in theme_data["prompts"]:
        ALL_PROMPTS.append((theme_key, p))


def build_api_workflow(positive_prompt: str, seed: int) -> dict:
    """GUI形式ワークフローをもとに API形式プロンプトを構築"""
    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": MODEL},
        },
        "31": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["4", 0],
                "lora_name": LORA,
                "strength_model": LORA_STR,
            },
        },
        "13": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1},
        },
        "26": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": f"{BASE_PREFIX}, {positive_prompt}",
            },
        },
        "25": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": NEGATIVE,
            },
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["31", 0],
                "positive": ["26", 0],
                "negative": ["25", 0],
                "latent_image": ["13", 0],
                "seed": seed,
                "steps": STEPS,
                "cfg": CFG,
                "sampler_name": SAMPLER,
                "scheduler": SCHEDULER,
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": FILENAME_PREFIX,
            },
        },
    }


def api_get(path: str) -> dict:
    url = f"{COMFYUI_URL}{path}"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def api_post(path: str, data: dict) -> dict:
    url = f"{COMFYUI_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def check_running() -> bool:
    try:
        api_get("/system_stats")
        return True
    except Exception:
        return False


def queue_prompt(workflow: dict) -> str:
    """ワークフローをキューに追加してprompt_idを返す"""
    result = api_post("/prompt", {"prompt": workflow})
    return result.get("prompt_id", "")


def get_queue_status() -> tuple[int, int]:
    """(running, pending) の件数を返す"""
    data = api_get("/queue")
    running = len(data.get("queue_running", []))
    pending = len(data.get("queue_pending", []))
    return running, pending


def wait_for_queue(total: int):
    """キューが空になるまで進捗を表示しながら待つ"""
    print()
    completed = 0
    last_pending = total
    start = time.time()

    while True:
        try:
            running, pending = get_queue_status()
        except Exception:
            time.sleep(2)
            continue

        current_pending = running + pending
        if current_pending < last_pending:
            completed += last_pending - current_pending
            last_pending = current_pending

        elapsed = int(time.time() - start)
        bar_len = 30
        done = int(bar_len * completed / total) if total > 0 else 0
        bar = "█" * done + "░" * (bar_len - done)

        print(f"\r  [{bar}] {completed}/{total} 完了  経過: {elapsed//60:02d}:{elapsed%60:02d}  キュー: {current_pending}件", end="", flush=True)

        if current_pending == 0 and completed >= total:
            break

        time.sleep(2)

    print(f"\n  完了！ 合計時間: {int(time.time()-start)//60}分{int(time.time()-start)%60}秒")


def load_llm_prompts() -> list[tuple[str, str]] | None:
    """prompt-gen.py が生成したキャッシュを読み込む"""
    cache = Path(__file__).parent / ".generated-prompts.json"
    if not cache.exists():
        return None
    try:
        data = json.load(cache.open(encoding="utf-8"))
        prompts = data.get("prompts", [])
        theme = data.get("theme", "llm-generated")
        print(f"  LLM生成プロンプト読み込み: {len(prompts)}個 (テーマ: {theme})")
        return [("llm_generated", p) for p in prompts]
    except Exception as e:
        print(f"  [WARN] キャッシュ読み込み失敗: {e}")
        return None


def select_prompts(theme: str, count: int, day: int | None) -> list[tuple[str, str]]:
    """テーマと枚数に応じてプロンプトを選択"""
    if day is not None:
        day_map = {
            1: "day1_metaverse_classroom",
            2: "day2_ai_researcher",
            3: "day3_future_city",
            4: "day4_ai_employee_daily",
            5: "day5_setting_document",
            6: "day6_emotional_scene",
        }
        theme_key = day_map.get(day)
        if not theme_key:
            print(f"[ERROR] Day {day} は未定義です（1〜6）")
            sys.exit(1)
        prompts = [(theme_key, p) for p in THEMES[theme_key]["prompts"]]
    elif theme == "all":
        prompts = ALL_PROMPTS.copy()
    elif theme in THEMES:
        prompts = [(theme, p) for p in THEMES[theme]["prompts"]]
    else:
        print(f"[ERROR] テーマ '{theme}' が見つかりません。--list-themes で確認してください。")
        sys.exit(1)

    # count枚になるようにループ or トリム
    if len(prompts) < count:
        full_cycles = count // len(prompts)
        remainder = count % len(prompts)
        prompts = prompts * full_cycles + prompts[:remainder]
    else:
        random.shuffle(prompts)
        prompts = prompts[:count]

    return prompts


def main():
    parser = argparse.ArgumentParser(description="ComfyUI バッチ生成ツール")
    parser.add_argument("--count", type=int, default=20, help="生成枚数（デフォルト: 20）")
    parser.add_argument("--theme", default="all", help="テーマ名（all / テーマキー）")
    parser.add_argument("--day", type=int, help="7日間プランのDay番号（1〜6）")
    parser.add_argument("--from-llm", action="store_true",
                        help="prompt-gen.py が生成したプロンプトを使用")
    parser.add_argument("--dry-run", action="store_true", help="キューに追加せず確認のみ")
    parser.add_argument("--list-themes", action="store_true", help="テーマ一覧を表示")
    parser.add_argument("--no-wait", action="store_true", help="キュー追加後に待機しない")
    args = parser.parse_args()

    if args.list_themes:
        print("\n利用可能なテーマ:\n")
        for key, data in THEMES.items():
            print(f"  {key:<35} {data['label']}")
        print(f"\n  {'all':<35} 全テーマをランダムに混在")
        print()
        return

    # ComfyUI起動確認
    if not check_running():
        print("\n[ERROR] ComfyUI が起動していません。")
        print()
        print("起動コマンド:")
        print("  cd D:/ComfyUI")
        print("  python main.py --listen")
        print()
        print("起動後、このスクリプトを再実行してください。")
        sys.exit(1)

    print(f"\nComfyUI 接続OK")

    # プロンプト選択
    if args.from_llm:
        selected = load_llm_prompts()
        if not selected:
            print("[ERROR] LLM生成プロンプトが見つかりません。")
            print("先に prompt-gen.py を実行してください:")
            print("  py -3 prompt-gen.py --theme \"テーマ名\" --count 10")
            sys.exit(1)
        if args.count < len(selected):
            selected = selected[:args.count]
    else:
        selected = select_prompts(args.theme, args.count, args.day)

    print(f"生成予定: {len(selected)}枚")
    print(f"モデル: {MODEL}")
    print(f"LoRA: {LORA} (strength: {LORA_STR})")
    print(f"サイズ: {WIDTH}x{HEIGHT} / Steps: {STEPS} / CFG: {CFG}")
    print()

    # プロンプト一覧を表示
    for i, (theme_key, prompt) in enumerate(selected, 1):
        label = THEMES[theme_key]["label"] if theme_key in THEMES else theme_key
        print(f"  [{i:02d}] {label}")
        print(f"       {prompt[:80]}{'...' if len(prompt) > 80 else ''}")

    print()

    if args.dry_run:
        print("[dry-run] キューへの追加はスキップします。")
        return

    # キューに追加
    print("キューに追加中...")
    prompt_ids = []
    seeds_used = []
    for i, (theme_key, prompt) in enumerate(selected, 1):
        seed = random.randint(1, 2**32 - 1)
        seeds_used.append(seed)
        workflow = build_api_workflow(prompt, seed)
        try:
            pid = queue_prompt(workflow)
            prompt_ids.append(pid)
            print(f"  [{i:02d}/{len(selected)}] キュー追加: seed={seed}")
        except Exception as e:
            print(f"  [{i:02d}] [ERROR] {e}")

    print(f"\n{len(prompt_ids)}件をキューに追加しました。")

    # 使用シード記録
    log_path = STUDIO_ROOT / "03-tech-studio" / "automation" / ".batch-gen-log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        log_entry = {
            "date": datetime.now().isoformat(),
            "count": len(prompt_ids),
            "theme": args.theme,
            "model": MODEL,
            "lora": LORA,
            "prompts": [
                {"theme": t, "prompt": p, "seed": s}
                for (t, p), s in zip(selected, seeds_used)
            ],
        }
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    if args.no_wait:
        print(f"\nComfyUI で生成が完了したら、以下を実行して取り込んでください:")
        print(f"  py -3 comfyui-sync.py --since {datetime.now().strftime('%Y-%m-%d')}")
        return

    # 完了まで待機
    print("\n生成完了まで待機中... (Ctrl+C でスキップ)")
    try:
        wait_for_queue(len(prompt_ids))
    except KeyboardInterrupt:
        print("\n\n待機をスキップしました。")

    print(f"\n取り込みコマンド:")
    print(f"  py -3 comfyui-sync.py --since {datetime.now().strftime('%Y-%m-%d')}")
    print()


if __name__ == "__main__":
    main()
