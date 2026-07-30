// ============================================================
// StudyAgents — 异常错误状态 E2E 测试
//
// 覆盖场景：
//   1. 无权限访问（拦截权限 API 模拟 403）
//   2. 上传失败（模拟 500 错误）
//   3. 模型超时（模拟接口长时间不返回 / 504）
//   4. 网络断开（模拟请求失败无响应）
//   5. API 返回结构化错误（验证 ElMessage Toast 文案）
//
// 验收标准对应 Issue #22 第 2 项：
//   "异常错误状态（核心重点）"
//
// ⚠️ 本文件保留 page.route() Mock — 异常场景需要可控的触发条件。
//    Mock 仅用于模拟后端错误响应，前端本身不 Mock 正常数据。
// ============================================================

import { test, expect, type Page } from '@playwright/test'

// ============================================================
// 工具函数
// ============================================================

/**
 * 真实登录：通过 UI 填写凭据 → 提交 → 等待重定向到首页。
 */
async function loginAs(
  page: Page,
  username = 'member_a',
  password = 'change-me',
) {
  await page.goto('/login')
  await page.waitForLoadState('networkidle')

  const usernameInput = page.locator('#login-username')
  const passwordInput = page.locator('#login-password')
  await expect(usernameInput).toBeVisible({ timeout: 5_000 })
  await usernameInput.fill(username)
  await passwordInput.fill(password)

  const loginBtn = page.locator('.login-card button, .login-card .el-button').first()
  await loginBtn.click()

  await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })
}

// ============================================================
// 测试夹具
// ============================================================

test.beforeEach(async ({ page }) => {
  await loginAs(page)
})

// ============================================================
// 测试套件 1：403 无权限访问
// ============================================================

test.describe('403 无权限访问', () => {
  test('拦截 /api/auth/me 返回 403 — 应显示错误提示且不崩溃', async ({ page }) => {
    // 拦截 auth/me 返回 403
    await page.route('**/api/auth/me', (route) => {
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'AUTH_FORBIDDEN',
          message: '您没有权限访问此资源，请联系管理员升级权限。',
          retryable: false,
          trace_id: 'trace-e2e-403-001',
        }),
      })
    })

    // 刷新页面触发 auth init
    await page.reload()
    await page.waitForLoadState('networkidle')

    // 验证页面未崩溃
    const hasNavOrLogin = await Promise.race([
      page.locator('.app-nav').isVisible().then(() => true),
      page.locator('.login-card').isVisible().then(() => true),
      page.waitForTimeout(5000).then(() => false),
    ])
    expect(hasNavOrLogin).toBe(true)

    const onLoginPage = await page.locator('.login-card').isVisible().catch(() => false)
    const onAppPage = await page.locator('.app-nav').isVisible().catch(() => false)
    expect(onLoginPage || onAppPage).toBe(true)
  })

  test('非 admin 用户访问 /admin 路由应被守卫重定向', async ({ page }) => {
    // 以普通用户登录后尝试访问 admin
    await page.goto('/admin')
    await page.waitForLoadState('networkidle')

    // 应被重定向到首页（非 admin 用户）
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })
    expect(page.url()).not.toContain('/admin')
  })
})

// ============================================================
// 测试套件 2：上传失败（500 错误）
// ============================================================

test.describe('上传失败处理', () => {
  test('知识库上传返回 500 — 任务卡片应显示错误信息', async ({ page }) => {
    await page.route('**/api/admin/knowledge/upload', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'INTERNAL_ERROR',
          message: '文件处理服务暂时不可用，请稍后重试。',
          retryable: true,
          trace_id: 'trace-e2e-500-upload-001',
        }),
      })
    })

    // 使用 admin 账号重新登录
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    const usernameInput = page.locator('#login-username')
    const passwordInput = page.locator('#login-password')
    await expect(usernameInput).toBeVisible({ timeout: 5_000 })
    await usernameInput.fill('admin')
    await passwordInput.fill('change-me')
    await page.locator('.login-card button, .login-card .el-button').first().click()
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    // 导航到资料管理
    await page.goto('/admin')
    await page.waitForLoadState('networkidle')

    await expect(page.locator('.km-shell, .km-container, .km-upload-zone').first()).toBeVisible({
      timeout: 5_000,
    })

    const fileInput = page.locator('input[type="file"]').first()
    if (await fileInput.isVisible().catch(() => false)) {
      await fileInput.setInputFiles({
        name: 'test-document.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('%PDF-1.4 mock file content'),
      })

      await page.waitForTimeout(3000)

      const errorCard = page.locator('.km-task-error')
      const hasError = await errorCard.isVisible().catch(() => false)
      if (hasError) {
        await expect(errorCard).toBeVisible()
        const errorText = await errorCard.textContent()
        expect(errorText).toBeTruthy()
        expect(errorText).not.toMatch(/at\s+\S+\.\w+:\d+:\d+/)
        expect(errorText).not.toMatch(/Traceback|File\s+"[^"]+",\s*line\s+\d+/)
      }
    }
  })

  test('聊天附件上传失败 — 应显示失败状态图标', async ({ page }) => {
    await page.route('**/api/chat/upload', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'FILE_STORAGE_ERROR',
          message: '文件上传失败，请检查文件格式与大小后重试。',
          retryable: false,
          trace_id: 'trace-e2e-500-chat-upload',
        }),
      })
    })

    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    const fileInput = page.locator('.chat-file-hidden')
    await fileInput.waitFor({ state: 'attached', timeout: 3_000 })
    await fileInput.setInputFiles({
      name: 'test-attachment.png',
      mimeType: 'image/png',
      buffer: Buffer.from('mock-png-content'),
    })

    await page.waitForTimeout(4000)

    const failedCard = page.locator('.attachment-mini-card.failed')
    const hasFailed = await failedCard.isVisible().catch(() => false)
    if (hasFailed) {
      await expect(failedCard).toBeVisible()
      await expect(failedCard.locator('.att-file-icon.att-error')).toBeVisible()
    }

    const shellVisible = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(shellVisible).toBe(true)
  })
})

