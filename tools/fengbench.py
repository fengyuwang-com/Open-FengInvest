#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fengbench.py — 金融知识门禁：用本地 FinEval 学术 val 集给基底 LLM 打分（准确率）。

用途：
  - 客观度量基底模型在财报/金融科目上的单题作答正确率，当作"知识面"粗筛。
  - 不当决策评分、不进七层状态机。产出仅供参考 + 可追溯的每题 JSON/MD。

数据来源（只读，不写回）：
  - 仓库：~/FinEval（本地已克隆，只读）
  - 科目表：code/opensource_eval/1academic_eval/code/subject_mapping.json
  - val 集：code/data/val/<subject>_val.csv（按 docs 下载 FinEval.zip 解压到 code/data，
            参考 code/opensource_eval/1academic_eval/docs/zh_cn/get_started/dataset_pre.md：
                cd code/data
                wget https://huggingface.co/datasets/SUFE-AIFLM-Lab/FinEval/resolve/main/FinEval.zip
                unzip FinEval.zip
            CSV 列：id, question, A, B, C, D, answer（answer ∈ A/B/C/D）

用法：
  python tools/fengbench.py --subjects 投资学,公司金融,金融市场 --model <模型名> [--limit 50]
  python tools/fengbench.py --selfcheck                          # 纯离线：读 CSV + 校验结构

环境变量：
  FENGBENCH_BASE_URL    OpenAI-compatible API 根地址（默认 https://api.openai.com/v1）
  FENGBENCH_API_KEY     API 密钥
  FENGBENCH_MODEL       默认模型名（--model 优先于它）

无 key 流程：
  打印"无 key, 仅交付 harness"，做离线读 CSV + 结构自检后 exit 0，不卡在 API。

仅用 stdlib + requests，UTF-8 读写。
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# ---------------------------------------------------------------- 常量（按磁盘实况写死，可用参数覆盖）
FINEEVAL_REPO = Path("~/FinEval").expanduser()
SUBJECT_MAPPING_PATH = FINEEVAL_REPO / "code" / "opensource_eval" / "1academic_eval" / "code" / "subject_mapping.json"
# val 集候选目录：zip 解压实际布局有几种可能，全部探测（datasets_pre.md 约定 code/data 下 dev/val/test）
VAL_DIR_CANDIDATES = [
    FINEEVAL_REPO / "code" / "data" / "val",
    FINEEVAL_REPO / "code" / "data" / "FinEval" / "val",
    FINEEVAL_REPO / "code" / "data" / "data" / "val",
    # 与 eval.py 同逻辑运行的相对目录（eval.py: os.listdir("data/val")，cwd = 1academic_eval/code）
    FINEEVAL_REPO / "code" / "opensource_eval" / "1academic_eval" / "data" / "val",
]
DEV_DIR = FINEEVAL_REPO / "code" / "data" / "dev"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "research" / "fengbench"

CSV_COLUMNS = ["id", "question", "A", "B", "C", "D", "answer"]
CHOICES = ["A", "B", "C", "D"]

# FinEval unify_evaluator.extract_answer 的答案正则链（参考其思路，选主用"答案是([ABCD])"）
# 逐条尝试，命中即取第一个捕获组（含中文冒号/英文冒号/空格/选项等变体）
ANSWER_PATTERNS = [
    r"答案是([ABCD])",
    r"答案是\s?选?项?\s?([A-D])",
    r"答案为\s?选?项?\s?([A-D])",
    r"答案应为\s?选?项?\s?([A-D])",
    r"答案选\s?选?项?\s?([A-D])",
    r"答案([ABCD])",
    r"答案：\s?选?项?\s?([A-D])",
    r"选择答案([ABCD])",
    r"选择([ABCD])",
    r"选项([ABCD])正确",
    r"([ABCD])是正确的",
    r"正确答案[是为:：]?\s?选?项?\s?([A-D])",
    r"所以答案是([ABCD])",
    r"^选([A-D])",
    r"^选项([A-D])",
]


# ---------------------------------------------------------------- 工具函数
def load_subject_mapping(path: Path) -> dict:
    """读 subject_mapping.json -> {英文键: [en, 中文名, 分组]}；同时建中文/中文去'学'的查询索引。"""
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    by_cn = {}
    by_cn_trim = {}
    for key, info in mapping.items():
        cn = info[1]
        by_cn[cn] = key
        if cn.endswith("学"):
            by_cn_trim[cn[:-1]] = key
    by_cn.update(by_cn_trim)  # "金融市场" 亦可命中 "金融市场学"
    return mapping, by_cn


