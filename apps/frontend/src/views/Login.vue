<script setup lang="ts">
// ============================================================
// StudyAgents — 登录页面
//
// 居中卡片式登录表单，对接 Pinia useAuthStore。
// 登录成功后自动跳转到 redirect 参数指向的页面（默认 /）。
// ============================================================

import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

// ============================================================
// 表单数据
// ============================================================

const formRef = ref<FormInstance>()

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
  ],
}

// ============================================================
// 提交状态
// ============================================================

const submitting = ref(false)

// ============================================================
// 提交登录
// ============================================================

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')

    // 登录后跳转：优先取 redirect 参数，否则到首页
    const redirect = (route.query.redirect as string) || '/'
    router.replace(redirect)
  } catch {
    // 错误提示已由 request.ts 的响应拦截器通过 ElMessage.error 处理
    // 此处仅防止未捕获异常
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">StudyAgents</h1>
      <p class="login-subtitle">多 Agent 可信知识问答与专项复习系统</p>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            :disabled="submitting"
            clearable
          />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            :disabled="submitting"
            show-password
            clearable
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            :loading="submitting"
            class="login-button"
            @click="handleLogin"
          >
            {{ submitting ? '登录中…' : '登录' }}
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-bg-color-page, #f5f5f5);
}

.login-card {
  width: 400px;
  padding: 40px 36px 32px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
}

.login-title {
  margin: 0 0 4px;
  font-size: 26px;
  text-align: center;
  color: var(--el-color-primary, #409eff);
}

.login-subtitle {
  margin: 0 0 28px;
  font-size: 13px;
  text-align: center;
  color: #999;
}

.login-button {
  width: 100%;
}
</style>
