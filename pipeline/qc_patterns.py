"""句子级"复查队列"判据：正则只能发现疑点，不能判定对错。

为什么是 WARN 而不是 error：方法句与本研究结论句同形（Discussion 里回述方法、
`underwent radiation therapy` 出现在与他人系列的对比里），引文编号也会出现在
"consistent with Smith et al. (24), we found…" 这种本研究结论上。硬拦必然误砍合法关系，
所以这里只把候选送进人工复查队列。

判据来自 EXTRACTION_SPEC §4.7（不断言关系的句式）与 §10（禁止事项）。
两处消费：`agent_generated/scripts/check_agent_raw.py`（落盘前质检门）、
`scripts/summarize_agent_outputs.py`（汇总报告复查清单）。别再各自抄一份正则。
"""
from __future__ import annotations

import re

# 方法句/目的句谓词：形如 "we examined X with Y"、"X was performed to evaluate Y"、
# "four MRI sequences were available"、"patients underwent DWI"。描述做了什么，
# 不是发现了什么。
# 方法句/目的句谓词：形如 "we examined X with Y"。
# 三条件同时成立才拦（AGENT_INSTRUCTION §4.7）：① 主语是本研究 ② 谓语是方法动词 ③ 句中不含结果动词。
# 此处仅做条件②的正则匹配，条件③由下面的 RESULT_VERB_RE 判断。
METHOD_PREDICATE_RE = re.compile(
    r"\b(?:we|the authors?)\s+(?:examined|used|employed|applied|acquired|scanned|measured|"
    r"performed|collected|analyzed|analysed|studied|enrolled|obtained|recorded)\b"
    r"|\b(?:was|were)\s+(?:used|applied|performed|acquired|obtained|collected|recorded|"
    r"analysed|analyzed|evaluated|assessed|measured|implemented)\b"
    r"|\b(?:was|were|is|are)\s+(?:performed|acquired|obtained|done|carried out|prepared)\s+to\s+"
    r"(?:evaluate|assess|detect|investigate|study|determine|measure|identify|quantify)\b"
    r"|\bunderwent\b|\bsequences?\s+(?:were\s+)?available\b"
    r"|\b(?:with|using)\s+(?:a|an|the)\s+[\w\s-]{0,24}\b(?:sequence|protocol|coil|mode|paradigm|scanner)\b",
    re.I,
)

# 结果动词：句中出现这些词说明是结论句，不是纯方法句，应豁免方法句黑名单。
# 如 "We detected lesions on ASL"（detected 是结果动词）→ 不标记 method_like
# v3 教训（51 条误删复核）：词表缺 displayed / resulted in / confirmed / is based on /
# 否定结果句（did not observe / no significant / not associated），执行侧把它们当流程句剪。
# 注意：只补 found/finds，不补 finding（会撞上名词 "imaging finding"）。
# 动名词形式（detecting/identifying 等）：用于豁免 "was acquired for detecting lesions" 这类
# 目的从句——虽然语法上是方法目的句，但隐含了发现性结果（lesions were detected）。
RESULT_VERB_RE = re.compile(
    r"\b(?:showed|shows|show|shown|found|finds|demonstrated|demonstrates|"
    r"detected|detects|identified|identifies|revealed|reveals|"
    r"observed|observes|noted|notes|displayed|resulted\s+in|confirmed|confirms|"
    r"detecting|identifying|revealing|observing|showing|demonstrating|confirming|"
    r"(?:is|are|was|were)\s+based\s+on|"
    r"had|were\s+(?:higher|lower|greater|less|increased|decreased|reduced|enhanced|diminished)|"
    r"was\s+(?:higher|lower|greater|less|increased|decreased|reduced|enhanced|diminished)|"
    r"(?:was|were)\s+(?:not\s+)?associated\s+with|no\s+association|"
    r"(?:no|not)\s+significant|"
    r"did\s+not\s+(?:observe|detect|find|show|differ|induce|reveal|identify|alter|change)\b|"
    r"(?:is|are|was|were)\s+affected\s+by|"
    r"correlated\s+with|was\s+correlated\s+with|"
    r"was\s+seen|were\s+seen|was\s+visible|were\s+visible|"
    r"was\s+a\s+sensitive|was\s+a\s+specific|is\s+a\s+sensitive|is\s+a\s+specific|"
    r"suggests|suggesting|was\s+obtained|were\s+obtained)\b",
    re.I,
)

