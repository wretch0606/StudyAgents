<script setup lang="ts">
// ============================================================
// StudyAgents — 资料管理页（占位）
//
// 后续填充：文档上传、导入任务监控、复核管理 UI
// ============================================================
</script>

<template>
  <div class="page-placeholder">
    <span class="page-icon">📂</span>
    <h1>资料管理</h1>
    <p>文档上传 · 导入任务监控 · 复核管理</p>
    <span class="page-badge">Admin Only</span>
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

.page-badge {
  margin-top: 8px;
  padding: 4px 14px;
  border-radius: 12px;
  font-size: 12px;
  color: #f0a060;
  background: rgba(240, 160, 96, 0.12);
  border: 1px solid rgba(240, 160, 96, 0.3);
}
</style>
