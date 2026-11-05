# 中文 Chinese

**中文** | [English](README_en.md)
## 配置与运行

1. 如果项目是从另一台电脑复制过来的，请重新创建本机的 `.venv`，不要复用复制来的环境。当前电脑上已经正常使用的环境不需要删除。
2. 确保 `requirements.txt` 中的依赖库均已安装到项目虚拟环境中。
3. 在 `Knowledge Base` 文件夹下放置原始资料，支持 PDF、TXT、CSV、Markdown、DOCX、PPTX、XLSX、HTML，以及 PNG/JPEG/TIFF/BMP/WebP 图片。
4. 当前版本配置为调用 DeepSeek。在 `.env` 中设置 `DEEPSEEK_API_KEY`，并确保账户有足够的 API 额度。不要分享密钥。
5. 在已激活环境的项目终端运行 `python main.py --choose`，在弹出的窗口中选择从 Opal 下载的 Markdown 问题文件。
6. 运行后，项目根目录（`main.py` 所在目录）会直接生成一份中文版和一份英文版 Markdown 报告。

## 相关细节

程序每批次只加载一次知识库并建立内存索引，再逐题调用 DeepSeek。
每道题通常对应一次 API 请求；问题及所检索的原文会发送到 DeepSeek，并按账户规则计费。
每次默认在**项目根目录**直接写入两份 UTF-8 Markdown 文件：

- `rag_report_时间_zh.md`：中文问题译文、中文回答、中文报告说明。
- `rag_report_时间_en.md`：英文问题译文、英文回答、英文报告说明。

## Opal 问题输出约定

可以把下面这段要求加到负责整理问题的 Opal Agent：

> 请输出 Markdown 问题清单，第一行是 `# RAG Questions`。
> 每道问题使用独立二级标题 `## Q001`、`## Q002` 等，编号唯一且大于零。
> 标题下只写问题正文，可跨多行。每个问题应能独立理解，明确对象和时间范围。
> 不输出答案、额外解释、三级标题或代码围栏。只输出要保存为 .md 的正文。


## 更新资料

原始资料放在 `Knowledge Base`。每次重新运行都会从当前目录重建索引，
因此新增、修改、删除的原始资料在下一次运行生效；运行途中请不要改动资料。
报告保留知识库整体版本哈希，不再列出全部文件及逐文件 SHA256；每题仍保留来源文件名、位置和引用编号。版本哈希不是原始资料备份。
历史报告仍包含当时的旧信息；资料变化后请生成新报告，并替换 Opal 中的旧输入。
**不要将 Questions、Reports 或模型回答放入 Knowledge Base。**

可通过 `--knowledge-base "目录"` 指定其他资料目录，`--output-dir "目录"` 覆盖默认项目根目录位置，
`--top-k 5` 调整每题返回片段数（默认 3）。报告目录不得位于知识库内。

## 状态与边界

- 完成：生成调用完成，不代表内容经过人工审核。
- 需复核：回答引用异常、缺失或模型没有正常结束。
- 处理失败：网络、认证、超长问题等错误，**不是 NOT FOUND**；其他题继续处理。
- NOT FOUND：模型认为本次检索证据不足，不代表穷尽整个资料库。
- Ctrl+C：停止本批次，保留已经写入的题目，并标注批次中断。

来源定位：

- TXT 保留行号。
- Docling 的 PDF/图片保留可用页码，PPTX 保留幻灯片编号，XLSX 保留工作表名称；其他格式保留标题与文档元素编号。不会把转换后的行号冒充原文件行号。
- CSV 保留记录 ID。

## Docling 多格式解析

所有资料统一从 `ingestion.prepare_chunks()` 进入：TXT/CSV 使用原有读取与切分规则，PDF 及其他复杂格式使用 Docling，最后统一输出正文和来源元数据。旧 PDF 读取器及 `--pdf-parser` 参数已移除，PDF 始终使用 Docling。

- `ingestion.py`：文件扫描、TXT/CSV 读取与切分、Docling 解析与切分、统一长度校验。
- `rag_backend.py`：加载 E5/tokenizer，将统一文本块向量化并建立内存索引。
- `main.py`：读取问题、调用建库与检索、生成回答并导出报告；解析检查模式直接调用统一入口。

在项目终端安装依赖（当前集成固定 Docling 2.146.0、docling-core 2.106.0，兼容原有 E5/torch 配置）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

PDF、图片、Office、Markdown 和 HTML 使用 Docling 解析，再用 HybridChunker 按标题、段落、表格结构与 E5 tokenizer 切分。表格使用 Markdown 表示，长表格分块时重复表头。TXT/CSV 保留原有读取方式，CSV 的说明行和业务 ID 不丢失；先按 800 字符/120 字符重叠切分，超过 token 预算时继续细分。所有块在入库前检查包含 `passage:` 前缀的实际长度不超过 512 tokens，不静默截断。

先查看解析结果，不调用 DeepSeek、不需要 API 密钥：

```powershell
.\.venv\Scripts\python.exe main.py --inspect-ingestion work/chunks.json
```

JSON 包含可检索正文、来源、标题、页码/幻灯片/工作表和 token 数。输出必须在知识库外，已有文件不会被覆盖。检查表格值和 OCR 是否正确后，按原来的方式运行：

```powershell
.\.venv\Scripts\python.exe main.py --choose
# 只检索并导出引用，不调用 DeepSeek
.\.venv\Scripts\python.exe main.py Questions.md --retrieve-only --top-k 5
# 对扫描件强制整页 OCR
.\.venv\Scripts\python.exe main.py --choose --force-full-page-ocr
```

默认使用 RapidOCR 的中文模型识别中英文文字；`--no-ocr` 可关闭 OCR。PDF/图片首次运行需要联网下载版面、表格和 OCR 模型，CPU 运行可能较慢。Hugging Face/Docling 缓存默认位于项目 `models` 下，用户已有的 `HF_HUB_CACHE`、`DOCLING_CACHE_DIR` 配置优先；RapidOCR 还可能在其安装目录保存权重。模型就绪后解析在本机执行，不调用远程视觉 API。转换失败、部分成功或整个文件没有可检索内容时会明确停止，避免漏掉文件后继续回答。

限制：

- 支持的是 `.pptx/.docx/.xlsx`；旧 `.ppt/.doc/.xls` 需要先另存为新格式。
- 图片支持 OCR 与文档版面提取，不等于理解照片、流程图或图表含义。当前未启用视觉描述模型。
- Office 内嵌图片不能保证经过 OCR；只有截图的 PPT 建议先导出 PDF，或将图片单独放入知识库。
- Excel 公式不由本程序重算；请先在 Excel 中计算并保存。复杂合并单元格、手写文字和低清扫描仍需人工核对。
- Docling 改善的是内容提取与结构保留。仍使用 E5 语义检索和内存索引，没有加入重排、全表 SQL 统计、父子分块或跨会话记忆；不能据此保证所有问答效果提升。

测试：`python -m unittest discover -s tests -v`（E5 模型需已缓存）。设置 `RAG_TEST_OCR=1` 可额外测试真实 PNG/扫描 PDF OCR；首次下载时同时设置 `HF_HUB_OFFLINE=0` 和 `TRANSFORMERS_OFFLINE=0`。测试使用临时合成资料，不调用 DeepSeek。

参考：[Docling 支持格式](https://docling-project.github.io/docling/usage/supported_formats/)、[结构化切分](https://docling-project.github.io/docling/concepts/chunking/)、[视觉描述扩展](https://docling-project.github.io/docling/usage/enrichments/)。