# 引用他人研究：引文标记 + 转述引导语 + 无本研究指称，三条同时满足才算舍弃候选
CITATION_MARK_RE = re.compile(r"\(\d{1,3}\)|\[\d{1,3}\]|\b(?:19|20)\d{2}[a-c]?\b|\bet al\b", re.I)
CITATION_LEAD_RE = re.compile(
    r"in one reported series|it has been\s+(?:shown|reported|demonstrated|observed)"
    r"|has been\s+(?:shown|reported|demonstrated|observed)"
    r"|have been\s+(?:shown|reported|demonstrated|observed)"
    r"|(?:have|has)\s+(?:shown|reported|demonstrated|observed|described|found)"
    r"|is generally\s+described\s+as|was generally\s+described\s+as|are generally\s+described\s+as"
    r"|as reported by|previously\s+(?:shown|reported|described)"
    r"|(?:was|were)\s+first\s+(?:described|reported)"
    r"|in (?:a|an) (?:previous|prior|earlier) stud|earlier studies|in the literature"
    r"|\bet al\.?\s+(?:reported|described|found|observed|demonstrated|showed|have)"
    r"|(?:reported|described|found|observed) (?:by|in)",
    re.I,
)
OWN_STUDY_RE = re.compile(
    r"\b(?:our|we|us)\b|in this study|the present study|in the current stud"
    r"|our (?:patients|results|data|series|findings|study|cohort|group)"
    r"|\bhere\b"                          # "were assessed here" — self-reference
    r"|[Rr]ho\s*[=:]|p\s*[=<>]\s*0?\.\d|r\s*=\s*0?\.\d"  # statistical results = own data
    r"|which\s+suggests|which\s+suggesting|which\s+implies|which\s+indicates",  # study's own conclusion
    re.I,
)

# 能力句：描述工具的潜在用途，不是本研究的结果断言（EXTRACTION_SPEC §9 待修项）。
# "MRI can be used to assess X"≠"本研究用 MRI 评估了 X"。结果动词豁免同样适用：
# "we showed that ASL can detect lesions" 是本研究结论，不标。
CAPABILITY_RE = re.compile(
    r"\bcan\s+(?:also\s+)?be\s+(?:used|applied|employed|performed)\s+to\b"
    r"|\bcan\s+(?:indirectly\s+)?(?:be\s+)?(?:measure[dd]?|assess|evaluate|detect|quantify|identify)\b"
    r"|\b(?:is|are)\s+(?:often|commonly|routinely|typically)\s+used\s+to\b"
    r"|\bmay\s+be\s+used\s+to\b|\bcould\s+be\s+used\s+to\b"
    r"|\b(?:is|are)\s+useful\s+for\b|\b(?:is|are)\s+suitable\s+for\b|\bis\s+able\s+to\b",
    re.I,
)

# 统计量/性能指标：不得抽成实体（Entity_schema §4：Biomarker 排除统计指标；Other 非默认桶）。
# v3 教训："receiver coil sensitivity profile (RP)" 是 MR 物理量，不是统计指标——
# 上一版 search 全文匹配导致门队列 5 条全是误报。现改为**锚定 mention 开头**匹配：
# 指标词必须是 mention 的首词（或整个 mention），长复合词中间的指标词不算。
METRIC_START_RE = re.compile(
    r"^(?:the\s+)?(?:sensitivity(?:\s+and\s+specificity)?|specificity|"
    r"dice(?:\s+similarity)?(?:\s+coefficient)?|dsc|ppv|positive\s+predictive\s+value|"
    r"accuracy|auc|hazard\s+ratio|odds\s+ratio|p\s*-?\s*value|confidence\s+interval|"
    r"correlation\s+coefficient|cohen'?s?\s+(?:d|kappa))\b",
    re.I,
)

# --------------------------------------------------------------------------- #
# Assertion 一致性校验：检查 source_text 的否定/不确定/比较标记与 assertion_type 是否匹配
# --------------------------------------------------------------------------- #

