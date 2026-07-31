// ============================================================
// StudyAgents — 用户会话状态管理（Pinia Store）
//
// 职责：
//   1. 持有 Bearer Token（JWT）与当前用户信息
//   2. 封装 login / logout / init 动作
//   3. Token 同步持久化到 localStorage，页面刷新后可恢复
//   4. 登录/登出时同步设置/清除 request.ts 中的 Bearer Token，
//      确保请求拦截器自动携带 Authorization 头
//
// 与 useAuthStore 的关系：
//   - useAuthStore 负责 CSRF Token（X-CSRF-Token 头）
//   - useUserStore 负责 Bearer Token（Authorization 头）
//   - 二者协作完成完整的认证闭环
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserInfo, LoginRequest } from '../types/api'
import { loginApi, getCurrentUserApi } from '../api/auth'
import {
  setBearerToken,
  clearBearerToken,
  setCsrfToken,
  clearCsrfToken,
} from '../utils/request'

/** localStorage 键名 */
const TOKEN_KEY = 'authToken'
const USER_KEY = 'authUser'

// ============================================================
// Store 定义
// ============================================================

export const useUserStore = defineStore('user', () => {
  // ============================================================
  // State
  // ============================================================

  /** 从 localStorage 恢复用户信息（页面刷新后同步可用） */
  function loadUserFromStorage(): UserInfo | null {
    try {
      const raw = localStorage.getItem(USER_KEY)
      return raw ? (JSON.parse(raw) as UserInfo) : null
    } catch {
      return null
    }
  }

  /** Bearer Token（页面刷新后从 localStorage 恢复） */
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY))

  /** 当前登录用户信息（页面刷新后从 localStorage 同步恢复） */
  const user = ref<UserInfo | null>(loadUserFromStorage())

  /** 是否已完成初始化检查 */
  const initialized = ref(false)

  /** 是否正在执行登录请求 */
  const loggingIn = ref(false)

  // ============================================================
  // Getters
  // ============================================================

  /** 当前是否已登录（有有效 Token） */
  const isLoggedIn = computed(() => token.value !== null)

  /** 当前用户是否为管理员 */
  const isAdmin = computed(() => user.value?.role === 'admin')

  // ============================================================
  // Actions
  // ============================================================

  /**
   * 登录：提交凭证 → 持久化登录标记 → 写入用户信息。
   *
   * 真实后端（Session Cookie 模式）：
   *   LoginResponse = { user, csrf_token }（无 JWT token 字段）。
   *   前端用 csrf_token 作为"已登录"标记持久化，
   *   实际 API 认证依赖 Session Cookie（withCredentials） + X-CSRF-Token 头。
   *
   * @param username 用户名
   * @param password 密码
   * @returns 登录后的 UserInfo
   */
  async function login(username: string, password: string): Promise<UserInfo> {
    loggingIn.value = true

    try {
      const request: LoginRequest = { username, password }
      const response = await loginApi(request)

      // 真实后端 LoginResponse = { user, csrf_token }，不返回 JWT。
      // 以 csrf_token 作为"已登录"标记持久化到 localStorage，
      // 保证页面刷新后路由守卫仍能判定 isLoggedIn = true。
      const authToken = response.csrf_token

      // 持久化登录标记到 localStorage（页面刷新后恢复）
      localStorage.setItem(TOKEN_KEY, authToken)

      // 同步写入 CSRF Token（写请求需要 X-CSRF-Token 头）
      setCsrfToken(response.csrf_token)

      // 持久化用户信息到 localStorage（路由守卫同步读取角色）
      localStorage.setItem(USER_KEY, JSON.stringify(response.user))

      // 写入 Pinia 状态
      token.value = authToken
      user.value = response.user
      initialized.value = true

      return response.user
    } finally {
      loggingIn.value = false
    }
  }

  /**
   * 注销：清除本地 Token、用户信息与 CSRF Token。
   */
  function logout(): void {
    // 清除 localStorage
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)

    // 清除内存中的 Token
    clearBearerToken()
    clearCsrfToken()

    // 清除 Pinia 状态
    token.value = null
    user.value = null
  }

  /**
   * 初始化（应用启动 / 页面刷新时调用）：
   * 从 localStorage 恢复 Token → 尝试从后端获取用户信息。
   *
   * - Token 存在且有效：恢复 user
   * - Token 不存在或已过期：user 保持 null，路由守卫重定向到 /login
   */
  async function init(): Promise<void> {
    const storedToken = localStorage.getItem(TOKEN_KEY)

    if (!storedToken) {
      initialized.value = true
      return
    }

    // 恢复 Token 到内存
    setBearerToken(storedToken)
    token.value = storedToken

    try {
      const currentUser = await getCurrentUserApi()
      user.value = currentUser
    } catch {
      // Token 无效或网络错误 → 清除状态
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      clearBearerToken()
      clearCsrfToken()
      token.value = null
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
    token,
    user,
    initialized,
    loggingIn,
    // getters
    isLoggedIn,
    isAdmin,
    // actions
    login,
    logout,
    init,
  }
})
