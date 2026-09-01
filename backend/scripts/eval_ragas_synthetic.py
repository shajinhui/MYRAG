"""
MYRAG 第 3 阶段 —— RAGAS 合成测试集生成 + 评估。

工作流：
  1. 通过 API 从工作区提取文档分块
  2. 使用 RAGAS TestsetGenerator 生成带标准答案的合成问答对
  3. 将每个问题发送到 MYRAG 聊天端点
  4. 使用 RAGAS 基于参考的指标 + 自定义规则指标评估
  5. 输出详细评分表

用法：
    cd MYRAG/backend
    source ../venv/bin/activate

    # 第 1 步：生成测试集（需要 Gemini API 密钥）
    python scripts/eval_ragas_synthetic.py generate \
        --workspace 11 --size 50 \
        --gemini-key "YOUR_KEY"

    # 第 2 步：评估已生成的测试集
    python scripts/eval_ragas_synthetic.py evaluate \
        --workspace 11 \
        --testset scripts/ragas_testset.json

    # 一步完成：生成 + 评估
    python scripts/eval_ragas_synthetic.py all \
        --workspace 11 --size 50 \
        --gemini-key "YOUR_KEY"
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests


# ── 配置 ────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8080/api/v1/rag"
TIMEOUT = 120
SCRIPTS_DIR = Path(__file__).parent


# ── 第 1 步：从工作区提取分块 ────────────────────────────────────

def fetch_workspace_documents(workspace_id: int) -> list[dict]:
    """通过 stats 与 chunks 端点获取工作区中的文档列表。"""
    print(f"\n[1/4] Fetching documents from workspace {workspace_id}...")

    # 获取工作区统计信息，以了解文档数量
    stats = requests.get(f"{BASE_URL}/stats/{workspace_id}", timeout=10).json()
    print(f"  Workspace has {stats['total_documents']} documents, "
          f"{stats['indexed_documents']} indexed, {stats['total_chunks']} total chunks")

    # 我们需要知道文档 ID。逐个查询可能的文档。
    # 对于工作区 11：文档 11 和 12
    all_chunks = []

    # 在工作区附近尝试一段范围的文档 ID
    # 更稳妥的方式是直接查询数据库，但 API 更简单
    doc_ids_found = []
    for doc_id in range(1, 200):
        try:
            r = requests.get(f"{BASE_URL}/chunks/{doc_id}", timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("chunks") and data.get("status") == "INDEXED":
                    doc_ids_found.append(doc_id)
                    for chunk in data["chunks"]:
                        content = chunk.get("content", "")
                        if content and len(content.strip()) > 20:
                            all_chunks.append({
                                "content": content,
                                "document_id": doc_id,
                                "chunk_id": chunk.get("chunk_id", ""),
                                "metadata": chunk.get("metadata", {}),
                            })
                    print(f"  Doc {doc_id}: {len(data['chunks'])} chunks loaded")

            # 找到足够多的文档后提前停止
            if len(doc_ids_found) >= stats["indexed_documents"]:
                break
        except Exception:
            continue

    print(f"  Total: {len(all_chunks)} usable chunks from {len(doc_ids_found)} documents")
    return all_chunks


def fetch_workspace_chunks_fast(workspace_id: int, doc_ids: list[int]) -> list[dict]:
    """获取已知文档 ID 的分块（比扫描更快）。"""
    print(f"\n[1/4] Fetching chunks for documents {doc_ids}...")
    all_chunks = []

    for doc_id in doc_ids:
        r = requests.get(f"{BASE_URL}/chunks/{doc_id}", timeout=10)
        r.raise_for_status()
        data = r.json()

        for chunk in data.get("chunks", []):
            content = chunk.get("content", "")
            if content and len(content.strip()) > 20:
                all_chunks.append({
                    "content": content,
                    "document_id": doc_id,
                    "chunk_id": chunk.get("chunk_id", ""),
                    "metadata": chunk.get("metadata", {}),
                })
        print(f"  Doc {doc_id}: {len(data.get('chunks', []))} chunks")

    print(f"  Total: {len(all_chunks)} usable chunks")
    return all_chunks


# ── 第 2 步：使用 RAGAS 生成合成测试集 ────────────────────────────

GENERATION_PROMPT = """\
You are a RAG evaluation expert. Given document chunks below, generate {batch_size} diverse \
question-answer pairs that test a RAG system's ability to retrieve and synthesize information.