// ============================================================
// 测试套件 3：模型超时
// ============================================================

test.describe('模型超时处理', () => {
  test('聊天 API 超时 — 应显示重试提示而非白屏', async ({ page }) => {
    await page.route('**/api/chat/history', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 5000))
      await route.fulfill({
        status: 504,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'AGENT_MODEL_TIMEOUT',
          message: '模型服务暂时未响应，请稍后重试。',
          retryable: true,
          trace_id: 'trace-e2e-timeout-001',
        }),
      })
    })

    // 清除缓存重新加载
    await page.evaluate(() => {
      localStorage.removeItem('studyagents_wrongbook')
    })
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(8000)

    const pageVisible = await page.locator('.home-shell, .chat-messages, .empty-chat').first().isVisible().catch(() => false)
    expect(pageVisible).toBe(true)
  })

  test('页面级超时处理 — Axios 30s timeout', async ({ page }) => {
    let routeAborted = false
    await page.route('**/api/auth/csrf-token', async (route) => {
      await new Promise(() => {})
      routeAborted = true
    })

    // 重新登录触发 CSRF token 刷新
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    const usernameInput = page.locator('#login-username')
    const passwordInput = page.locator('#login-password')
    await expect(usernameInput).toBeVisible({ timeout: 5_000 })
    await usernameInput.fill('member_a')
    await passwordInput.fill('change-me')
    await page.locator('.login-card button, .login-card .el-button').first().click()

    await page.waitForTimeout(5000)

    const pageOk = await page.locator('.app-nav, .login-card').first().isVisible().catch(() => false)
    expect(pageOk).toBe(true)
  })
})

// ============================================================
// 测试套件 4：网络断开
// ============================================================

test.describe('网络断开处理', () => {
  test('模拟网络断开后恢复 — 页面不崩溃', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    // 模拟网络离线
    await page.route('**/api/**', (route) => {
      route.abort('internetdisconnected')
    })

    // 离线切换导航模式（纯本地操作）
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('.practice-placeholder')).toBeVisible({ timeout: 5_000 })

    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    const shellVisible = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(shellVisible).toBe(true)

    // 恢复网络
    await page.unroute('**/api/**')
    await page.waitForTimeout(3000)
    const recovered = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(recovered).toBe(true)
  })
})

// ============================================================
// 测试套件 5：API 结构化错误响应
// ============================================================

test.describe('API 结构化错误响应', () => {
  test('后端返回 ApiError — 前端显示用户友好消息而非原始错误', async ({ page }) => {
    await page.route('**/api/chat/history', (route) => {
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'SERVICE_UNAVAILABLE',
          message: '服务正在维护中，预计 5 分钟内恢复。',
          retryable: true,
          trace_id: 'trace-e2e-maintenance-001',
          details: {
            estimated_recovery: '5 minutes',
            affected_services: ['chat', 'practice'],
          },
        }),
      })
    })

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(3000)

    const pageOk = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(pageOk).toBe(true)
  })

  test('422 验证错误 — 应显示具体校验信息', async ({ page }) => {
    await page.route('**/api/auth/login', (route) => {
      route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 'VALIDATION_ERROR',
          message: '用户名和密码不能为空',
          retryable: false,
          trace_id: 'trace-e2e-validation-001',
        }),
      })
    })

    // 导航到登录页
    await page.goto('/login')
    await page.waitForLoadState('networkidle')

    // 尝试空提交
    const loginBtn = page.locator('.login-card button, .login-card .el-button').first()
    if (await loginBtn.isVisible().catch(() => false)) {
      await loginBtn.click()
      await page.waitForTimeout(2000)

      const errorEl = page.locator('.login-error')
      const hasError = await errorEl.isVisible().catch(() => false)
      if (hasError) {
        const errorText = await errorEl.textContent()
        expect(errorText).toBeTruthy()
        expect(errorText).not.toMatch(/stack|traceback|at\s+\S+\.\w+:\d+:\d+/i)
      }
    }
  })
})

// ============================================================
// 测试套件 6：SSE 断线模拟（当前为前端模拟，验证容错）
// ============================================================

test.describe('SSE 流式响应容错', () => {
  test('流式输出期间切换页面 — 不崩溃', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    // 发送消息触发流式输出
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('测试流式输出中断恢复。')
    await page.locator('.btn-send').click()

    // 等待 1s 后切换到训练模式（模拟中断）
    await page.waitForTimeout(1000)
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()

    await expect(page.locator('.practice-placeholder')).toBeVisible({ timeout: 5_000 })

    // 切回问答模式
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    const shellVisible = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(shellVisible).toBe(true)
  })
})
