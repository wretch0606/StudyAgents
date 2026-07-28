<script setup lang="ts">
// ============================================================
// StudyAgents — 错题本页（占位）
//
// 后续填充：错题列表、状态筛选、重新练习、查看解析 UI
// ============================================================
</script>

<template>
  <div class="page-placeholder">
    <span class="page-icon">📖</span>
    <h1>错题本</h1>
    <p>错题回顾 · 状态追踪 · 针对性复习</p>
  </div>
</template>

<style scoped>
.page-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 10px;
  color: #e0e0e0;
  background: #1a1a2e;
}

.page-icon {
  font-size: 48px;
}

.page-placeholder h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0;
  letter-spacing: 1px;
}

.page-placeholder p {
  color: #888;
  margin: 0;
  font-size: 14px;
}
</style>
