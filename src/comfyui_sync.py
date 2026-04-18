#!/usr/bin/env python3
"""
ComfyUI → AI Studio 画像同期ツール

ComfyUI/output/ にある新しい画像を ai-studio に取り込み、
命名規則に沿ってリネームし、投稿下書きファイルを自動生成する。

使い方:
  python comfyui-sync.py                        # 新しい画像をすべて取り込む
  python comfyui-sync.py --since 2026-03-07     # 指定日以降の画像
  python comfyui-sync.py --dry-run              # 実際にはコピーせず確認だけ
  python comfyui-sync.py --series metaverse     # シリーズ名を指定
"""

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

# --- 設定 ---
COMFYUI_OUTPUT = Path("D:/ComfyUI/output")
STUDIO_ROOT = Path("D:/ai-studio")
DRAFTS_DIR = STUDIO_ROOT / "01-pixiv-studio" / "drafts"
STATE_FILE = STUDIO_ROOT / "03-tech-studio" / "automation" / ".comfyui-sync-state.txt"

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

DRAFT_TEMPLATE = """\
---
status: draft
created: {date}
source: comfyui
original: {original_path}
series: {series}
platform: pixiv
---

# 投稿下書き: {title}

## ComfyUIプロンプト
```
（ここにプロンプトを貼り付け）
```

## ネガティブプロンプト
```
（ここにネガティブプロンプトを貼り付け）
```

## pixivキャプション（100〜150字）
（世界観の入口となる一文を書く）

## pixivタグ（10個）
1.
2.
3.
4.
5.
6.
7.
8.
9.
10.

## Patreon接続
- [ ] Patreon向け価値あり（差分/HD版/制作解説）
- [ ] 無料のみでOK

## メモ
"""


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:40].rstrip("-")


def load_synced_files() -> set:
    """同期済みファイルのパスセットを読み込む"""
    if not STATE_FILE.exists():
        return set()
    return set(STATE_FILE.read_text(encoding="utf-8").splitlines())


def save_synced_files(synced: set):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text("\n".join(sorted(synced)), encoding="utf-8")


def find_new_images(since: datetime | None) -> list[Path]:
    """ComfyUI outputから新しい画像を収集する"""
    images = []
    for item in sorted(COMFYUI_OUTPUT.rglob("*")):
        if item.suffix.lower() not in SUPPORTED_EXTS:
            continue
        if item.is_file():
            if since and datetime.fromtimestamp(item.stat().st_mtime) < since:
                continue
            images.append(item)
    return images


def sync(args):
    since = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")

    synced = load_synced_files()
    images = find_new_images(since)

    new_images = [img for img in images if str(img) not in synced]
    if not new_images:
        print("新しい画像はありません。")
        return

    print(f"{len(new_images)} 件の新しい画像が見つかりました。\n")
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)

    series = args.series or "general"
    date_str = datetime.now().strftime("%Y%m%d")

    for i, img in enumerate(new_images, 1):
        # ファイル名からスラッグを生成
        stem = img.stem
        # ComfyUIの典型的なファイル名（例: NetaYume_Lumina_3.5_00025_）から末尾の番号を抜く
        slug = slugify(stem)

        dest_stem = f"{date_str}-draft-pixiv-{slug}"
        dest_img = DRAFTS_DIR / f"{dest_stem}{img.suffix}"
        dest_md = DRAFTS_DIR / f"{dest_stem}.md"

        # 重複回避
        counter = 1
        while dest_img.exists() or dest_md.exists():
            dest_stem = f"{date_str}-draft-pixiv-{slug}-{counter:02d}"
            dest_img = DRAFTS_DIR / f"{dest_stem}{img.suffix}"
            dest_md = DRAFTS_DIR / f"{dest_stem}.md"
            counter += 1

        print(f"[{i}/{len(new_images)}] {img.name}")
        print(f"  → {dest_img.relative_to(STUDIO_ROOT)}")

        if not args.dry_run:
            shutil.copy2(img, dest_img)

            # 下書きMarkdownを生成
            md_content = DRAFT_TEMPLATE.format(
                date=datetime.now().strftime("%Y-%m-%d"),
                original_path=str(img),
                series=series,
                title=stem,
            )
            dest_md.write_text(md_content, encoding="utf-8")
            print(f"  → {dest_md.relative_to(STUDIO_ROOT)} (下書き作成)")

            synced.add(str(img))
        else:
            print("  [dry-run] コピーはスキップ")

    if not args.dry_run:
        save_synced_files(synced)
        print(f"\n完了。{len(new_images)} 件を {DRAFTS_DIR.relative_to(STUDIO_ROOT)} に取り込みました。")
    else:
        print(f"\n[dry-run] 実際にコピーされた画像はありません。")


def main():
    parser = argparse.ArgumentParser(description="ComfyUI → AI Studio 画像同期ツール")
    parser.add_argument("--since", metavar="YYYY-MM-DD", help="この日付以降のファイルのみ対象")
    parser.add_argument("--series", help="シリーズ名（例: metaverse / ai-employee / future-city）")
    parser.add_argument("--dry-run", action="store_true", help="実際にはコピーしない（確認用）")
    args = parser.parse_args()
    sync(args)


if __name__ == "__main__":
    main()
