# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
画像品質評価ツール

2段階評価:
  Stage 1 (PIL高速): 解像度・輝度・コントラスト・彩度・シャープネスを即時スコアリング
  Stage 2 (Qwen VL): AIが画像を見て構図・世界観一致・投稿適性を詳細評価

使い方:
  python quality-eval.py --folder drafts/          # フォルダ内全画像を評価
  python quality-eval.py image.png                 # 1枚評価
  python quality-eval.py --folder drafts/ --llm    # Qwen VL詳細評価も実行
  python quality-eval.py --folder drafts/ --auto-reject 60  # 60点未満を自動却下

出力:
  - コンソールにスコア一覧
  - 03-tech-studio/experiments/YYYYMMDD-quality-report.md
  - --auto-reject 使用時: rejected/ フォルダに低品質画像を移動

スコア基準（100点満点）:
  90-100: 即投稿OK
  70-89:  投稿可（minor改善の余地あり）
  50-69:  要検討（Qwen評価を推奨）
  0-49:   却下推奨（プロンプト改善が必要）
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Windows端末でUTF-8出力を強制
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ComfyUI venv の PIL/numpy を使う
COMFYUI_VENV = Path("D:/ComfyUI/venv/Lib/site-packages")
if COMFYUI_VENV.exists():
    sys.path.insert(0, str(COMFYUI_VENV))

try:
    from PIL import Image, ImageFilter, ImageStat
    import numpy as np
    PIL_OK = True
except ImportError:
    PIL_OK = False

STUDIO_ROOT = Path("D:/ai-studio")
REPORT_DIR = STUDIO_ROOT / "03-tech-studio" / "experiments"
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


# ===================================================================
# Stage 1: PIL 高速スコアリング
# ===================================================================

def score_resolution(img: "Image.Image") -> tuple[float, str]:
    w, h = img.size
    mp = (w * h) / 1_000_000
    if mp >= 1.5:
        return 100.0, f"{w}x{h} ({mp:.1f}MP) OK"
    elif mp >= 0.8:
        return 75.0, f"{w}x{h} ({mp:.1f}MP) やや小さい"
    else:
        return 40.0, f"{w}x{h} ({mp:.1f}MP) 低解像度"


def score_brightness(img: "Image.Image") -> tuple[float, str]:
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    mean = stat.mean[0]
    # 理想: 80-180（暗すぎず明るすぎず）
    if 70 <= mean <= 190:
        return 100.0, f"輝度平均={mean:.0f} OK"
    elif 50 <= mean <= 210:
        return 75.0, f"輝度平均={mean:.0f} やや外れ"
    else:
        issue = "暗すぎ" if mean < 50 else "明るすぎ"
        return 45.0, f"輝度平均={mean:.0f} {issue}"


def score_contrast(img: "Image.Image") -> tuple[float, str]:
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    std = stat.stddev[0]
    if std >= 50:
        return 100.0, f"コントラスト={std:.0f} OK"
    elif std >= 30:
        return 70.0, f"コントラスト={std:.0f} 低め"
    else:
        return 40.0, f"コントラスト={std:.0f} 低すぎ（フラット）"


def score_saturation(img: "Image.Image") -> tuple[float, str]:
    hsv = img.convert("HSV") if hasattr(Image, "HSV") else None
    rgb = np.array(img.convert("RGB"), dtype=float)
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    sat = np.where(cmax > 0, delta / cmax, 0)
    mean_sat = sat.mean() * 100

    if mean_sat >= 20:
        return 100.0, f"彩度={mean_sat:.0f} OK"
    elif mean_sat >= 10:
        return 70.0, f"彩度={mean_sat:.0f} やや低い"
    else:
        return 40.0, f"彩度={mean_sat:.0f} 低い（モノクロ気味）"


def score_sharpness(img: "Image.Image") -> tuple[float, str]:
    gray = img.convert("L")
    lap = gray.filter(ImageFilter.FIND_EDGES)
    stat = ImageStat.Stat(lap)
    sharpness = stat.stddev[0]
    if sharpness >= 15:
        return 100.0, f"シャープネス={sharpness:.1f} OK"
    elif sharpness >= 8:
        return 70.0, f"シャープネス={sharpness:.1f} やや甘い"
    else:
        return 35.0, f"シャープネス={sharpness:.1f} ブレ・ぼけ気味"


