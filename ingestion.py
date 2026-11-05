"""统一资料处理层：TXT/CSV 原有读取与切分 + Docling 多格式解析与切分。"""
from dataclasses import dataclass
from pathlib import Path
import os

# 在 transformers/docling 首次导入前设置下载缓存；用户显式配置优先。
os.environ.setdefault("HF_HUB_CACHE", str(Path(__file__).resolve().parent / "models" / "hub"))
os.environ.setdefault("DOCLING_CACHE_DIR", str(Path(__file__).resolve().parent / "models" / "docling"))


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
DOCLING_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".html", ".htm"} | IMAGE_EXTENSIONS
SUPPORTED_EXTENSIONS = DOCLING_EXTENSIONS | {".txt", ".csv"}


@dataclass(frozen=True)
class IngestionOptions:
    ocr: bool = True
    force_full_page_ocr: bool = False

    def __post_init__(self):
        if self.force_full_page_ocr and not self.ocr:
            raise ValueError("全页 OCR 不能与禁用 OCR 同时使用。")


def scan_sources(folder):
    """与报告版本清单共享同一套规则，忽略 Office 临时文件。"""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError(f"找不到知识库文件夹：{folder}")
    files = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
        elif path.suffix.lower() in {".ppt", ".doc", ".xls"}:
            raise ValueError(f"请先将旧版 Office 文件另存为 pptx/docx/xlsx：{path.name}")
    if not files:
        raise ValueError("知识库没有支持的文件：" + ", ".join(sorted(SUPPORTED_EXTENSIONS)))
    return files


def load_txt_csv_documents(files, source_dir):
    """读取 TXT/CSV，保留原有说明行、业务 ID、列数校验和来源定位。"""
    # -------------------- 步骤 1A：读取 TXT 全文 --------------------
    # 先保留全文，后面分块时根据字符位置计算每块覆盖的原始行号。
    # 保存 TXT 文件的正文和来源信息
    txt_documents = []

    for path in files:
        if path.suffix.lower() != ".txt":
            continue

        text = path.read_text(encoding="utf-8-sig")
        line_count = len(text.splitlines())

        record = {
            "source": path.name,
            "source_path": str(path),
            "text": text,
            "line_count": line_count,
        }

        txt_documents.append(record)

        print(
            f"\n读取 TXT：{path.name}"
            f"\n  字符数：{len(text)}，行数：{line_count}"
        )

        if not text.strip():
            print("  注意：这个文件没有文字内容。")

    print(f"\n共读取 {len(txt_documents)} 个 TXT 文件。")

    # -------------------- 步骤 1B：读取 CSV，每条记录独立处理 --------------------
    # 先找真正的表头；资料包中表头前的说明行会作为上下文保留。
    # 每条记录转换成“字段名：值”的文字，仍保留业务 ID，不纠正原始数据。
    import csv

    # 每条 CSV 数据记录对应一个字典
    csv_records = []

    for path in files:
        if path.suffix.lower() != ".csv":
            continue

        file_record_count = 0

        with path.open("r", encoding="utf-8-sig", newline="") as file:
            source_notes = []
            fieldnames = None

            # 先识别文件开头的说明和真正的表头
            raw_reader = csv.reader(file)
            for candidate in raw_reader:
                if not candidate or not any(value.strip() for value in candidate):
                    continue

                # 这里只处理表头前的单列说明，不过滤正常数据中的 #
                if len(candidate) == 1 and candidate[0].lstrip().startswith("#"):
                    source_notes.append(candidate[0].lstrip()[1:].strip())
                    continue

                fieldnames = candidate
                break

            reader = csv.DictReader(file, fieldnames=fieldnames)

            if not reader.fieldnames:
                raise ValueError(f"CSV 缺少表头：{path.name}")

            for record_number, row in enumerate(reader, start=1):
                # 检查每条记录的列数是否与表头一致
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(
                        f"{path.name} 第 {record_number} 条记录的列数与表头不一致"
                    )

                # 忽略所有字段都为空的记录
                if not any(value.strip() for value in row.values()):
                    continue

                # 将一条记录整理成“字段名：值”的文本
                text = "\n".join(
                    [f"Source note: {note}" for note in source_notes]
                    + [f"{field}: {value}" for field, value in row.items()]
                )

                csv_records.append({
                    "source": path.name,
                    "source_path": str(path),
                    "record_number": record_number,
                    "fields": row,
                    "source_notes": list(source_notes),
                    "text": text,
                })

                file_record_count += 1

        print(f"\n读取 CSV：{path.name}，共 {file_record_count} 条有效记录")

    print(f"\n共读取 {len(csv_records)} 条 CSV 数据记录。")

    # -------------------- 步骤 2：统一正文与来源元数据 --------------------
    # text 是可以检索的正文；metadata 是文件路径、行号、记录 ID 等来源信息。
    # 元数据跟着文本一路进入分块和索引，最终用于给回答添加出处。
    # 本步骤不生成答案，也不改变原始资料中互相矛盾的事实。
    # 统一 TXT/CSV 资料格式：每条资料都包含 text（正文）和 metadata（来源信息）
    documents = []


    def add_document(record, file_type, unit, **location):
        """保留原文，给一个 TXT 文件或一条 CSV 记录添加统一来源信息。"""
        if not record["text"].strip():
            print(f"跳过空内容：{record['source']}，位置：{unit}")
            return

        # 使用相对路径，避免不同子文件夹中的同名文件被混淆
        source = Path(record["source_path"]).resolve().relative_to(
            source_dir.resolve()
        ).as_posix()

        metadata = {
            "document_id": f"{source}::{unit}",
            "source": source,
            "source_path": record["source_path"],
            "file_type": file_type,
            **location,
        }

        documents.append({
            "text": record["text"],
            "metadata": metadata,
        })


    # TXT：暂时保留全文；分块时会进一步计算各块的准确行号
    for record in txt_documents:
        add_document(
            record, "txt", "full-text",
            line_start=1,
            line_end=record["line_count"],
        )

    # CSV：保留独立记录和原始业务 ID，避免把相邻记录拼在一起
    for record in csv_records:
        record_id = next(
            (
                record["fields"][key].strip()
                for key in ("risk_id", "response_id", "id")
                if record["fields"].get(key, "").strip()
            ),
            "",
        )

        add_document(
            record, "csv", f"record:{record_id or record['record_number']}",
            record_number=record["record_number"],
            record_id=record_id,
            source_notes="\n".join(record["source_notes"]),
        )

    # 重复来源位置可能导致后续索引覆盖，发现时及时停止
    document_ids = [doc["metadata"]["document_id"] for doc in documents]
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("存在重复的资料 ID，请检查文件扫描范围或 CSV 记录 ID。")

    print("\n===== 统一格式完成 =====")
    for file_type in ("txt", "csv"):
        count = sum(doc["metadata"]["file_type"] == file_type for doc in documents)
        print(f"{file_type.upper()}：{count} 条资料")
    print(f"共 {len(documents)} 条资料；尚未分块。")

    return documents


