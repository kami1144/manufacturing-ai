<template>
  <div class="qa-container">
    <div class="upload-section">
      <h2>📤 Upload Blueprint</h2>
      <div class="upload-area" @dragover.prevent @drop.prevent="handleDrop">
        <input type="file" @change="handleFileChange" accept=".pdf,.dwg,.dxf" />
        <p>Drag blueprint files or click to upload (PDF, DWG, DXF)</p>
      </div>
      <div v-if="uploadedFile" class="file-info">
        ✅ {{ uploadedFile.name }}
      </div>
    </div>

    <div class="chat-section">
      <h2>💬 Blueprint Q&A</h2>
      <div class="chat-history">
        <div v-for="(msg, i) in messages" :key="i" :class="['message', msg.role]">
          <strong>{{ msg.role === 'user' ? '👤' : '🤖' }}</strong>
          <div class="content">{{ msg.content }}</div>
        </div>
      </div>
      <div class="chat-input">
        <input v-model="question" @keyup.enter="sendQuery" placeholder="Ask about blueprints..." :disabled="loading" />
        <button @click="sendQuery" :disabled="loading">
          {{ loading ? 'Analyzing...' : 'Send' }}
        </button>
      </div>
      <div class="quick-questions">
        <button v-for="q in quickQuestions" :key="q" @click="askQuestion(q)">{{ q }}</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const question = ref('')
const loading = ref(false)
const uploadedFile = ref<File | null>(null)
const sessionId = ref('')
const messages = ref<{role: string, content: string}[]>([])

const quickQuestions = ['Material?', 'Process flow?', 'Dimensions?', 'BOM list?', 'SOP steps?', 'Anomaly records?']

const handleFileChange = (e: Event) => {
  const target = e.target as HTMLInputElement
  if (target.files?.[0]) {
    uploadedFile.value = target.files[0]
    uploadFile(target.files[0])
  }
}

const handleDrop = (e: DragEvent) => {
  const file = e.dataTransfer?.files[0]
  if (file) {
    uploadedFile.value = file
    uploadFile(file)
  }
}

const uploadFile = async (file: File) => {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch('/api/blueprint/upload', { method: 'POST', body: formData })
  const data = await res.json()
  sessionId.value = data.file_id
  messages.value.push({ role: 'system', content: `Blueprint uploaded: ${file.name}` })
}

const sendQuery = async () => {
  if (!question.value.trim() || loading.value) return
  const q = question.value
  messages.value.push({ role: 'user', content: q })
  question.value = ''
  loading.value = true

  try {
    const res = await fetch('/api/blueprint/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, session_id: sessionId.value })
    })
    const data = await res.json()
    messages.value.push({ role: 'assistant', content: data.answer })
  } catch (err) {
    messages.value.push({ role: 'assistant', content: 'Request failed, please retry.' })
  }
  loading.value = false
}

const askQuestion = (q: string) => {
  question.value = q
  sendQuery()
}
</script>

<style scoped>
.qa-container { max-width: 900px; margin: 0 auto; display: grid; gap: 2rem; }
.upload-section, .chat-section { background: #1e293b; border-radius: 12px; padding: 1.5rem; }
h2 { margin-bottom: 1rem; font-size: 1.2rem; }
.upload-area { border: 2px dashed #475569; border-radius: 8px; padding: 2rem; text-align: center; cursor: pointer; transition: border-color 0.2s; }
.upload-area:hover { border-color: #3b82f6; }
.upload-area input { margin-bottom: 0.5rem; }
.file-info { margin-top: 1rem; padding: 0.75rem; background: #065f46; border-radius: 6px; font-size: 0.9rem; }
.chat-history { height: 300px; overflow-y: auto; margin-bottom: 1rem; display: flex; flex-direction: column; gap: 0.75rem; }
.message { display: flex; gap: 0.75rem; padding: 0.75rem; border-radius: 8px; }
.message.user { background: #1e40af; align-self: flex-end; }
.message.assistant { background: #374151; align-self: flex-start; }
.message.system { background: #065f46; align-self: flex-start; font-size: 0.85rem; }
.content { white-space: pre-wrap; line-height: 1.5; }
.chat-input { display: flex; gap: 0.5rem; margin-bottom: 1rem; }
.chat-input input { flex: 1; padding: 0.75rem; border-radius: 6px; border: 1px solid #475569; background: #0f172a; color: #e2e8f0; }
.chat-input button { padding: 0.75rem 1.5rem; border-radius: 6px; border: none; background: #3b82f6; color: white; cursor: pointer; }
.chat-input button:disabled { background: #475569; cursor: not-allowed; }
.quick-questions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.quick-questions button { padding: 0.5rem 1rem; border-radius: 20px; border: 1px solid #475569; background: transparent; color: #94a3b8; cursor: pointer; font-size: 0.85rem; }
.quick-questions button:hover { background: #374151; color: #e2e8f0; }
</style>