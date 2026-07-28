<script setup lang="ts">
// ============================================================
// StudyAgents — 错题本独立路由页
//
// 该页面直接重定向到首页的错题本内嵌视图（/?mode=wrongbook），
// 确保通过 /wrong-book 直接访问时也能看到完整的错题本界面。
// ============================================================
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

onMounted(() => {
  router.replace({ path: '/', query: { mode: 'wrongbook' } })
})
</script>

<template>
  <div class="wb-redirect">
    <span class="wb-redirect-icon">📖</span>
    <p>正在跳转至错题本…</p>
  </div>
</template>

<style scoped>
.wb-redirect {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  gap: 12px;
  color: #888;
  background: #1a1a2e;
}

.wb-redirect-icon {
  font-size: 48px;
  animation: wb-pulse 1.2s ease-in-out infinite;
}

@keyframes wb-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.95); }
}

.wb-redirect p {
  font-size: 14px;
  margin: 0;
}
</style>