def pil_score(image_path: Path) -> dict:
    """PIL メトリクスによる高速スコアリング"""
    if not PIL_OK:
        return {"total": 0, "error": "PIL が利用できません（ComfyUI venv を確認）"}

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        return {"total": 0, "error": str(e)}

    res_score, res_note   = score_resolution(img)
    bri_score, bri_note   = score_brightness(img)
    con_score, con_note   = score_contrast(img)
    sat_score, sat_note   = score_saturation(img)
    sha_score, sha_note   = score_sharpness(img)

    # 重み付き合計（解像度30%、シャープネス25%、コントラスト20%、輝度15%、彩度10%）
    total = (
        res_score * 0.30 +
        sha_score * 0.25 +
        con_score * 0.20 +
        bri_score * 0.15 +
        sat_score * 0.10
    )

    return {
        "total": round(total, 1),
        "breakdown": {
            "解像度(30%)":     {"score": res_score, "note": res_note},
            "シャープネス(25%)": {"score": sha_score, "note": sha_note},
            "コントラスト(20%)": {"score": con_score, "note": con_note},
            "輝度(15%)":       {"score": bri_score, "note": bri_note},
            "彩度(10%)":       {"score": sat_score, "note": sat_note},
        },
    }


# ===================================================================
# Stage 2: Qwen VL 詳細評価
# ===================================================================

EVAL_SYSTEM = """あなたはAIイラストの品質評価専門家です。
pixiv向けのAI生成イラスト（未来都市・メタバース・AI社員などのテーマ）を評価します。
必ず以下のJSON形式のみで回答してください。説明文は不要です。"""

EVAL_PROMPT = """この画像を評価してください。以下のJSON形式で回答:
{
  "composition": 0-10,
  "detail_quality": 0-10,
  "color_harmony": 0-10,
  "worldview_fit": 0-10,
  "pixiv_appeal": 0-10,
  "total_100": 0-100,
  "strengths": ["強み1", "強み2"],
  "issues": ["問題1", "問題2"],
  "prompt_suggestions": ["改善提案1", "改善提案2"]
}"""


def llm_score(image_path: Path) -> dict:
    """Qwen VL による詳細評価"""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from llm_client import LLMClient
        llm = LLMClient()
    except Exception as e:
        return {"error": f"LLM初期化失敗: {e}"}

    try:
        raw = llm.generate_with_image(EVAL_PROMPT, image_path, system=EVAL_SYSTEM)
        # JSON部分を抽出
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return {"error": f"JSON解析失敗: {raw[:200]}"}
        result = json.loads(raw[start:end])
        return result
    except json.JSONDecodeError as e:
        return {"error": f"JSON解析失敗: {e}"}
    except Exception as e:
        return {"error": str(e)}


# ===================================================================
# レポート生成
# ===================================================================

def grade(score: float) -> str:
    if score >= 90: return "S"
    if score >= 75: return "A"
    if score >= 60: return "B"
    if score >= 45: return "C"
    return "D"


def print_result(path: Path, pil: dict, llm_result: dict | None):
    total = pil.get("total", 0)
    g = grade(total)
    status = "OK  投稿可" if total >= 70 else ("-- 要検討" if total >= 50 else "NG  却下推奨")
    print(f"\n  [{g}] {path.name}  PIL={total:.0f}点  {status}")
    if "breakdown" in pil:
        for k, v in pil["breakdown"].items():
            bar = "█" * int(v["score"] / 10) + "░" * (10 - int(v["score"] / 10))
            print(f"       {k:<18} [{bar}] {v['score']:.0f}  {v['note']}")
    if llm_result and "total_100" in llm_result:
        lt = llm_result["total_100"]
        print(f"       Qwen評価={lt}点  構図:{llm_result.get('composition')}/10  "
              f"品質:{llm_result.get('detail_quality')}/10  "
              f"色調:{llm_result.get('color_harmony')}/10")
        if llm_result.get("issues"):
            print(f"       問題: {', '.join(llm_result['issues'][:2])}")
        if llm_result.get("prompt_suggestions"):
            print(f"       改善: {llm_result['prompt_suggestions'][0]}")
    if "error" in pil:
        print(f"       [ERROR] {pil['error']}")


