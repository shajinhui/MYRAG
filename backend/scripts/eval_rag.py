"""
MYRAG 评估脚本 —— 面向生产级的 RAG 质量评估。

使用 DeepEval 指标（LLM 作为裁判）+ 自定义规则校验。
支持 Ollama（本地）和 Gemini（云端）作为裁判模型。

用法：
    cd MYRAG/backend
    source ../venv/bin/activate
    python scripts/eval_rag.py --workspace 11 [--judge ollama|gemini]
"""

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

# ── 配置 ─────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8080/api/v1/rag"
TIMEOUT = 120  # 每个请求的秒数


# ── 数据结构 ───────────────────────────────────────────────────────────

@dataclass
class TestCase:
    """单个评估测试用例。"""
    id: str
    category: str  # fact_extraction、table_data、cross_doc、anti_hallucination、history、citation
    question: str
    language: str  # vi、en
    history: list[dict] = field(default_factory=list)
    # 标准答案（可选 —— 供基于参考的指标使用）
    expected_answer: str = ""
    expected_keywords: list[str] = field(default_factory=list)
    expected_refuse: bool = False  # 系统是否应该拒绝回答？
    # 结果（评估完成后填充）
    answer: str = ""
    retrieved_contexts: list[str] = field(default_factory=list)
    source_count: int = 0
    latency_ms: float = 0


@dataclass
class MetricResult:
    """单项指标评估结果。"""
    name: str
    score: float  # 0.0 - 1.0
    passed: bool
    reason: str = ""


@dataclass
class TestResult:
    """测试用例的完整评估结果。"""
    test_id: str
    category: str
    question: str
    language: str
    answer_preview: str
    source_count: int
    latency_ms: float
    metrics: list[MetricResult] = field(default_factory=list)
    overall_score: float = 0.0


# ── 测试数据集 ──────────────────────────────────────────────────────────────

