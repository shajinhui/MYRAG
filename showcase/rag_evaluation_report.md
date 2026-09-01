# MYRAG 评测报告

## 概览

通过 3 个阶段评估 RAG 聊天系统的质量，同时使用基于规则的指标和 RAGAS LLM 评判。

**测试工作区**：KBG9（id=11）
- 文档 11：新莱应材 2024 年报（中文，26 个分块，17 页）
- 文档 12：DeepSeek-V3.2 技术论文（英语，57 个分块，23 页）

**技术栈**：BAAI/bge-m3 向量化 → ChromaDB + LightRAG（知识图谱）→ 重排序 bge-reranker-v2-m3

---

## 执行摘要

### 系统概览

| 项目 | 详情 |
|------|--------|
| **系统** | MYRAG —— 检索增强生成聊天系统 |
| **流水线** | BAAI/bge-m3 向量化 → ChromaDB + LightRAG（KG）→ bge-reranker-v2-m3 → LLM |
| **测试语料** | 2 个文档：TechVina 2025 年报（VI，26 分块）+ DeepSeek-V3.2 论文（EN，57 分块） |
| **评测方法** | 阶段 1：16 个手工测试（基于规则）· 阶段 3：30 个 RAGAS 合成测试（LLM 评判） |

### 阶段 1 —— 手工测试（基于规则）

| 类别 | 通过率 | 平均分 | 备注 |
|----------|-----------|-----------|-------|
| 事实提取 | 5/5 | 0.93 | 同时覆盖中文和英语文档 |
| 表格数据 | 2/3 | 0.83 | gemma3:12b 无法处理“Key, Year = Value”格式 |
| 跨文档 | 2/2 | 0.89 | 能综合两个文档作答 |
| 防幻觉 | 3/3 | 1.00 | 正确拒绝超出范围的问题 |
| 历史（多轮） | 2/2 | 0.87 | 追问上下文处理良好 |
| 引用准确性 | 1/1 | 0.85 | 并购交易引用 |
| **总体** | **15/16** | **0.89** | **结论：优秀** |

### 阶段 3 —— RAGAS 合成测试（LLM 评判）

| 指标 | gemma3:12b（本地） | gemini-2.5-flash（API） | 胜出者 |
|--------|-------------------|----------------------|--------|
| **总体得分** | 0.832 | **0.846** | Gemini |
| **通过率** | 25/30（83%） | **26/30（87%）** | Gemini |
| 忠实度 | 0.749 | **0.812** | Gemini（+0.063） |
| 事实正确性 | **0.773** | 0.749 | gemma3（+0.024） |
| 上下文召回 | 0.833 | 0.833 | 平局 |
| 上下文利用率 | 0.472 | **0.533** | Gemini（+0.061） |
| 表格提取 | 0.697 | **0.905** | Gemini（+0.208） |
| 对比分析 | 0.734 | **0.873** | Gemini（+0.139） |
| 平均延迟 | **3076ms** | 3283ms | gemma3（-207ms） |

### 优势与不足

| 方面 | 状态 | 详情 |
|--------|--------|--------|
| 防幻觉 | ✅ 强 | 对超出范围的问题能完美拒绝 |
| 引用格式 | ✅ 强 | 所有测试中格式 100% 正确 |
| 跨文档推理 | ✅ 强 | 能成功综合多个来源作答 |
| 表格解析 | ⚠️ 依赖模型 | gemma3 无法处理复杂表格；Gemini 表现良好 |
| 语言一致性 | ⚠️ 依赖模型 | gemma3 偶尔会用错误语言回答 |
| 检索覆盖 | ❌ 弱 | 5 个用例 context_recall = 0（董事长姓名、流失率、同比增长） |
| 忠实度 | ❌ 弱 | 4 个失败用例 —— LLM 展开回答时添加了无依据的细节 |

### 建议

| 优先级 | 行动 | 预期影响 |
|----------|--------|-----------------|
| 1 | 生产环境切换到 **Gemini 2.5 Flash** | 通过率 +4%、表格准确率 +20%、语言一致性更好 |
| 2 | 改善 context_recall 偏低的检索 | 修复 5 个检索漏掉相关分块的用例 |
| 3 | 关注忠实度 | 减少 4 个失败用例中的过度展开 |

---

## 阶段 1：手工测试用例（基于规则）

**脚本**：`backend/scripts/eval_rag.py`
**LLM**：Ollama gemma3:12b

### 数据集
覆盖 6 个类别的 16 个手工测试用例：

