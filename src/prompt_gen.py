#!/usr/bin/env python3
"""
LLM プロンプト生成ツール（Qwen 2.5 powered）

テーマや改善要求からComfyUI用英語プロンプトを自動生成する。
生成されたプロンプトは comfyui-batch-gen.py が読み込むJSONに保存される。

使い方:
  python prompt-gen.py --theme "メタバース大学の図書館" --count 5
  python prompt-gen.py --series metaverse --count 10
  python prompt-gen.py --improve "背景がフラットすぎる。もっと奥行きが欲しい" --base-prompt "..."
  python prompt-gen.py --caption "drafts/20260307-draft-pixiv-xxx.png"  # pixivキャプション生成
  python prompt-gen.py --tags "drafts/20260307-draft-pixiv-xxx.png"     # pixivタグ生成

出力先:
  03-tech-studio/automation/.generated-prompts.json  （batch-gen が読み込む）
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

STUDIO_ROOT = Path("D:/ai-studio")
PROMPTS_CACHE = Path(__file__).parent / ".generated-prompts.json"

# シリーズキーワードマッピング
SERIES_CONTEXT = {
    "metaverse":       "2040年のメタバース大学キャンパス、仮想教室、ホログラム講義",
    "ai_employee":     "AI社員（Future Researcher / AI Engineer）の研究風景、未来のオフィス",
    "future_city":     "2040年の街角、未来都市、サイバーパンク日常風景",
    "student_life":    "2040年の学生の日常、寮生活、通学、食堂、未来の若者",
    "memory_restorer": "記憶復元士という架空の未来職業、記憶データの可視化、神秘的な作業空間",
    "r18":             "成人向け、美少女、R18",
}

PROMPT_GEN_SYSTEM = """あなたはStable Diffusion / ComfyUI の英語プロンプト専門家です。
pixivに投稿するAIイラスト向けの高品質なプロンプトを生成します。
スタジオの世界観: 2040年の未来社会、メタバース大学、AI社員、SF美少女
画風: セミリアル寄りアニメ調、美しく・知的・物語性あり"""

CAPTION_SYSTEM = """あなたはpixivの投稿文章のプロ編集者です。
スタジオの世界観: 2040年の未来社会、メタバース大学、AI社員、SF美少女
ルール:
- 100〜150字
- 世界観の「入口」となる一文（説明ではなく誘い込む）
- 問いかけ型 / ワンシーン解説型 / 設定語り型 のいずれか
- ハッシュタグなし（タグは別途）"""

TAG_SYSTEM = """あなたはpixivのタグ最適化専門家です。
以下の条件でタグを10個生成:
- 検索されやすい人気タグ3〜4個
- 世界観・ジャンルタグ3〜4個
- 感情・雰囲気タグ2〜3個
- R18作品の場合は必ず「R-18」を含める
JSON配列形式のみで回答"""


def load_llm():
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from llm_client import LLMClient
        return LLMClient()
    except Exception as e:
        print(f"[ERROR] LLM初期化失敗: {e}")
        print("setup-qwen.bat を実行してOllamaをセットアップしてください")
        sys.exit(1)


def generate_prompts(theme: str, series: str | None, count: int, llm) -> list[str]:
    """テーマからComfyUIプロンプトをcount個生成"""
    context = ""
    if series and series in SERIES_CONTEXT:
        context = f"\nシリーズコンテキスト: {SERIES_CONTEXT[series]}"

    prompt = f"""以下のテーマで、ComfyUI/Stable Diffusion用の英語プロンプトを{count}個生成してください。
{context}

テーマ: {theme}

要件:
- 各プロンプトは50〜120語の英語
- 構図・光・雰囲気・画風を含める
- 世界観（2040年未来・メタバース・AI社会）を反映
- プロンプトのみを番号付きリストで出力（説明文なし）

例の形式:
1. futuristic classroom, holographic screens, soft blue glow, female student...
2. neon city street 2040, rain reflections, cyberpunk aesthetic...
"""
    raw = llm.generate(prompt, system=PROMPT_GEN_SYSTEM)

    # 番号付きリストを抽出
    prompts = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and "." in line[:4]:
            p = line.split(".", 1)[1].strip()
            if len(p) > 20:
                prompts.append(p)

    if not prompts:
        # フォールバック: 行ごとに取得
        prompts = [l.strip() for l in raw.splitlines() if len(l.strip()) > 30]

    return prompts[:count]


def improve_prompt(base_prompt: str, issue: str, llm) -> list[str]:
    """品質評価の問題点からプロンプトを改善"""
    prompt = f"""以下のComfyUIプロンプトを改善してください。

元のプロンプト:
{base_prompt}

問題点・改善要求:
{issue}

