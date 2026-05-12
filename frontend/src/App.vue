<template>
  <div class="app">
    <header class="header">
      <h1>🏭 Manufacturing AI</h1>
      <p>Manufacturing AI Assistant</p>
    </header>
    <nav class="nav">
      <button :class="{ active: currentView === 'blueprint' }" @click="currentView = 'blueprint'">蓝图问答</button>
      <button :class="{ active: currentView === 'quote' }" @click="currentView = 'quote'">AI报价</button>
    </nav>
    <BlueprintQA v-if="currentView === 'blueprint'" />
    <QuoteSystem v-else-if="currentView === 'quote'" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import BlueprintQA from './views/BlueprintQA.vue'
import QuoteSystem from './views/QuoteSystem.vue'

const currentView = ref<'blueprint' | 'quote'>('blueprint')
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
.app { min-height: 100vh; padding: 2rem; }
.header { text-align: center; margin-bottom: 1.5rem; }
.header h1 { font-size: 2.5rem; margin-bottom: 0.5rem; }
.header p { color: #94a3b8; }
.nav {
  display: flex;
  justify-content: center;
  gap: 1rem;
  margin-bottom: 2rem;
}
.nav button {
  padding: 0.6rem 1.5rem;
  border-radius: 8px;
  border: 1px solid #475569;
  background: #1e293b;
  color: #94a3b8;
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.2s;
}
.nav button:hover {
  background: #334155;
  color: #e2e8f0;
}
.nav button.active {
  background: #3b82f6;
  border-color: #3b82f6;
  color: white;
}
</style>