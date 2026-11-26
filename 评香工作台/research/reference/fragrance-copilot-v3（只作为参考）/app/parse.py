"""File text extraction.

Every extractor returns:
  {"text": str, "page_count": int|None, "meta": [...], "assets": [...],
   "extractor": str, "status": "parsed"|"needs_text"|"error", "error": str|None,
   "warnings": [...]}
meta  = [{"locator": "第3页", "text": "..."}]  -- 文字块，用于引用
assets = [{"locator": "第3页/图1", "data": b"...", "mime": "image/png"}] -- 待视觉识别的图片
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
if VENDOR.exists() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

MAX_TEXT = 300_000
MAX_CHUNKS = 800
CHUNK_CHARS = 1500


def _clean(s: str) -> str:
    s = (s or "").replace("\x00", " ")
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{4,}", "\n\n\n", s)
    return s.strip()


def _result(text: str, chunks: list[dict], extractor: str, page_count=None,
            status="parsed", error=None, assets=None, warnings=None):
    text = _clean(text)
    truncated = len(text) > MAX_TEXT
    if truncated:
        text = text[:MAX_TEXT] + "\n\n[内容过长，已截断；请拆分原文件]"
    warnings = list(warnings or [])
    if len(chunks) > MAX_CHUNKS:
        head = chunks[: MAX_CHUNKS - 1]
        tail_text = "\n".join(c["text"] for c in chunks[MAX_CHUNKS - 1:])
        head.append({"locator": f"第{MAX_CHUNKS}块起（尾部合并）", "text": tail_text[:20000]})
        chunks = head
        warnings.append(f"块数超过 {MAX_CHUNKS}，尾部已合并")
    return {"text": text, "page_count": page_count, "meta": chunks,
            "assets": list(assets or []),
            "extractor": extractor, "status": 'needs_text' if truncated else status,
            "incomplete": truncated, "warnings": warnings,
            "error": '资料超过解析容量，已保留原件，请拆分文件' if truncated else error}


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
            return _result("", [{"locator": "图片 1", "text": ""}], "image", status="needs_text",
                           assets=[{"locator": "图片 1", "data": p.read_bytes(),
                                    "mime": mime or f"image/{'jpeg' if ext in ('jpg', 'jpeg') else ext}"}],
                           error="图片待视觉识别。")
        if ext in ("wav", "mp3", "m4a", "aac", "ogg", "flac", "amr"):
            return _result("", [{"locator": "音频", "text": ""}], "audio",
                           status="needs_text",
                           error="音频已保存。可点“语音转写”（需 Qwen 密钥，单段≤7MB/5分钟），或上传会议纪要文字。")
        if ext in ("mp4", "mov", "avi", "mkv", "webm"):
            return _result("", [{"locator": "视频", "text": ""}], "video",
                           status="needs_text",
                           error="视频已保存。第一版不做视频理解，请提供转写文字和关键画面截图。")
        return _result("", [{"locator": name, "text": ""}], "unknown",
                       status="error", error=f"暂不支持 .{ext} 的自动解析，请人工补充摘录。")
    except Exception as e:  # 文件不丢，但状态必须是 error，不能混成 needs_text
        return _result("", [{"locator": name, "text": ""}], ext or "unknown",
                       status="error", error=f"解析失败：{type(e).__name__}: {e}")


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
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(p))
    chunks, parts, assets = [], [], []
    buf, buf_start, buf_chars = [], 0, 0
    n = 0  # 段号
    ti = 0

    def flush_paras(end):
        nonlocal buf, buf_start, buf_chars
        if not buf:
            return
        loc = f"第{buf_start}段" if buf_start == end else f"第{buf_start}-{end}段"
        txt = "\n".join(buf)
        parts.append(txt)
        chunks.append({"locator": loc, "text": txt})
        buf, buf_start, buf_chars = [], 0, 0

    for element in d.element.body:
        if element.tag.endswith('}p'):
            para = Paragraph(element, d)
            # 图片先于文字入 assets，保证图不会因段落为空而丢
            for bi, blip in enumerate(element.iter(qn('a:blip')), 1):
                rid = blip.get(qn('r:embed'))
                part = d.part.related_parts.get(rid) if rid else None
                blob = getattr(part, 'blob', None)
                if blob:
                    assets.append({"locator": f"第{n + 1}段/图{bi}", "data": blob,
                                   "mime": getattr(part, 'content_type', 'image/png')})
            t = para.text.strip()
            if not t:
                continue
            n += 1
            if not buf:
                buf_start = n
            buf.append(t)
            buf_chars += len(t)
            if buf_chars >= CHUNK_CHARS:
                flush_paras(n)
        elif element.tag.endswith('}tbl'):
            ti += 1
            table = Table(element, d)
            rows = [' | '.join(c.text.strip().replace('\n', ' ') for c in row.cells) for row in table.rows]
            if any(rows):
                flush_paras(n)
                txt = f'[表{ti}]\n' + '\n'.join(rows)
                parts.append(txt)
                chunks.append({'locator': f'表{ti}', 'text': txt})
    flush_paras(n)
    warnings = [f"内嵌图片 {len(assets)} 张，已提交视觉识别"] if assets else []
    return _result("\n\n".join(parts), chunks, "docx", assets=assets, warnings=warnings)


def _pptx(p: Path) -> dict:
    from pptx import Presentation  # type: ignore
    from pptx.enum.shapes import MSO_SHAPE_TYPE  # type: ignore

    prs = Presentation(str(p))
    parts, chunks, assets = [], [], []
    for i, slide in enumerate(prs.slides, 1):
        st, imgs = [], 0
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
            if getattr(sh, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = sh.image.blob
                    imgs += 1
                    assets.append({"locator": f"第{i}页/图{imgs}", "data": blob,
                                   "mime": sh.image.content_type or "image/png"})
                except Exception:
                    pass
        if getattr(slide, "has_notes_slide", False):
            nt = slide.notes_slide.notes_text_frame.text.strip()
            if nt:
                st.append("[演讲者备注] " + nt)
        txt = "\n".join(st)
        if txt:
            parts.append(f"第{i}页\n{txt}")
            chunks.append({"locator": f"第{i}页", "text": txt})
    warnings = [f"内嵌图片 {len(assets)} 张，已提交视觉识别"] if assets else []
    return _result("\n\n".join(parts), chunks, "pptx", page_count=len(prs.slides),
                   assets=assets, warnings=warnings)


def _xlsx(p: Path) -> dict:
    import openpyxl  # type: ignore
    wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
    parts, chunks, assets = [], [], []
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
        try:
            for im in getattr(ws, "_images", []) or []:
                blob = im._data()
                assets.append({"locator": f"工作表 {ws.title}/图{len(assets) + 1}",
                               "data": blob, "mime": getattr(im, 'format', 'png') and 'image/png'})
        except Exception:
            pass
    return _result("\n\n".join(parts), chunks, "xlsx", page_count=len(wb.worksheets), assets=assets)


def _pdf(p: Path) -> dict:
    from pypdf import PdfReader  # type: ignore

    r = PdfReader(str(p))
    parts, chunks, assets, missing = [], [], [], []
    for i, page in enumerate(r.pages, 1):
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            parts.append(f"第{i}页\n{t.strip()}")
            chunks.append({"locator": f"第{i}页", "text": t.strip()})
            continue
        before = len(assets)
        try:
            for im in page.images:
                raw = getattr(im, "data", b"")
                if raw and len(raw) < 12 * 1024 * 1024:
                    ext = Path(getattr(im, 'name', 'image.jpg')).suffix or '.jpg'
                    mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}.get(ext.lower(), 'image/jpeg')
                    assets.append({"locator": f"第{i}页/图{len(assets) - before + 1}", "data": raw, "mime": mime})
        except Exception:
            pass
        if len(assets) == before:
            # 没有文字层也没有内嵌图：整页渲染成图片，保证扫描页不会变成"空"
            try:
                import pymupdf  # type: ignore
                doc = pymupdf.open(str(p))
                pix = doc[i - 1].get_pixmap(dpi=150)
                assets.append({"locator": f"第{i}页/图1", "data": pix.tobytes("png"), "mime": "image/png"})
                doc.close()
            except Exception:
                missing.append(i)
    text = "\n\n".join(parts)
    warnings = []
    if assets:
        warnings.append(f"图片 {len(assets)} 张（含扫描页渲染），已提交视觉识别")
    if missing:
        warnings.append(f"第{missing}页没有文字或可识别图片")
    if not text.strip():
        status = "needs_text" if assets else "error"
        err = ("PDF 无文字层，已渲染页面图片待视觉识别。" if assets
               else "PDF 未提取到文字，也无法渲染页面图片。")
        return _result("", [], "pdf", page_count=len(r.pages), status=status,
                       error=err, assets=assets, warnings=warnings)
    return _result(text, chunks, "pdf", page_count=len(r.pages), assets=assets,
                   warnings=warnings, status="needs_text" if missing else "parsed")


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