改善されたプロンプトを3バリエーション生成してください。
番号付きリストで英語プロンプトのみを出力（説明文なし）。
"""
    raw = llm.generate(prompt, system=PROMPT_GEN_SYSTEM)

    improved = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line[0].isdigit() and "." in line[:4]:
            p = line.split(".", 1)[1].strip()
            if len(p) > 20:
                improved.append(p)
    return improved[:3]


def generate_caption(image_path: Path | None, theme: str | None, llm) -> str:
    """pixivキャプションを生成"""
    if image_path and image_path.exists():
        prompt = f"""この画像のpixivキャプション（100〜150字、日本語）を3パターン生成してください。
パターンA: ワンシーン解説型
パターンB: 問いかけ型
パターンC: 設定語り型"""
        raw = llm.generate_with_image(prompt, image_path, system=CAPTION_SYSTEM)
    else:
        prompt = f"""テーマ「{theme}」のpixivキャプション（100〜150字、日本語）を3パターン生成してください。
パターンA: ワンシーン解説型
パターンB: 問いかけ型
パターンC: 設定語り型"""
        raw = llm.generate(prompt, system=CAPTION_SYSTEM)
    return raw


def generate_tags(image_path: Path | None, theme: str | None, is_r18: bool, llm) -> list[str]:
    """pixivタグを生成"""
    r18_note = "（R-18作品）" if is_r18 else ""
    if image_path and image_path.exists():
        prompt = f"この画像{r18_note}のpixivタグを10個、JSON配列で生成してください。"
        raw = llm.generate_with_image(prompt, image_path, system=TAG_SYSTEM)
    else:
        prompt = f"テーマ「{theme}」{r18_note}のpixivタグを10個、JSON配列で生成してください。"
        raw = llm.generate(prompt, system=TAG_SYSTEM)

    # JSON配列を抽出
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except Exception:
            pass
    # フォールバック: クォートされた文字列を抽出
    import re
    return re.findall(r'"([^"]+)"', raw)[:10]


def save_prompts(prompts: list[str], theme: str, series: str | None):
    """生成プロンプトをキャッシュに保存（batch-gen が読み込む）"""
    data = {
        "generated_at": datetime.now().isoformat(),
        "theme": theme,
        "series": series,
        "prompts": prompts,
    }
    PROMPTS_CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  プロンプトをキャッシュに保存: {PROMPTS_CACHE.name}")
    print(f"  生成後に以下で使用できます:")
    print(f"    py -3 comfyui-batch-gen.py --from-llm --count {len(prompts)}")


def main():
    parser = argparse.ArgumentParser(description="LLM プロンプト生成ツール")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--theme",    help="テーマ（日本語でOK）")
    group.add_argument("--improve",  help="品質問題の説明（プロンプト改善モード）")
    group.add_argument("--caption",  metavar="IMAGE", help="pixivキャプション生成")
    group.add_argument("--tags",     metavar="IMAGE", help="pixivタグ生成")

    parser.add_argument("--series",       choices=list(SERIES_CONTEXT.keys()),
                        help="シリーズコンテキスト")
    parser.add_argument("--count",        type=int, default=5, help="生成数（デフォルト: 5）")
    parser.add_argument("--base-prompt",  help="--improve 使用時のベースプロンプト")
    parser.add_argument("--r18",          action="store_true", help="R18タグを含める")
    parser.add_argument("--no-save",      action="store_true", help="キャッシュに保存しない")
    args = parser.parse_args()

    llm = load_llm()

    if args.theme:
        print(f"\n[プロンプト生成] テーマ: {args.theme} / {args.count}個")
        prompts = generate_prompts(args.theme, args.series, args.count, llm)
        print(f"\n生成されたプロンプト ({len(prompts)}個):\n")
        for i, p in enumerate(prompts, 1):
            print(f"  {i}. {p}")
        if not args.no_save:
            save_prompts(prompts, args.theme, args.series)

    elif args.improve:
        base = args.base_prompt or "（ベースプロンプト未指定）"
        print(f"\n[プロンプト改善]")
        print(f"  問題: {args.improve}")
        improved = improve_prompt(base, args.improve, llm)
        print(f"\n改善案 ({len(improved)}個):\n")
        for i, p in enumerate(improved, 1):
            print(f"  {i}. {p}")
        if not args.no_save:
            save_prompts(improved, f"改善: {args.improve}", args.series)

    elif args.caption:
        img = Path(args.caption)
        theme_str = args.theme or img.stem
        print(f"\n[キャプション生成] {img.name if img.exists() else theme_str}")
        captions = generate_caption(img if img.exists() else None, theme_str, llm)
        print(f"\n{captions}")

    elif args.tags:
        img = Path(args.tags)
        theme_str = args.theme or img.stem
        print(f"\n[タグ生成] {img.name if img.exists() else theme_str}")
        tags = generate_tags(img if img.exists() else None, theme_str, args.r18, llm)
        print(f"\n生成タグ ({len(tags)}個):")
        for t in tags:
            print(f"  {t}")
        print(f"\nコピペ用: {', '.join(tags)}")

    print()


if __name__ == "__main__":
    main()
