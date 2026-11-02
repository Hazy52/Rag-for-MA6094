"""原有读取、CSV 修复、递归分块和 E5 检索逻辑；导入时不会运行。"""


# =============================================================================
# 知识库准备流程：由 main.py 的 main() 调用，每个问题批次只执行一次。
#
# 步骤 1：读取 PDF / TXT / CSV，得到原始文字和位置。
# 步骤 2：统一成 {text, metadata}，保留可追溯来源。
# 步骤 3：递归字符分块，得到 chunks。
# 步骤 4：加载本地 E5 嵌入模型，检查各块的 token 长度。
# 步骤 5：将文本块向量化，创建并填充内存向量索引。
# 随后返回 main.py 的 run_batch()，执行召回、模型生成和双语报告导出。
#
# 主要变量：files = 文件清单；documents = 统一后的资料；chunks = 切分后的块；
# embeddings = 文本转向量的模型；vectorstore = 保存向量、原文和来源的索引。
# 这里没有调用 DeepSeek，也没有训练或微调模型。
# =============================================================================
def extract_pdf_positions(page):
    """保留原有提取文字，同时记录文字在可见页面上、中、下三等分的位置。"""
    import math
    pieces, spans = [], []
    offset = 0
    box = page.cropbox
    left, bottom, right, top = map(float, (box.left, box.bottom, box.right, box.top))
    width, height = right - left, top - bottom
    rotation = int(page.rotation or 0) % 360

    def visitor(text, cm, tm, font, size):
        nonlocal offset
        start = offset
        pieces.append(text)
        offset += len(text)
        if not text.strip() or width <= 0 or height <= 0:
            return
        # 多行合并在一次回调中时，单个坐标不足以定位所有行，因此不猜测。
        if len([line for line in text.splitlines() if line.strip()]) > 1:
            return
        # 文本矩阵与当前变换矩阵相乘，得到页面坐标，不能只使用 tm 的 y。
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        if not (math.isfinite(x) and math.isfinite(y) and left <= x <= right and bottom <= y <= top):
            return
        # ratio 是在阅读器显示的页面上，从上到下的位置比例，兼容页面旋转。
        ratios = {0: (top - y) / height, 90: (x - left) / width,
                  180: (y - bottom) / height, 270: (right - x) / width}
        if rotation not in ratios:
            return
        band = min(2, int(ratios[rotation] * 3))
        spans.append((start, offset, band))

    text = page.extract_text(visitor_text=visitor) or ""
    # 无法将回调文字与最终原文精确对应时，仅保留页码。
    if "".join(pieces) != text:
        spans = []
    return text, spans


def pdf_chunk_region(text, spans, start, end):
    """按文本块实际覆盖的页面区域定位；跨区域时保留范围。"""
    covered, bands = 0, set()
    for a, b, band in spans:
        a, b = max(a, start), min(b, end)
        if a < b:
            count = sum(not char.isspace() for char in text[a:b])
            if count:
                covered += count
                bands.add(band)
    total = sum(not char.isspace() for char in text[start:end])
    # 有非空文字无法定位，就不为整个片段附加可能误导的方位。
    if not total or covered != total or not bands:
        return ""
    names = ("top", "middle", "bottom")
    return names[min(bands)] if len(bands) == 1 else f"{names[min(bands)]}-{names[max(bands)]}"