| 类别 | 数量 | 描述 |
|----------|-------|-------------|
| fact_extraction（VI） | 3 | 成立年份、营收、员工规模 |
| fact_extraction（EN） | 2 | 技术特性、竞争情况 |
| table_data | 3 | 财务指标、基准分数 |
| cross_doc | 2 | AI 平台 + DeepSeek 能力 |
| anti_hallucination | 3 | 超出范围的问题（应拒绝回答） |
| history | 2 | 多轮追问 |
| citation | 1 | 并购交易 |

### 指标（8 个基于规则，无 LLM 评判）
- keyword_coverage、refusal_accuracy、phantom_citations、citation_format
- token_artifacts、language_match、answer_completeness、context_utilization

### 结果

```
总体得分：0.89 | 通过：15/16 | 结论：优秀
```

| 类别 | 通过 | 平均分 |
|----------|------|-----------|
| fact_extraction | 5/5 | 0.93 |
| table_data | 2/3 | 0.83 |
| cross_doc | 2/2 | 0.89 |
| anti_hallucination | 3/3 | 1.00 |
| history | 2/2 | 0.87 |
| citation | 1/1 | 0.85 |

**遗留问题**：TABLE-02（毛利/ROE）—— gemma3:12b 无法解析“Key, Year = Value”表格格式。

---

## 阶段 3：RAGAS 合成测试集（LLM 评判）

**脚本**：`backend/scripts/eval_ragas_synthetic.py`
**测试集生成**：Gemini 2.0 Flash（30 对带标准答案的问答）
**RAGAS 评判**：Gemini 2.0 Flash（忠实度、上下文召回、事实正确性）

### 数据集
从文档分块自动生成 30 对问答：

| 合成器类型 | 数量 |
|-----------------|-------|
| single_hop_factual | 23 |
| table_extraction | 3 |
| comparison_analysis | 3 |
| multi_hop_reasoning | 1 |

### 模型对比：gemma3:12b vs gemini-2.5-flash

使用相同的 30 个问题和标准答案，仅更换回答的 LLM。

#### 汇总指标

| 指标 | gemma3:12b | gemini-2.5-flash | 差异 |
|--------|-----------|------------------|-------|
| **总体** | **0.832** | **0.846** | **+0.014** |
| **通过率** | **25/30（83%）** | **26/30（87%）** | **+1** |
| answer_substance | 0.997 | 0.997 | = |
| citation_format | 1.000 | 1.000 | = |
| no_token_artifacts | 1.000 | 1.000 | = |
| context_recall | 0.833 | 0.833 | = |
| faithfulness | 0.749 | **0.812** | **+0.063** |
| factual_correctness | **0.773** | 0.749 | -0.024 |
| context_utilization | 0.472 | **0.533** | **+0.061** |
| 平均延迟 | **3076ms** | 3283ms | +207ms |

#### 按合成器类型

| 类型 | gemma3:12b | gemini-2.5-flash |
|------|-----------|------------------|
| single_hop_factual | 0.836 | 0.839 |
| table_extraction | 0.697 | **0.905** |
| comparison_analysis | 0.734 | **0.873** |
| multi_hop_reasoning | 0.766 | 0.762 |

#### 关键差异

**Gemini 2.5 Flash 胜出：**
- RAGAS-006（研发成本）：gemma3 答错 320 亿 → gemini 答对 **382 亿**
- RAGAS-018（EBITDA 利润率）：gemma3 用马拉雅拉姆语回答（！）→ gemini 正确使用中文回答
- RAGAS-022（最佳 AI/ML 公司）：gemma3 回答 FPT IS → gemini 正确回答 **TechVina ★★★★★**
- 表格提取好得多（0.697 → 0.905）
- 语言一致性：Gemini 始终使用与问题相同的语言回答

**gemma3:12b 胜出：**
- 事实正确性略高（0.773 vs 0.749）—— 可能是随机波动

**两者都较弱（检索/上下文问题）：**
- RAGAS-009：“董事长”（Chủ tịch HĐQT）context_recall = 0（检索未找到足够上下文）
- RAGAS-023：流失率 faithfulness = 0
- RAGAS-027：竞争价格 faithfulness = 0
- RAGAS-029：同比增长 faithfulness = 0

---

## 逐样本详细结果（Gemini 2.5 Flash）

