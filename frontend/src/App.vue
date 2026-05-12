<template>
  <div class="app">
    <header class="header">
      <h1>🏭 Manufacturing AI</h1>
      <p>Manufacturing AI Assistant - Blueprint Q&A</p>
    </header>
    <BlueprintQA />
  </div>
</template>

<script setup lang="ts">
import BlueprintQA from './views/BlueprintQA.vue'
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
.app { min-height: 100vh; padding: 2rem; }
.header { text-align: center; margin-bottom: 2rem; }
.header h1 { font-size: 2.5rem; margin-bottom: 0.5rem; }
.header p { color: #94a3b8; }
</style>