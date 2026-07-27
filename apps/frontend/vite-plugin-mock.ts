// ============================================================
// StudyAgents — Vite Mock 插件（仅 dev 模式生效）
//
// 职责：
//   1. 在 Vite 开发服务器启动时，读取 contracts/mock/ 中的
//      JSON 响应文件作为 Mock 数据源
//   2. 拦截 /api/auth/* 请求，直接返回 Mock 数据，不经过代理
//   3. 非 Mock 路由原样放行，交给后续中间件（proxy 等）
//
// 架构：
//   向 connect 中间件栈的最前端注入一个拦截器，保证 Mock
//   优先于 Vite 内置的 server.proxy 中间件。
//
// 约束：
//   - 不修改 Pinia Store 或 request.ts 的任何业务逻辑
//   - Mock 数据与 API 类型契约（src/types/api.ts）严格对齐
// ============================================================

import type { Plugin, ViteDevServer } from 'vite'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// ============================================================
// 路径常量
// ============================================================

const __dirname = dirname(fileURLToPath(import.meta.url))
const MOCK_ROOT = resolve(__dirname, '../../contracts/mock')

// ============================================================
// Mock 路由表
// ============================================================

/** 模拟网络延迟（ms） */
const MOCK_DELAY_MS = 1000

/** 需要拦截的路由：method → path → JSON 文件 */
const MOCK_ROUTES: Record<string, Record<string, string>> = {
  POST: {
    '/api/auth/login': 'auth/login.json',
    '/api/auth/logout': 'auth/logout.json',
    '/api/admin/knowledge/upload': 'admin/knowledge-upload.json',
    '/api/chat/upload': 'chat/upload.json',
  },
  GET: {
    '/api/auth/csrf-token': 'auth/csrf-token.json',
    '/api/auth/me': 'auth/me.json',
    '/api/chat/history': 'chat/history.json',
  },
}

/** 文件上传类路由（multipart/form-data，不解析 JSON body） */
const UPLOAD_ROUTES: ReadonlySet<string> = new Set([
  '/api/admin/knowledge/upload',
  '/api/chat/upload',
])

// ============================================================
// 工具函数
// ============================================================

/** 从 contracts/mock/ 读取 JSON Mock 数据（同步，启动时缓存） */
function loadMock(filePath: string): object {
  const fullPath = resolve(MOCK_ROOT, filePath)
  try {
    return JSON.parse(readFileSync(fullPath, 'utf-8'))
  } catch (err) {
    console.error(`[studyagents-mock] 无法加载 Mock 文件: ${fullPath}`, err)
    throw err
  }
}

/** 解析 POST 请求的 JSON body */
function parseBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    req.on('data', (chunk: Buffer) => chunks.push(chunk))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf-8')
      if (!raw.trim()) {
        return resolve({})
      }
      try {
        resolve(JSON.parse(raw))
      } catch {
        reject(new Error('Invalid JSON body'))
      }
    })
    req.on('error', reject)
  })
}

/** 发送 JSON 响应 */
function sendJson(
  res: ServerResponse,
  data: object,
  statusCode = 200,
): void {
  const body = JSON.stringify(data)
  res.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
  })
  res.end(body)
}

// ============================================================
// 插件入口
// ============================================================

export function mockPlugin(): Plugin {
  // 预加载所有 Mock 数据到内存（避免每次请求读磁盘）
  const mockCache: Record<string, object> = {}

  return {
    name: 'studyagents-mock',
    apply: 'serve', // 仅 dev server 生效

    configureServer(server: ViteDevServer) {
      // ----- 预加载 Mock -----
      for (const methods of Object.values(MOCK_ROUTES)) {
        for (const fileName of Object.values(methods)) {
          if (!mockCache[fileName]) {
            mockCache[fileName] = loadMock(fileName)
          }
        }
      }
      // 额外预加载 admin 登录响应（由 login handler 内部引用，不在 MOCK_ROUTES 中）
      if (!mockCache['auth/login-admin.json']) {
        mockCache['auth/login-admin.json'] = loadMock('auth/login-admin.json')
      }

      // ----- 创建 Mock 中间件 -----
      const mockMiddleware = (
        req: IncomingMessage,
        res: ServerResponse,
        next: (err?: unknown) => void,
      ): void => {
        const method = (req.method ?? 'GET').toUpperCase()
        const url = req.url ?? '/'

        // 精确匹配（去除 query string）
        const pathname = url.split('?')[0]
        const routeMap = MOCK_ROUTES[method]
        const mockFile = routeMap?.[pathname]

        if (!mockFile) {
          // 非 Mock 路由 → 放行给后续中间件
          return next()
        }

        // Mock 路由 → 异步处理（需要解析 POST body）
        handleMockRequest(req, res, mockCache[mockFile], mockCache)
      }

      // ----- 注入到 connect 中间件栈的最前端 -----
      // connect 内部使用 stack 数组按序执行中间件；
      // unshift 到索引 0 保证它先于 proxy 等内置中间件运行
      const app = server.middlewares as unknown as {
        stack: Array<{ route: string; handle: (...args: unknown[]) => void }>
      }
      app.stack.unshift({ route: '', handle: mockMiddleware as (...args: unknown[]) => void })
    },
  }
}

// ============================================================
// Mock 请求处理
// ============================================================

async function handleMockRequest(
  req: IncomingMessage,
  res: ServerResponse,
  mockData: object,
  mockCache: Record<string, object>,
): Promise<void> {
  const method = (req.method ?? 'GET').toUpperCase()
  const pathname = (req.url ?? '/').split('?')[0]
  const isUpload = UPLOAD_ROUTES.has(pathname)

  try {
    if (method === 'POST') {
      // ----- 文件上传路由：跳过 JSON 解析，直接返回 Mock 数据 + 模拟延迟 -----
      if (isUpload) {
        await sleep(MOCK_DELAY_MS)
        return sendJson(res, mockData)
      }

      // ----- POST: 解析 body 并可做简单校验 -----
      const body = await parseBody(req)

      // 登录接口：校验非空 + 管理员凭据分流
      if (req.url?.startsWith('/api/auth/login')) {
        const creds = body as Record<string, unknown>
        if (!creds.username || !creds.password) {
          return sendJson(
            res,
            {
              code: 'VALIDATION_ERROR',
              message: '用户名和密码不能为空',
              retryable: false,
              trace_id: 'mock-trace-validation',
            },
            422,
          )
        }

        // 管理员凭据 → 返回 admin 角色响应
        if (creds.username === 'admin' && creds.password === 'admin123') {
          return sendJson(res, mockCache['auth/login-admin.json'])
        }

        // 错误密码（仅 admin 用户校验密码，其余接受任意密码）
        if (creds.username === 'admin' && creds.password !== 'admin123') {
          return sendJson(
            res,
            {
              code: 'AUTH_INVALID_CREDENTIALS',
              message: '用户名或密码错误',
              retryable: false,
              trace_id: 'mock-trace-auth-failure',
            },
            401,
          )
        }
      }

      sendJson(res, mockData)
    } else {
      // ----- GET: 直接返回 -----
      sendJson(res, mockData)
    }
  } catch {
    sendJson(
      res,
      {
        code: 'MOCK_INTERNAL_ERROR',
        message: 'Mock 服务内部错误',
        retryable: false,
        trace_id: 'mock-trace-internal',
      },
      500,
    )
  }
}

/** Promise 形式的延迟 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
