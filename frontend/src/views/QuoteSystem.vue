<template>
  <div class="quote-container">
    <div class="header">
      <h2>AI报价系统</h2>
      <p>上传图纸，自动生成报价单</p>
    </div>

    <div class="content">
      <!-- 报价参数 -->
      <div class="form-section">
        <h3>报价参数</h3>
        <div class="form-grid">
          <div class="form-group">
            <label>材质</label>
            <select v-model="quoteParams.material">
              <option value="SUS304">SUS304 不锈钢</option>
              <option value="SUS316">SUS316 不锈钢</option>
              <option value="SECC">SECC 镀锌钢板</option>
              <option value="ADC12">ADC12 铝合金</option>
              <option value="A383">A383 铝合金</option>
            </select>
          </div>
          <div class="form-group">
            <label>重量 (kg)</label>
            <input type="number" v-model.number="quoteParams.weight" min="0.1" step="0.1" />
          </div>
          <div class="form-group">
            <label>数量</label>
            <input type="number" v-model.number="quoteParams.quantity" min="1" />
          </div>
          <div class="form-group">
            <label>公差要求</label>
            <select v-model="quoteParams.tolerance">
              <option value="normal">普通 (±0.1mm)</option>
              <option value="precision">精密 (±0.02mm)</option>
              <option value="high">高精度 (±0.01mm)</option>
            </select>
          </div>
        </div>
        <button class="calc-btn" @click="calculateQuote" :disabled="loading">
          {{ loading ? '计算中...' : '开始报价' }}
        </button>
      </div>

      <!-- 报价结果 -->
      <div v-if="quoteResult" class="result-section">
        <h3>报价单</h3>
        <div class="quote-summary">
          <div class="summary-item">
            <span class="label">预估价格</span>
            <span class="value price">¥{{ quoteResult.estimated_price.toLocaleString() }}</span>
          </div>
          <div class="summary-item">
            <span class="label">材料费</span>
            <span class="value">¥{{ quoteResult.total_material_cost.toLocaleString() }}</span>
          </div>
          <div class="summary-item">
            <span class="label">人工费</span>
            <span class="value">¥{{ quoteResult.total_labor_cost.toLocaleString() }}</span>
          </div>
          <div class="summary-item">
            <span class="label">总工时</span>
            <span class="value">{{ quoteResult.total_hours }}h</span>
          </div>
          <div class="summary-item">
            <span class="label">交期</span>
            <span class="value">{{ quoteResult.lead_time_days }}天</span>
          </div>
        </div>

        <div class="process-breakdown" v-if="quoteResult.process_steps && quoteResult.process_steps.length">
          <h4>工序明细</h4>
          <table>
            <thead>
              <tr>
                <th>工序</th>
                <th>类型</th>
                <th>工时</th>
                <th>材料费</th>
                <th>人工费</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(step, i) in quoteResult.process_steps" :key="i">
                <td>{{ step.step }}</td>
                <td>{{ step.process_type }}</td>
                <td>{{ step.estimated_hours }}h</td>
                <td>��{{ step.material_cost.toLocaleString() }}</td>
                <td>¥{{ step.labor_cost.toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="notes" v-if="quoteResult.notes">
          <p>备注：{{ quoteResult.notes }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'

interface ProcessStep {
  step: string
  process_type: string
  estimated_hours: number
  material_cost: number
  labor_cost: number
}

interface QuoteData {
  quote_id: string
  filename: string
  material: string
  process_category: string
  process_steps: ProcessStep[]
  total_material_cost: number
  total_labor_cost: number
  total_hours: number
  estimated_price: number
  lead_time_days: number
  notes: string
}

const loading = ref(false)

const quoteParams = reactive({
  material: 'SUS304',
  weight: 1.0,
  quantity: 1,
  tolerance: 'normal'
})

const quoteResult = ref<QuoteData | null>(null)

const calculateQuote = async () => {
  loading.value = true
  try {
    const res = await fetch('/api/quote/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: 'blueprint.pdf',
        material: quoteParams.material,
        weight_kg: quoteParams.weight,
        quantity: quoteParams.quantity,
        tolerance: quoteParams.tolerance
      })
    })
    const data = await res.json()
    quoteResult.value = data
  } catch (err) {
    console.error(err)
  }
  loading.value = false
}
</script>

<style scoped>
.quote-container {
  max-width: 900px;
  margin: 0 auto;
}
.header {
  text-align: center;
  margin-bottom: 2rem;
}
.header h2 {
  font-size: 1.8rem;
  margin-bottom: 0.5rem;
}
.header p {
  color: #94a3b8;
}
.content {
  display: grid;
  gap: 1.5rem;
}
.form-section, .result-section {
  background: #1e293b;
  border-radius: 12px;
  padding: 1.5rem;
}
.form-section h3, .result-section h3 {
  margin-bottom: 1rem;
  font-size: 1.2rem;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  margin-bottom: 1rem;
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.form-group label {
  font-size: 0.85rem;
  color: #94a3b8;
}
.form-group input, .form-group select {
  padding: 0.6rem;
  border-radius: 6px;
  border: 1px solid #475569;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 0.95rem;
}
.calc-btn {
  width: 100%;
  padding: 0.8rem;
  border-radius: 8px;
  border: none;
  background: #3b82f6;
  color: white;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}
.calc-btn:hover { background: #2563eb; }
.calc-btn:disabled { background: #475569; cursor: not-allowed; }
.quote-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.summary-item {
  background: #0f172a;
  padding: 1rem;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.summary-item .label {
  font-size: 0.8rem;
  color: #94a3b8;
}
.summary-item .value {
  font-size: 1.1rem;
  font-weight: 600;
}
.summary-item .price {
  font-size: 1.4rem;
  color: #3b82f6;
}
.process-breakdown h4 {
  margin-bottom: 0.8rem;
  font-size: 1rem;
  color: #94a3b8;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
th, td {
  padding: 0.6rem;
  text-align: left;
  border-bottom: 1px solid #334155;
}
th { color: #94a3b8; font-weight: 500; }
.notes {
  margin-top: 1rem;
  padding: 1rem;
  background: #0f172a;
  border-radius: 6px;
  font-size: 0.9rem;
  color: #94a3b8;
}
</style>