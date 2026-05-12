from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import uuid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

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

    if any(k in question for k in ["material", "material", "zhi cai"]):
        answer = f"Material: {BLUEPRINT_SAMPLE['material']}"
    elif any(k in question for k in ["process", "gong yi"]):
        answer = f"Process: {BLUEPRINT_SAMPLE['process']}"
    elif any(k in question for k in ["dimension", "chi cun"]):
        answer = f"Dimensions: {BLUEPRINT_SAMPLE['dimensions']}"
    elif any(k in question for k in ["bom", "parts"]):
        answer = "BOM:\n" + "\n".join(BLUEPRINT_SAMPLE['bom'])
    elif any(k in question for k in ["sop", "process steps"]):
        answer = "SOP:\n" + BLUEPRINT_SAMPLE['sop']
    elif any(k in question for k in ["anomaly", "yi chang"]):
        answer = "Anomaly Records:\n" + BLUEPRINT_SAMPLE['anomaly']
    elif any(k in question for k in ["maintenance", "wei xiu"]):
        answer = "Maintenance Records:\n" + BLUEPRINT_SAMPLE['maintenance']
    else:
        answer = f"Based on blueprints:\n- Material: {BLUEPRINT_SAMPLE['material']}\n- Process: {BLUEPRINT_SAMPLE['process']}\n- Dimensions: {BLUEPRINT_SAMPLE['dimensions']}"

    return {
        "answer": answer,
        "sources": ["blueprint_data", "rag_knowledge_base"],
        "session_id": session_id
    }

@router.get("/status/{file_id}")
async def get_status(file_id: str):
    return {"file_id": file_id, "status": "ready", "progress": 100}