def build_test_cases(workspace_id: int) -> list[TestCase]:
    """
    为 KBG9 工作区（id=11）手工设计的测试用例。
    文档：
      - doc 11：新莱应材 2025 年报
      - doc 12：DeepSeek-V3.2 技术论文（英语）
    """
    cases = [
        # ── 事实提取（  ──
        TestCase(
            id="FACT-VI-01",
            category="fact_extraction",
            question="新莱应材成立于哪年并在多少个国家运营？",
            language="vi",
            expected_keywords=["2010", "12"],
        ),
        TestCase(
            id="FACT-VI-02",
            category="fact_extraction",
            question="新莱应材 2025 年的营收是多少，增长了多少百分比？",
            language="vi",
            expected_keywords=["4.850", "4850", "23,4", "23.4"],
        ),
        TestCase(
            id="FACT-VI-03",
            category="fact_extraction",
            question="新莱应材 有多少员工，按学历如何分布？",
            language="vi",
            expected_keywords=["3.200", "3200"],
        ),
        # ── 事实提取（英语文档） ──
        TestCase(
            id="FACT-EN-01",
            category="fact_extraction",
            question="What are the key technical breakthroughs of DeepSeek-V3.2?",
            language="en",
            expected_keywords=["DSA", "Sparse Attention", "reinforcement", "RL"],
        ),
        TestCase(
            id="FACT-EN-02",
            category="fact_extraction",
            question="What competitions did DeepSeek-V3.2 achieve gold-medal performance in?",
            language="en",
            expected_keywords=["IMO", "IOI"],
        ),
        # ── 表格数据提取 ──
        TestCase(
            id="TABLE-01",
            category="table_data",
            question="请告诉我 新莱应材 在 2023-2025 年的净营收和 EBITDA？",
            language="vi",
            expected_keywords=["3.180", "3180", "4.850", "4850", "890"],
        ),
        TestCase(
            id="TABLE-02",
            category="table_data",
            question="新莱应材 在 2023-2025 年的毛利率和 ROE 分别是多少？",
            language="vi",
            expected_keywords=["40", "42", "44", "12,8", "15,6", "18,7"],
        ),
        TestCase(
            id="TABLE-03",
            category="table_data",
            question="DeepSeek-V3.2 在 AIME 2025 和 HMMT 2025 年二月的成绩是多少？",
            language="vi",
            expected_keywords=["93.1", "AIME"],
        ),
        # ── 跨文档推理 ──
        TestCase(
            id="CROSS-01",
            category="cross_doc",
            question="新莱应材 是否有 AI Platform 业务？该业务的营收是多少？DeepSeek‑V3.2 有哪些突出的 AI 能力？",
            language="vi",
            expected_keywords=["AI Platform", "900", "DSA"],
        ),
        TestCase(
            id="CROSS-02",
            category="cross_doc",
            question="新莱应材 在研发上投入了多少？DeepSeek‑V3.2 为开源社区做了哪些贡献？",
            language="vi",
            expected_keywords=["R&D", "12"],
        ),
        # ── 反幻觉（应拒绝回答） ──
        TestCase(
            id="ANTI-01",
            category="anti_hallucination",
            question="埃隆·马斯克出生于哪一年？",
            language="vi",
            expected_refuse=True,
        ),
        TestCase(
            id="ANTI-02",
            category="anti_hallucination",
            question="如何煮出最美味的河内牛肉粉？",
            language="vi",
            expected_refuse=True,
        ),
        TestCase(
            id="ANTI-03",
            category="anti_hallucination",
            question="比特币今天的价格是多少？",
            language="vi",
            expected_refuse=True,
        ),
        # ── 历史 / 追问 ──
        TestCase(
            id="HIST-01",
            category="history",
            question="哪个业务板块增长最快？",
            language="vi",
            history=[
                {"role": "user", "content": "新莱应材 主要有哪些业务板块？"},
                {"role": "assistant", "content": "新莱应材 有 4 个主要业务板块：\n1. 软件解决方案：1.890 兆 VNĐ\n2. 云服务：1.520 兆 VNĐ\n3. AI Platform：900 兆 VNĐ\n4. 咨询与部署：540 兆 VNĐ"},
            ],
            expected_keywords=["AI Platform", "66", "67"],
        ),
        TestCase(
            id="HIST-02",
            category="history",
            question="请更详细解释第一点",
            language="vi",
            history=[
                {"role": "user", "content": "DeepSeek‑V3.2 有哪些突出的技术特性？"},
                {"role": "assistant", "content": "DeepSeek‑V3.2 有 3 个突出的技术特性：\n1. DeepSeek Sparse Attention (DSA) — 高效的 attention 机制\n2. Scalable RL framework — 可扩展的强化学习框架（用于 post-training）\n3. Agentic Task Synthesis — 为 agent 生成数据的流水线"},
            ],
            expected_keywords=["DSA", "Sparse Attention", "lightning", "indexer"],
        ),
        # ── 引用质量 ──
        TestCase(
            id="CITE-01",
            category="citation",
            question="新莱应材 在 2025 年进行了哪些并购交易及其价值是多少？",
            language="vi",
            expected_keywords=["DataStream", "Singapore", "45"],
        ),
    ]
    return cases


# ── 基于规则的指标（无需 LLM） ────────────────────────────────────

def eval_keyword_coverage(tc: TestCase) -> MetricResult:
    """检查预期关键词是否出现在回答中。"""
    if not tc.expected_keywords:
        return MetricResult("keyword_coverage", 1.0, True, "No keywords to check")

    found = 0
    missing = []
    for kw in tc.expected_keywords:
        if kw.lower() in tc.answer.lower():
            found += 1
        else:
            missing.append(kw)

    score = found / len(tc.expected_keywords) if tc.expected_keywords else 1.0
    passed = score >= 0.5  # 至少命中一半关键词
    reason = f"{found}/{len(tc.expected_keywords)} keywords found"
    if missing:
        reason += f". Missing: {missing}"
    return MetricResult("keyword_coverage", score, passed, reason)


