from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import uuid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 内存会话存储
_sessions: dict[str, list[dict]] = {}

# KB实例
_kb = None


def get_kb():
    global _kb
    if _kb is None:
        from app.modules.kb_module import get_kb as _get_kb, load_mock_data
        _kb = _get_kb()
        # 加载模拟数据
        load_mock_data()
        logger.info(f"KB loaded with {_kb.count()} entries")
    return _kb


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "blueprint"}


class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class ParseTextRequest(BaseModel):
    """纯文本解析请求（已有OCR结果时直接传文字）"""
    text: str


# 硬编码示例（保留作为 fallback）
BLUEPRINT_SAMPLE = {
    "material": "SUS304 Stainless Steel",
    "process": "CNC Machining + Surface Grinding",
    "dimensions": "L: 150mm x W: 80mm x H: 50mm",
    "tolerance": "+/-0.02mm",
    "bom": ["Base Plate x1", "Support Bracket x4", "Fastener M6 x12"],
    "sop": "1. Raw material inspection\n2. CNC rough cut\n3. Heat treatment\n4. Surface grinding\n5. QC inspection",
    "anomaly": "2024-03: Dimensional error, re-machined\n2024-05: Material defect, batch replaced",
    "maintenance": "2024-06: Equipment maintenance, lubricant replaced"
}

# 规则匹配关键词（对接 KB category）
RULE_CATEGORIES = {
    "material": ["material", "zhi cai", "材质", "材料", "钢材", "铝合金", "不锈钢"],
    "process": ["process", "gong yi", "工艺", "工序", "加工", "cnc", "铣削", "钣金", "折弯"],
    "surface": ["表面处理", "电镀", "喷涂", "阳极", "钝化", "镀镍", "镀铬", "surface treatment"],
    "tolerance": ["tolerance", "gong cha", "公差", "精度", "尺寸公差", "粗糙度"],
    "product": ["product", "产品", "目录", "报价", "价格"],
}

import logging
from pathlib import Path

# 本地上传目录
UPLOAD_DIR = Path.home() / "manufacturing-ai" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# 允许的 MIME 类型和扩展名
ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
    "image/tiff", "image/bmp",
}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf", "tiff", "tif", "bmp"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/upload")
async def upload_blueprint(file: UploadFile = File(...)):
    """上传图纸/文档 → 保存本地 + OCR解析 →存入知识库"""
    # ── 0. 文件安全验证 ─────────────────────────────────
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        return {"error": f"不支持的文件类型: .{file_ext}，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}"}, 400

    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        return {"error": f"文件大小超过限制({MAX_FILE_SIZE // 1024 // 1024}MB)"}, 400

    # 验证实际 MIME 类型
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        return {"error": f"不支持的MIME类型: {file.content_type}"}, 400

    file_id = str(uuid.uuid4())

    # ── 1. 保存原始文件到本地 ──────────────────────────────
    saved_path = None
    try:
        ext = f".{file_ext}" if file_ext else ""
        saved_path = UPLOAD_DIR / f"{file_id}{ext}"
        with open(saved_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"File saved: {saved_path}")
    except Exception as save_err:
        logger.warning(f"File save failed (continuing without save): {save_err}")

    # ── 2. OCR 解析（如果可用）────────────────────────────
    ocr_status = "skipped"
    ocr_result_text = ""
    ocr_confidence = 0.0
    ocr_language = "unknown"

    try:
        from app.modules.ocr_module import ocr_image, ocr_pdf_page, check_ocr_available

        if check_ocr_available():
            if file_ext == "pdf":
                ocr_result = ocr_pdf_page(file_bytes, page_number=0, dpi=200, language="en")
            else:
                ocr_result = ocr_image(image_bytes=file_bytes, language="en")
            ocr_result_text = ocr_result.text
            ocr_confidence = ocr_result.confidence
            ocr_language = ocr_result.language
            ocr_status = "success"
        else:
            ocr_status = "unavailable"
    except Exception as ocr_err:
        logger.warning(f"OCR failed: {ocr_err}")
        ocr_status = f"error: {ocr_err}"

    # ── 3. 存入知识库（文字）─────────────────────────────
    kb = get_kb()
    fname_lower = file.filename.lower() if file.filename else ""
    category = "other"
    if any(k in fname_lower for k in ["material", "材质", "钢材", "铝"]):
        category = "material"
    elif any(k in fname_lower for k in ["process", "工艺", "cnc", "钣金"]):
        category = "process"
    elif any(k in fname_lower for k in ["surface", "表面", "电镀", "喷涂"]):
        category = "surface"
    elif any(k in fname_lower for k in ["tolerance", "公差", "质量", "spec"]):
        category = "tolerance"
    elif any(k in fname_lower for k in ["product", "产品", "目录"]):
        category = "product"

    if ocr_result_text:
        kb.add(
            title=file.filename or "unknown",
            content=ocr_result_text,
            category=category,
            source=file.filename or ""
        )

    # ── 4. 返回结果 ──────────────────────────────────────
    return {
        "file_id": file_id,
        "filename": file.filename,
        "saved_path": str(saved_path) if saved_path else None,
        "status": "parsed" if ocr_status == "success" else "uploaded",
        "ocr_status": ocr_status,
        "message": f"Uploaded and stored in KB. KB now has {kb.count()} entries.",
        "extracted_text": ocr_result_text[:200] + "..." if len(ocr_result_text) > 200 else ocr_result_text,
        "confidence": ocr_confidence,
        "language": ocr_language,
        "kb_category": category
    }


