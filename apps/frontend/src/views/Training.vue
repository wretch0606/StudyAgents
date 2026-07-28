<script setup lang="ts">
// ============================================================
// StudyAgents — 专项训练页（占位）
//
// 后续填充：章节/知识点选择、题目展示、作答提交 UI
// ============================================================
</script>

<template>
  <div class="page-placeholder">
    <span class="page-icon">🎯</span>
    <h1>专项训练</h1>
    <p>章节选择 · 智能出题 · 分步评分</p>
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
