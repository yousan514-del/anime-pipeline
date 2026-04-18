#!/usr/bin/env python3
"""
pixiv 投稿準備ツール

指定した画像に AutoMosaic でモザイク（ブラー）処理をかけ、
pixiv・FANBOX への投稿に必要なファイル一式を生成する。

使い方:
  python prepare-upload.py image.png
  python prepare-upload.py image.png --meta draft.md
  python prepare-upload.py drafts/20260307-draft-pixiv-*.png
  python prepare-upload.py --folder drafts/

出力先:
  01-pixiv-studio/published/YYYYMMDD-[slug]-upload/
    ├── [image]_blur.png        ← モザイク済み（pixiv投稿用）
    ├── [image].png             ← オリジナル（Patreon限定用）
    ├── pixiv-meta.txt          ← pixivにコピペする情報
    └── fanbox-meta.txt         ← FANBOXにコピペする情報
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import re

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# --- 設定 ---
STUDIO_ROOT = Path("D:/ai-studio")
AUTOMOSAIC_DIR = STUDIO_ROOT / "01-pixiv-studio" / "AutoMosaic_R18_Full_321"
AUTOMOSAIC_EXE = AUTOMOSAIC_DIR / "AutoMosaic.exe"
AUTOMOSAIC_BAT = AUTOMOSAIC_DIR / "run-mosaic.bat"
AUTOMOSAIC_PRESET_FILE = AUTOMOSAIC_DIR / "preset" / "④精度最優先.amcfg"
PUBLISHED_DIR = STUDIO_ROOT / "01-pixiv-studio" / "published"

# AutoMosaic CLI設定（automosaic_settings.ini と揃える）
AUTOMOSAIC_PRESET = "④精度最優先"
BLUR_STRENGTH = 80

PIXIV_META_TEMPLATE = """\
【pixiv投稿情報】作成日: {date}
==========================================

■ タイトル
{title}

■ キャプション（そのままコピペ）
{caption}

■ タグ（カンマ区切り）
{tags}

■ 年齢制限
R-18

■ 元ファイル
{original}

■ Patreon接続
{patreon_note}

==========================================
投稿後にURLをdraft.mdのfrontmatterに記録すること:
  status: published
  published_at: {date}
  platform: pixiv
  url: https://www.pixiv.net/artworks/XXXXXXX
"""

FANBOX_META_TEMPLATE = """\
【FANBOX投稿情報】作成日: {date}
==========================================

■ タイトル（FANBOX用）
{title}（高解像度・差分版）

■ 本文
{caption}

---
この作品の高解像度版と差分をお届けします。
制作過程や設定資料は今月のまとめ記事でご覧いただけます。

■ 添付ファイル
- {original}（オリジナル解像度）