def make_text_chunks(source_documents, chunk_size=800, chunk_overlap=120, tokenizer=None):
    """每条原始资料单独切分；保留来源和字符位置，计算 TXT 的实际行号。"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
        length_function=len,
        keep_separator=True,
        strip_whitespace=False,
        # 要求切分器返回每块在原始正文中的起始字符位置，供来源定位使用。
        add_start_index=True,
    )

    result = []
    for document in source_documents:
        original_text = document["text"]
        # 每次只传入一条资料，不把不同 TXT 文件或 CSV 记录拼接
        parts = splitter.create_documents(
            [original_text],
            metadatas=[document["metadata"]],
        )

        if tokenizer is not None:
            safe_parts = []
            token_splitter = RecursiveCharacterTextSplitter(
                chunk_size=480, chunk_overlap=60,
                length_function=lambda text: len(tokenizer.encode(text, add_special_tokens=False)),
                separators=["\n\n", "\n", " ", ""],
                keep_separator=True, strip_whitespace=False, add_start_index=True,
            )
            for part in parts:
                if len(tokenizer.encode("passage: " + part.page_content)) <= 512:
                    safe_parts.append(part)
                    continue
                for subpart in token_splitter.create_documents([part.page_content]):
                    offset = subpart.metadata["start_index"]
                    subpart.metadata = dict(part.metadata)
                    subpart.metadata["start_index"] += offset
                    safe_parts.append(subpart)
            parts = safe_parts

        for index, part in enumerate(parts, start=1):
            if not part.page_content.strip():
                continue

            metadata = dict(part.metadata)
            start = metadata["start_index"]
            end = start + len(part.page_content)

            # 来源定位不准确时停止，避免生成错误引用
            if start < 0 or original_text[start:end] != part.page_content:
                raise ValueError(f"无法准确定位文本块：{metadata['document_id']}")

            metadata.update({
                "chunk_id": f"{metadata['document_id']}::chunk:{index}",
                "chunk_index": index,
                "end_index": end,
                "char_count": len(part.page_content),
            })

            if metadata["file_type"] == "txt":
                # start/end 是全文中的字符位置；行号从 1 开始
                metadata["line_start"] = original_text.count("\n", 0, start) + 1
                metadata["line_end"] = original_text.count("\n", 0, end - 1) + 1

            result.append({
                "text": part.page_content,
                "metadata": metadata,
            })

    return result


def create_converter(options):
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions, OcrMode
        from docling.document_converter import DocumentConverter, PdfFormatOption, ImageFormatOption
    except ImportError as error:
        raise ValueError("Docling 依赖不可用，请运行 python -m pip install -r requirements.txt") from error

    pipeline = PdfPipelineOptions()
    pipeline.do_ocr = options.ocr
    pipeline.do_table_structure = True
    pipeline.table_structure_options.do_cell_matching = True
    pipeline.ocr_options = RapidOcrOptions(
        backend="onnxruntime", mode=OcrMode.FULL_PAGE if options.force_full_page_ocr else OcrMode.DEFAULT,
    )
    pipeline.enable_remote_services = False
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.IMAGE, InputFormat.DOCX,
                         InputFormat.PPTX, InputFormat.XLSX, InputFormat.MD, InputFormat.HTML],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline),
        },
    )


def docling_chunks(files, source_dir, tokenizer, options):
    """保留文档结构、标题、表格列名和真实来源；按 E5 token 预算切分。"""
    if not files:
        return []
    converter = create_converter(options)
    from docling.datamodel.base_models import ConversionStatus
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
    from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer
    from docling_core.transforms.serializer.base import BaseSerializerProvider
    from docling_core.transforms.serializer.markdown import MarkdownTableSerializer

    class TableSerializerProvider(BaseSerializerProvider):
        def get_serializer(self, doc):
            return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())

    # 为 passage: 前缀与特殊 token 留余量；最后再检查实际输入长度。
    chunker = HybridChunker(
        tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=480),
        merge_peers=False,
        repeat_table_header=True,
        serializer_provider=TableSerializerProvider(),
    )
    chunks = []
    for path in files:
        source = path.relative_to(source_dir).as_posix()
        print(f"Docling 解析：{source}", flush=True)
        try:
            result = converter.convert(path, raises_on_error=True)
        except Exception as error:
            raise ValueError(
                f"Docling 无法解析 {source}（{type(error).__name__}）。"
                "请检查文件、依赖和模型下载；未将失败文件静默跳过。"
            ) from error
        if result.status != ConversionStatus.SUCCESS:
            raise ValueError(f"Docling 解析不完整：{source}，状态 {result.status}，请检查原文件。")
        count = 0
        for number, chunk in enumerate(chunker.chunk(dl_doc=result.document), 1):
            text = chunker.contextualize(chunk=chunk)
            if not text.strip():
                continue
            items = chunk.meta.doc_items
            pages = sorted({p.page_no for item in items for p in item.prov})
            sheets = []
            if path.suffix.lower() == ".xlsx":
                for item in items:
                    parent = item.parent
                    while parent is not None:
                        group = parent.resolve(result.document)
                        if getattr(group.label, "value", "") == "sheet" and group.name not in sheets:
                            sheets.append(group.name)
                        parent = group.parent
                if sheets:
                    text = "Sheet: " + ", ".join(sheets) + "\n" + text
            metadata = {
                "document_id": f"{source}::docling",
                "chunk_id": f"{source}::docling::chunk:{number}",
                "chunk_index": number,
                "source": source,
                "source_path": str(path),
                "file_type": path.suffix.lower().lstrip("."),
                "parser": "docling",
                "headings": list(chunk.meta.headings or []),
                "doc_items": [item.self_ref for item in items],
                "content_types": sorted({item.label.value for item in items}),
                "pages": pages,
                "sheets": sheets,
                "char_count": len(text),
            }
            if pages:
                metadata["page"] = pages[0]
            if path.suffix.lower() == ".pptx":
                metadata["slides"] = pages
            chunks.append({"text": text, "metadata": metadata})
            count += 1
        if not count:
            raise ValueError(f"{source} 未提取到可检索内容。请检查 OCR，或补充图片的文字说明。")
        print(f"  生成 {count} 个结构化文本块。", flush=True)
    return chunks


def prepare_chunks(knowledge_base, tokenizer, options=None):
    """统一入口：扫描 → 按格式读取与切分 → 校验，返回 {text, metadata} 列表。"""
    options = options or IngestionOptions()
    source_dir = Path(knowledge_base).resolve()
    files = scan_sources(source_dir)
    text_files = [p for p in files if p.suffix.lower() in {".txt", ".csv"}]
    structured_files = [p for p in files if p.suffix.lower() in DOCLING_EXTENSIONS]
    documents = load_txt_csv_documents(text_files, source_dir)
    chunks = make_text_chunks(documents, tokenizer=tokenizer)
    chunks.extend(docling_chunks(structured_files, source_dir, tokenizer, options))
    if not chunks:
        raise ValueError("知识库没有可检索的文本。")
    ids = [chunk["metadata"]["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("存在重复文本块 ID。")
    for chunk in chunks:
        count = len(tokenizer.encode("passage: " + chunk["text"], truncation=False))
        chunk["metadata"]["token_count"] = count
        if count > 512:
            raise ValueError(f"文本块超过 E5 的 512 token 限制：{chunk['metadata']['chunk_id']}。"
                             "请缩短异常长的标题或表头后重试；未截断内容。")
    return chunks