# 否定标记：句中出现这些词时，assertion 应为 Negative
# 注意：不用裸 "not"/"no"，因为 "not common"、"not only" 等不是否定结果。
NEGATION_RE = re.compile(
    r"\b(?:none\s+of|without|absence\s+of|absent|"
    r"did\s+not\s+(?:show|find|detect|observe|reveal|identify|demonstrate|differ|alter|change)\b|"
    r"were\s+not\s+(?:found|detected|observed|identified|seen|visible|present|associated)\b|"
    r"was\s+not\s+(?:found|detected|observed|identified|seen|visible|present|associated)\b|"
    r"not\s+(?:associated\s+with|significant|present|visible|detected|found|observed|seen)\b|"
    r"no\s+(?:significant|association|evidence\s+of|lesion|abnormality|finding|difference|correlation|enhancement|signal|defect|abnormal)\b|"
    r"negative\s+for|ruled\s+out|excluded|"
    r"absence\s+of\s+(?:enhancement|signal|lesion|abnormality|finding))\b",
    re.I,
)

# 不确定标记：句中出现这些词时，assertion 应为 Uncertain
UNCERTAINTY_RE = re.compile(
    r"\b(?:may|might|could\s+(?:be|represent|indicate|suggest)|"
    r"possibly|perhaps|appears\s+to|seems\s+to|"
    r"marginally|trend\s+toward|tendency|"
    r"uncertain|unclear|equivocal|indeterminate)\b",
    re.I,
)

# 比较标记：句中出现这些词时，assertion 应为 Comparative
COMPARISON_RE = re.compile(
    r"\b(?:compared\s+(?:to|with|against)|"
    r"higher|lower|greater|less|larger|smaller|"
    r"increased|decreased|elevated|reduced|diminished|enhanced|"
    r"more\s+(?:than|pronounced|severe|frequent)|less\s+(?:than|pronounced|severe|frequent)|"
    r"difference\s+(?:between|in|of)|"
    r"significantly\s+(?:different|higher|lower|greater|less))\b",
    re.I,
)


# source_text 结束位置之后紧跟的引文标记（citation_truncated 判据）。
# 逃逸路径：标注员把 source_text 截到引文标记之前（如整句以 [6, 17, 18] 结尾，
# 引文只到 "…fibres"），规则 7 的 CITATION_MARK_RE 在被截断的 source_text 里就扫不到了。
CITATION_TRAILING_RE = re.compile(
    r"\[\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*\]"
    r"|\(\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*\)"
    r"|\(\s*[A-Z][a-zA-Z]+(?:\s+et\s+al\.?)?(?:\s*[;,]\s*(?:19|20)\d{2})?\s*\)"
    r"|\bet\s+al\b",
)

# ASSESSED_BY 的 tail 必须是评估手段（序列/模态/量表/指标），不能是刺激范式、任务、
# 线圈、硬件、腰穿/活检这类操作或材料。词表不全，只出候选。
ASSESSED_BY_TAIL_BAN_RE = re.compile(
    r"\b(?:paradigm|task|stimulation|stimuli|stimulus|reading|typing|n-?back|condition|runs?)\b"
    r"|\b(?:coil|array|scanner|software|package|electrode|cap|system|unit)\b"
    r"|\b(?:lumbar puncture|cerebrospinal fluid sampling|biopsy|craniotomy|venipuncture|injection)\b",
    re.I,
)


def citation_candidate(source_text: str) -> str | None:
    """返回舍弃理由；不是候选时返回 None。"""
    mark = CITATION_MARK_RE.search(source_text or "")
    lead = CITATION_LEAD_RE.search(source_text or "")
    if not (mark and lead):
        return None
    own = OWN_STUDY_RE.search(source_text or "")
    if own:
        return None
    return (f"引文标记 {mark.group(0)!r} + 转述引导语 {lead.group(0)!r}，"
            f"句中无本研究指称 → 疑似他人研究背景，按 §4.7 应舍弃")


