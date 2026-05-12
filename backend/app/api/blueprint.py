from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import uuid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# 内存会话存储（生产环境换Redis）
_sessions: dict[str, list[dict]] = {}

@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "blueprint"}

class QueryRequest(BaseModel):
    question: str
    session_id: Optional[str] = None

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

@router.post("/upload")
async def upload_blueprint(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())

    # 读取文件内容
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

        # 判断文件类型
        if file_ext == "pdf":
            ocr_result = ocr_pdf_page(file_bytes, page_number=0, dpi=200, language="en")
        else:
            ocr_result = ocr_image(image_bytes=file_bytes, language="en")

        return {
            "file_id": file_id,
            "filename": file.filename,
            "status": "parsed",
            "ocr_status": "success",
            "message": "Blueprint uploaded and parsed successfully.",
            "extracted_text": ocr_result.text,
            "confidence": ocr_result.confidence,
            "language": ocr_result.language
        }

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return {
            "file_id": file_id,
            "filename": file.filename,
            "status": "uploaded",
            "ocr_status": "error",
            "message": f"OCR failed: {str(e)}"
        }

@router.post("/query")
async def query_blueprint(req: QueryRequest):
    session_id = req.session_id or str(uuid.uuid4())
    question = req.question.lower()

    # 关键词规则匹配（制造业垂直问题）
    if any(k in question for k in ["material", "zhi cai", "材质", "材料"]):
        answer = f"Material: {BLUEPRINT_SAMPLE['material']}"
    elif any(k in question for k in ["process", "gong yi", "工艺", "工序"]):
        answer = f"Process: {BLUEPRINT_SAMPLE['process']}"
    elif any(k in question for k in ["dimension", "chi cun", "尺寸", "大小"]):
        answer = f"Dimensions: {BLUEPRINT_SAMPLE['dimensions']}"
    elif any(k in question for k in ["bom", "parts", "物料", "零件"]):
        answer = "BOM:\n" + "\n".join(BLUEPRINT_SAMPLE['bom'])
    elif any(k in question for k in ["sop", "process steps", "作业步骤"]):
        answer = "SOP:\n" + BLUEPRINT_SAMPLE['sop']
    elif any(k in question for k in ["anomaly", "yi chang", "异常"]):
        answer = "Anomaly Records:\n" + BLUEPRINT_SAMPLE['anomaly']
    elif any(k in question for k in ["maintenance", "wei xiu", "维护"]):
        answer = "Maintenance Records:\n" + BLUEPRINT_SAMPLE['maintenance']
    else:
        # 非规则问题 → 调 AI
        from app.modules.ai_module import ai_manufacturing
        history = _sessions.get(session_id, [])
        answer = await ai_manufacturing.chat(req.question, history)

    # 更新会话历史
    if session_id not in _sessions:
        _sessions[session_id] = []
    _sessions[session_id].append({"role": "user", "content": req.question})
    _sessions[session_id].append({"role": "assistant", "content": answer})
    # 最多保留20条
    if len(_sessions[session_id]) > 20:
        _sessions[session_id] = _sessions[session_id][-20:]

    return {
        "answer": answer,
        "sources": ["blueprint_data", "ai_model"],
        "session_id": session_id
    }

@router.get("/status/{file_id}")
async def get_status(file_id: str):
    return {"file_id": file_id, "status": "ready", "progress": 100}