==========================================
"""


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:40].rstrip("-")


def read_draft_meta(draft_md: Path) -> dict:
    """下書きMarkdownからメタデータを読み取る"""
    meta = {
        "title": draft_md.stem,
        "caption": "（キャプションをここに入力）",
        "tags": "AIイラスト, AI生成, 未来, メタバース, 2040年, デジタルアート",
        "series": "",
        "patreon_note": "未設定",
    }
    if not draft_md.exists():
        return meta

    content = draft_md.read_text(encoding="utf-8")

    # キャプションを探す
    cap_match = re.search(r"## pixivキャプション.*?\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if cap_match:
        cap = cap_match.group(1).strip()
        if cap and "（" not in cap:
            meta["caption"] = cap

    # タグを探す
    tag_match = re.search(r"## pixivタグ.*?\n((?:\d+\..*\n?)+)", content)
    if tag_match:
        tags = re.findall(r"\d+\.\s*(.+)", tag_match.group(1))
        tags = [t.strip() for t in tags if t.strip() and t.strip() != ""]
        if tags:
            meta["tags"] = ", ".join(tags)

    # Patreon接続
    if "Patreon向け価値あり" in content and "[x]" in content.lower():
        meta["patreon_note"] = "Patreon/FANBOX限定コンテンツあり（差分・HD版）"

    return meta


def run_automosaic(input_image: Path, output_dir: Path) -> Path | None:
    """AutoMosaicをCLIで実行して処理済み画像を返す"""
    if not AUTOMOSAIC_EXE.exists():
        print(f"[ERROR] AutoMosaic.exe が見つかりません: {AUTOMOSAIC_EXE}")
        return None

    cmd = [
        str(AUTOMOSAIC_EXE),
        str(input_image.resolve()),
        "--preset", AUTOMOSAIC_PRESET,
        "--enable-blur",
        "--blur-strength", str(BLUR_STRENGTH),
        "--no-meta",
        "-o", str(output_dir.resolve()),
    ]

    print(f"  AutoMosaic 実行中...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(AUTOMOSAIC_DIR),  # AutoMosaicはカレントディレクトリがインストール先である必要がある
        )
        if result.returncode not in (0, 1):
            print(f"  [ERROR] AutoMosaic エラー (exit={result.returncode}):")
            if result.stderr:
                print(result.stderr[:500])
            return None
    except Exception as e:
        print(f"  [ERROR] AutoMosaic 起動失敗: {e}")
        return None

    # 処理済みファイルを探す（_mosaic / _blur / _black どれかのサフィックス）
    for suffix_keyword in ["mosaic", "blur", "black", "bar"]:
        candidate = output_dir / f"{input_image.stem}_{suffix_keyword}{input_image.suffix}"
        if candidate.exists():
            return candidate

    # サフィックスパターンで再探索
    for f in output_dir.iterdir():
        if f.suffix == input_image.suffix and f.stem != input_image.stem:
            if any(k in f.name for k in ["mosaic", "blur", "black", "bar"]):
                return f

    # R18コンテンツが検出されなかった場合、元ファイル名でそのまま出力される
    same_name = output_dir / input_image.name
    if same_name.exists():
        print("  [INFO] R18箇所が検出されなかったため、オリジナルをそのまま使用します。")
        return same_name

    print("  [WARN] 処理済みファイルが見つかりませんでした。outputフォルダを確認してください。")
    return None


def prepare(image_path: Path, draft_md: Path | None, dry_run: bool):
    print(f"\n処理: {image_path.name}")

    date_str = datetime.now().strftime("%Y%m%d")
    slug = slugify(image_path.stem)
    upload_dir = PUBLISHED_DIR / f"{date_str}-{slug}-upload"

    if dry_run:
        print(f"  [dry-run] 出力先: {upload_dir.relative_to(STUDIO_ROOT)}")
        return

    upload_dir.mkdir(parents=True, exist_ok=True)

    # AutoMosaicでブラー処理
    blur_file = run_automosaic(image_path, upload_dir)

    if blur_file is None:
        print("  [SKIP] AutoMosaic処理に失敗したため、スキップします。")
        return

    # メタデータを読み込む
    meta = read_draft_meta(draft_md) if draft_md else {
        "title": image_path.stem,
        "caption": "（キャプションをここに入力）",
        "tags": "AIイラスト, AI生成, 未来",
        "patreon_note": "未設定",
    }

    date_display = datetime.now().strftime("%Y-%m-%d")

    # オリジナルも upload_dir にコピー（copy_unprocessed で既にコピーされている場合もあるが念のため）
    original_in_dir = upload_dir / image_path.name
    if not original_in_dir.exists():
        import shutil
        shutil.copy2(image_path, original_in_dir)

    # pixiv-meta.txt 生成
    pixiv_meta = PIXIV_META_TEMPLATE.format(
        date=date_display,
        title=meta["title"],
        caption=meta["caption"],
        tags=meta["tags"],
        original=original_in_dir.name,
        patreon_note=meta["patreon_note"],
    )
    (upload_dir / "pixiv-meta.txt").write_text(pixiv_meta, encoding="utf-8")

    # fanbox-meta.txt 生成
    fanbox_meta = FANBOX_META_TEMPLATE.format(
        date=date_display,
        title=meta["title"],
        caption=meta["caption"],
        original=original_in_dir.name,
    )
    (upload_dir / "fanbox-meta.txt").write_text(fanbox_meta, encoding="utf-8")

    print(f"  完了: {upload_dir.relative_to(STUDIO_ROOT)}/")
    print(f"    ├── {blur_file.name}  ← pixiv投稿用（モザイク済み）")
    print(f"    ├── {original_in_dir.name}  ← Patreon/FANBOX用（オリジナル）")
    print(f"    ├── pixiv-meta.txt")
    print(f"    └── fanbox-meta.txt")


def main():
    parser = argparse.ArgumentParser(description="pixiv 投稿準備ツール（AutoMosaicブラー処理込み）")
    parser.add_argument("images", nargs="*", help="対象画像ファイル")
    parser.add_argument("--folder", help="フォルダを指定（drafts以下のpng/jpg全件）")
    parser.add_argument("--meta", help="メタデータを読み込む下書き.mdファイル")
    parser.add_argument("--dry-run", action="store_true", help="実際には処理しない（確認用）")
    args = parser.parse_args()

    images: list[Path] = []

    if args.folder:
        folder = Path(args.folder)
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            images.extend(folder.glob(f"*{ext}"))
    else:
        images = [Path(p) for p in args.images]

    if not images:
        print("対象画像を指定してください。")
        print("例: python prepare-upload.py image.png")
        print("例: python prepare-upload.py --folder 01-pixiv-studio/drafts/")
        sys.exit(1)

    draft_md = Path(args.meta) if args.meta else None

    for img in images:
        if not img.exists():
            print(f"[SKIP] ファイルが見つかりません: {img}")
            continue
        prepare(img, draft_md, args.dry_run)

    print("\n全て完了しました。")


if __name__ == "__main__":
    main()
