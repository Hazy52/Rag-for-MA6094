# RAG for MA6094

[中文说明](README_zh.md) | [English documentation](README_en.md)

用于 MA6094 Harbourline 项目的本地 RAG：读取 PDF、TXT、CSV 知识库，接收 Markdown 问题清单，调用 DeepSeek，在项目根目录生成中英文两份 Markdown 报告。

Local retrieval-augmented question answering for the MA6094 Harbourline project. The application reads PDF, TXT and CSV sources, accepts Markdown questions, and generates Chinese and English Markdown reports using DeepSeek.

## Windows / PowerShell 快速开始

使用 Python 3.10，进入下载或克隆后的项目目录，然后执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在本机 `.env` 中填写 `DEEPSEEK_API_KEY`，然后运行：

```powershell
.\.venv\Scripts\python.exe main.py --choose
```

第一次使用需要下载嵌入模型。DeepSeek API 调用按账户规则计费。具体设置及使用限制请查看上面的中英文说明。

## Markdown 问题文件

问题文件放在 `Knowledge Base` 之外，例如保存为项目根目录的 `questions.md`：

```markdown
# RAG Questions

## Q001
What asbestos issue was reported in March 2027, and what were the estimated cost and duration?
```

## 项目文件

- `main.py`：问题输入、检索调用、双语回答和 Markdown 报告导出。
- `rag_backend.py`：资料读取、来源定位、递归分块、嵌入与内存索引。
- `Knowledge Base/`：教学项目原始资料。
- `requirements.txt`：Python 依赖版本。
- `.env.example`：空白密钥配置模板。

`.env`、虚拟环境、下载的模型缓存和生成的报告均不提交到 Git。不要在代码、说明文档或 `.env.example` 中填写真实密钥。
