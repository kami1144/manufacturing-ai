# 制造业AI系统 - 技术规格书

## 项目概述

**项目名称:** Manufacturing AI Suite（制造业AI套件）
**项目路径:** `~/manufacturing-ai/`
**当前阶段:** Demo开发中
**目标用户:** 日本制造业中小企业

---

## 三大核心模块

### 模块1: 蓝图问答系统（Blueprint Q&A）

**功能:**
- 上传PDF/CAD图纸 → 自动解析
- 提取：材质、工艺说明、SOP、异常记录、OCR文字、尺寸、BOM、维修记录

**技术栈:**
- 图纸解析：Qwen2.5-VL（多模态，本地Docker）
- OCR：PaddleOCR
- RAG：Qdrant向量数据库
- LLM推理：DeepSeek-R1（本地Docker）
- 后端：FastAPI
- 前端：Vue3/TypeScript

**目录结构:**
```
backend/
  app/
    api/
      blueprint.py      # 图纸问答API
    core/
      ocr.py            # OCR模块
      rag.py            # RAG检索模块
      llm.py            # LLM调用模块
    models/
    main.py
  requirements.txt
  Dockerfile

frontend/
  src/
    views/
      BlueprintQA.vue   # 图纸问答页面
    components/
    App.vue
  package.json
```

**API端点:**
```
POST /api/blueprint/upload     # 上传图纸
POST /api/blueprint/query      # 问答查询
GET  /api/blueprint/status     # 任务状态
```

---

### 模块2: AI报价系统（AI Quote）

**功能:**
- 上传图纸 → AI自动提取信息 → 分类工艺 → 估算工时 → 生成报价模板

**技术栈:** 复用蓝图问答的LLM+RAG模块 + 规则引擎

---

### 模块3: 工厂知识库（Factory KB）

**功能:**
- 模块化：OCR/RAG/LINE/报价 可复用
- 行业模板：制造业知识库模板

**模块结构:**
```
backend/app/modules/
  ocr_module.py     # OCR模块（独立）
  rag_module.py     # RAG模块（独立）
  line_module.py    # LINE模块（复用ai-line-solution）
  quote_module.py   # 报价模块（独立）
```

---

## 开发阶段

### Phase 1: Demo ✅
- [x] 蓝图问答后端API
- [x] 蓝图问答前端页面
- [x] 本地模型集成（Qwen2.5-VL + DeepSeek-R1）

### Phase 2: AI报价系统 + 工厂知识库模块化（进行中）
- [ ] AI报价后端API
- [ ] AI报价前端页面
- [ ] 工厂知识库模块化（OCR/RAG/报价 独立模块）
- [ ] 报价规则引擎

### Phase 3: 扩展
- [ ] LINE集成

---

## 本地模型方案

**Docker部署（免费）：**
```bash
# DeepSeek-R1（推理）
docker pull deepseek-ai/deepseek-r1
docker run -d -p 8001:8001 deepseek-ai/deepseek-r1

# Qwen2.5-VL（视觉）
docker pull qwen/qwen2.5-vl
docker run -d -p 8002:8001 qwen/qwen2.5-vl

# Qdrant（向量数据库）
docker pull qdrant/qdrant
docker run -d -p 6333:6333 qdrant/qdrant
```

---

## 验收标准

1. 图纸上传后能返回解析结果
2. 问答能返回相关答案（基于RAG检索）
3. 本地Docker运行，无需云端API
4. Git commit + push 完成