def eval_refusal_accuracy(tc: TestCase) -> MetricResult:
    """检查系统是否正确拒绝（或没有拒绝）回答。

    区分两种情况：
    - 完全拒绝：整个回答都是拒绝（例如 "Tài liệu không chứa thông tin này."）
    - 部分缺口说明：回答提供数据，但说明存在部分缺口（可接受）
    """
        refusal_phrases = [
            "不包含信息",
            "没有相关信息",
            "文档不",
            "not contain",
            "no relevant information",
        ]
    answer_lower = tc.answer.lower()

    # 统计拒绝短语出现次数
        refusal_hits = sum(1 for p in refusal_phrases if p in answer_lower)

    # 检查回答是否主要是拒绝（简短 + 包含拒绝短语）
    word_count = len(tc.answer.split())
    is_full_refusal = refusal_hits > 0 and word_count < 20
    # 部分缺口：回答有实质内容 + 说明存在缺口
    is_partial_gap = refusal_hits > 0 and word_count >= 20

    if tc.expected_refuse:
        if refusal_hits > 0:
            return MetricResult("refusal_accuracy", 1.0, True, "Correctly refused")
        else:
            return MetricResult("refusal_accuracy", 0.0, False,
                                "Should have refused but answered")
    else:
        if is_full_refusal:
            return MetricResult("refusal_accuracy", 0.0, False,
                                "Over-refusal: entire answer is a refusal")
        elif is_partial_gap:
            # 回答提供部分数据但说明缺口——这是可接受的行为
            return MetricResult("refusal_accuracy", 0.8, True,
                                "Partial answer with noted gaps (acceptable)")
        else:
            return MetricResult("refusal_accuracy", 1.0, True, "Correctly answered")


def eval_phantom_citations(tc: TestCase) -> MetricResult:
    """检查拒绝回答时是否出现幻觉引用。

    仅在以下情况标记为幻觉引用：
    - 回答是完全拒绝（简短、无实质内容）且带引用
    - 或拒绝句本身包含引用（例如 "Không có thông tin [1]"）

    如果回答提供了带引用的有用数据并说明部分缺口，则不标记。
    """
    refusal_phrases = ["không chứa", "không có thông tin", "not contain", "no information"]
    answer_lower = tc.answer.lower()
    word_count = len(tc.answer.split())

    # 完全拒绝且带引用 = 幻觉引用
        is_full_refusal = any(p in answer_lower for p in refusal_phrases) and word_count < 20
    all_citations = re.findall(r'\[(?:IMG-)?\d+\]', tc.answer)

    if is_full_refusal and all_citations:
        return MetricResult("no_phantom_citations", 0.0, False,
                            f"Phantom citations on full refusal: {all_citations}")

    # 专门检查拒绝句中是否包含引用
    sentences = re.split(r'[.!?\n]', tc.answer)
    phantom_in_sentence = []
    for sent in sentences:
        sent_lower = sent.lower().strip()
        if any(p in sent_lower for p in refusal_phrases):
            sent_citations = re.findall(r'\[(?:IMG-)?\d+\]', sent)
            if sent_citations:
                phantom_in_sentence.extend(sent_citations)

    if phantom_in_sentence:
        return MetricResult("no_phantom_citations", 0.3, False,
                            f"Citations in refusal sentences: {phantom_in_sentence}")

    return MetricResult("no_phantom_citations", 1.0, True, "No phantom citations")


def eval_citation_format(tc: TestCase) -> MetricResult:
    """检查引用格式：[1] [2]，而不是 [1, 2] 或 [1][2]。"""
    # 检查分组引用（错误格式：[1, 2] 或 [1,2]）
    grouped = re.findall(r'\[\d+[,\s]+\d+\]', tc.answer)
    if grouped:
        return MetricResult("citation_format", 0.0, False,
                            f"Grouped citations found: {grouped}")
    return MetricResult("citation_format", 1.0, True, "Citations properly formatted")


