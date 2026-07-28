// ============================================================
// StudyAgents — Axios 请求封装（纯底层 HTTP 客户端）
//
// 职责：
//   1. 创建 Axios 实例，配置 baseURL + withCredentials
//   2. 请求拦截器：自动注入 X-CSRF-Token、X-Idempotency-Key
//   3. 响应拦截器：解析 ApiError、自动重试（复用幂等键）、
//      ElMessage 全局错误提示、401 会话过期重定向
//   4. 对上层暴露 http 实例 + CSRF / 登录重定向工具函数
//
// 对应类型契约：src/types/api.ts（V1.0 已冻结）
// ============================================================

import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import { ElMessage } from 'element-plus'
import type { ApiError, CsrfTokenResponse } from '../types/api'

// ============================================================
// 0. 扩展 Axios 配置（内部字段，业务层不应直接使用）
// ============================================================

declare module 'axios' {
  interface AxiosRequestConfig {
    /**
     * 标记此请求为幂等写操作。
     * 设为 true 后，拦截器自动生成 UUID 并注入 X-Idempotency-Key 请求头；
     * 自动重试时复用同一个键，不会生成新键。
     */
    idempotent?: boolean

    /**
     * [内部] 已分配的幂等键。
     * 首次请求时由拦截器写入；重试时直接复用。
     * 业务代码请勿手动设置此字段。
     */
    _idempotencyKey?: string

    /**
     * [内部] 当前已重试次数。
     * 由响应拦截器递增并用于退避计算。
     */
    _retryCount?: number

    /**
     * [内部] CSRF Token 刷新后是否已重试过。
     * 防止无限刷新→重试循环。
     */
    _csrfRetried?: boolean

    /**
     * 跳过自动 ElMessage 错误提示。
     * 适用于业务层需要自行处理错误文案的场景。
     */
    skipErrorToast?: boolean
  }
}

// ============================================================
// 1. 常量
// ============================================================

/** 最大自动重试次数 */
const MAX_RETRIES = 2

/** 基础重试延迟（ms），实际延迟 = delay * retryCount（指数退避） */
const BASE_RETRY_DELAY_MS = 800

/** 可自动重试的 HTTP 状态码 */
const RETRYABLE_STATUS_CODES: ReadonlySet<number> = new Set([
  408, // Request Timeout
  429, // Too Many Requests
  500, // Internal Server Error
  502, // Bad Gateway
  503, // Service Unavailable
  504, // Gateway Timeout
])

// ============================================================
// 2. CSRF Token（仅存内存，不持久化）
// ============================================================

let csrfToken: string | null = null

/** 手动写入 CSRF Token（登录成功后调用） */
export function setCsrfToken(token: string): void {
  csrfToken = token
}

/** 读取当前内存中的 CSRF Token */
export function getCsrfToken(): string | null {
  return csrfToken
}

/** 清除 CSRF Token（登出 / 会话过期时调用） */
export function clearCsrfToken(): void {
  csrfToken = null
}

// ============================================================
// 2b. Bearer Token（JWT，持久化到 localStorage）
// ============================================================

let bearerToken: string | null = null

/** 手动写入 Bearer Token（登录成功后调用） */
export function setBearerToken(token: string): void {
  bearerToken = token
}

/** 读取当前内存中的 Bearer Token */
export function getBearerToken(): string | null {
  return bearerToken
}

/** 清除 Bearer Token（登出 / 会话过期时调用） */
export function clearBearerToken(): void {
  bearerToken = null
}

/**
 * 从后端获取 CSRF Token 并存入内存。
 * 应用启动、页面刷新、Token 失效恢复时调用。
 *
 * 对应契约：GET /api/auth/csrf-token → CsrfTokenResponse
 */
export async function fetchAndStoreCsrfToken(): Promise<string> {
  // 直接使用 axios（而非 http 实例），避免循环依赖和缺少 Token 的死锁
  const response = await axios.get<CsrfTokenResponse>('/api/auth/csrf-token', {
    withCredentials: true,
  })
  csrfToken = response.data.csrf_token
  return csrfToken
}

// ============================================================
// 3. 登录重定向
// ============================================================

type LoginRedirectHandler = () => void

let loginRedirectHandler: LoginRedirectHandler = () => {
  // 默认行为：硬跳转到 /login
  window.location.href = '/login'
}

/**
 * 注册 401 会话过期时的重定向回调。
 * 应用初始化时调用，可接入 vue-router：
 *
 * ```ts
 * import { useRouter } from 'vue-router'
 * setLoginRedirectHandler(() => {
 *   const router = useRouter()
 *   router.push('/login')
 * })
 * ```
 */
export function setLoginRedirectHandler(handler: LoginRedirectHandler): void {
  loginRedirectHandler = handler
}

// ============================================================
// 4. Axios 实例
// ============================================================