def build_index(knowledge_base):
    """每个批次调用一次，返回内存索引和用于检查查询长度的 tokenizer。"""
    from pathlib import Path

    # -------------------- 步骤 1A：扫描知识库目录 --------------------
    # 这里只收集资料路径，不会扫描项目里的 Questions、模型缓存或桌面报告。
    # 原始资料所在的目录
    source_dir = Path(knowledge_base).resolve()

    # 自动扫描整个资料目录及其子文件夹
    sources = [source_dir]

    files = []

    for source in sources:
        if not source.exists():
            raise FileNotFoundError(f"找不到资料：{source}")

        if source.is_file():
            files.append(source)
        else:
            # 搜索资料包及其所有子文件夹
            for path in sorted(source.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".pdf", ".txt", ".csv"}:
                    files.append(path)

    print(f"共找到 {len(files)} 个资料文件：")

    for index, path in enumerate(files, start=1):
        print(f"{index}. [{path.suffix}] {path.name}")

    # -------------------- 步骤 1B：读取 PDF，按页提取文字 --------------------
    # 一页对应一条原始资料，保留从 1 开始的页码；本程序不执行图片 OCR。
    # 如果是扫描件且页面没有可提取文字，会提示检查。
    from pypdf import PdfReader

    # 保存从 PDF 中提取的每页文字及来源信息
    pdf_pages = []

    for path in files:
        if path.suffix.lower() != ".pdf":
            continue

        reader = PdfReader(path)
        print(f"\n正在读取：{path.name}，共 {len(reader.pages)} 页")

        for page_number, page in enumerate(reader.pages, start=1):
            text, position_spans = extract_pdf_positions(page)
            pdf_pages.append({
                "source": path.name,
                "source_path": str(path),
                "page": page_number,
                "pdf_spans": position_spans,
                "text": text,
            })

            print(f"  第 {page_number} 页：提取到 {len(text)} 个字符")
            if not text.strip():
                print("  注意：这一页没有提取到文字，需要进一步检查。")

    print(f"\n共读取 {len(pdf_pages)} 页 PDF。")

    # -------------------- 步骤 1C：读取 TXT 全文 --------------------
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

    # -------------------- 步骤 1D：读取 CSV，每条记录独立处理 --------------------
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
    # text 是可以检索的正文；metadata 是文件路径、页码、记录 ID 等来源信息。
    # 元数据跟着文本一路进入分块和索引，最终用于给回答添加出处。
    # 本步骤不生成答案，也不改变原始资料中互相矛盾的事实。
    # 统一三种资料格式：每条资料都包含 text（正文）和 metadata（来源信息）
    documents = []


    def add_document(record, file_type, unit, **location):
        """保留原文，给一页 PDF、一个 TXT 文件或一条 CSV 记录添加统一来源信息。"""
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
            "pdf_spans": record.get("pdf_spans", []),
        })


    # PDF：一页对应一条资料，保留从 1 开始的页码
    for record in pdf_pages:
        add_document(
            record, "pdf", f"page:{record['page']}",
            page=record["page"],
        )

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
    for file_type in ("pdf", "txt", "csv"):
        count = sum(doc["metadata"]["file_type"] == file_type for doc in documents)
        print(f"{file_type.upper()}：{count} 条资料")
    print(f"共 {len(documents)} 条资料；尚未分块。")

    # -------------------- 步骤 3：递归字符分块（Chunking） --------------------
    # 输入：documents；输出：chunks，每块同时携带自己的正文和来源。
    # 优先保留较大的自然边界，超长部分再尝试更细的分隔符。
    # 800 是最大字符数；120 是目标重叠上限，实际重叠由文本边界决定。
    # 重叠可以减少边界信息丢失，但不能保证句子或语义总是完整。
    # 当前是普通递归分块，没有父子块映射或父块回取逻辑。
    # 递归字符分块：先按段落，再按换行、空格，最后按字符切分
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # 这里的单位是字符，不是英文单词，也不是模型 token
    CHUNK_SIZE = 800
    CHUNK_OVERLAP = 120


    def make_chunks(source_documents, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP):
        """每条原始资料单独切分；保留来源和字符位置，计算 TXT 的实际行号。"""
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
            # 每次只传入一条资料，不把不同文件、PDF 页或 CSV 记录拼接
            parts = splitter.create_documents(
                [original_text],
                metadatas=[document["metadata"]],
            )

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

                if metadata["file_type"] == "pdf":
                    # 页面按可见高度分三等份；不是按字符数量或块编号猜方位。
                    region = pdf_chunk_region(original_text, document["pdf_spans"], start, end)
                    if region:
                        metadata["pdf_region"] = region

                if metadata["file_type"] == "txt":
                    # start/end 是全文中的字符位置；行号从 1 开始
                    metadata["line_start"] = original_text.count("\n", 0, start) + 1
                    metadata["line_end"] = original_text.count("\n", 0, end - 1) + 1

                result.append({
                    "text": part.page_content,
                    "metadata": metadata,
                })

        return result


    # 上面只是定义 make_chunks；执行下面这一行时才真正切分所有资料。
    chunks = make_chunks(documents)

    print("\n===== 递归分块完成 =====")
    print(f"每块最多 {CHUNK_SIZE} 个字符；目标重叠最多 {CHUNK_OVERLAP} 个字符。")
    print(f"{len(documents)} 条原始资料生成 {len(chunks)} 个文本块。")
    for file_type in ("pdf", "txt", "csv"):
        count = sum(chunk["metadata"]["file_type"] == file_type for chunk in chunks)
        print(f"{file_type.upper()}：{count} 个文本块")

    # -------------------- 步骤 4A：准备嵌入模型（Embedding） --------------------
    # 使用本地 CPU 运行 multilingual-e5-small，把文本转换成 384 维语义向量。
    # 创建 embeddings 时主要加载模型；全部块的向量计算在步骤 5 的 add_texts 内触发。
    # models 文件夹保存下载的模型文件，不保存本次内存向量索引。
    from langchain_huggingface import HuggingFaceEmbeddings

    # 把模型文件缓存到当前项目的 models 文件夹
    model_cache = Path(__file__).resolve().parent / "models"

    print("\n正在加载嵌入模型，首次运行需要下载……")

    embeddings = HuggingFaceEmbeddings(
        model_name="intfloat/multilingual-e5-small",
        cache_folder=str(model_cache),
        model_kwargs={"device": "cpu"},
        # 资料编码配置：归一化向量，使用模型要求的 passage: 前缀。
        # batch_size=16 是每批编码的文本块数量，不是返回给用户的证据数量。
        encode_kwargs={
            "normalize_embeddings": True,
            "prompt": "passage: ",
            "batch_size": 16,
        },
        # 问题编码配置：召回时由索引调用，使用同一个模型及 query: 前缀。
        # 资料和问题使用匹配的编码方式，才能比较它们的语义相似程度。
        query_encode_kwargs={
            "normalize_embeddings": True,
            "prompt": "query: ",
        },
    )

    if not chunks:
        raise ValueError("知识库没有可检索的文本。")

    from langchain_core.vectorstores import InMemoryVectorStore
    from transformers import AutoTokenizer

    # -------------------- 步骤 4B：检查嵌入模型输入长度 --------------------
    # 字符数和 token 数不同，所以即使已经按 800 字符分块，也仍要检查 token。
    # tokenizer 只做 token 切分和计数；它不是实际的向量编码结果。
    # 检查文本块是否超过模型的输入长度限制，避免被悄悄截断
    tokenizer = AutoTokenizer.from_pretrained(
        "intfloat/multilingual-e5-small",
        cache_dir=str(model_cache),
        local_files_only=True,
    )

    for chunk in chunks:
        token_ids = tokenizer.encode(
            "passage: " + chunk["text"],
            add_special_tokens=True,
            truncation=False,
        )

        if len(token_ids) > 512:
            raise ValueError(
                f"文本块超过模型的 512 token 限制："
                f"{chunk['metadata']['chunk_id']}。"
                "请减小 CHUNK_SIZE 后重新运行。"
            )

    print("\n正在为全部文本块建立向量索引……")

    # -------------------- 步骤 5：计算向量并建立索引（Indexing） --------------------
    # InMemoryVectorStore 在运行内存中保存数据；关闭程序后，本次索引不会持久保存。
    # 新批次会根据当时的知识库重新建立索引，新增和删除的资料在下次运行生效。
    # 创建一个存放在内存中的向量索引
    vectorstore = InMemoryVectorStore(embeddings)

    # 正文、来源信息、块 ID 按相同顺序一一对应
    # 这一调用内部使用 embeddings 编码每个文本块，将向量、原文和 metadata 关联保存。
    # 三个列表顺序必须一致，才能保证召回的证据和引用位置相互对应。
    vectorstore.add_texts(
        texts=[chunk["text"] for chunk in chunks],
        metadatas=[chunk["metadata"] for chunk in chunks],
        ids=[chunk["metadata"]["chunk_id"] for chunk in chunks],
    )

    print(f"索引建立成功，共加入 {len(chunks)} 个文本块。")
    # 准备完成：把索引和 tokenizer 交回 main.py，接下来进入逐题召回流程。
    return vectorstore, tokenizer