def eval_token_artifacts(tc: TestCase) -> MetricResult:
    """检查 <unusedNNN> 之类的 Gemini token 残留。"""
    artifacts = re.findall(r'<unused\d+>:?\s*', tc.answer)
    if artifacts:
        return MetricResult("no_token_artifacts", 0.0, False,
                            f"Token artifacts: {artifacts}")
    return MetricResult("no_token_artifacts", 1.0, True, "No token artifacts")


def eval_language_match(tc: TestCase) -> MetricResult:
    """检查回答语言是否与问题语言匹配。"""
    # 简单启发式：越南语包含大量变音符号
    vn_chars = set("áàảãạăắằẳẵặâấầẩẫậéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵđ")
    vn_count = sum(1 for c in tc.answer.lower() if c in vn_chars)
    total_alpha = sum(1 for c in tc.answer if c.isalpha())

    if total_alpha == 0:
        return MetricResult("language_match", 1.0, True, "No text to check")

    vn_ratio = vn_count / total_alpha

    if tc.language == "vi":
        # 越南语问题应得到越南语回答
        # 允许少量英语（技术术语），但越南语字符占比至少 5%
        if vn_ratio > 0.03:
            return MetricResult("language_match", 1.0, True,
                                f"Vietnamese content detected ({vn_ratio:.1%})")
        else:
            return MetricResult("language_match", 0.0, False,
                                f"Expected Vietnamese but got mostly English ({vn_ratio:.1%})")
    else:
        return MetricResult("language_match", 1.0, True, "English response OK")


def eval_answer_completeness(tc: TestCase) -> MetricResult:
    """检查回答是否有实质内容（非拒绝用例中不能只是一句拒绝）。"""
    if tc.expected_refuse:
        return MetricResult("answer_completeness", 1.0, True, "Refusal case — skip")

    word_count = len(tc.answer.split())
    if word_count < 10:
        return MetricResult("answer_completeness", 0.2, False,
                            f"Answer too short ({word_count} words)")
    elif word_count < 30:
        return MetricResult("answer_completeness", 0.6, True,
                            f"Brief answer ({word_count} words)")
    else:
        return MetricResult("answer_completeness", 1.0, True,
                            f"Detailed answer ({word_count} words)")


def eval_context_utilization(tc: TestCase) -> MetricResult:
    """检查检索到的上下文是否真的被回答引用。"""
    if tc.expected_refuse or tc.source_count == 0:
        return MetricResult("context_utilization", 1.0, True, "Skip — refusal or no sources")

    citations = re.findall(r'\[(\d+)\]', tc.answer)
    cited_indices = set(int(c) for c in citations)
    if not cited_indices:
        return MetricResult("context_utilization", 0.0, False,
                            "Answer uses sources but cites none")

    ratio = len(cited_indices) / max(tc.source_count, 1)
    score = min(ratio, 1.0)
    return MetricResult("context_utilization", score,
                        score >= 0.2,
                        f"Cited {len(cited_indices)}/{tc.source_count} sources")


# ── 通过 DeepEval 使用 LLM 作为裁判的指标 ─────────────────────────────────────

