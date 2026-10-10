"""给 Agent 直读产出加摘要：每份 {doc}_unified.json 开头写入 _summary，并汇总成 SUMMARY.md。

为什么要脚本算而不是标注者自报：_summary 必须与 entities/relations 实际内容一致，
自报数字会漂；同一批里"0 error"只证明自洽，这里顺带把已知的三类语义风险量化出来。

用法：
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/summarize_agent_outputs.py
    PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe scripts/summarize_agent_outputs.py --dir data/agent_generated
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.qc_patterns import relation_review_tags  # noqa: E402
from pipeline.source_locator import contains_phrase, normalize  # noqa: E402


def build_summary(obj: dict) -> dict:
    ents = obj.get("entities", [])
    rels = obj.get("relations", [])

    registered: set[tuple[str, str]] = set()
    case_variants: dict[str, set[str]] = {}
    for e in ents:
        key = (e.get("mention", ""), e.get("entity_type", ""))
        registered.add(key)
        case_variants.setdefault(normalize(e.get("mention", "")), set()).add(e.get("mention", ""))

    involved: set[tuple[str, str]] = set()
    for r in rels:
        involved.add((r.get("head_mention", ""), r.get("head_entity_type", "")))
        involved.add((r.get("tail_mention", ""), r.get("tail_entity_type", "")))

    orphans = sorted(m for m, t in registered - involved)
    self_contained = [
        f'{r["relation_type"]}: {r["head_mention"]} -> {r["tail_mention"]}'
        for r in rels
        if r.get("head_mention") and r.get("tail_mention")
        and (contains_phrase(normalize(r["tail_mention"]), normalize(r["head_mention"]))
             or contains_phrase(normalize(r["head_mention"]), normalize(r["tail_mention"])))
    ]
    long_mentions = [e["mention"] for e in ents if len(e.get("mention", "").split()) > 6]
    dup_case = [sorted(v) for v in case_variants.values() if len(v) > 1]
    assertion = Counter(r.get("assertion_type", "?") for r in rels)
    sections = Counter(str(r.get("section")) for r in rels)

    # 句式级疑点：与落盘前质检门共用 pipeline/qc_patterns 的判据，不各写一份正则
    review = []
    for i, r in enumerate(rels, 1):
        for tag, why in relation_review_tags(r.get("source_text", ""),
                                             r.get("relation_type", ""),
                                             r.get("tail_mention", ""),
                                             head_entity_type=r.get("head_entity_type", ""),
                                             tail_entity_type=r.get("tail_entity_type", "")):
            review.append({
                "tag": tag, "index": i, "section": r.get("section"), "page": r.get("page"),
                "triple": f"{r.get('head_mention')} --{r.get('relation_type')}"
                          f"--({r.get('assertion_type')})--> {r.get('tail_mention')}",
                "why": why, "source_text": r.get("source_text", ""),
            })

    return {
        "entities": len(registered),
        "entities_listed": len(ents),
        "relations": len(rels),
        "relation_coverage": round(len(registered & involved) / len(registered), 3) if registered else 0.0,
        "orphan_entities": len(orphans),
        "orphan_entity_list": orphans,
        "entity_types": dict(Counter(e.get("entity_type", "?") for e in ents).most_common()),
        "relation_types": dict(Counter(r.get("relation_type", "?") for r in rels).most_common()),
        "assertion_types": dict(assertion.most_common()),
        "negative_relations": assertion.get("Negative", 0),
        "uncertain_relations": assertion.get("Uncertain", 0),
        "relation_sections": dict(sections.most_common()),
        "review_queue_counts": dict(Counter(x["tag"] for x in review).most_common()),
        "review_queue": review,
        "checks": {
            "head_tail_self_contained": self_contained,
            "mentions_over_6_words": long_mentions,
            "case_only_duplicate_mentions": dup_case,
            "page_null_entities": sum(1 for e in ents if e.get("page") is None),
            "section_null_entities": sum(1 for e in ents if e.get("section") is None),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("用法：")[0])
    ap.add_argument("--dir", default="data/agent_generated")
    ap.add_argument("--single", metavar="DOC_ID",
                    help="只处理单篇文献（不生成 SUMMARY.md，仅写 _summary）")
    args = ap.parse_args()

    out_dir = PROJECT_ROOT / args.dir

    # --single 模式：只处理一篇，不生成 SUMMARY.md
    if args.single:
        path = out_dir / f"{args.single}_unified.json"
        if not path.exists():
            print(f"未找到: {path}")
            return 1
        obj = json.loads(path.read_text(encoding="utf-8"))
        summary = build_summary(obj)
        obj.pop("_summary", None)
        ordered = {"document_id": obj.pop("document_id", args.single),
                   "_summary": summary}
        ordered.update(obj)
        path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{args.single}: ENT={summary['entities']} REL={summary['relations']} "
              f"覆盖率={summary['relation_coverage']:.0%} 孤儿={summary['orphan_entities']}")
        return 0

    files = sorted(p for p in out_dir.glob("*_unified.json"))
    if not files:
        print(f"未找到产出: {out_dir}/*_unified.json")
        return 1

    rows = []
    for path in files:
        obj = json.loads(path.read_text(encoding="utf-8"))
        summary = build_summary(obj)
        obj.pop("_summary", None)
        ordered = {"document_id": obj.pop("document_id", path.name.replace("_unified.json", "")),
                   "_summary": summary}
        ordered.update(obj)
        path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append((path.name.replace("_unified.json", ""), summary))
        print(f"{rows[-1][0]:10} ENT {summary['entities']:3} | REL {summary['relations']:3} "
              f"| 覆盖率 {summary['relation_coverage']:.0%} | 孤儿 {summary['orphan_entities']:2} "
              f"| Neg {summary['negative_relations']:2}")

    md = ["# Agent 直读抽取汇总", "",
          f"共 {len(rows)} 篇 | Entity {sum(s['entities'] for _, s in rows)} "
          f"| Relation {sum(s['relations'] for _, s in rows)}", "",
          "| 文献 | 实体 | 关系 | 关系/实体 | 覆盖率 | 孤儿 | Negative | Uncertain | 疑点 | 主要关系类型 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for doc, s in rows:
        top = ", ".join(f"{k}×{v}" for k, v in s["relation_types"].items())
        ratio = round(s["relations"] / s["entities"], 2) if s["entities"] else 0
        md.append(f"| {doc} | {s['entities']} | {s['relations']} | {ratio} "
                  f"| {s['relation_coverage']:.0%} | {s['orphan_entities']} "
                  f"| {s['negative_relations']} | {s['uncertain_relations']} "
                  f"| {sum(s['review_queue_counts'].values())} | {top} |")

    md += ["", "## 语义风险计数（质检门查不到，需人工抽检）", "",
           "> 本节日志不截断：历史上 `[:50]` 把长 mention 显示成半句，被误读成抽取质量问题。", ""]
    for doc, s in rows:
        c = s["checks"]
        bits = []
        if c["head_tail_self_contained"]:
            bits.append(f"自包含关系 {len(c['head_tail_self_contained'])} 条: "
                        + "; ".join(c["head_tail_self_contained"]))
        if c["mentions_over_6_words"]:
            bits.append(f">6 词 mention {len(c['mentions_over_6_words'])} 个: "
                        + "; ".join(f'"{m}"' for m in c["mentions_over_6_words"]))
        if c["case_only_duplicate_mentions"]:
            bits.append(f"仅大小写重复 {len(c['case_only_duplicate_mentions'])} 组: "
                        + "; ".join("/".join(v) for v in c["case_only_duplicate_mentions"]))
        bg = s["relation_sections"].get("Methods", 0) + s["relation_sections"].get("Introduction", 0)
        if bg:
            pct = bg / s["relations"] if s["relations"] else 0
            bits.append(f"Methods/Introduction 来源关系 {bg} 条（{pct:.0%}）")
        md.append(f"- **{doc}**：" + ("；".join(bits) if bits else "无异常"))

    queue = [(doc, item) for doc, s in rows for item in s["review_queue"]]
    md += ["", "## 复查队列（句式级疑点，不是判定）", ""]
    if queue:
        md.append("按 tag 汇总：" + ", ".join(f"{k}×{v}" for k, v in
                    sorted(Counter(i["tag"] for _, i in queue).items(), key=lambda x: -x[1])))
        md.append("")
        md.append("疑点只由句式正则得出：方法/目的句、他人研究引文句、ASSESSED_BY 的 tail 像刺激范式或设备。"
                  "逐条人工判定 `成立 / 应舍弃`，判定前不要据此删数据。")
        md.append("")
        md.append("| 文献 | # | tag | 三元组 | 章节 | 页 | 疑点 | 原文 |")
        md.append("|---|---|---|---|---|---|---|---|")
        for doc, item in queue:
            md.append(f"| {doc} | {item['index']} | {item['tag']} | {item['triple']} "
                      f"| {item['section'] or '—'} | {item['page']} | {item['why']} "
                      f"| {item['source_text']} |")
    else:
        md.append("空 —— 本批没有出现方法句/引文句/可疑 ASSESSED_BY tail。")

    # SUMMARY 归档到 audits/ 子目录，与 raw JSON（data/agent_generated 根）分离
    audit_dir = out_dir / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (audit_dir / "SUMMARY.json").write_text(
        json.dumps({doc: s for doc, s in rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出: {audit_dir / 'SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
