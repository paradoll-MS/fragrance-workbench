"""File text extraction.

Every extractor returns:
  {"text": str, "page_count": int|None, "meta": [...], "extractor": str,
   "status": "parsed"|"needs_text", "error": str|None}
meta is a list of {"locator": "第3页", "text": "..."} used for citations.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
if VENDOR.exists() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

MAX_TEXT = 300_000
MAX_CHUNKS = 400


def _clean(s: str) -> str:
    s = (s or "").replace("\x00", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{4,}", "\n\n\n", s)
    return s.strip()


def _result(text: str, chunks: list[dict], extractor: str, page_count=None,
            status="parsed", error=None):
    text = _clean(text)
    truncated = len(text) > MAX_TEXT
    if truncated:
        text = text[:MAX_TEXT] + "\n\n[内容过长，已截断；请拆分原文件]"
    if len(chunks) > MAX_CHUNKS:
        # merge tail chunks
        head = chunks[: MAX_CHUNKS - 1]
        tail_text = "\n".join(c["text"] for c in chunks[MAX_CHUNKS - 1:])
        head.append({"locator": "后段", "text": tail_text[:20000]})
        chunks = head
    return {"text": text, "page_count": page_count, "meta": chunks,
            "extractor": extractor, "status": 'needs_text' if truncated else status,
            "incomplete": truncated, "error": '资料超过解析容量，已保留原件，请拆分文件' if truncated else error}


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def extract(path: str | Path, filename: str | None = None, mime: str | None = None) -> dict:
    p = Path(path)
    name = filename or p.name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        if ext in ("txt", "md", "markdown", "csv", "tsv", "log", "json", "xml", "yaml", "yml"):
            return _text_file(p, ext)
        if ext == "docx":
            return _docx(p)
        if ext in ("pptx", "pptm"):
            return _pptx(p)
        if ext in ("xlsx", "xlsm"):
            return _xlsx(p)
        if ext == "pdf":
            return _pdf(p)
        if ext in ("html", "htm"):
            return _html(p)
        if ext in ("png", "jpg", "jpeg", "webp", "bmp", "gif", "heic"):
            return _result("", [{"locator": "图片", "text": ""}], "image",
                           status="needs_text",
                           error="图片已保存。可点“视觉识别”让模型描述可见文字与外观，或人工补充摘录。")
        if ext in ("wav", "mp3", "m4a", "aac", "ogg", "flac", "amr"):
            return _result("", [{"locator": "音频", "text": ""}], "audio",
                           status="needs_text",
                           error="音频已保存。可点“语音转写”（需 Qwen 密钥，单段≤7MB/5分钟），或上传会议纪要文字。")
        if ext in ("mp4", "mov", "avi", "mkv", "webm"):
            return _result("", [{"locator": "视频", "text": ""}], "video",
                           status="needs_text",
                           error="视频已保存。第一版不做视频理解，请提供转写文字和关键画面截图。")
        return _result("", [{"locator": name, "text": ""}], "unknown",
                       status="needs_text", error=f"暂不支持 .{ext} 的自动解析，请人工补充摘录。")
    except Exception as e:  # never lose the file because parsing failed
        return _result("", [{"locator": name, "text": ""}], ext or "unknown",
                       status="needs_text", error=f"解析失败：{type(e).__name__}: {e}")


def _text_file(p: Path, ext: str) -> dict:
    text = _decode(p.read_bytes())
    lines = text.splitlines()
    chunks = []
    buf, start = [], 0
    for i, line in enumerate(lines, 1):
        buf.append(line)
        if len(buf) >= 40:
            chunks.append({"locator": f"第{start+1}-{i}行", "text": "\n".join(buf)})
            buf, start = [], i
    if buf:
        chunks.append({"locator": f"第{start+1}-{len(lines)}行", "text": "\n".join(buf)})
    if not chunks:
        chunks = [{"locator": "全文", "text": text}]
    return _result(text, chunks, ext, page_count=len(lines))


def _docx(p: Path) -> dict:
    import docx  # type: ignore
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    d = docx.Document(str(p))
    chunks, parts = [], []
    n, ti = 0, 0
    # Preserve source order: moving every table to the end can change what it qualifies.
    for element in d.element.body:
        if element.tag.endswith('}p'):
            para = Paragraph(element, d)
            t = para.text.strip()
            if t:
                n += 1; parts.append(t)
                chunks.append({'locator':f'第{n}段', 'text':t})
        elif element.tag.endswith('}tbl'):
            ti += 1
            table = Table(element, d)
            rows = [' | '.join(c.text.strip().replace('\n', ' ') for c in row.cells) for row in table.rows]
            if any(rows):
                txt = f'[表{ti}]\n' + '\n'.join(rows)
                parts.append(txt); chunks.append({'locator':f'表{ti}', 'text':txt})
    return _result("\n\n".join(parts), chunks, "docx")


def _pptx(p: Path) -> dict:
    from pptx import Presentation  # type: ignore
    prs = Presentation(str(p))
    parts, chunks = [], []
    for i, slide in enumerate(prs.slides, 1):
        st = []
        for sh in slide.shapes:
            if getattr(sh, "has_text_frame", False):
                t = sh.text_frame.text.strip()
                if t:
                    st.append(t)
            if getattr(sh, "has_table", False):
                for row in sh.table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    if any(cells):
                        st.append(" | ".join(cells))
        if getattr(slide, "has_notes_slide", False):
            nt = slide.notes_slide.notes_text_frame.text.strip()
            if nt:
                st.append("[演讲者备注] " + nt)
        txt = "\n".join(st)
        if txt:
            parts.append(f"第{i}页\n{txt}")
            chunks.append({"locator": f"第{i}页", "text": txt})
    return _result("\n\n".join(parts), chunks, "pptx", page_count=len(prs.slides))


def _xlsx(p: Path) -> dict:
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
    parts, chunks = [], []
    for ws in wb.worksheets:
        rows = []
        for ri, row in enumerate(ws.iter_rows(values_only=True), 1):
            if ri > 5000:
                rows.append("[超过 5000 行，已截断]")
                break
            vals = [str(c).strip() if c is not None else "" for c in row]
            if any(vals):
                rows.append(f"R{ri}: " + " | ".join(vals))
        txt = "\n".join(rows)
        if txt:
            parts.append(f"[工作表：{ws.title}]\n{txt}")
            chunks.append({"locator": f"工作表 {ws.title}", "text": txt})
    return _result("\n\n".join(parts), chunks, "xlsx", page_count=len(wb.worksheets))


def _pdf(p: Path) -> dict:
    from pypdf import PdfReader  # type: ignore
    r = PdfReader(str(p))
    parts, chunks, images, missing = [], [], [], []
    for i, page in enumerate(r.pages, 1):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            parts.append(f"第{i}页\n{t.strip()}")
            chunks.append({"locator": f"第{i}页", "text": t.strip()})
        else:
            # 扫描件常见：页面没有文字层，但内嵌整页图片；交给视觉模型做深度理解
            before = len(images)
            try:
                for im in page.images:
                    raw = getattr(im, "data", b"")
                    if raw and len(raw) < 12 * 1024 * 1024:
                        ext = Path(getattr(im, 'name', 'image.jpg')).suffix
                        images.append({"name": f"p{i}_{getattr(im, 'name', 'image')}", "locator": f'第{i}页',
                                       "mime": __import__('mimetypes').guess_type('image'+ext)[0] or 'image/jpeg', "data": raw})
            except Exception:
                pass
            if len(images) == before:
                missing.append(i)
    text = "\n\n".join(parts)
    if not text.strip():
        res = _result("", [], "pdf", page_count=len(r.pages), status="needs_text",
                      error="PDF 未提取到文字（可能是扫描件）。正在尝试页面图片视觉识别；也可上传截图。")
        res["images"] = images
        if missing:
            res.update(incomplete=True, error=f'第{missing}页没有文字或可识别图片，请补充截图/摘录')
        return res
    res = _result(text, chunks, "pdf", page_count=len(r.pages))
    res['images'] = images
    if missing:
        res.update(incomplete=True, status='needs_text', error=f'第{missing}页未解析，请补充截图/摘录')
    return res


def _html(p: Path) -> dict:
    raw = _decode(p.read_bytes())
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", raw)
    txt = re.sub(r"&nbsp;", " ", txt)
    txt = re.sub(r"&amp;", "&", txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    return _result(txt, [{"locator": "全文", "text": txt}], "html")


def chunk_text(text: str, size: int = 1200, overlap: int = 120) -> list[dict]:
    """Utility for QA over a long text without page metadata."""
    text = text or ""
    out = []
    i = 0
    n = 1
    while i < len(text):
        piece = text[i:i + size]
        out.append({"locator": f"片段{n}", "text": piece})
        i += max(1, size - overlap)
        n += 1
    return out
