"""M08 知识库摄取管道：提取 -> 清洗 -> 中文标点感知重叠切块 -> 向量化入库。

pypdf 6.x（官方现行版）：PdfReader(path).pages[i].extract_text()。
切块策略（rag-skills 分块章节）：500 字/块、80 字重叠、优先在句读处断开。
chunk metadata: {source, page, chunk_id}，与 M07 出处卡字段一一对应。
"""
import re
from pathlib import Path

from app.kb import embedder, vectorstore

CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
_BREAKS = "。！？!?；;\n"
ALLOWED_SUFFIXES = (".pdf", ".txt", ".md")


def extract_pages(file_path):
    """按类型提取 -> [(页码, 文本)]；txt/md 视为单页。"""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    if suffix in (".txt", ".md"):
        return [(1, path.read_text(encoding="utf-8", errors="ignore"))]
    raise ValueError(f"不支持的文件类型: {suffix}（仅支持 PDF/TXT/MD）")


def clean_text(text):
    """清洗：统一换行、压缩空白、去多余空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """重叠切块：优先在句末标点断开（向前回溯不超过半块），块间保留 overlap 重叠。"""
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            cut = -1
            for i in range(end - 1, start + size // 2, -1):
                if text[i] in _BREAKS:
                    cut = i + 1
                    break
            if cut > 0:
                end = cut
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def ingest(file_path, source_name=None):
    """摄取单个文件；同名来源先删后写（重新上传即覆盖）。"""
    source = source_name or Path(file_path).name
    vectorstore.delete_by_source(source)

    ids, documents, metadatas = [], [], []
    for page_no, raw in extract_pages(file_path):
        for piece in chunk_text(clean_text(raw)):
            chunk_id = f"{source}::p{page_no}::c{len(ids)}"
            ids.append(chunk_id)
            documents.append(piece)
            metadatas.append({"source": source, "page": page_no, "chunk_id": chunk_id})

    if not documents:
        return {"source": source, "chunks": 0}

    embeddings = embedder.encode(documents)
    vectorstore.add(ids, embeddings, documents, metadatas)
    return {"source": source, "chunks": len(documents)}
