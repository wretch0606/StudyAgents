// ============================================================
// StudyAgents — 身份认证 API
//
// 所有函数基于 src/utils/request.ts 的 http 实例，
// 类型严格引用 src/types/api.ts 的 V1.0 契约。
// ============================================================

import http from '../utils/request'
import type {
  LoginRequest,
  LoginResponse,
  CurrentUserResponse,
  LogoutResponse,
  CsrfTokenResponse,
} from '../types/api'

// ============================================================
// POST /api/auth/login
// ============================================================

/** 登录：提交用户名密码，返回用户信息与 CSRF Token */
export async function loginApi(data: LoginRequest): Promise<LoginResponse> {
  const response = await http.post<LoginResponse>('/auth/login', data)
  return response.data
}

// ============================================================
// GET /api/auth/me
// ============================================================

/** 获取当前登录用户信息（用于页面刷新后恢复会话） */
export async function getCurrentUserApi(): Promise<CurrentUserResponse> {
  const response = await http.get<CurrentUserResponse>('/auth/me')
  return response.data
}

// ============================================================
// POST /api/auth/logout
// ============================================================

/** 注销当前会话 */
export async function logoutApi(): Promise<LogoutResponse> {
  const response = await http.post<LogoutResponse>('/auth/logout')
  return response.data
}

// ============================================================
// GET /api/auth/csrf-token
// ============================================================

/** 刷新 CSRF Token（通常由请求拦截器自动处理，业务层较少直接调用） */
export async function refreshCsrfTokenApi(): Promise<CsrfTokenResponse> {
  const response = await http.get<CsrfTokenResponse>('/auth/csrf-token')
  return response.data
}