@router.post("/query")
async def query_blueprint(req: QueryRequest):
    """蓝图问答（支持会话历史）"""
    session_id = req.session_id or str(uuid.uuid4())
    question = req.question.lower()

    # KB 检索
    kb = get_kb()
    results = kb.search(req.question, top_k=3)

    if results:
        # 取最高分结果
        best = results[0]
        # 只有 score >= 1.5 才返回，否则走 AI fallback
        if best.get("score", 0) >= 1.5:
            answer = f"【{best['title']}】\n{best['content'][:500]}"
            sources = ["knowledge_base", best.get("category", "")]
        else:
            # KB 相关性太低 → 返回空，让调用方走 AI
            answer = ""
            sources = []
    else:
        # KB 无结果 → 返回空，走 AI fallback
        answer = ""
        sources = []

    # 更新会话历史
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({"role": "user", "content": req.question})
    _sessions[session_id].append({"role": "assistant", "content": answer})
    if len(_sessions[session_id]) > 20:
        _sessions[session_id] = _sessions[session_id][-20:]

    return {
        "answer": answer,
        "sources": sources,
        "session_id": session_id
    }


@router.post("/search")
async def search_blueprint(req: SearchRequest):
    """知识库搜索（供 LINE Bot 调用）"""
    kb = get_kb()
    results = kb.search(req.query, top_k=req.top_k)

    # 过滤低相关性结果（score < 1.5），避免答非所问
    # 关键词匹配一个字给30分，必须匹配2个以上关键词才返回
    if results:
        filtered = [r for r in results if r.get("score", 0) >= 1.5]
        if filtered:
            return {"results": [{"title": r["title"], "content": r["content"][:300]} for r in filtered]}
        # KB 相关性太低 → 返回空，让调用方走 AI fallback
        return {"results": []}
    else:
        # KB 完全无结果 → 也返回空，让调用方走 AI fallback
        return {"results": []}


@router.get("/status/{file_id}")
async def get_status(file_id: str):
    return {"file_id": file_id, "status": "ready", "progress": 100}


@router.get("/kb/count")
async def kb_count():
    """知识库条目数量"""
    kb = get_kb()
    return {"count": kb.count(), "service": "knowledge_base"}


@router.post("/parse")
async def parse_blueprint(req: ParseTextRequest):
    """
    蓝图文本 → 结构化参数解析

    输入 OCR 原始文字，输出 BlueprintSpec 结构化数据。
    用于：上传文件后解析结构化参数 → 报价系统联动
    """
    from app.modules.blueprint_parser import BlueprintParser

    parser = BlueprintParser()
    spec = parser.parse(req.text)

    return {
        "material": spec.material,
        "quantity": spec.quantity,
        "dimensions": spec.dimensions,
        "tolerance": spec.tolerance,
        "surface": spec.surface,
        "weight_kg": spec.weight_kg,
        "process_type": spec.process_type,
        "raw_text_length": len(spec.raw_text),
    }


