# 50 条人工评测基线

本目录由成员 A 维护，用于 Issue #18 和第 6 天集成门。它把检索、回答、
引用、拒答和评分统一到一套可重复的输入、标注及指标口径中。

## 数据分布

| 类别 | 数量 | 主要目标 |
| --- | ---: | --- |
| `fact_qa` | 15 | 单页事实、歧义澄清 |
| `computation_short_answer` | 15 | 综合简答与训练评分 |
| `visual` | 10 | 扫描 PDF、OCR、题号和版面 |
| `refusal` | 5 | 资料外、答案泄露、提示注入 |
| `cross_knowledge` | 5 | 多页综合、表面冲突 |

共 50 条；覆盖 `in_scope`、`out_of_scope`、`multi_page`、`ambiguous`、
`conflict`、`visual` 和 `prompt_injection` 场景。

## 文件

- `cases.public.jsonl`：可提交的 50 条输入、期望证据定位、期望行为和评分策略。
- `case.schema.json`：单条样本的字段约束。
- `policies.json`：不含标准答案的公共评分口径和质量门槛。
- `evaluate.py`：数据校验、Recall@5、人工指标汇总和缺陷清单生成器。
- `run_live.py`：使用真实文本、视觉和 Embedding 服务执行 50 条本机评测。
- `create_annotation_packets.py`：按 B/C/E 分工生成私有人工标注包。
- `merge_annotation_packets.py`：校验、修复上下文引号损坏并合并返还的标注包。
- `templates/`：系统结果、双人标注和运行快照示例。
- `reports/baseline.md`：当前可用模块下的基线状态，不伪造尚未产生的指标。

## 隐私边界

公开文件不得包含课程 PDF、考试原文、标准答案、私有评分点、真实学习记录或
本机绝对路径。需要保密的答案、细粒度评分点和标注原稿统一放在
`tests/evaluation/private/`；该目录已被 `.gitignore` 排除。

公共样本只保存原创提问、文档标识、页码、期望行为和通用评分策略 ID。
`expected_evidence` 是定位信息，不是答案摘录。

| 文档标识 | 本地文件 | 页数 |
| --- | --- | ---: |
| `db-intro-digital` | `digital-lecture-intro.pdf` | 15 |
| `db-exam-scan` | `scan-exam-2018-2019-A-pages-1-2.pdf` | 2 |

## 字段说明

| 字段 | 含义 |
| --- | --- |
| `case_id` | 稳定且唯一的样本编号 |
| `category` | 五类样本之一 |
| `mode` | `qa` 或 `training` |
| `query` | 发送给系统的公开输入 |
| `student_answer` | 仅训练评分样本使用的合成作答；不包含标准答案 |
| `source_scope` | 本次允许检索的资料标识 |
| `expected_behavior` | `answer`、`refuse`、`clarify`、`flag_conflict` 或 `grade` |
| `expected_evidence` | 期望命中的文档与页码；无证据场景必须为空数组 |
| `evidence_match` | `any`、`all` 或 `none` |
| `scoring_policy` | `policies.json` 中的公共评分策略 |
| `critical` | 是否必须完成双人标注 |
| `tags` | 场景、资料形态与风险标签 |

## 执行流程

1. 按 `docs/COURSE_MATERIALS.md` 在本地准备资料，不提交原文件。
2. 在本机 `.env` 配置模型与 Embedding 服务；不得提交或打印密钥。
3. 运行真实服务评测。脚本会固定代码提交、资料提交、模型、提示词和检索参数，
   并把原始回答保存到 Git 忽略目录：

```powershell
python tests/evaluation/run_live.py
```

4. 生成按角色分开的私有标注包：

```powershell
python tests/evaluation/create_annotation_packets.py
```

5. 每条关键样本由两个不同成员独立标注；不允许同一人重复计数。收齐后合并：

```powershell
python tests/evaluation/merge_annotation_packets.py `
  <B 返回文件> <C 返回文件> <E 返回文件>
```

6. A 把分歧仲裁保存到私有 `arbitrations.jsonl`；每行记录 `case_id`、
   `metric`、`arbiter_id`、`judgment` 和 `reason`。
7. 生成报告和缺陷清单：

```powershell
python tests/evaluation/evaluate.py validate
python tests/evaluation/evaluate.py report `
  --results tests/evaluation/private/run-results.jsonl `
  --annotations tests/evaluation/private/annotations.jsonl `
  --arbitrations tests/evaluation/private/arbitrations.jsonl `
  --manifest tests/evaluation/private/run-manifest.json `
  --output tests/evaluation/private/report.md `
  --defects tests/evaluation/private/defects.jsonl
```

没有 C/D/E 的真实输出或关键样本双人标注时，报告必须保持 `INCOMPLETE`，
不得把空值、示例数据或单人判断写成达标结果。

若实际行为与期望行为不一致，依赖该行为的回答、引用或评分指标直接判为失败；
它是可重复的系统结果，不要求标注者把无输出的引用从 `na` 人工改写为 `fail`。

如需单独复现某条失败样本，可执行：

```powershell
python tests/evaluation/run_live.py --case-id db-001 `
  --output-dir .local-data/evaluation-db-001
```

## 双人标注分工

| 样本主类 | 第一标注角色 | 第二标注角色 | 分歧仲裁 |
| --- | --- | --- | --- |
| 检索、事实问答 | B | E | A |
| 综合简答、拒答 | C | E | A |
| 扫描件、引用 | B | E | A |
| 训练评分 | C | B | A |
| 跨知识点 | B | C | A |

当 A 本人参与标注时，仲裁必须改由未参与该条首轮标注的成员完成。