const http: AxiosInstance = axios.create({
  baseURL: '/api',
  withCredentials: true,
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ============================================================
// 5. 工具函数
// ============================================================

/** Promise 形式的延迟（用于重试退避） */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 从 AxiosError 中提取结构化 ApiError */
function extractApiError(error: AxiosError): ApiError | null {
  if (error.response?.data && typeof error.response.data === 'object') {
    const data = error.response.data as Record<string, unknown>
    if (typeof data.code === 'string' && typeof data.message === 'string') {
      return {
        code: data.code as string,
        message: data.message as string,
        retryable: (data.retryable as boolean) ?? false,
        trace_id: (data.trace_id as string) ?? '',
        details: data.details,
      }
    }
  }
  return null
}

/** 判断当前错误是否应自动重试 */
function shouldRetry(error: AxiosError, retryCount: number): boolean {
  if (retryCount >= MAX_RETRIES) return false

  // 请求已被用户取消 → 不重试
  if (axios.isCancel(error)) return false

  // 网络超时（ECONNABORTED）
  if (error.code === 'ECONNABORTED') return true

  // 网络层错误（无 response，如断网、DNS 失败）
  if (!error.response) return true

  // HTTP 状态码在可重试范围内
  const status = error.response.status
  if (RETRYABLE_STATUS_CODES.has(status)) {
    // 若后端在 ApiError 中明确标记 retryable: false，则不重试
    const apiError = error.response.data as ApiError | undefined
    if (apiError && apiError.retryable === false) return false
    return true
  }

  return false
}

// ============================================================
// 6. 请求拦截器
// ============================================================

http.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // --- 6.1 CSRF Token ---
    if (csrfToken && config.headers) {
      config.headers['X-CSRF-Token'] = csrfToken
    }

    // --- 6.1b Bearer Token (JWT) ---
    if (bearerToken && config.headers) {
      config.headers['Authorization'] = `Bearer ${bearerToken}`
    }

    // --- 6.2 幂等键 ---
    if (config.idempotent && config.headers) {
      // 首次请求：生成新 UUID 并写入 config
      // 重试请求：config._idempotencyKey 已存在，直接复用
      if (!config._idempotencyKey) {
        config._idempotencyKey = crypto.randomUUID()
      }
      config.headers['X-Idempotency-Key'] = config._idempotencyKey
    }

    return config
  },
  (error: AxiosError) => Promise.reject(error),
)

// ============================================================
// 7. 响应拦截器
// ============================================================

http.interceptors.response.use(
  // 2xx：直接透传包装后的 axios 响应对象
  (response) => response,

  // 非 2xx / 网络错误
  async (error: AxiosError<ApiError>) => {
    const config = error.config as
      | (InternalAxiosRequestConfig & {
          _retryCount?: number
          _idempotencyKey?: string
          _csrfRetried?: boolean
          skipErrorToast?: boolean
        })
      | undefined

    // ----- 7.1 自动重试（复用同一幂等键） -----
    if (config && shouldRetry(error, config._retryCount ?? 0)) {
      config._retryCount = (config._retryCount ?? 0) + 1

      // 指数退避：800ms、1600ms
      await sleep(BASE_RETRY_DELAY_MS * config._retryCount)

      // 使用同一个 config 重试，_idempotencyKey 不变
      // → X-Idempotency-Key 保持首次分配的值
      return http.request(config)
    }

    // ----- 7.2 解析结构化错误 -----
    const apiError = extractApiError(error)

    // ----- 7.3 CSRF Token 失效 → 刷新后重试一次 -----
    if (
      config &&
      apiError?.code === 'CSRF_TOKEN_INVALID' &&
      !config._csrfRetried
    ) {
      config._csrfRetried = true
      try {
        await fetchAndStoreCsrfToken()
        if (config.headers) {
          config.headers['X-CSRF-Token'] = csrfToken
        }
        return http.request(config)
      } catch {
        // 刷新失败，继续走错误提示
      }
    }

    // ----- 7.4 401 会话过期 → 登录重定向 -----
    if (
      error.response?.status === 401 ||
      apiError?.code === 'AUTH_SESSION_EXPIRED'
    ) {
      clearCsrfToken()
      loginRedirectHandler()
      return Promise.reject(error)
    }

    // ----- 7.5 UI 错误提示 -----
    if (!config?.skipErrorToast) {
      if (apiError?.message) {
        ElMessage.error(apiError.message)
      } else if (!error.response && error.code !== 'ECONNABORTED') {
        // 网络不可达（非超时），给出通用提示
        ElMessage.error('网络连接失败，请检查网络后重试')
      } else if (error.code === 'ECONNABORTED') {
        ElMessage.error('请求超时，已自动重试，仍失败请稍后再试')
      }
    }

    return Promise.reject(error)
  },
)

// ============================================================
// 8. 导出
// ============================================================

/** Axios 实例（默认导出，供各业务 API 模块使用） */
export default http

/**
 * 便捷导出：是否为 Axios 取消错误（配合 AbortSignal 使用）
 *
 * ```ts
 * try {
 *   await http.get('/api/...', { signal: abortController.signal })
 * } catch (e) {
 *   if (isCancel(e)) return // 用户取消，忽略
 *   // 真实错误处理...
 * }
 * ```
 */
export { axios }
export const isCancel = axios.isCancel