def resolve_subjects(requests_subjects, mapping, by_cn):
    """把输入（中文名或英文键，逗号分隔）解析成 (key, cn_name, group) 列表。"""
    out = []
    errors = []
    for token in requests_subjects:
        token = token.strip()
        if not token:
            continue
        if token in mapping:                      # 英文键
            key = token
        elif token in by_cn:                      # 中文名 / 中文去"学"
            key = by_cn[token]
        else:
            errors.append(token)
            continue
        info = mapping[key]
        out.append((key, info[1], info[2]))
    return out, errors


def find_val_dir(candidates, override=None) -> Path:
    """返回存在且含 *_val.csv 的 val 目录；找不到则返回 override（如果有）或第一个候选。"""
    if override:
        return Path(override)
    for d in candidates:
        if d.is_dir() and list(d.glob("*_val.csv")):
            return d
    return candidates[0]  # 未就绪时的占位，后续报错清晰


def validate_csv(path: Path):
    """读 CSV + 校验结构：必需列、answer ∈ {A,B,C,D}。返回 (rows, 问题列表)。"""
    rows = []
    problems = []
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 剥 BOM（官方 CSV 首列带 \ufeff）
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return rows, problems
            missing = [c for c in CSV_COLUMNS if c not in reader.fieldnames]
            if missing:
                problems.append(f"缺列: {missing} (实际列: {reader.fieldnames})")
                return rows, problems
            for i, line in enumerate(reader, start=1):
                ans = (line.get("answer") or "").strip().upper()
                if ans not in CHOICES:
                    problems.append(f"第{i}行 answer 非法: {line.get('answer')!r}")
                    continue
                # 四个选项至少非空（宽松校验，不阻塞）
                if any(not (line.get(c) or "").strip() for c in CHOICES):
                    problems.append(f"第{i}行存在空选项")
                rows.append(line)
    except Exception as e:  # noqa: BLE001
        problems.append(f"读取失败: {e}")
    return rows, problems


# ---------------------------------------------------------------- 生成 prompt / 抽取答案
def build_prompt(item: dict, cn_name: str) -> str:
    """按 FinEval format_example 风格拼 prompt，answer-only。"""
    q = item["question"]
    lines = [f"{c}. {item[c]}" for c in CHOICES]
    return (
        f"以下是中国关于{cn_name}的考试单项选择题。请作答，只输出答案选项字母"
        f"（A、B、C 或 D 中的一个），不要输出多余内容。\n\n{q}\n" + "\n".join(lines) + "\n\n答案："
    )


def extract_answer(raw: str):
    """按 FinEval unify_evaluator 思路从模型输出中抽选项字母。返回 (choice|None, 抽取方式)。"""
    if not raw:
        return None, "empty"
    for pat in ANSWER_PATTERNS:
        m = re.search(pat, raw, re.M)
        if m:
            return m.group(1).upper(), "regex"
    # 兜底：整段里第一个 A/B/C/D 字符
    m = re.search(r"[ABCD]", raw, re.M)
    if m:
        return m.group(0), "first-char"
    return None, "none"


# ---------------------------------------------------------------- API 调用（OpenAI-compatible）
def call_llm(base_url, api_key, model, prompt, temperature, max_tokens, timeout):
    """POST {base_url}/chat/completions。返回 (content|None, error|None)。"""
    if requests is None:
        return None, "requests 未安装"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是金融知识测评助手。根据单选题作答，只输出选项字母。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:300]}"
        data = r.json()
        return data["choices"][0]["message"]["content"], None
    except Exception as e:  # noqa: BLE001
        return None, f"请求异常: {e}"


# ---------------------------------------------------------------- 主流程
def run_offline(val_dir, subjects, limit):
    """无 key 流程：读 CSV + 结构自检，退出 0。返回校验报告。"""
    report = {"data_dir": str(val_dir), "subjects": {}}
    for key, cn, group in subjects:
        subject_report = {"cn_name": cn, "group": group, "file": None, "rows": 0, "problems": []}
        fpath = val_dir / f"{key}_val.csv"
        if not fpath.is_file():
            subject_report["problems"].append("val CSV 不存在")
            report["subjects"][key] = subject_report
            continue
        rows, problems = validate_csv(fpath)
        if limit and limit > 0:
            rows = rows[:limit]
        subject_report["file"] = str(fpath)
        subject_report["rows"] = len(rows)
        subject_report["problems"] = problems
        report["subjects"][key] = subject_report
    return report