REQUIREMENTS:
- Generate questions in the SAME language as the chunk content
- Each Q&A must be answerable from the provided chunks
- Include a mix of:
  * Simple factual questions (single chunk)
  * Multi-hop questions (require combining 2+ chunks)
  * Table/numeric data extraction
  * Comparison/analysis questions
- The "reference" answer must be accurate and grounded in the chunks
- The "reference_contexts" list the chunk indices used (0-based)
- Each "synthesizer_name" should be one of: single_hop_factual, multi_hop_reasoning, \
table_extraction, comparison_analysis

CHUNKS:
{chunks_text}

OUTPUT FORMAT — return ONLY a JSON array, no markdown:
[
  {{
    "user_input": "the question",
    "reference": "the ideal ground-truth answer",
    "reference_contexts": [0, 3],
    "synthesizer_name": "single_hop_factual"
  }},
  ...
]

Generate exactly {batch_size} items. Return ONLY the JSON array.
"""


def generate_testset(
    chunks: list[dict],
    testset_size: int,
    gemini_key: str,
) -> list[dict]:
    """
    直接使用 Gemini 生成合成问答对。
    分批处理分块，以应对上下文窗口限制。
    """
    print(f"\n[2/4] Generating {testset_size} synthetic Q&A pairs with Gemini...")

    from google import genai

    client = genai.Client(api_key=gemini_key)
    print("  LLM: Gemini 2.0 Flash (direct generation)")

    # 按文档分组，确保多样性
    doc_chunks: dict[int, list[dict]] = {}
    for c in chunks:
        doc_id = c.get("document_id", 0)
        doc_chunks.setdefault(doc_id, []).append(c)

    all_samples = []
    samples_per_batch = 10
    batch_num = 0

    start_time = time.time()

    while len(all_samples) < testset_size:
        remaining = testset_size - len(all_samples)
        batch_size = min(samples_per_batch, remaining)
        batch_num += 1

        # 为该批次选择分块 —— 在文档之间轮换
        selected_chunks = []
        for doc_id, doc_chunk_list in doc_chunks.items():
            # 从每个文档取一个分块窗口
            start_idx = ((batch_num - 1) * 5) % len(doc_chunk_list)
            for i in range(min(8, len(doc_chunk_list))):
                idx = (start_idx + i) % len(doc_chunk_list)
                selected_chunks.append(doc_chunk_list[idx])

        # 构建分块文本
        chunks_text = ""
        for i, c in enumerate(selected_chunks):
            content = c["content"][:800]  # 截断过长的分块
            chunks_text += f"\n--- Chunk {i} (doc {c.get('document_id', '?')}) ---\n{content}\n"

        prompt = GENERATION_PROMPT.format(
            batch_size=batch_size,
            chunks_text=chunks_text,
        )

        print(f"  Batch {batch_num}: generating {batch_size} samples from "
              f"{len(selected_chunks)} chunks...", end=" ", flush=True)

        try:
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            text = resp.text.strip()

            # 清理可能存在的 markdown 代码围栏
            if text.startswith("```"):
                text = re.sub(r'^```(?:json)?\s*', '', text)
                text = re.sub(r'\s*```$', '', text)

            batch_items = json.loads(text)

            for item in batch_items:
                if not item.get("user_input") or not item.get("reference"):
                    continue
                # 将 reference_contexts 从索引映射为实际分块内容
                ctx_indices = item.get("reference_contexts", [])
                ref_contexts = []
                for idx in ctx_indices:
                    if isinstance(idx, int) and 0 <= idx < len(selected_chunks):
                        ref_contexts.append(selected_chunks[idx]["content"][:500])

                all_samples.append({
                    "id": f"RAGAS-{len(all_samples)+1:03d}",
                    "user_input": item["user_input"],
                    "reference": item["reference"],
                    "reference_contexts": ref_contexts,
                    "synthesizer_name": item.get("synthesizer_name", "unknown"),
                })

            print(f"OK ({len(batch_items)} items)")

        except Exception as e:
            print(f"ERROR: {e}")

        # 遵守速率限制
        time.sleep(2)

    elapsed = time.time() - start_time
    print(f"  Generated {len(all_samples)} samples in {elapsed:.0f}s")

    return all_samples[:testset_size]


# ── 第 3 步：让 MYRAG 聊天处理测试集 ─────────────────────────────────

def run_testset_through_chat(
    workspace_id: int,
    samples: list[dict],
) -> list[dict]:
    """将每个问题发送到 debug-chat 端点并收集响应。"""
    print(f"\n[3/4] Running {len(samples)} questions through MYRAG chat...")

    results = []
    for i, sample in enumerate(samples):
        question = sample["user_input"]
        if not question.strip():
            print(f"  [{i+1}/{len(samples)}] SKIP (empty question)")
            continue

        print(f"  [{i+1}/{len(samples)}] {question[:60]}...", end=" ", flush=True)

        try:
            start = time.time()
            r = requests.post(
                f"{BASE_URL}/debug-chat/{workspace_id}",
                json={"message": question},
                timeout=TIMEOUT,
            )
            latency = (time.time() - start) * 1000
            r.raise_for_status()
            data = r.json()

            answer = data.get("answer", "")
            retrieved_sources = data.get("retrieved_sources", [])
            retrieved_contexts = [
                s.get("content_preview", "") for s in retrieved_sources
            ]

            results.append({
                **sample,
                "response": answer,
                "retrieved_contexts_actual": retrieved_contexts,
                "source_count": len(retrieved_sources),
                "latency_ms": latency,
            })
            print(f"OK ({latency:.0f}ms)")

        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                **sample,
                "response": f"ERROR: {e}",
                "retrieved_contexts_actual": [],
                "source_count": 0,
                "latency_ms": 0,
            })

    return results


# ── 第 4 步：使用 RAGAS 指标 + 规则评估 ─────────────────────────

def evaluate_with_ragas(
    results: list[dict],
    gemini_key: Optional[str] = None,
) -> list[dict]:
    """
    使用以下指标评估：
    - RAGAS 基于参考：AnswerCorrectness、Faithfulness、ContextRecall
    - 基于规则：citation_format、token_artifacts、language_match
    """
    print(f"\n[4/4] Evaluating {len(results)} samples...")

    # ── 基于规则的指标 ──
    for r in results:
        answer = r.get("response", "")
        r["metrics"] = {}

        # 引用格式
        grouped = re.findall(r'\[\d+[,\s]+\d+\]', answer)
        r["metrics"]["citation_format"] = 1.0 if not grouped else 0.0

        # Token 残留
        artifacts = re.findall(r'<unused\d+>:?\s*', answer)
        r["metrics"]["no_token_artifacts"] = 1.0 if not artifacts else 0.0

        # 回答长度 —— 事实问答可以较短，因此降低标准（10 词 = 1.0）
        word_count = len(answer.split())
        if word_count >= 10:
            r["metrics"]["answer_substance"] = 1.0
        elif word_count > 0:
            r["metrics"]["answer_substance"] = word_count / 10.0
        else:
            r["metrics"]["answer_substance"] = 0.0

        # 上下文利用率 —— 已引用来源与检索来源的比值
        # 对于单一事实回答，引用 8 个来源中的 1 个即可
        citations = re.findall(r'\[(\d+)\]', answer)
        cited = len(set(citations))
        source_count = r.get("source_count", 0)
        if source_count == 0:
            r["metrics"]["context_utilization"] = 1.0
        elif cited > 0:
            # 评分：cited >= 3 或 cited/sources >= 0.5 时为 1.0
            ratio = cited / source_count
            r["metrics"]["context_utilization"] = min(max(ratio, cited / 3.0), 1.0)
        else:
            r["metrics"]["context_utilization"] = 0.0

    # ── RAGAS 基于 LLM 的指标 ──
    if gemini_key:
        print("  Running RAGAS LLM metrics (Faithfulness, AnswerCorrectness, ContextRecall)...")
        os.environ["GOOGLE_API_KEY"] = gemini_key

        try:
            from ragas import evaluate as ragas_evaluate, EvaluationDataset
            from ragas.llms import llm_factory
            from ragas.metrics import (
                Faithfulness,
                ResponseRelevancy,
                LLMContextRecall,
                FactualCorrectness,
            )

            from google import genai
            client = genai.Client(api_key=gemini_key)
            evaluator_llm = llm_factory(
                "gemini-2.0-flash",
                provider="google",
                client=client,
            )

            # 构建 EvaluationDataset
            eval_samples = []
            for r in results:
                if r.get("response", "").startswith("ERROR"):
                    continue
                sample_dict = {
                    "user_input": r["user_input"],
                    "response": r["response"],
                    "retrieved_contexts": r.get("retrieved_contexts_actual", []),
                }
                # 为基于参考的指标添加标准答案
                if r.get("reference"):
                    sample_dict["reference"] = r["reference"]
                eval_samples.append(sample_dict)

            if not eval_samples:
                print("  No valid samples for RAGAS evaluation")
                return results

            eval_dataset = EvaluationDataset.from_list(eval_samples)

            # 根据是否拥有参考来选择指标
            has_references = any(s.get("reference") for s in eval_samples)
            metrics = [Faithfulness(llm=evaluator_llm)]

            if has_references:
                metrics.extend([
                    LLMContextRecall(llm=evaluator_llm),
                    FactualCorrectness(llm=evaluator_llm),
                ])
                print(f"  Metrics: Faithfulness, ContextRecall, FactualCorrectness "
                      f"({len(eval_samples)} samples with reference)")
            else:
                print(f"  Metrics: Faithfulness only ({len(eval_samples)} samples, no reference)")

            ragas_result = ragas_evaluate(
                dataset=eval_dataset,
                metrics=metrics,
                llm=evaluator_llm,
            )

            # 将 RAGAS 分数合并回结果
            df = ragas_result.to_pandas()
            valid_idx = 0
            for r in results:
                if r.get("response", "").startswith("ERROR"):
                    continue
                if valid_idx < len(df):
                    row = df.iloc[valid_idx]
                    for col in df.columns:
                        if col not in ("user_input", "response", "retrieved_contexts", "reference"):
                            val = row[col]
                            if isinstance(val, (int, float)) and not (val != val):  # 不是 NaN
                                r["metrics"][col] = float(val)
                    valid_idx += 1

            print(f"  RAGAS evaluation complete. Aggregate scores:")
            try:
                # 先尝试类似字典的访问方式
                scores_dict = ragas_result.scores if hasattr(ragas_result, 'scores') else {}
                if not scores_dict and hasattr(ragas_result, 'to_pandas'):
                    agg = ragas_result.to_pandas().select_dtypes(include='number').mean()
                    scores_dict = agg.to_dict()
                for metric_name, score in scores_dict.items():
                    if isinstance(score, (int, float)):
                        print(f"    {metric_name}: {score:.3f}")
            except Exception:
                print("    (aggregate scores unavailable)")

        except Exception as e:
            print(f"  WARNING: RAGAS evaluation failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("  Skipping RAGAS LLM metrics (no Gemini key). Rule-based only.")

    return results


# ── 输出格式化 ────────────────────────────────────────────────────────

def print_evaluation_report(results: list[dict]):
    """打印格式化评估报告。"""
    print("\n" + "=" * 120)
    print("RAGAS SYNTHETIC TESTSET — EVALUATION REPORT")
    print("=" * 120)

    # ── 逐样本详情 ──
    for r in results:
        metrics = r.get("metrics", {})
        avg_score = sum(metrics.values()) / len(metrics) if metrics else 0
        icon = "✓" if avg_score >= 0.7 else "~" if avg_score >= 0.5 else "✗"

        print(f"\n{icon} [{r['id']}] score={avg_score:.2f} | {r.get('latency_ms', 0):.0f}ms | "
              f"{r.get('source_count', 0)} sources | synth={r.get('synthesizer_name', '?')}")
        print(f"  Q: {r['user_input'][:80]}")
        print(f"  A: {r['response'][:80]}..." if len(r.get('response', '')) > 80 else f"  A: {r.get('response', '')}")
        if r.get("reference"):
            print(f"  Ref: {r['reference'][:80]}...")

        # 显示未通过的指标
        for name, score in sorted(metrics.items()):
            if score < 0.7:
                print(f"    ✗ {name}: {score:.2f}")

    # ── 聚合指标 ──
    print("\n" + "=" * 120)
    print("AGGREGATE METRICS")
    print("=" * 120)

    all_metric_names = set()
    for r in results:
        all_metric_names.update(r.get("metrics", {}).keys())

    print(f"\n{'Metric':<30} {'Avg Score':>10} {'Pass Rate':>10} {'Samples':>8}")
    print("-" * 62)

    metric_avgs = {}
    for name in sorted(all_metric_names):
        scores = [r["metrics"][name] for r in results if name in r.get("metrics", {})]
        if scores:
            avg = sum(scores) / len(scores)
            pass_rate = sum(1 for s in scores if s >= 0.7) / len(scores)
            metric_avgs[name] = avg
            print(f"{name:<30} {avg:>9.3f} {pass_rate:>9.0%} {len(scores):>8}")

    # ── 按合成器类型 ──
    print("\n" + "=" * 120)
    print("BY SYNTHESIZER TYPE")
    print("=" * 120)

    synth_groups = {}
    for r in results:
        synth = r.get("synthesizer_name", "unknown")
        synth_groups.setdefault(synth, []).append(r)

    print(f"\n{'Synthesizer':<45} {'Count':>6} {'Avg Score':>10}")
    print("-" * 65)

    for synth, group in sorted(synth_groups.items()):
        scores = []
        for r in group:
            metrics = r.get("metrics", {})
            if metrics:
                scores.append(sum(metrics.values()) / len(metrics))
        avg = sum(scores) / len(scores) if scores else 0
        print(f"{synth:<45} {len(group):>6} {avg:>9.3f}")

    # ── 总体 ──
    print("\n" + "=" * 120)
    overall_scores = []
    for r in results:
        metrics = r.get("metrics", {})
        if metrics:
            overall_scores.append(sum(metrics.values()) / len(metrics))

    if overall_scores:
        avg_overall = sum(overall_scores) / len(overall_scores)
        pass_count = sum(1 for s in overall_scores if s >= 0.7)
        total = len(overall_scores)
        avg_latency = sum(r.get("latency_ms", 0) for r in results) / len(results)

        print(f"OVERALL SCORE: {avg_overall:.3f} | PASS: {pass_count}/{total} | "
              f"AVG LATENCY: {avg_latency:.0f}ms")
        print("=" * 120)

        if avg_overall >= 0.85:
            print("\nVerdict: EXCELLENT — Production-ready quality")
        elif avg_overall >= 0.7:
            print("\nVerdict: GOOD — Acceptable for production")
        elif avg_overall >= 0.5:
            print("\nVerdict: FAIR — Needs improvement")
        else:
            print("\nVerdict: POOR — Significant issues")
    else:
        print("No valid results to aggregate")
        print("=" * 120)


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_generate(args):
    """生成合成测试集并保存为 JSON。"""
    gemini_key = args.gemini_key or os.environ.get("GOOGLE_AI_API_KEY", "")
    if not gemini_key:
        print("ERROR: --gemini-key required (or set GOOGLE_AI_API_KEY env var)")
        sys.exit(1)

    # 获取分块
    if args.doc_ids:
        doc_ids = [int(d) for d in args.doc_ids.split(",")]
        chunks = fetch_workspace_chunks_fast(args.workspace, doc_ids)
    else:
        chunks = fetch_workspace_documents(args.workspace)

    if not chunks:
        print("ERROR: No chunks found. Is the workspace indexed?")
        sys.exit(1)

    # 生成
    samples = generate_testset(chunks, args.size, gemini_key)

    # 保存
    output_path = Path(args.output) if args.output else SCRIPTS_DIR / "ragas_testset.json"
    output_path.write_text(json.dumps(samples, indent=2, ensure_ascii=False))
    print(f"\nTestset saved to: {output_path}")
    print(f"  Total samples: {len(samples)}")

    # 显示分布
    synth_counts = {}
    for s in samples:
        synth_counts[s.get("synthesizer_name", "?")] = synth_counts.get(s.get("synthesizer_name", "?"), 0) + 1
    print(f"  Distribution:")
    for synth, count in sorted(synth_counts.items()):
        print(f"    {synth}: {count}")

    return samples


def cmd_evaluate(args):
    """评估之前生成的测试集。"""
    testset_path = Path(args.testset)
    if not testset_path.exists():
        print(f"ERROR: Testset not found: {testset_path}")
        sys.exit(1)

    samples = json.loads(testset_path.read_text())
    print(f"Loaded {len(samples)} samples from {testset_path}")

    # 让聊天处理
    results = run_testset_through_chat(args.workspace, samples)

    # 评估
    gemini_key = args.gemini_key or os.environ.get("GOOGLE_AI_API_KEY", "")
    results = evaluate_with_ragas(results, gemini_key if gemini_key else None)

    # 打印报告
    print_evaluation_report(results)

    # 保存结果
    output_path = SCRIPTS_DIR / "ragas_eval_results.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"\nResults saved to: {output_path}")

    return results


def cmd_all(args):
    """一步完成生成 + 评估。"""
    gemini_key = args.gemini_key or os.environ.get("GOOGLE_AI_API_KEY", "")
    if not gemini_key:
        print("ERROR: --gemini-key required (or set GOOGLE_AI_API_KEY env var)")
        sys.exit(1)

    # 获取分块
    if args.doc_ids:
        doc_ids = [int(d) for d in args.doc_ids.split(",")]
        chunks = fetch_workspace_chunks_fast(args.workspace, doc_ids)
    else:
        chunks = fetch_workspace_documents(args.workspace)

    if not chunks:
        print("ERROR: No chunks found")
        sys.exit(1)

    # 生成
    samples = generate_testset(chunks, args.size, gemini_key)

    # 保存测试集
    testset_path = SCRIPTS_DIR / "ragas_testset.json"
    testset_path.write_text(json.dumps(samples, indent=2, ensure_ascii=False))
    print(f"\nTestset saved to: {testset_path}")

    # 让聊天处理
    results = run_testset_through_chat(args.workspace, samples)

    # 评估
    results = evaluate_with_ragas(results, gemini_key)

    # 打印报告
    print_evaluation_report(results)

    # 保存结果
    output_path = SCRIPTS_DIR / "ragas_eval_results.json"
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"\nResults saved to: {output_path}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="MYRAG Phase 3 — RAGAS Synthetic Testset Generation + Evaluation"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # 公共参数
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", type=int, default=11, help="Workspace ID")
    common.add_argument("--gemini-key", type=str, help="Gemini API key")
    common.add_argument("--doc-ids", type=str, help="Comma-separated doc IDs (e.g., '11,12')")

    # 生成
    gen_parser = subparsers.add_parser("generate", parents=[common], help="Generate synthetic testset")
    gen_parser.add_argument("--size", type=int, default=50, help="Number of Q&A pairs to generate")
    gen_parser.add_argument("--output", type=str, help="Output file path")

    # 评估
    eval_parser = subparsers.add_parser("evaluate", parents=[common], help="Evaluate existing testset")
    eval_parser.add_argument("--testset", type=str, required=True, help="Path to testset JSON")

    # 一步完成
    all_parser = subparsers.add_parser("all", parents=[common], help="Generate + evaluate")
    all_parser.add_argument("--size", type=int, default=50, help="Number of Q&A pairs")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # 确认服务器
    try:
        r = requests.get("http://localhost:8080/health", timeout=5)
        r.raise_for_status()
        print("Server: OK")
    except Exception:
        if args.command != "evaluate":
            print("ERROR: Server not reachable at localhost:8080")
            sys.exit(1)

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "all":
        cmd_all(args)


if __name__ == "__main__":
    main()
