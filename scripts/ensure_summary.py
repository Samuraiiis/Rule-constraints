#!/usr/bin/env python
"""给 raw agent JSON 补 _summary 字段（entities/relations 数量等）。

此脚本是 summarize_agent_outputs.py --single 的兼容入口。
保留旧命令 `ensure_summary.py <doc_id>` 不变，内部委托给
summarize_agent_outputs.build_summary（更全面的摘要，含 review_queue）。

用法：
    .venv\\Scripts\\python.exe scripts\\ensure_summary.py <doc_id>
    .venv\\Scripts\\python.exe scripts\\ensure_summary.py --all
    # 等价于：
    .venv\\Scripts\\python.exe scripts\\summarize_agent_outputs.py --single <doc_id>
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.summarize_agent_outputs import build_summary  # noqa: E402

RAW_DIR = ROOT / "data" / "agent_generated"


def ensure_one(path: Path) -> tuple[int, int]:
    import json
    doc = json.loads(path.read_text(encoding="utf-8"))
    summary = build_summary(doc)
    new_doc = {"document_id": doc.get("document_id", path.stem.replace("_unified", "")),
               "_summary": summary}
    new_doc.update({k: v for k, v in doc.items() if k not in ("document_id", "_summary")})
    path.write_text(json.dumps(new_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary["entities"], summary["relations"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("doc_id", nargs="?", help="e.g. NL003342")
    ap.add_argument("--all", action="store_true", help="process all *_unified.json")
    args = ap.parse_args()

    if args.all:
        for p in sorted(RAW_DIR.glob("*_unified.json")):
            n, m = ensure_one(p)
            print(f"{p.stem[:-len('_unified')]}: ENT={n} REL={m}")
        return
    if not args.doc_id:
        ap.error("doc_id or --all required")
    n, m = ensure_one(RAW_DIR / f"{args.doc_id}_unified.json")
    print(f"{args.doc_id}: ENT={n} REL={m}")


if __name__ == "__main__":
    main()