def get_deepeval_model(judge: str):
    """获取用于裁判 LLM 的 DeepEval 模型包装器。"""
    if judge == "gemini":
        # 通过 google-genai 使用 Gemini
        from deepeval.models import DeepEvalBaseLLM

        class GeminiJudge(DeepEvalBaseLLM):
            def __init__(self):
                self.model_name = "gemini-2.0-flash"

            def load_model(self):
                from google import genai
                import os
                return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

            def generate(self, prompt: str, schema=None) -> str:
                client = self.load_model()
                resp = client.models.generate_content(
                    model=self.model_name, contents=prompt
                )
                return resp.text

            async def a_generate(self, prompt: str, schema=None) -> str:
                return self.generate(prompt, schema)

            def get_model_name(self):
                return self.model_name

        return GeminiJudge()

    elif judge == "ollama":
        from deepeval.models import DeepEvalBaseLLM
        import requests as req

        class OllamaJudge(DeepEvalBaseLLM):
            def __init__(self, model="gemma3:12b", host="http://localhost:11434"):
                self.model_name = model
                self.host = host

            def load_model(self):
                return None

            def generate(self, prompt: str, schema=None) -> str:
                resp = req.post(
                    f"{self.host}/api/generate",
                    json={"model": self.model_name, "prompt": prompt, "stream": False},
                    timeout=120,
                )
                resp.raise_for_status()
                return resp.json().get("response", "")

            async def a_generate(self, prompt: str, schema=None) -> str:
                return self.generate(prompt, schema)

            def get_model_name(self):
                return self.model_name

        return OllamaJudge()

    else:
        raise ValueError(f"Unknown judge: {judge}")


def run_deepeval_metrics(tc: TestCase, judge_model) -> list[MetricResult]:
    """在测试用例上运行 DeepEval 的 LLM 裁判指标。"""
    results = []

    if tc.expected_refuse:
        return results  # 跳过拒绝用例的 LLM 指标

    if not tc.retrieved_contexts:
        return results

    try:
        from deepeval.test_case import LLMTestCase
        from deepeval.metrics import (
            FaithfulnessMetric,
            AnswerRelevancyMetric,
            ContextualRelevancyMetric,
        )

        deepeval_tc = LLMTestCase(
            input=tc.question,
            actual_output=tc.answer,
            retrieval_context=tc.retrieved_contexts[:5],  # 限制数量以避免 token 溢出
        )

        metrics = [
            ("faithfulness", FaithfulnessMetric(model=judge_model, threshold=0.7)),
            ("answer_relevancy", AnswerRelevancyMetric(model=judge_model, threshold=0.7)),
            ("context_relevancy", ContextualRelevancyMetric(model=judge_model, threshold=0.5)),
        ]

        for name, metric in metrics:
            try:
                metric.measure(deepeval_tc)
                results.append(MetricResult(
                    name=name,
                    score=metric.score or 0.0,
                    passed=metric.is_successful(),
                    reason=str(metric.reason)[:200] if metric.reason else "",
                ))
            except Exception as e:
                results.append(MetricResult(
                    name=name, score=0.0, passed=False,
                    reason=f"Error: {str(e)[:150]}",
                ))

    except Exception as e:
        results.append(MetricResult(
            name="deepeval_error", score=0.0, passed=False,
            reason=f"DeepEval setup error: {str(e)[:200]}",
        ))

    return results


# ── 主评估运行器 ────────────────────────────────────────────────

def call_debug_chat(workspace_id: int, tc: TestCase) -> dict:
    """调用 debug-chat 端点并返回完整响应。"""
    payload = {"message": tc.question}
    if tc.history:
        payload["history"] = tc.history

    start = time.time()
    r = requests.post(
        f"{BASE_URL}/debug-chat/{workspace_id}",
        json=payload,
        timeout=TIMEOUT,
    )
    latency = (time.time() - start) * 1000
    r.raise_for_status()
    data = r.json()
    data["_latency_ms"] = latency
    return data


