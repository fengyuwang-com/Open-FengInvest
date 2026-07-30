#!/usr/bin/env python3
"""
fenglearn.py — 投资学习工具

记录进度、出题、生成课件、回溯复盘。
配合 fenginvest-learn skill 使用。
"""

import json, sys
from datetime import date
from pathlib import Path

LEARNING_DIR = Path(__file__).resolve().parent.parent / "research" / "100-learning-investment"
PROGRESS_FILE = LEARNING_DIR / "progress.json"
OUTPUTS_DIR = LEARNING_DIR / "outputs"

# 书单（自动生成用）
BOOKS = {
    "聪明的投资者": {"author": "格雷厄姆", "level": 1, "chapters": 20},
    "彼得·林奇的成功投资": {"author": "彼得·林奇", "level": 1, "chapters": 20},
    "巴菲特致股东的信": {"author": "巴菲特", "level": 2, "chapters": 0},
    "投资最重要的事": {"author": "霍华德·马克斯", "level": 2, "chapters": 20},
    "安全边际": {"author": "卡拉曼", "level": 2, "chapters": 0},
    "穷查理宝典": {"author": "芒格", "level": 3, "chapters": 0},
    "原则": {"author": "达利欧", "level": 3, "chapters": 0},
    "黑天鹅": {"author": "塔勒布", "level": 3, "chapters": 0},
    "反脆弱": {"author": "塔勒布", "level": 3, "chapters": 0},
    "股票作手回忆录": {"author": "利弗莫尔", "level": 4, "chapters": 0},
    "战胜华尔街": {"author": "彼得·林奇", "level": 4, "chapters": 0},
}

PHASES = {
    1: {"name": "建立地基", "books": ["聪明的投资者", "彼得·林奇的成功投资"]},
    2: {"name": "深度价值", "books": ["投资最重要的事", "巴菲特致股东的信", "安全边际"]},
    3: {"name": "多元思维", "books": ["穷查理宝典", "原则", "黑天鹅"]},
    4: {"name": "实战循环", "books": ["股票作手回忆录", "战胜华尔街"]},
}


def _load():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"books": {}, "current_phase": 1, "analyses_done": 0, "sessions_done": 0}


def _save(data):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_status():
    """显示学习进度"""
    data = _load()
    phase = data["current_phase"]
    info = PHASES[phase]

    print(f"\n当前阶段：Phase {phase} — {info['name']}")
    print()

    # 书的状态
    for title, meta in BOOKS.items():
        if meta["level"] != phase and title not in data.get("books", {}):
            continue
        prog = data.get("books", {}).get(title, {})
        status = prog.get("status", "未开始")
        ch = f" ({prog.get('chapters_done', 0)}/{meta['chapters']}章)" if meta["chapters"] else ""
        print(f"  {title:20s} [{status:8s}]{ch}")

    print(f"\n  完整分析完成: {data['analyses_done']} 次")
    print(f"  教练对话: {data['sessions_done']} 次")
    print()


def cmd_track(args):
    """记录阅读进度：--book <书名> [--chapter <章>] [--note <笔记>]"""
    book = None
    chapter = None
    note = None
    for i, a in enumerate(args):
        if a == "--book" and i + 1 < len(args):
            book = args[i + 1]
        if a == "--chapter" and i + 1 < len(args):
            chapter = int(args[i + 1])
        if a == "--note" and i + 1 < len(args):
            note = args[i + 1]

    if not book:
        print("用法: fenglearn.py track --book <书名> [--chapter <章>] [--note <笔记>]")
        print("可用: " + ", ".join(BOOKS.keys()))
        return

    data = _load()
    if book not in data["books"]:
        data["books"][book] = {
            "status": "reading",
            "chapters_done": 0,
            "notes": [],
            "started": str(date.today()),
        }

    b = data["books"][book]
    if chapter:
        b["chapters_done"] = max(b["chapters_done"], chapter)
        info = BOOKS.get(book)
        if info and info["chapters"] and b["chapters_done"] >= info["chapters"]:
            b["status"] = "completed"

    if note:
        b["notes"].append({"date": str(date.today()), "text": note})
        # save to outputs
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        notes_file = OUTPUTS_DIR / f"notes-{book}-{date.today()}.md"
        with open(notes_file, "a", encoding="utf-8") as f:
            f.write(f"## {date.today()} — 第{chapter or '?'}章\n\n{note}\n\n")

    _save(data)
    ch_info = f" 第{chapter}章" if chapter else ""
    print(f"✓ 已记录: {book}{ch_info}")