def run_score(val_dir, subjects, args, api_key):
    """有 key 流程：逐题提问 → 抽答案 → 计分。"""
    base_url = args.base_url or os.environ.get("FENGBENCH_BASE_URL") or "https://api.openai.com/v1"
    model = args.model or os.environ.get("FENGBENCH_MODEL")
    if not model:
        print("错误：设置了 API key 但未指定 --model，且环境变量 FENGBENCH_MODEL 为空。")
        sys.exit(1)

    result = {"meta": {}, "subjects": {}, "overall": {}}
    result["meta"] = {
        "data_dir": str(val_dir),
        "model": model,
        "base_url": base_url,
        "temperature": args.temperature,
        "max_tokens": args.max_tokens,
        "limit": args.limit,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "仅作金融知识门禁参考，不构成决策评分，未进七层流程。",
    }

    for key, cn, group in subjects:
        fpath = val_dir / f"{key}_val.csv"
        if not fpath.is_file():
            print(f"[skip] {key} ({cn}): val CSV 不存在 -> {fpath}")
            result["subjects"][key] = {"cn_name": cn, "group": group, "error": "val CSV 不存在"}
            continue
        rows, problems = validate_csv(fpath)
        if args.limit and args.limit > 0:
            rows = rows[:args.limit]

        correct = 0
        unresolved = 0
        details = []
        total = len(rows)
        for i, item in enumerate(rows, start=1):
            prompt = build_prompt(item, cn)
            raw, err = call_llm(base_url, api_key, model, prompt,
                                args.temperature, args.max_tokens, args.timeout)
            if err:
                raw = ""
            ans, method = extract_answer(raw)
            truth = item["answer"].strip().upper()
            is_correct = bool(ans and ans == truth)
            if is_correct:
                correct += 1
            if not ans:
                unresolved += 1
            details.append({
                "id": item["id"],
                "question": item["question"],
                "options": {c: item[c] for c in CHOICES},
                "answer": truth,
                "model_output": raw,
                "extracted": ans,
                "extract_method": method,
                "api_error": err,
                "correct": is_correct,
            })
            if args.verbose and i % 10 == 0:
                print(f"  [{key}] {i}/{total} 提问中…（当前正确 {correct}）")

        acc = round(correct / total, 4) if total else 0.0
        result["subjects"][key] = {
            "cn_name": cn,
            "group": group,
            "file": str(fpath),
            "total": total,
            "correct": correct,
            "accuracy": acc,
            "unresolved": unresolved,
            "details": details,
        }
        print(f"[done] {key} ({cn})  acc={acc:.1%}  correct={correct}/{total}  unresolved={unresolved}")

    # overall（只统计有 total 的科目）
    subjects_with_rows = [s for s in result["subjects"].values() if s.get("total")]
    if subjects_with_rows:
        tot = sum(s["total"] for s in subjects_with_rows)
        corr = sum(s["correct"] for s in subjects_with_rows)
        result["overall"] = {
            "subjects": len(subjects_with_rows),
            "total": tot,
            "correct": corr,
            "accuracy": round(corr / tot, 4) if tot else 0.0,
        }
    return result