def evaluate_test_case(tc: TestCase, judge_model=None) -> TestResult:
    """在单个测试用例上运行全部指标。"""
    # 基于规则的指标（始终运行）
    rule_metrics = [
        eval_keyword_coverage(tc),
        eval_refusal_accuracy(tc),
        eval_phantom_citations(tc),
        eval_citation_format(tc),
        eval_token_artifacts(tc),
        eval_language_match(tc),
        eval_answer_completeness(tc),
        eval_context_utilization(tc),
    ]

    # LLM 裁判指标（可选）
    llm_metrics = []
    if judge_model and not tc.expected_refuse and tc.retrieved_contexts:
        llm_metrics = run_deepeval_metrics(tc, judge_model)

    all_metrics = rule_metrics + llm_metrics

    # 总体分数 = 加权平均
    scores = [m.score for m in all_metrics if m.score >= 0]
    overall = sum(scores) / len(scores) if scores else 0.0

    return TestResult(
        test_id=tc.id,
        category=tc.category,
        question=tc.question[:60] + "..." if len(tc.question) > 60 else tc.question,
        language=tc.language,
        answer_preview=tc.answer[:80] + "..." if len(tc.answer) > 80 else tc.answer,
        source_count=tc.source_count,
        latency_ms=tc.latency_ms,
        metrics=all_metrics,
        overall_score=overall,
    )


def print_results_table(results: list[TestResult], show_llm: bool = False):
    """以格式化表格打印详细评估结果。"""

    # ── 按测试用例的结果 ──
    print("\n" + "=" * 120)
    print("DETAILED RESULTS")
    print("=" * 120)

    for r in results:
        status = "PASS" if r.overall_score >= 0.7 else "PARTIAL" if r.overall_score >= 0.5 else "FAIL"
        icon = "✓" if status == "PASS" else "~" if status == "PARTIAL" else "✗"

        print(f"\n{icon} [{r.test_id}] ({r.category}) score={r.overall_score:.2f} | {r.latency_ms:.0f}ms | {r.source_count} sources")
        print(f"  Q: {r.question}")
        print(f"  A: {r.answer_preview}")

        for m in r.metrics:
            m_icon = "✓" if m.passed else "✗"
            suffix = f" — {m.reason}" if m.reason and not m.passed else ""
            if not m.passed or m.score < 1.0:
                print(f"    {m_icon} {m.name}: {m.score:.2f}{suffix}")

    # ── 按类别汇总 ──
    print("\n" + "=" * 120)
    print("SUMMARY BY CATEGORY")
    print("=" * 120)

    categories = {}
    for r in results:
        categories.setdefault(r.category, []).append(r)

    print(f"\n{'Category':<22} {'Tests':>5} {'Pass':>5} {'Avg Score':>10} {'Avg Latency':>12}")
    print("-" * 60)

    for cat, cat_results in sorted(categories.items()):
        total = len(cat_results)
        passed = sum(1 for r in cat_results if r.overall_score >= 0.7)
        avg_score = sum(r.overall_score for r in cat_results) / total
        avg_latency = sum(r.latency_ms for r in cat_results) / total
        print(f"{cat:<22} {total:>5} {passed:>5} {avg_score:>9.2f} {avg_latency:>10.0f}ms")

    # ── 按指标汇总 ──
    print("\n" + "=" * 120)
    print("SUMMARY BY METRIC")
    print("=" * 120)

    metric_scores: dict[str, list[float]] = {}
    metric_passes: dict[str, list[bool]] = {}
    for r in results:
        for m in r.metrics:
            metric_scores.setdefault(m.name, []).append(m.score)
            metric_passes.setdefault(m.name, []).append(m.passed)

    print(f"\n{'Metric':<25} {'Avg Score':>10} {'Pass Rate':>10} {'Count':>6}")
    print("-" * 55)

    for name in sorted(metric_scores.keys()):
        scores = metric_scores[name]
        passes = metric_passes[name]
        avg = sum(scores) / len(scores)
        pass_rate = sum(passes) / len(passes)
        print(f"{name:<25} {avg:>9.2f} {pass_rate:>9.0%} {len(scores):>6}")

    # ── 总体 ──
    print("\n" + "=" * 120)
    all_scores = [r.overall_score for r in results]
    avg_overall = sum(all_scores) / len(all_scores)
    pass_count = sum(1 for s in all_scores if s >= 0.7)
    total_tests = len(results)

    print(f"OVERALL SCORE: {avg_overall:.2f} | PASS: {pass_count}/{total_tests} | "
          f"AVG LATENCY: {sum(r.latency_ms for r in results) / total_tests:.0f}ms")
    print("=" * 120)

    # ── 最终结论 ──
    if avg_overall >= 0.85:
        print("\nVerdict: EXCELLENT — Production-ready quality")
    elif avg_overall >= 0.7:
        print("\nVerdict: GOOD — Acceptable for production with minor improvements")
    elif avg_overall >= 0.5:
        print("\nVerdict: FAIR — Needs improvement before production")
    else:
        print("\nVerdict: POOR — Significant issues to address")