def cmd_quiz(args):
    """输出测验指令（让 AI 执行测验）"""
    book = None
    for i, a in enumerate(args):
        if a == "--book" and i + 1 < len(args):
            book = args[i + 1]

    if not book:
        print("用法: fenglearn.py quiz --book <书名>")
        return

    data = _load()
    prog = data.get("books", {}).get(book, {})
    chapters = prog.get("chapters_done", 0)

    print(f"\n你已读完《{book}》{chapters} 章。测验指令：")
    print()
    if chapters >= 3:
        print(f"我刚读完《{book}》前 {chapters} 章。出 5 道题让我答：")
        print("2 道概念题 + 2 道判断题 + 1 道实战应用题。")
        print("先让我答，再给正确答案和解析。")
    else:
        print(f"我刚读完《{book}》{chapters} 章（刚开始）。")
        print("出 3 道简单题，确认我掌握了核心概念就够。")


def cmd_pptr(args):
    """输出 PPT 生成指令"""
    book = None
    for i, a in enumerate(args):
        if a == "--book" and i + 1 < len(args):
            book = args[i + 1]

    if not book:
        print("用法: fenglearn.py pptr --book <书名>")
        print("可用: " + ", ".join(BOOKS.keys()))
        return

    info = BOOKS.get(book, {})
    level = info.get("level", "?")

    ppt_path = OUTPUTS_DIR / f"ppt-{book}-{date.today()}.md"
    print(f"PPT 大纲将保存到: {ppt_path}")
    print()
    print(f"为《{book}》（Level {level}）生成 8 页 PPT：")
    print(f"- 第 1 页：封面 — {book} + 一句话核心价值")
    print(f"- 第 2-7 页：每页一个关键概念 + 一句话解释 + 实战用法")
    print(f"- 第 8 页：总结 + 行动清单")
    print(f"使用 markdown 格式，每页用 --- 分隔。")


def cmd_review(args):
    """输出回溯复盘指令"""
    ticker = None
    for i, a in enumerate(args):
        if a == "--ticker" and i + 1 < len(args):
            ticker = args[i + 1]

    if not ticker:
        print("用法: fenglearn.py review --ticker <TICKER>")
        return

    data = _load()
    data["analyses_done"] += 1
    _save(data)

    print(f"回溯复盘《{ticker}》分析：")
    print()
    print(f"1. 调出当时 L0→L4 的所有 temp 文件")
    print(f"2. 对比当前股价")
    print(f"3. 分析：哪些判断对了？哪些错了？原因？")
    print(f"4. 更新你的 check list")


def cmd_coach(args):
    """切换到教练模式"""
    mode = "tutor"
    for i, a in enumerate(args):
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]

    data = _load()
    phase = data["current_phase"]

    modes = {
        "tutor": f"你目前在 Phase {phase}（{PHASES[phase]['name']}）。我当你的 tutor，帮你理解概念。你可以随时问我问题。",
        "devil": "你有一个投资想法。我扮演魔鬼代言人，全力反驳你。你说你的观点，我从每个角度挑战你。",
        "socratic": "我不用直接答案的方式教你。我问你问题，你回答，我从你的回答中继续追问。目标是让你自己想明白。",
        "quiz": "我刚读完一部分内容。你出题考我，我答完后你给我反馈。",
    }

    print()
    print(modes.get(mode, modes["tutor"]))
    print(f"\n记得写入进度: fenglearn.py coach --mode {mode} --log true")


def main():
    if len(sys.argv) < 2:
        print("用法: fenglearn.py <命令> [参数]")
        print()
        print("命令:")
        print("  status                   显示学习进度")
        print("  track --book <书名>      记录阅读进度")
        print("         [--chapter <章>]")
        print("         [--note <笔记>]")
        print("  quiz --book <书名>       出测验指令")
        print("  pptr --book <书名>       生成 PPT 大纲")
        print("  review --ticker <TICKER> 回溯复盘")
        print("  coach --mode <模式>      切换教练模式 (tutor/devil/socratic/quiz)")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "status": cmd_status,
        "track": cmd_track,
        "quiz": cmd_quiz,
        "pptr": cmd_pptr,
        "review": cmd_review,
        "coach": cmd_coach,
    }

    if cmd in commands:
        commands[cmd](args)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