@router.post("/upload-and-parse")
async def upload_and_parse_blueprint(file: UploadFile = File(...)):
    """
    上传图纸 → OCR → 解析结构化参数 → 返回完整结果

    完整流水线：文件 → OCR识别 → 结构化解析 → 返回参数
    """
    file_bytes = await file.read()
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""

    # ── 1. 提取文字（OCR 或直接读取）───────────────────────
    ocr_result_text = ""
    ocr_confidence = 0.0
    ocr_language = "unknown"
    ocr_status = "skipped"

    try:
        from app.modules.ocr_module import ocr_image, ocr_pdf_page, check_ocr_available

        if file_ext in ("png", "jpg", "jpeg", "bmp", "tiff", "tif", "gif"):
            # 图片 → OCR
            if check_ocr_available():
                ocr_result = ocr_image(image_bytes=file_bytes, language="en")
                ocr_result_text = ocr_result.text
                ocr_confidence = ocr_result.confidence
                ocr_language = ocr_result.language
                ocr_status = "success"
            else:
                ocr_status = "unavailable"

        elif file_ext == "pdf":
            # PDF → OCR
            if check_ocr_available():
                ocr_result = ocr_pdf_page(file_bytes, page_number=0, dpi=200, language="en")
                ocr_result_text = ocr_result.text
                ocr_confidence = ocr_result.confidence
                ocr_language = ocr_result.language
                ocr_status = "success"
            else:
                ocr_status = "unavailable"

        else:
            # 文本文件 → 直接读取内容
            try:
                ocr_result_text = file_bytes.decode("utf-8")
                ocr_status = "text_file"
                ocr_confidence = 1.0
            except Exception:
                ocr_result_text = ""
                ocr_status = "decode_error"

    except Exception as ocr_err:
        logger.warning(f"OCR failed: {ocr_err}")
        ocr_status = f"error: {ocr_err}"

    # ── 2. 结构化解析 ──────────────────────────────────
    if ocr_result_text:
        from app.modules.blueprint_parser import BlueprintParser
        parser = BlueprintParser()
        spec = parser.parse(ocr_result_text)
    else:
        from app.modules.blueprint_parser import BlueprintSpec
        spec = BlueprintSpec(raw_text=ocr_result_text)

    return {
        "filename": file.filename,
        "ocr_status": ocr_status,
        "ocr_confidence": ocr_confidence,
        "ocr_language": ocr_language,
        "extracted_text": ocr_result_text[:500] if ocr_result_text else "",
        "spec": {
            "material": spec.material,
            "quantity": spec.quantity,
            "dimensions": spec.dimensions,
            "tolerance": spec.tolerance,
            "surface": spec.surface,
            "weight_kg": spec.weight_kg,
            "process_type": spec.process_type,
        }
    }


async def _rule_match(question: str) -> str:
    """规则匹配 fallback"""
    if any(k in question for k in ["material", "zhi cai", "材质", "材料"]):
        return f"Material: {BLUEPRINT_SAMPLE['material']}"
    elif any(k in question for k in ["process", "gong yi", "工艺", "工序"]):
        return f"Process: {BLUEPRINT_SAMPLE['process']}"
    elif any(k in question for k in ["dimension", "chi cun", "尺寸", "大小"]):
        return f"Dimensions: {BLUEPRINT_SAMPLE['dimensions']}"
    elif any(k in question for k in ["bom", "parts", "物料", "零件"]):
        return "BOM:\n" + "\n".join(BLUEPRINT_SAMPLE['bom'])
    elif any(k in question for k in ["sop", "process steps", "作业步骤"]):
        return "SOP:\n" + BLUEPRINT_SAMPLE['sop']
    elif any(k in question for k in ["anomaly", "yi chang", "异常"]):
        return "Anomaly Records:\n" + BLUEPRINT_SAMPLE['anomaly']
    elif any(k in question for k in ["maintenance", "wei xiu", "维护"]):
        return "Maintenance Records:\n" + BLUEPRINT_SAMPLE['maintenance']
    elif any(k in question for k in ["tolerance", "gong cha", "公差"]):
        return f"Tolerance: {BLUEPRINT_SAMPLE['tolerance']}"
    else:
        # 不再调用 AI，直接用示例数据
        return (f"Sorry, I don't have specific information about that in the knowledge base. "
                f"Here is general info — Material: {BLUEPRINT_SAMPLE['material']}, "
                f"Process: {BLUEPRINT_SAMPLE['process']}, "
                f"Tolerance: {BLUEPRINT_SAMPLE['tolerance']}. "
                f"Please upload a blueprint or contact us for detailed pricing.")
