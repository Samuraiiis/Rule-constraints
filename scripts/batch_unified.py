"""批量统一抽取脚本（方案C）——带进度显示。

逐篇调用 unified_extractor，每步打印进度，最后输出对比表。

用法：
    .venv\\Scripts\\python.exe -m scripts.batch_unified BT000001 BT000002 ... --force
    .venv\\Scripts\\python.exe -m scripts.batch_unified --all --force   # 跑全部10篇
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 默认 10 篇（与之前测试一致）
DEFAULT_DOCS = [
    "BT000001", "BT000002", "BT000003", "BT000004", "BT000005",
    "BT000006", "BT000007", "BT000008", "BT000009", "BT000010",
]


def main() -> int:
    # 解析参数
    force = "--force" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if "--all" in sys.argv or not args:
        docs = DEFAULT_DOCS
    else:
        docs = args

    total = len(docs)
    print(f"{'='*60}")
    print(f"批量统一抽取（方案C）")
    print(f"模型: 见 .env LLM_MODEL")
    print(f"文献数: {total}")
    print(f"强制重新抽取: {'是' if force else '否'}")
    print(f"{'='*60}\n")

    # 延迟导入（避免 --help 时加载不必要的模块）
    from pipeline.cache_manager import get_cache_path, get_run_version
    from pipeline.llm_client import LLMClient
    from pipeline.markdown_reader import MarkdownReaderImpl
    from pipeline.metadata_provider import MetadataProviderImpl
    from pipeline.entity_normalizer import EntityNormalizerImpl
    from pipeline.unified_extractor import (
        UnifiedExtractorImpl,
        run_validation_report,
        save_unified_cache,
    )
    from pipeline.single_doc_runner import ExtractionError

    # 构造客户端
    try:
        client = LLMClient.from_env()
    except ValueError as exc:
        print(f"配置错误: {exc}")
        return 2

    run_version = get_run_version()
    print(f"endpoint : {client._endpoint}")
    print(f"model    : {client.model}")
    print(f"version  : {run_version}\n")

    reader = MarkdownReaderImpl(PROJECT_ROOT)
    provider = MetadataProviderImpl(PROJECT_ROOT)
    normalizer = EntityNormalizerImpl(PROJECT_ROOT)
    extractor = UnifiedExtractorImpl(client, normalizer=normalizer)

    # 结果汇总
    results: list[dict] = []
    success_count = 0
    fail_count = 0

    for idx, doc_id in enumerate(docs, 1):
        print(f"{'─'*60}")
        print(f"[{idx}/{total}] {doc_id}")
        print(f"{'─'*60}")
        t0 = time.time()

        # 1. 检查缓存
        cache_path = get_cache_path(doc_id, "unified", PROJECT_ROOT)
        if cache_path.exists() and not force:
            print(f"  [1/5] 缓存命中，跳过（加 --force 重新抽取）")
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            results.append({
                "doc_id": doc_id,
                "status": "cached",
                "evidence": cache.get("evidence_count", 0),
                "entity": cache.get("entity_count", 0),
                "relation": cache.get("relation_count", 0),
                "issues": cache.get("validation", {}).get("issue_count", "?"),
                "time": 0,
            })
            success_count += 1
            print(f"  → EV={cache.get('evidence_count',0)} ENT={cache.get('entity_count',0)} REL={cache.get('relation_count',0)} (缓存)")
            continue

        # 2. 读取 Markdown
        print(f"  [1/5] 读取 Markdown...", end="", flush=True)
        try:
            md_text, md_path = reader.read(doc_id)
        except FileNotFoundError as exc:
            print(f" 失败: {exc}")
            results.append({"doc_id": doc_id, "status": "fail", "error": str(exc)})
            fail_count += 1
            continue
        print(f" OK ({len(md_text)} 字符, {md_path.name})")

        # 3. 读取元数据
        print(f"  [2/5] 读取元数据...", end="", flush=True)
        try:
            metadata = provider.get_metadata(doc_id)
        except Exception:
            metadata = {}
        print(f" OK ({metadata.get('title', '')[:40]}...)")

        # 4. 调用 LLM 抽取
        print(f"  [3/5] 调用 LLM 抽取中（可能需要 30-300 秒）...", flush=True)
        try:
            result = extractor.extract(doc_id, md_text, metadata)
        except ExtractionError as exc:
            print(f"  [3/5] 失败: {exc}")
            results.append({"doc_id": doc_id, "status": "fail", "error": str(exc)})
            fail_count += 1
            continue

        ev_count = len(result.processed["evidences"])
        ent_count = len(result.processed["entities"])
        rel_count = len(result.processed["relations"])
        elapsed = time.time() - t0
        print(f"  [3/5] 完成: EV={ev_count} ENT={ent_count} REL={rel_count} ({elapsed:.0f}s)")

        # 5. P7 校验
        print(f"  [4/5] P7 校验...", end="", flush=True)
        summary = run_validation_report(doc_id, result.processed)
        print(f" issue={summary['issue_count']} 阻断={summary['blocking_count']}")

        # 6. 保存缓存
        print(f"  [5/5] 保存缓存...", end="", flush=True)
        cache_path = save_unified_cache(doc_id, result.processed, client.model, PROJECT_ROOT, metadata, summary)
        print(f" OK ({cache_path.name})")

        results.append({
            "doc_id": doc_id,
            "status": "ok",
            "evidence": ev_count,
            "entity": ent_count,
            "relation": rel_count,
            "rel_per_ent": round(rel_count / ent_count, 2) if ent_count else 0,
            "issues": summary["issue_count"],
            "blocking": summary["blocking_count"],
            "time": round(elapsed, 0),
        })
        success_count += 1

    # 汇总表
    print(f"\n{'='*60}")
    print(f"批量完成: {success_count} 成功 / {fail_count} 失败 / {total} 总计")
    print(f"{'='*60}\n")

    if results:
        print(f"{'文档':<12} {'状态':<8} {'EV':>5} {'ENT':>5} {'REL':>5} {'REL/ENT':>8} {'issue':>6} {'阻断':>5} {'耗时':>6}")
        print(f"{'─'*60}")
        for r in results:
            status = r.get("status", "?")
            ev = r.get("evidence", "-")
            ent = r.get("entity", "-")
            rel = r.get("relation", "-")
            rpe = r.get("rel_per_ent", "-")
            iss = r.get("issues", "-")
            blk = r.get("blocking", "-")
            t = r.get("time", "-")
            if isinstance(t, (int, float)) and t > 0:
                t_str = f"{t:.0f}s"
            else:
                t_str = str(t)
            print(f"{r['doc_id']:<12} {status:<8} {ev:>5} {ent:>5} {rel:>5} {rpe:>8} {iss:>6} {blk:>5} {t_str:>6}")

    # 保存汇总
    summary_path = PROJECT_ROOT / "data" / "extracted" / run_version / "batch_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n汇总已保存: {summary_path}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
