#!/usr/bin/env python3
"""
AI Studio コンテンツ生成補助ツール（CLI雛形）

将来的にAPI連携やバッチ処理を追加するための基盤。
現段階では、テンプレートからファイルを生成する機能のみ。

使い方:
  python content-generator.py new post-draft "春のファンタジー"
  python content-generator.py new short-video-script "AIの倫理"
  python content-generator.py new experiment-log "LoRAテスト"
  python content-generator.py calendar 2026-03-10
  python content-generator.py list templates
"""

import argparse
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# --- 設定 ---
STUDIO_ROOT = Path(__file__).resolve().parent.parent.parent  # ai-studio/
TEMPLATES_DIR = STUDIO_ROOT / "_templates"

# テンプレート → 保存先フォルダのマッピング
TEMPLATE_DEST = {
    "planning": "01-pixiv-studio/ideas",  # デフォルト。プロジェクト指定で変更可
    "post-draft": "01-pixiv-studio/drafts",
    "short-video-script": "06-corporate/shorts",
    "long-video-outline": "02-metaverse-university/scripts",
    "worldbuilding": "02-metaverse-university/worldbuilding",
    "ethics-thought": "02-metaverse-university/thoughts",
    "research-note": "03-tech-studio/research",
    "experiment-log": "03-tech-studio/experiments",
    "patreon-post": "01-pixiv-studio/patreon",
    "pixiv-post": "01-pixiv-studio/drafts",
    "corporate-daily": "06-corporate/daily-life",
}

# 曜日ローテーション
WEEKLY_ROTATION = {
    0: ("Future Researcher", "思想・倫理ショート", "02-metaverse-university"),
    1: ("AI Illustrator", "新作イラスト", "01-pixiv-studio"),
    2: ("AI Engineer", "技術Tips・実験レポート", "03-tech-studio"),
    3: ("Game Researcher", "スマブラ分析", "04-smash-lab"),
    4: ("Innovation Strategist", "未来予測・事業アイデア", "05-business-dev"),
    5: ("Corporate Staff", "AI社員の日常・週まとめ", "06-corporate"),
    6: ("自由枠", "特別企画/Patreon限定", ""),
}

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def slugify(text: str) -> str:
    """日本語テキストを簡易的にファイル名用に変換"""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    return text[:50]


def cmd_new(args):
    """テンプレートから新しいファイルを作成"""
    template_name = args.template
    title = args.title
    project = args.project

    template_file = TEMPLATES_DIR / f"{template_name}.md"
    if not template_file.exists():
        print(f"テンプレートが見つかりません: {template_file}")
        print(f"利用可能: {', '.join(TEMPLATE_DEST.keys())}")
        return

    # 保存先の決定
    if project:
        dest_dir = STUDIO_ROOT / project
    else:
        dest_dir = STUDIO_ROOT / TEMPLATE_DEST.get(template_name, "")

    dest_dir.mkdir(parents=True, exist_ok=True)

    # ファイル名の生成
    date_str = datetime.now().strftime("%Y%m%d")
    slug = slugify(title) if title else template_name
    filename = f"{date_str}-{slug}.md"
    dest_file = dest_dir / filename

    # テンプレートをコピー
    shutil.copy2(template_file, dest_file)

    # 日付を置換
    content = dest_file.read_text(encoding="utf-8")
    content = content.replace("YYYY-MM-DD", datetime.now().strftime("%Y-%m-%d"))
    dest_file.write_text(content, encoding="utf-8")

    print(f"作成しました: {dest_file}")


def cmd_calendar(args):
    """指定週の投稿カレンダーを表示"""
    start_str = args.start_date
    start = datetime.strptime(start_str, "%Y-%m-%d")

    # 月曜始まりに調整
    start -= timedelta(days=start.weekday())

    print(f"\n投稿カレンダー: {start.strftime('%Y/%m/%d')}週\n")
    print(f"{'曜日':<4} {'日付':<12} {'担当':<24} {'コンテンツ'}")
    print("-" * 70)

    for i in range(7):
        day = start + timedelta(days=i)
        role, content_type, _ = WEEKLY_ROTATION[i]
        weekday = WEEKDAY_JP[i]
        print(f"{weekday:<4} {day.strftime('%Y-%m-%d'):<12} {role:<24} {content_type}")

    print()


def cmd_list(args):
    """テンプレートや構造を一覧表示"""
    target = args.target

    if target == "templates":
        print("\n利用可能なテンプレート:\n")
        for name, dest in TEMPLATE_DEST.items():
            template_file = TEMPLATES_DIR / f"{name}.md"
            exists = "OK" if template_file.exists() else "MISSING"
            print(f"  [{exists}] {name:<25} → {dest}")
        print()

    elif target == "roles":
        print("\nAI社員一覧:\n")
        for i, (role, content, project) in WEEKLY_ROTATION.items():
            weekday = WEEKDAY_JP[i]
            print(f"  {weekday} | {role:<24} | {content:<20} | {project}")
        print()

    elif target == "projects":
        print("\nプロジェクト一覧:\n")
        for d in sorted(STUDIO_ROOT.iterdir()):
            if d.is_dir() and not d.name.startswith("_") and not d.name.startswith("."):
                print(f"  {d.name}/")
        print()


def cmd_today(args):
    """今日の担当と投稿テーマを表示"""
    today = datetime.now()
    weekday_idx = today.weekday()
    weekday = WEEKDAY_JP[weekday_idx]
    role, content_type, project = WEEKLY_ROTATION[weekday_idx]

    print(f"\n今日は {today.strftime('%Y-%m-%d')}（{weekday}）です。\n")
    print(f"  担当: {role}")
    print(f"  コンテンツ: {content_type}")
    print(f"  プロジェクト: {project}")
    print(f"\n使い方:")
    print(f"  python content-generator.py new short-video-script \"テーマ名\"")
    print()


def main():
    parser = argparse.ArgumentParser(description="AI Studio コンテンツ生成補助ツール")
    subparsers = parser.add_subparsers(dest="command")

    # new コマンド
    new_parser = subparsers.add_parser("new", help="テンプレートから新しいファイルを作成")
    new_parser.add_argument("template", help="テンプレート名")
    new_parser.add_argument("title", nargs="?", default="", help="タイトル（ファイル名に使用）")
    new_parser.add_argument("-p", "--project", help="保存先プロジェクトフォルダ")
    new_parser.set_defaults(func=cmd_new)

    # calendar コマンド
    cal_parser = subparsers.add_parser("calendar", help="投稿カレンダーを表示")
    cal_parser.add_argument("start_date", help="開始日 (YYYY-MM-DD)")
    cal_parser.set_defaults(func=cmd_calendar)

    # list コマンド
    list_parser = subparsers.add_parser("list", help="一覧を表示")
    list_parser.add_argument("target", choices=["templates", "roles", "projects"],
                             help="表示対象")
    list_parser.set_defaults(func=cmd_list)

    # today コマンド
    today_parser = subparsers.add_parser("today", help="今日の担当を表示")
    today_parser.set_defaults(func=cmd_today)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