def save_report(results: list[dict], output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 品質評価レポート",
        f"**作成: {date_str}** | 評価件数: {len(results)}枚",
        "",
        "## サマリー",
        "",
        "| グレード | 件数 | 目安 |",
        "|---------|------|------|",
    ]
    grades = {"S":0, "A":0, "B":0, "C":0, "D":0}
    for r in results:
        g = grade(r["pil"].get("total", 0))
        grades[g] += 1
    grade_notes = {"S":"即投稿OK", "A":"投稿可", "B":"要確認", "C":"改善推奨", "D":"却下推奨"}
    for g, cnt in grades.items():
        lines.append(f"| {g} | {cnt}枚 | {grade_notes[g]} |")

    lines += ["", "## 詳細結果", ""]
    for r in sorted(results, key=lambda x: -x["pil"].get("total", 0)):
        path = r["path"]
        pil = r["pil"]
        llm_r = r.get("llm")
        total = pil.get("total", 0)
        g = grade(total)

        lines.append(f"### [{g}] `{path.name}` — PIL: {total:.0f}点")
        if "breakdown" in pil:
            for k, v in pil["breakdown"].items():
                lines.append(f"- {k}: {v['score']:.0f}点 — {v['note']}")
        if llm_r and "total_100" in llm_r:
            lines.append(f"\n**Qwen評価: {llm_r['total_100']}点**")
            if llm_r.get("strengths"):
                lines.append(f"- 強み: {', '.join(llm_r['strengths'])}")
            if llm_r.get("issues"):
                lines.append(f"- 問題: {', '.join(llm_r['issues'])}")
            if llm_r.get("prompt_suggestions"):
                lines.append("- プロンプト改善案:")
                for s in llm_r["prompt_suggestions"]:
                    lines.append(f"  - {s}")
        lines.append("")

    lines += [
        "## 改善サイクルの使い方",
        "",
        "1. グレードD/Cの画像のプロンプト改善案を `prompt-gen.py` に渡す",
        "2. `comfyui-batch-gen.py` で再生成",
        "3. この評価を再実行",
        "```bash",
        "py -3 prompt-gen.py --improve \"問題点の説明\" --theme metaverse",
        "py -3 comfyui-batch-gen.py --theme metaverse --count 5",
        "py -3 quality-eval.py --folder drafts/ --llm",
        "```",
    ]

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  レポート保存: {output_path.relative_to(STUDIO_ROOT)}")


def main():
    parser = argparse.ArgumentParser(description="画像品質評価ツール")
    parser.add_argument("images", nargs="*", help="評価する画像ファイル")
    parser.add_argument("--folder", help="フォルダを指定（以下の画像を全評価）")
    parser.add_argument("--llm", action="store_true", help="Qwen VL による詳細評価も実行")
    parser.add_argument("--auto-reject", type=float, metavar="SCORE",
                        help="このスコア未満を rejected/ フォルダに移動")
    parser.add_argument("--no-report", action="store_true", help="レポートファイルを保存しない")
    args = parser.parse_args()

    if not PIL_OK:
        print("[ERROR] PIL が利用できません。ComfyUI venv を確認してください。")
        print(f"  確認: {COMFYUI_VENV}")
        sys.exit(1)

    # 対象画像を収集
    images: list[Path] = []
    if args.folder:
        folder = Path(args.folder)
        for ext in SUPPORTED_EXTS:
            images.extend(sorted(folder.glob(f"*{ext}")))
    for p in args.images:
        images.append(Path(p))

    images = [p for p in images if p.exists()]
    if not images:
        print("評価対象の画像が見つかりません。")
        sys.exit(1)

    print(f"\n品質評価開始: {len(images)}枚")
    if args.llm:
        print("  Qwen VL詳細評価: 有効（時間がかかります）")
    print()

    results = []
    rejected = []

    for i, img_path in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img_path.name}", end="", flush=True)

        pil = pil_score(img_path)
        llm_result = None

        if args.llm and pil.get("total", 0) > 0:
            print(" → Qwen評価中...", end="", flush=True)
            llm_result = llm_score(img_path)

        print()
        print_result(img_path, pil, llm_result)

        result = {"path": img_path, "pil": pil, "llm": llm_result}
        results.append(result)

        if args.auto_reject and pil.get("total", 100) < args.auto_reject:
            rejected.append(img_path)

    # サマリー
    scores = [r["pil"].get("total", 0) for r in results]
    avg = sum(scores) / len(scores) if scores else 0
    passed = sum(1 for s in scores if s >= 70)

    print(f"\n{'='*50}")
    print(f"  評価枚数: {len(results)}")
    print(f"  平均スコア: {avg:.1f}点")
    print(f"  投稿OK (70点以上): {passed}枚 / {len(results)}枚")
    if rejected:
        print(f"  却下 ({args.auto_reject}点未満): {len(rejected)}枚")

    # 自動却下処理
    if rejected:
        reject_dir = images[0].parent / "rejected"
        reject_dir.mkdir(exist_ok=True)
        for p in rejected:
            shutil.move(str(p), str(reject_dir / p.name))
            print(f"  [却下] {p.name} → rejected/")

    # レポート保存
    if not args.no_report:
        date_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = REPORT_DIR / f"{date_str}-quality-report.md"
        save_report(results, report_path)

    print()


if __name__ == "__main__":
    main()
