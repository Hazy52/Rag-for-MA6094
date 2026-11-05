# English

[中文](README_zh.md) | **English**

## Setup and Usage

1. If you copied this project from another computer, recreate `.venv` locally instead of reusing the copied environment. You do not need to delete a working environment on your current computer.
2. Make sure the dependencies listed in `requirements.txt` are installed in your project's virtual environment.
3. Place your source documents in `Knowledge Base`. Supported formats: PDF, TXT, CSV, Markdown, DOCX, PPTX, XLSX, HTML, and PNG/JPEG/TIFF/BMP/WebP images.
4. This version is configured to use DeepSeek. Set `DEEPSEEK_API_KEY` in `.env` and ensure your account has sufficient API credits. Do not share your API key.
5. From an activated project terminal, run `python main.py --choose`. Select the Markdown question file downloaded from Opal in the file selection window.
6. A Chinese Markdown report and an English Markdown report will be saved directly to the project root (the directory containing `main.py`).

## Implementation Details

The program loads the knowledge base and builds an in-memory vector index once per batch, then calls DeepSeek for each question.
Each question normally requires one API request. The question and retrieved source passages are sent to DeepSeek, and usage is billed according to your account's API terms.
By default, each run writes two UTF-8 Markdown files directly to your **project root**:

- `rag_report_<timestamp>_zh.md`: the question in Chinese, a Chinese answer, and Chinese report labels and explanations.
- `rag_report_<timestamp>_en.md`: the question in English, an English answer, and English report labels and explanations.

## Opal Question Output Format

Add the following instructions to the Opal agent responsible for preparing questions:

> Output a Markdown question list with `# RAG Questions` as the first line.
> Give each question a separate level-two heading, such as `## Q001` or `## Q002`. Question identifiers must be unique and greater than zero.
> Place only the question text below each heading; it may span multiple lines. Each question must be understandable independently, with a clear subject and time frame.
> Do not include answers, additional explanations, level-three headings, or code fences. Output only the content to be saved as an .md file.

## Updating Source Documents

Store original source documents in `Knowledge Base`. Each run rebuilds the index from the files currently in that directory.
New, modified, or deleted source documents therefore take effect on the next run. Do not change the source documents during a run.
Reports retain an overall knowledge base version hash, but omit the full file list and per-file SHA256 values. Each question still includes source filenames, locations, and evidence identifiers. The version hash is not a backup of the original documents.
Historical reports still contain information from earlier versions. After changing the source documents, generate a new report and replace the old input in Opal.
**Do not place Questions, Reports, or model-generated answers inside Knowledge Base.**

Use `--knowledge-base "directory"` to select another source directory, `--output-dir "directory"` to override the default project root location,
or `--top-k 5` to change the number of retrieved passages per question (default: 3). The report directory must not be inside the knowledge base.

## Statuses and Limitations

- Completed: The generation request completed; this does not mean the content has been reviewed by a person.
- Review required: Citations are missing or invalid, or the model did not finish normally.
- Failed: Processing encountered a network, authentication, question-length, or other error. This is **not NOT FOUND**. The remaining questions continue to be processed.
- NOT FOUND: The model considers the retrieved evidence insufficient. This does not mean the entire knowledge base has been searched exhaustively.
- Ctrl+C: Stops the batch, preserves questions already written to the reports, and marks the batch as interrupted.

Source locations are recorded as follows:

- TXT: line numbers.
- Docling PDF/images: available page numbers; PPTX: slide numbers; XLSX: sheet names; other formats: headings and document element references. Converted line numbers are never presented as original source lines.
- CSV: record IDs.

## Docling ingestion

All sources enter through `ingestion.prepare_chunks()`: TXT/CSV retain their existing readers and splitters, while PDF and other complex formats use Docling. Both paths return text and source metadata in the same format. The old PDF reader and `--pdf-parser` option have been removed; PDF always uses Docling.

- `ingestion.py`: scanning, TXT/CSV reading and splitting, Docling conversion and chunking, and final length validation.
- `rag_backend.py`: E5/tokenizer loading, embeddings and the in-memory index.
- `main.py`: question input, orchestration, retrieval, answer generation and reports; inspection calls the ingestion entry point directly.

Install with `python -m pip install -r requirements.txt`. Docling 2.146.0 and docling-core 2.106.0 are pinned alongside the existing E5/torch dependencies.

Docling parses PDF, images, Office, Markdown and HTML. HybridChunker preserves document structure and repeats Markdown table headers across chunks, using the E5 tokenizer. TXT/CSV retain their existing readers, source notes and business IDs. They use 800-character chunks with a target 120-character overlap, with further token-aware splitting when necessary. Every final embedding input, including `passage:`, is checked against the 512-token limit.

```powershell
# Inspect extracted text and metadata without DeepSeek or an API key
.\.venv\Scripts\python.exe main.py --inspect-ingestion work/chunks.json
# Normal question selection
.\.venv\Scripts\python.exe main.py --choose
# Retrieval only
.\.venv\Scripts\python.exe main.py Questions.md --retrieve-only --top-k 5
# Full-page OCR for scans
.\.venv\Scripts\python.exe main.py --choose --force-full-page-ocr
```

Inspection output must be outside the knowledge base and must not already exist. It includes text, locations and token counts. Default RapidOCR recognizes Chinese and English; `--no-ocr` disables OCR. The first PDF/image conversion downloads layout, table and OCR models. CPU conversion can be slow. Hugging Face/Docling caches default to project `models`, honoring existing `HF_HUB_CACHE`/`DOCLING_CACHE_DIR` settings; RapidOCR may also store weights in its installation directory. Parsing runs locally without remote vision APIs. Failed/partial conversions and files without searchable content stop ingestion explicitly.

Limitations: convert legacy `.ppt/.doc/.xls` to modern Office formats first. OCR extracts visible text, not the meaning of photos or diagrams; no picture-description model is enabled. Embedded Office images are not guaranteed to undergo OCR: export image-only slides to PDF or ingest their images separately. Excel formulas are not recalculated; calculate and save the workbook first. Review complex tables, handwriting and poor scans. E5 retrieval and the in-memory index remain; reranking, full-table SQL analytics, parent-child retrieval and cross-session memory are not implemented. Better extraction alone does not establish better answer accuracy.

Tests: `python -m unittest discover -s tests -v` requires the cached E5 tokenizer. Set `RAG_TEST_OCR=1` to include actual PNG/scanned-PDF OCR tests; allow initial downloads with `HF_HUB_OFFLINE=0` and `TRANSFORMERS_OFFLINE=0`. Tests use synthetic temporary files and never call DeepSeek.

References: [formats](https://docling-project.github.io/docling/usage/supported_formats/), [chunking](https://docling-project.github.io/docling/concepts/chunking/), [picture enrichment](https://docling-project.github.io/docling/usage/enrichments/).
