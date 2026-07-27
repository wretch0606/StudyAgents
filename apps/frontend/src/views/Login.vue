<script setup lang="ts">
// ============================================================
// StudyAgents — 登录页
//
// 使用 useUserStore.login() 调用 POST /api/auth/login，
// 成功后持久化 Bearer Token 到 localStorage 并跳转到首页。
//
// Mock 凭据（dev 模式）：
//   - 任意非空用户名 + 任意密码 → 普通用户 (member)
//   - admin / admin123            → 管理员 (admin)
// ============================================================

import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../stores/useUserStore'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// ---- 表单状态 ----
const username = ref('')
const password = ref('')
const errorMsg = ref('')
const submitting = ref(false)

// ---- 登录 ----
async function handleLogin() {
  errorMsg.value = ''

  const u = username.value.trim()
  const p = password.value

  if (!u || !p) {
    errorMsg.value = '请输入用户名和密码'
    return
  }

  submitting.value = true
  try {
    await userStore.login(u, p)

    // 登录成功 → 跳转到目标页（或首页）
    const redirect = (route.query.redirect as string) || '/'
    router.replace(redirect)
  } catch (err: any) {
    // 提取后端返回的错误消息
    const data = err?.response?.data
    if (data?.message) {
      errorMsg.value = data.message
    } else if (err?.message) {
      errorMsg.value = err.message
    } else {
      errorMsg.value = '登录失败，请检查网络连接后重试'
    }
  } finally {
    submitting.value = false
  }
}

// ---- 回车发送 ----
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    handleLogin()
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">StudyAgents</h1>
      <p class="login-subtitle">多 Agent 可信知识问答与专项复习系统</p>

      <!-- 登录表单 -->
      <div class="login-form">
        <div class="form-group">
          <label class="form-label" for="login-username">用户名</label>
          <input
            id="login-username"
            v-model="username"
            type="text"
            class="form-input"
            placeholder="输入用户名"
            autocomplete="username"
            :disabled="submitting"
            @keydown="onKeydown"
          />
        </div>

        <div class="form-group">
          <label class="form-label" for="login-password">密码</label>
          <input
            id="login-password"
            v-model="password"
            type="password"
            class="form-input"
            placeholder="输入密码"
            autocomplete="current-password"
            :disabled="submitting"
            @keydown="onKeydown"
          />
        </div>

        <!-- 错误提示 -->
        <p v-if="errorMsg" class="login-error">{{ errorMsg }}</p>

        <!-- 登录按钮 -->
        <button
          class="btn-login"
          :disabled="submitting"
          @click="handleLogin"
        >
          <span v-if="submitting" class="btn-spinner"></span>
          {{ submitting ? '登录中...' : '登 录' }}
        </button>
      </div>

      <!-- 快捷提示 -->
      <p class="login-hint">
        💡 演示凭据：<code>admin</code> / <code>admin123</code>（管理员）<br />
        其他任意非空用户名和密码即可作为普通用户登录
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
  margin: 0 0 28px;
  font-size: 13px;
  color: #888;
}

/* ---- 表单 ---- */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  text-align: left;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-label {
  font-size: 12px;
  font-weight: 600;
  color: #999;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.form-input {
  width: 100%;
  padding: 11px 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
  color: #e0e0e0;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s, background 0.2s;
  box-sizing: border-box;
}

.form-input::placeholder {
  color: #555;
}

.form-input:focus {
  border-color: #a78bfa;
  background: rgba(167, 139, 250, 0.04);
}

.form-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* ---- 错误提示 ---- */
.login-error {
  margin: 0;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(255, 107, 107, 0.1);
  border: 1px solid rgba(255, 107, 107, 0.25);
  color: #ff6b6b;
  font-size: 13px;
  text-align: center;
}

/* ---- 登录按钮 ---- */
.btn-login {
  width: 100%;
  padding: 12px 0;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  background: linear-gradient(135deg, #7c3aed, #a78bfa);
  cursor: pointer;
  transition: opacity 0.2s, transform 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
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

/* ---- 加载旋转器 ---- */
.btn-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ---- 提示 ---- */
.login-hint {
  margin: 22px 0 0;
  font-size: 12px;
  color: #555;
  line-height: 1.7;
}

.login-hint code {
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(167, 139, 250, 0.12);
  color: #a78bfa;
  font-family: 'Consolas', 'Menlo', monospace;
  font-size: 12px;
}

/* ---- 响应式 ---- */
@media (max-width: 480px) {
  .login-card {
    width: 90%;
    padding: 32px 20px 28px;
  }
}
</style>
