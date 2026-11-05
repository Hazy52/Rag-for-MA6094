"""E5 嵌入模型与内存向量索引；资料读取和切分统一由 ingestion.py 负责。"""
from pathlib import Path

from ingestion import prepare_chunks


def load_tokenizer():
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(
        "intfloat/multilingual-e5-small",
        cache_dir=str(Path(__file__).resolve().parent / "models"),
    )


def build_index(knowledge_base, options=None):
    """每批次解析一次、建库一次，返回内存索引和 tokenizer。"""
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_core.vectorstores import InMemoryVectorStore

    tokenizer = load_tokenizer()
    chunks = prepare_chunks(knowledge_base, tokenizer, options)
    print("正在加载 E5 嵌入模型并建立向量索引……", flush=True)
    embeddings = HuggingFaceEmbeddings(
        model_name="intfloat/multilingual-e5-small",
        cache_folder=str(Path(__file__).resolve().parent / "models"),
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True, "prompt": "passage: ", "batch_size": 16},
        query_encode_kwargs={"normalize_embeddings": True, "prompt": "query: "},
    )
    vectorstore = InMemoryVectorStore(embeddings)
    vectorstore.add_texts(
        texts=[chunk["text"] for chunk in chunks],
        metadatas=[chunk["metadata"] for chunk in chunks],
        ids=[chunk["metadata"]["chunk_id"] for chunk in chunks],
    )
    print(f"索引建立成功，共加入 {len(chunks)} 个文本块。")
    return vectorstore, tokenizer