def relation_review_tags(source_text: str, relation_type: str = "",
                         tail_mention: str = "",
                         head_entity_type: str = "",
                         tail_entity_type: str = "",
                         assertion_type: str = "") -> list[tuple[str, str]]:
    """一条 Relation 的句式级疑点，返回 [(tag, why)]，可为空。"""
    out: list[tuple[str, str]] = []
    text = source_text or ""
    m = METHOD_PREDICATE_RE.search(text)
    if m and not RESULT_VERB_RE.search(text):
        # ASSESSED_BY/DIAGNOSED_BY/COMPARED_WITH 天然含方法谓词，不标记 method_like
        if relation_type not in ("ASSESSED_BY", "DIAGNOSED_BY", "COMPARED_WITH"):
            # 命中方法句谓词且不含结果动词 → 纯方法句，标记复查
            out.append(("method_like", f"方法/目的句谓词 {m.group(0)!r}，无结果动词（§4.7 三条件）"))
    c = CAPABILITY_RE.search(text)
    if c and not RESULT_VERB_RE.search(text):
        out.append(("capability_like",
                    f"能力句谓词 {c.group(0)!r}：描述工具潜在用途而非本研究结果，不得据此建边"))
    why = citation_candidate(text)
    if why and relation_type != "ASSOCIATED_WITH":
        # ASSOCIATED_WITH 是背景关联，即使引用他人研究也合理保留
        out.append(("cited_other_study", why))
    if relation_type == "ASSESSED_BY":
        b = ASSESSED_BY_TAIL_BAN_RE.search(tail_mention or "")
        if b:
            out.append(("assessed_by_tail_suspect",
                        f"tail {tail_mention!r} 含 {b.group(0)!r}，疑似刺激范式/设备/操作而非评估方法"))
    # IMPROVES/WORSENS 语义约束（按 tail 分型，head 豁免 Treatment）：
    #   tail 是疾病/病理/影像表现/症状/临床特征 → 只有 head 是 Treatment 才合法
    #   （"treatment IMPROVES cognitive decline"）；
    #   head 是技术/序列/模态/Other（如 "the proposed pre-processing"）→ 技术不治疗疾病，
    #   大概率是把改善对象误当成了被改善的性能
    #   （畸变例：BT000930 "pre-processing IMPROVES necrosis"，原句改善的是勾画精度）。
    #   合法 tail：性能/任务名词（accuracy）、另一技术/序列（GRAPPA IMPROVES TOF MRA）
    _NOT_TREATABLE = {"Disease", "Pathology", "ImagingFinding", "Symptom", "ClinicalFeature"}
    if (relation_type in {"IMPROVES", "WORSENS"}
            and tail_entity_type in _NOT_TREATABLE
            and head_entity_type != "Treatment"):
        out.append(("improves_semantics",
                    f"{relation_type} 的 tail {tail_mention!r}（{tail_entity_type}）是疾病/病理/表现，"
                    f"但 head（{head_entity_type or '类型未知'}）不是 Treatment——"
                    f"原句改善的可能是精度而非该对象本身"))

    # Assertion 一致性：source_text 的语境标记应与 assertion_type 匹配
    if assertion_type:
        has_neg = NEGATION_RE.search(text)
        has_unc = UNCERTAINTY_RE.search(text)
        has_cmp = COMPARISON_RE.search(text)
        if has_neg and assertion_type == "Positive":
            out.append(("assertion_mismatch",
                        f"source_text 含否定标记 {has_neg.group(0)!r} 但 assertion=Positive"
                        f"→ 建议 Negative"))
        if has_unc and assertion_type == "Positive":
            out.append(("assertion_mismatch",
                        f"source_text 含不确定标记 {has_unc.group(0)!r} 但 assertion=Positive"
                        f"→ 建议 Uncertain"))
        if has_cmp and assertion_type == "Positive":
            out.append(("assertion_mismatch",
                        f"source_text 含比较标记 {has_cmp.group(0)!r} 但 assertion=Positive"
                        f"→ 建议 Comparative"))
    return out


def entity_review_tags(mention: str, entity_type: str = "") -> list[tuple[str, str]]:
    """一个 Entity 的句式级疑点，返回 [(tag, why)]，可为空。"""
    out: list[tuple[str, str]] = []
    m = METRIC_START_RE.match(mention or "")
    if m:
        out.append(("metric_as_entity",
                    f"mention {mention!r} 以统计量/性能指标 {m.group(0).strip()!r} 开头："
                    f"统计量默认不抽实体（受限规则见 AGENT_INSTRUCTION 实体规则 10）"))
    return out


def citation_truncated_after(lookahead: str) -> str | None:
    """source_text 结束位置之后是否紧跟引文标记（句末标点之前）。

    传入 source_text 在输入原文中结束位置起的一段后文（建议 120 字符）。
    规则：引文标记出现在任何句末标点（. ! ? 换行）之前 → source_text 被截断到
    引文标记之前（规避规则 7），返回标记文本；否则 None。
    """
    if not lookahead:
        return None
    m = CITATION_TRAILING_RE.search(lookahead)
    if not m:
        return None
    enders = re.search(r"[.!?\n]", lookahead[: m.start()])
    if enders:
        return None
    return m.group(0)