| ID | 类别 | 得分 | 状态 | 问题 |
|----|----------|-------|--------|-------|
| RAGAS-001 | single_hop | 1.00 | 通过 | |
| RAGAS-002 | table | 0.90 | 通过 | |
| RAGAS-003 | multi_hop | 0.76 | 通过 | factual_correctness: 0.00 |
| RAGAS-004 | single_hop | 0.76 | 通过 | factual_correctness: 0.00 |
| RAGAS-005 | table | 0.90 | 通过 | |
| RAGAS-006 | table | 0.90 | 通过 | 相比 gemma3 已修复（原为 0.62） |
| RAGAS-007 | single_hop | 0.88 | 通过 | |
| RAGAS-008 | comparison | 0.95 | 通过 | |
| RAGAS-009 | single_hop | 0.62 | 失败 | context_recall: 0, faithfulness: 0 |
| RAGAS-010 | single_hop | 0.90 | 通过 | |
| RAGAS-011 | single_hop | 0.89 | 通过 | |
| RAGAS-012 | single_hop | 0.93 | 通过 | |
| RAGAS-013 | single_hop | 0.90 | 通过 | |
| RAGAS-014 | single_hop | 0.86 | 通过 | |
| RAGAS-015 | single_hop | 0.93 | 通过 | |
| RAGAS-016 | single_hop | 1.00 | 通过 | |
| RAGAS-017 | single_hop | 0.86 | 通过 | |
| RAGAS-018 | comparison | 0.90 | 通过 | 相比 gemma3 已修复（原为 0.59） |
| RAGAS-019 | single_hop | 0.86 | 通过 | |
| RAGAS-020 | single_hop | 0.90 | 通过 | |
| RAGAS-021 | single_hop | 0.90 | 通过 | |
| RAGAS-022 | single_hop | 0.84 | 通过 | 相比 gemma3 已修复（原为 0.77） |
| RAGAS-023 | single_hop | 0.54 | 失败 | context_recall: 0, faithfulness: 0.29 |
| RAGAS-024 | single_hop | 0.93 | 通过 | |
| RAGAS-025 | single_hop | 0.95 | 通过 | |
| RAGAS-026 | comparison | 0.76 | 通过 | |
| RAGAS-027 | single_hop | 0.62 | 失败 | context_recall: 0, faithfulness: 0 |
| RAGAS-028 | single_hop | 0.81 | 通过 | |
| RAGAS-029 | single_hop | 0.48 | 失败 | faithfulness: 0, factual: 0 |
| RAGAS-030 | single_hop | 0.93 | 通过 | |

---

## 问题分析

### 已解决的问题（从最初的 7/10 → 15/16）
1. **过度拒绝** —— 已修复：将提示词从“ONLY”/“NEVER”改为更均衡的指令
2. **虚假引用** —— 已修复：增加“拒绝回答时不加引用”规则
3. **历史处理** —— 已修复：提问前先回顾对话上下文
4. **令牌残留** —— 已修复：`re.sub(r'<unused\d+>:?\s*', '', answer)`
5. **跨文档推理** —— 已修复：明确允许“综合多个来源作答”

### 遗留问题
1. **忠实度（4 个失败）** —— LLM 展开回答时偶尔添加无依据的细节
2. **上下文召回（5 个用例为 0）** —— 检索流水线无法为某些具体事实找到相关分块（如董事长姓名、流失率）
3. **表格数据解析** —— gemma3:12b 难以处理“Key, Year = Value”格式；Gemini 表现良好
4. **语言混杂** —— gemma3 有时会用错误语言回答；Gemini 保持一致

### 建议
1. **生产环境切换到 Gemini 2.5 Flash** —— 忠实度、表格解析、语言一致性更好
2. **改善 context_recall 偏低的检索** —— 考虑调整分块大小或增加元数据过滤
3. **关注忠实度** —— 4 个失败用例表明 LLM 有时会超出来源内容过度展开

---

## 脚本参考

| 脚本 | 用途 | 用法 |
|--------|---------|-------|
| `eval_rag.py` | 阶段 1：16 个手工测试，基于规则 | `python scripts/eval_rag.py --workspace 11` |
| `eval_ragas_synthetic.py generate` | 生成合成测试集 | `python scripts/eval_ragas_synthetic.py generate --workspace 11 --size 30 --gemini-key KEY` |
| `eval_ragas_synthetic.py evaluate` | 使用 RAGAS 评判进行评估 | `python scripts/eval_ragas_synthetic.py evaluate --workspace 11 --testset scripts/ragas_testset.json --gemini-key KEY` |

### 切换 LLM 提供商
```bash
# 编辑 myrag/.env
# 注释掉 Ollama，取消注释 Gemini（或反之）
# 重启服务器（必需 —— 设置通过 @lru_cache 缓存）
```

切换 LLM 无需重新索引 —— 只有更换向量化模型时才需要重新索引。
