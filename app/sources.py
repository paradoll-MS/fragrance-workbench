"""Extract searchable text and image regions with source locations."""

from base64 import b64decode, b64encode
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import re


MAX_UPLOAD = 30 * 1024 * 1024


def decode_upload(data):
    try:
        raw = b64decode(data.get("base64", ""), validate=True)
    except ValueError as exc:
        raise ValueError("文件内容无法读取") from exc
    if not raw or len(raw) > MAX_UPLOAD:
        raise ValueError("文件必须非空，且不超过 30 MB")
    return raw


def extract_source(name, raw, vision=None):
    extension = Path(name).suffix.lower()
    segments, images, warnings = [], [], []

    def add(locator, value, kind="verbatim"):
        value = re.sub(r"\n{3,}", "\n\n", value.replace("\x00", "")).strip()
        if value:
            segments.append({"locator": locator, "kind": kind, "text": value})

    if extension in (".txt", ".md", ".csv", ".tsv"):
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                text = None
        if text is None:
            raise ValueError("无法识别文本编码，请另存为 UTF-8")
        lines = text.splitlines()
        offset = 0
        if "---原文开始---" in lines and "---原文结束---" in lines:
            offset = lines.index("---原文开始---") + 1
            lines = lines[offset:lines.index("---原文结束---", offset)]
        for start in range(0, len(lines), 24):
            end = min(start + 24, len(lines))
            add(f"第 {offset + start + 1}–{offset + end} 行", "\n".join(lines[start:end]))
    elif extension == ".pdf":
        import pymupdf

        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            for number, page in enumerate(pdf, 1):
                loc = f"第 {number} 页"
                text = page.get_text(sort=True).strip()
                if text:
                    add(loc, text)
                else:
                    images.append((loc, page.get_pixmap(dpi=150, alpha=False).tobytes("png")))
    elif extension == ".docx":
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        doc = Document(BytesIO(raw))
        for number, block in enumerate(doc.element.body, 1):
            if block.tag == qn("w:p"):
                add(f"段落 {number}", Paragraph(block, doc).text)
            elif block.tag == qn("w:tbl"):
                table = Table(block, doc)
                for row_number, row in enumerate(table.rows, 1):
                    add(f"表格 {number} · 第 {row_number} 行", " | ".join(cell.text for cell in row.cells))
            for index, blip in enumerate(block.iter(qn("a:blip")), 1):
                part = doc.part.related_parts.get(blip.get(qn("r:embed")))
                if part and part.content_type.startswith("image/"):
                    images.append((f"块 {number} · 图 {index}", part.blob))
    elif extension == ".pptx":
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE

        def walk(shapes):
            for shape in shapes:
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    yield from walk(shape.shapes)
                else:
                    yield shape

        slides = Presentation(BytesIO(raw)).slides
        for number, slide in enumerate(slides, 1):
            text, slide_images = [], []
            for shape in walk(slide.shapes):
                if shape.has_text_frame:
                    text.append(shape.text)
                if shape.has_table:
                    text.extend(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    slide_images.append(shape.image.blob)
            add(f"幻灯片 {number}", "\n".join(text))
            images.extend((f"幻灯片 {number} · 图 {i}", blob) for i, blob in enumerate(slide_images, 1))
    elif extension == ".xlsx":
        from openpyxl import load_workbook

        book = load_workbook(BytesIO(raw), read_only=True, data_only=True)
        try:
            for sheet in book.worksheets:
                for number, row in enumerate(sheet.values, 1):
                    if number > 3000:
                        warnings.append(f"工作表 {sheet.title} 第 3001 行起需另分文件读取")
                        break
                    fields = [str(cell) if cell is not None else "" for cell in row]
                    if any(fields):
                        add(f"{sheet.title} · 第 {number} 行", " | ".join(fields).rstrip(" |"))
        finally:
            book.close()
    elif extension in (".png", ".jpg", ".jpeg", ".webp"):
        images.append(("图片", raw))
    else:
        warnings.append("此格式已保存原件，可补充文字")
    if images:
        if vision:
            batch = images[:16]

            def read_image(image):
                locator, content = image
                try:
                    return locator, vision(image_url(content)), None
                except (OSError, ValueError):
                    return locator, "", f"{locator} 视觉读取失败，可重试或补文字"

            with ThreadPoolExecutor(max_workers=4) as executor:
                for locator, text, issue in executor.map(read_image, batch):
                    if issue or not text:
                        warnings.append(issue or f"{locator} 未发现可读内容")
                    else:
                        add(locator, text, "visual")
        else:
            batch = []
        for locator, _ in images[len(batch):]:
            warnings.append(f"{locator} 待视觉读取")
    return {"segments": segments, "warnings": warnings,
            "status": "partial" if warnings and segments else "ready" if segments else "needs_text"}


def image_url(raw):
    from PIL import Image, ImageOps

    with Image.open(BytesIO(raw)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1800, 1800))
        out = BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + b64encode(out.getvalue()).decode("ascii")
