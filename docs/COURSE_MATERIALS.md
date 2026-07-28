# 课程资料与本地样例清单

## 课程基线

| 字段 | 值 |
| --- | --- |
| 目标课程 | 数据库系统原理 |
| 授课教师 | 李旭东 |
| 来源仓库 | [Asever611/NKU-SE-Passport](https://github.com/Asever611/NKU-SE-Passport) |
| 来源目录 | [`2_2_数据库系统原理_李旭东`](https://github.com/Asever611/NKU-SE-Passport/tree/main/2_2_%E6%95%B0%E6%8D%AE%E5%BA%93%E7%B3%BB%E7%BB%9F%E5%8E%9F%E7%90%86_%E6%9D%8E%E6%97%AD%E4%B8%9C) |
| 固定来源提交 | `bbb111f2241211c9037afbfa9829216d04d34eaa` |
| 资料规模 | 38 份 PDF：课件 10、期末 5、实验 11、作业 12 |

来源仓库公开可读，但未声明开源许可证。课程资料仅用于小组本地开发、评测与答辩，不复制到本公有仓库，也不作二次分发。

## MVP 样例

| 类型 | 本地文件名 | 来源或生成方式 | 页数 | 文本层 | SHA-256 |
| --- | --- | --- | ---: | --- | --- |
| 数字 PDF | `digital-lecture-intro.pdf` | `课件/lecture01DbSystemIntroBasicR6.pdf` | 15 | 15/15 页可提取文本 | `5c9509194e36bceda7dfa711e72596868af43519266c1f5821ee141070fa69fe` |
| OCR 测试 PDF | `scan-exam-2018-2019-A-pages-1-2.pdf` | 将 `期末/数据库期末考试真题2018-2019(A).pdf` 第 1–2 页以 150 DPI 图像化，生成无文本层的本地派生样例 | 2 | 0/2 页含文本层 | 运行脚本后记录在本地 `manifest.json` |

数字样例已核对：15 页均有文本层，中位每页可提取 1124 个字符。原始真题本身也有文本层，因此不能直接作为扫描 PDF；OCR 样例必须使用明确标记的图像化派生文件，禁止把数字 PDF 冒充扫描件。

参考环境使用 PyMuPDF 1.28.0 生成的 OCR 样例为 2 页、528930 字节、零文本字符，SHA-256 为 `f71091f85c1a0c49b26786f198bd33e22847e8847d803f1d58e2762a8eb2ce3b`。不同 PyMuPDF 版本可能产生不同字节哈希，以脚本生成的本地 `manifest.json` 为实际记录。

## 本地准备

项目文档处理环境安装 PyMuPDF 后，在仓库根目录运行：

```powershell
python scripts/prepare_course_samples.py
```

默认输出到已被 `.gitignore` 排除的 `.local-data/course-samples/`：

```text
.local-data/course-samples/
├─ digital-lecture-intro.pdf
├─ _source-exam-2018-2019-A.pdf
├─ scan-exam-2018-2019-A-pages-1-2.pdf
└─ manifest.json
```

脚本固定来源提交并校验两个源文件的 SHA-256。`manifest.json` 记录本机生成文件的页数、文本层和哈希，可用于 B 的导入测试和 A 的验收记录。

## 使用边界

- 不提交 `.local-data/`、原始课程 PDF、生成的扫描样例或其中的答案内容。
- 公有 Issue、日志和测试报告只记录文件名、类型、页数、SHA-256 与统计结果。
- 评测问题引用资料内容时使用最少必要摘录，不公开整页或完整试题。
- 若上游文件发生变化，先固定新的来源提交并重新核对哈希，不静默替换样例。
- 删除本地资料时，同时清理解析文件、页图、向量和临时缓存。