def write_outputs(result, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "bench_result.json"
    md_path = output_dir / "bench_result.md"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    lines = []
    lines.append(f"# FengBench 金融知识门禁")
    lines.append("")
    meta = result.get("meta", {})
    if meta:
        lines.append(f"- 模型: {meta.get('model')} / {meta.get('base_url')}")
        lines.append(f"- 数据: {meta.get('data_dir')}")
        lines.append(f"- 时间: {meta.get('ts')}  limit: {meta.get('limit')}")
    lines.append("")
    lines.append("| 科目 | 分组 | total | correct | accuracy | unresolved |")
    lines.append("|---|---|---|---|---|---|")
    for key, s in result.get("subjects", {}).items():
        if "total" in s:
            lines.append(f"| {key} ({s['cn_name']}) | {s['group']} | {s['total']} | {s['correct']} | {s['accuracy']:.1%} | {s['unresolved']} |")
        else:
            lines.append(f"| {key} ({s.get('cn_name','')}) | {s.get('group','')} | - | - | - | error: {s.get('error','')} |")
    ov = result.get("overall")
    if ov:
        lines.append(f"| **合计** | - | {ov['total']} | {ov['correct']} | **{ov['accuracy']:.1%}** | - |")
    lines.append("")
    lines.append("> 说明：本题库仅作金融知识面门禁参考，不当决策评分、不进七层流程。")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return json_path, md_path


# ---------------------------------------------------------------- CLI
def main():
    parser = argparse.ArgumentParser(
        description="fengbench: 用本地 FinEval 学术 val 集给基底 LLM 做金融知识门禁（准准确率，不决策）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--subjects", default="投资学,公司金融,金融市场",
                        help="科目：中文名或英文键，逗号分隔（默认 投资学,公司金融,金融市场）")
    parser.add_argument("--model", default=None, help="模型名，env FENGBENCH_MODEL 优先于此参数")
    parser.add_argument("--base-url", default=None, help="API 根地址，env FENGBENCH_BASE_URL 优先")
    parser.add_argument("--api-key", default=None, help="API 密钥，env FENGBENCH_API_KEY 优先")
    parser.add_argument("--limit", type=int, default=None, help="每科目最多做几题（默认全部）")
    parser.add_argument("--data-dir", default=None, help="val 目录覆盖（默认按常量候选自动探测）")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="JSON/MD 输出目录")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=16, help="answer-only，小即可")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--selfcheck", action="store_true",
                        help="纯离线自检：只读 CSV + 校验结构，不碰 API，exit 0")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # 加载科目表
    if not SUBJECT_MAPPING_PATH.is_file():
        print(f"错误：找不到 subject_mapping.json -> {SUBJECT_MAPPING_PATH}")
        sys.exit(2)
    mapping, by_cn = load_subject_mapping(SUBJECT_MAPPING_PATH)
    subject_tokens = [s for s in re.split(r"[,，;；\s]+", args.subjects) if s]
    subjects, bad = resolve_subjects(subject_tokens, mapping, by_cn)
    if bad:
        print(f"警告：无法识别的科目被忽略：{bad}")

    val_dir = find_val_dir(VAL_DIR_CANDIDATES, args.data_dir)
    api_key = args.api_key or os.environ.get("FENGBENCH_API_KEY")
    if not api_key or args.selfcheck:
        # ---- 无 key / 主动自检：离线读 CSV + 校验，不卡 API，exit 0
        print("无 key, 仅交付 harness" if not api_key else "--selfcheck 模式：")
        report = run_offline(val_dir, subjects, args.limit)
        print(f"数据目录: {report['data_dir']}  科目数: {len(report['subjects'])}")
        for key, s in report["subjects"].items():
            state = "OK" if not s["problems"] else "问题"
            print(f"  [{state}] {key} ({s['cn_name']}) rows={s['rows']} file={s['file']}")
            for p in s["problems"][:8]:
                print(f"       - {p}")
        if not any(fil for fil in (s.get("file") for s in report["subjects"].values())):
            print()
            print("提示：本地未找到 FinEval 学术 val 数据。请按官方 docs 准备（FinEval 为只读仓库，不代写入）")
            print("  1) cd ~/FinEval\\code\\data")
            print("  2) wget https://huggingface.co/datasets/SUFE-AIFLM-Lab/FinEval/resolve/main/FinEval.zip")
            print("  3) unzip FinEval.zip   # 期望出现 dev/val/test 目录结构")
            print("  也可以用 --data-dir <你的 val 目录> 指定别的位置。")
        sys.exit(0)

    # ---- 有 key：正式打分
    print(f"API key 已就绪，开始评测 {model_name(args)} ……")
    result = run_score(val_dir, subjects, args, api_key)

    ov = result.get("overall")
    if ov:
        print(f"=== overall acc = {ov['accuracy']:.1%} ({ov['correct']}/{ov['total']}) ===")
    json_path, md_path = write_outputs(result, args.output_dir)
    print(f"JSON: {json_path}")
    print(f"MD  : {md_path}")


def model_name(args):
    return args.model or os.environ.get("FENGBENCH_MODEL") or "(未指定)"


if __name__ == "__main__":
    main()