def main():
    parser = argparse.ArgumentParser(description="MYRAG Evaluation")
    parser.add_argument("--workspace", type=int, default=11, help="Workspace ID")
    parser.add_argument("--judge", choices=["ollama", "gemini", "none"], default="none",
                        help="LLM judge for DeepEval metrics (default: none = rule-based only)")
    parser.add_argument("--test-ids", nargs="*", help="Run specific test IDs only")
    args = parser.parse_args()

    print(f"MYRAG Evaluation — Workspace {args.workspace}")
    print(f"Judge: {args.judge}")
    print(f"Endpoint: {BASE_URL}")

    # 确认服务器正在运行
    try:
        r = requests.get("http://localhost:8080/health", timeout=5)
        r.raise_for_status()
        print("Server: OK\n")
    except Exception:
        print("ERROR: Server not reachable at localhost:8080")
        sys.exit(1)

    # 构建测试用例
    test_cases = build_test_cases(args.workspace)
    if args.test_ids:
        test_cases = [tc for tc in test_cases if tc.id in args.test_ids]

    print(f"Running {len(test_cases)} test cases...\n")

    # 设置裁判模型（如果指定）
    judge_model = None
    if args.judge != "none":
        try:
            judge_model = get_deepeval_model(args.judge)
            print(f"Judge model: {judge_model.get_model_name()}")
        except Exception as e:
            print(f"WARNING: Failed to init judge model: {e}")
            print("Falling back to rule-based only.\n")

    # 运行评估
    results: list[TestResult] = []
    for i, tc in enumerate(test_cases):
        print(f"[{i+1}/{len(test_cases)}] {tc.id}: {tc.question[:50]}...", end=" ", flush=True)

        try:
            data = call_debug_chat(args.workspace, tc)
            tc.answer = data.get("answer", "")
            tc.source_count = data.get("total_sources", 0)
            tc.latency_ms = data.get("_latency_ms", 0)

            # 提取检索上下文，供 DeepEval 使用
            tc.retrieved_contexts = [
                s.get("content_preview", "")
                for s in data.get("retrieved_sources", [])
            ]

            result = evaluate_test_case(tc, judge_model)
            results.append(result)

            icon = "✓" if result.overall_score >= 0.7 else "✗"
            print(f"{icon} {result.overall_score:.2f}")

        except Exception as e:
            print(f"ERROR: {e}")
            results.append(TestResult(
                test_id=tc.id, category=tc.category,
                question=tc.question[:60], language=tc.language,
                answer_preview=f"ERROR: {e}", source_count=0,
                latency_ms=0, overall_score=0.0,
            ))

    # 打印结果
    print_results_table(results, show_llm=(args.judge != "none"))

    # 保存 JSON 结果
    output_path = Path(__file__).parent / "eval_results.json"
    json_results = []
    for r in results:
        json_results.append({
            "test_id": r.test_id,
            "category": r.category,
            "question": r.question,
            "language": r.language,
            "overall_score": r.overall_score,
            "source_count": r.source_count,
            "latency_ms": r.latency_ms,
            "metrics": [{"name": m.name, "score": m.score, "passed": m.passed, "reason": m.reason} for m in r.metrics],
        })
    output_path.write_text(json.dumps(json_results, indent=2, ensure_ascii=False))
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
