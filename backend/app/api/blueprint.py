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


@router.post("/upload")
async def upload_blueprint(file: UploadFile = File(...)):
    """上传图纸/文档 → OCR解析 →存入知识库"""
    file_id = str(uuid.uuid4())
    file_bytes = await file.read()
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""

    try:
        from app.modules.ocr_module import ocr_image, ocr_pdf_page, check_ocr_available

        if not check_ocr_available():
            return {
                "file_id": file_id,
                "filename": file.filename,
                "status": "uploaded",
                "ocr_status": "unavailable",
                "message": "PaddleOCR not installed. Upload successful, OCR skipped."
            }

        # OCR 解析
        if file_ext == "pdf":
            ocr_result = ocr_pdf_page(file_bytes, page_number=0, dpi=200, language="en")
        else:
            ocr_result = ocr_image(image_bytes=file_bytes, language="en")

        # 存入知识库
        kb = get_kb()
        # 从文件名推断分类
        fname_lower = file.filename.lower()
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

        kb.add(
            title=file.filename,
            content=ocr_result.text,
            category=category,
            source=file.filename
        )

        return {
            "file_id": file_id,
            "filename": file.filename,
            "status": "parsed",
            "ocr_status": "success",
            "message": f"Uploaded and stored in KB. KB now has {kb.count()} entries.",
            "extracted_text": ocr_result.text[:200] + "..." if len(ocr_result.text) > 200 else ocr_result.text,
            "confidence": ocr_result.confidence,
            "language": ocr_result.language,
            "kb_category": category
        }

    except Exception as e:
        logger.error(f"OCR/KB error: {e}")
        return {
            "file_id": file_id,
            "filename": file.filename,
            "status": "uploaded",
            "ocr_status": "error",
            "message": f"OCR/KB failed: {str(e)}"
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
        answer = f"【{best['title']}】\n{best['content'][:500]}"
        sources = ["knowledge_base", best.get("category", "")]
    else:
        # Fallback: 规则匹配
        answer = await _rule_match(question)
        sources = ["rules"]

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

    if results:
        return {"results": [{"title": r["title"], "content": r["content"][:300]} for r in results]}
    else:
        # Fallback: 规则匹配
        answer = await _rule_match(req.query.lower())
        return {
            "results": [{
                "title": "规则匹配",
                "content": answer
            }]
        }


@router.get("/status/{file_id}")
async def get_status(file_id: str):
    return {"file_id": file_id, "status": "ready", "progress": 100}


@router.get("/kb/count")
async def kb_count():
    """知识库条目数量"""
    kb = get_kb()
    return {"count": kb.count(), "service": "knowledge_base"}


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
