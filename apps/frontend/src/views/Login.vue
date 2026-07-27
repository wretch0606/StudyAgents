<script setup lang="ts">
// ============================================================
// StudyAgents — 登录页（占位）
//
// 当前使用 localStorage['userRole'] 模拟登录状态，
// 路由守卫 router.beforeEach 据此判断权限。
// 后续将替换为完整的 Pinia + API 登录表单。
// ============================================================

import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const loggingIn = ref(false)

/** 模拟登录：写入 role 到 localStorage 并跳转 */
function simulateLogin(role: 'admin' | 'user') {
  loggingIn.value = true
  localStorage.setItem('userRole', role)

  // 短暂延迟模拟网络请求
  setTimeout(() => {
    if (role === 'admin') {
      router.push('/admin')
    } else {
      router.push('/')
    }
  }, 300)
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">StudyAgents</h1>
      <p class="login-subtitle">多 Agent 可信知识问答与专项复习系统</p>

      <div class="login-actions">
        <button
          class="btn-login btn-admin"
          :disabled="loggingIn"
          @click="simulateLogin('admin')"
        >
          🔑 管理员登录
        </button>
        <button
          class="btn-login btn-user"
          :disabled="loggingIn"
          @click="simulateLogin('user')"
        >
          👤 普通用户登录
        </button>
      </div>

      <p class="login-hint">
        当前为占位登录页，点击上方按钮模拟登录。<br />
        localStorage['userRole'] = 'admin' | 'user'
      </p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1a1a2e;
}

.login-card {
  width: 400px;
  padding: 44px 40px 36px;
  border-radius: 12px;
  background: #16213e;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
  text-align: center;
}

.login-title {
  margin: 0 0 4px;
  font-size: 28px;
  font-weight: 700;
  color: #a78bfa;
  letter-spacing: 1px;
}

.login-subtitle {
  margin: 0 0 32px;
  font-size: 13px;
  color: #888;
}

.login-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.btn-login {
  width: 100%;
  padding: 12px 0;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s, transform 0.15s;
}

.btn-login:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-login:not(:disabled):hover {
  transform: translateY(-1px);
}

.btn-login:not(:disabled):active {
  transform: translateY(0);
}

.btn-admin {
  color: #fff;
  background: linear-gradient(135deg, #7c3aed, #a78bfa);
}

.btn-user {
  color: #e0e0e0;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.12);
}

.btn-user:not(:disabled):hover {
  background: rgba(255, 255, 255, 0.14);
}

.login-hint {
  margin: 24px 0 0;
  font-size: 12px;
  color: #555;
  line-height: 1.7;
}
</style>
