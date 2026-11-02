# English

[中文](README_zh.md) | **English**

## Setup and Usage

1. If you copied this project from another computer, recreate `.venv` locally instead of reusing the copied environment. You do not need to delete a working environment on your current computer.
2. Make sure the dependencies listed in `requirements.txt` are installed in your project's virtual environment.
3. Place your source documents in `Knowledge Base`. Supported formats are PDF, TXT, and CSV.
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

Store original source documents in `Knowledge Base`. PDF, TXT, and CSV are supported. Each run rebuilds the index from the files currently in that directory.
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
- PDF: page numbers plus top, middle or bottom based on text coordinates. Passages spanning regions show a range (such as top to middle); unreliable coordinates fall back to page numbers only. Regions indicate the approximate location of the retrieved passage.
- CSV: record IDs.

The system uses recursive character splitting, with a maximum of 800 characters per chunk and a target overlap of up to 120 characters between adjacent chunks.
Parent-child chunking and cross-session decision memory have not been implemented.
