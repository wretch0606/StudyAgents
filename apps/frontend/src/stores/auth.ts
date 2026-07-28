// ============================================================
// StudyAgents — 认证状态管理（Pinia Store）
//
// 职责：
//   1. 持有当前用户信息与初始化标记
//   2. 封装 login / logout / init（会话恢复）动作
//   3. 与 src/utils/request.ts 的 CSRF Token 工具函数协作
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserInfo } from '../types/api'
import { loginApi, getCurrentUserApi, logoutApi } from '../api/auth'
import {
  setCsrfToken,
  clearCsrfToken,
  fetchAndStoreCsrfToken,
} from '../utils/request'

export const useAuthStore = defineStore('auth', () => {
  // ============================================================
  // State
  // ============================================================

  /** 当前登录用户信息 */
  const user = ref<UserInfo | null>(null)

  /** 是否已完成初始化检查（页面刷新后恢复会话） */
  const initialized = ref(false)

  // ============================================================
  // Getters
  // ============================================================

  /** 当前是否已登录 */
  const isLoggedIn = computed(() => user.value !== null)

  // ============================================================
  // Actions
  // ============================================================

  /**
   * 登录：提交凭证 → 写入 CSRF Token → 写入用户
   *
   * @param username 用户名
   * @param password 密码
   * @returns 登录后的 UserInfo
   */
  async function login(username: string, password: string): Promise<UserInfo> {
    const res = await loginApi({ username, password })

    // 将 CSRF Token 写入内存（后续所有写请求自动携带）
    setCsrfToken(res.csrf_token)

    // 写入用户信息
    user.value = res.user
    initialized.value = true

    return res.user
  }

  /**
   * 注销：通知后端 → 清除本地状态 → 清除 CSRF Token
   */
  async function logout(): Promise<void> {
    try {
      await logoutApi()
    } finally {
      // 无论后端是否成功，前端都清除会话
      user.value = null
      clearCsrfToken()
    }
  }

  /**
   * 初始化（应用启动 / 页面刷新时调用）：
   * 尝试用现有 cookie 会话拉取当前用户。
   *
   * - 成功：恢复 user，页面维持在受保护路由
   * - 失败：user 保持 null，路由守卫将其重定向到 /login
   */
  async function init(): Promise<void> {
    try {
      // 先确保内存中有 CSRF Token
      await fetchAndStoreCsrfToken()
      // 再用该 Token 拉取用户信息
      const currentUser = await getCurrentUserApi()
      user.value = currentUser
    } catch {
      // 无有效会话 → user 保持 null
      user.value = null
    } finally {
      initialized.value = true
    }
  }

  // ============================================================
  // 导出
  // ============================================================

  return {
    // state
    user,
    initialized,
    // getters
    isLoggedIn,
    // actions
    login,
    logout,
    init,
  }
})
