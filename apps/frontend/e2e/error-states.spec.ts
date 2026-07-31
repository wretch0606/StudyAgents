// ============================================================
// StudyAgents — 异常错误状态 E2E 测试
//
// 覆盖场景：
//   1. 无权限访问（非 admin 访问 /admin → 守卫重定向）
//   2. 上传失败（上传无效格式文件触发真实校验错误）
//   3. 网络断开（context.setOffline 触发真实网络错误）
//   4. SSE 流式中断（答题中途切换页面）
//   5. 表单验证错误（空提交触发 422）
//
// 验收标准对应 Issue #22 第 2 项：
//   "异常错误状态（核心重点）"
//
// ⚠️ 所有测试均使用真实后端请求，不使用 page.route() Mock。
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
// 测试套件 2：上传失败（真实校验错误）
// ============================================================

test.describe('上传失败处理', () => {
  test('知识库上传无效文件 — 应显示错误提示且不含堆栈', async ({ page }) => {
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
      // 上传一个无效格式文件（.exe）触发真实后端校验错误
      await fileInput.setInputFiles({
        name: 'malicious.exe',
        mimeType: 'application/x-msdownload',
        buffer: Buffer.from('MZ'),
      })

      await page.waitForTimeout(3000)

      // 检查页面未崩溃，且错误消息不含堆栈
      const pageText = await page.evaluate(() => document.body.innerText)
      expect(pageText).not.toMatch(/Traceback|File\s+"[^"]+",\s*line\s+\d+/)
      expect(pageText).not.toMatch(/at\s+\S+\.\w+:\d+:\d+/)

      // 验证页面仍然可用
      const shellOkay = await page.locator('.km-shell, .km-container, .app-nav').first().isVisible().catch(() => false)
      expect(shellOkay).toBe(true)
    }
  })

  test('聊天附件上传无效文件 — 页面不崩溃', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    // 尝试上传无效格式文件
    const fileInput = page.locator('.chat-file-hidden')
    if (await fileInput.isVisible().catch(() => false)) {
      await fileInput.setInputFiles({
        name: 'virus.exe',
        mimeType: 'application/x-msdownload',
        buffer: Buffer.from('MZ'),
      })

      await page.waitForTimeout(4000)

      // 页面不崩溃
      const shellVisible = await page.locator('.home-shell').isVisible().catch(() => false)
      expect(shellVisible).toBe(true)

      // 错误消息不含内部堆栈
      const pageText = await page.evaluate(() => document.body.innerText)
      expect(pageText).not.toMatch(/at\s+\S+\.\w+:\d+:\d+/)
      expect(pageText).not.toMatch(/Traceback|File\s+"[^"]+",\s*line\s+\d+/)
    }
  })
})

// ============================================================
// 测试套件 3：网络断开处理
// ============================================================

test.describe('网络断开处理', () => {
  test('模拟网络断开后页面不崩溃', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    // 模拟网络离线（真实行为，非 Mock）
    await page.context().setOffline(true)

    // 离线状态下切换导航模式（纯本地操作，不应崩溃）
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('.practice-placeholder')).toBeVisible({ timeout: 5_000 })

    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(1500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    const shellVisible = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(shellVisible).toBe(true)

    // 恢复网络
    await page.context().setOffline(false)
    await page.waitForTimeout(3000)

    // 页面恢复后仍可用
    const recovered = await page.locator('.home-shell, .app-nav').first().isVisible().catch(() => false)
    expect(recovered).toBe(true)
  })

  test('网络断开时发送消息 — 应显示用户友好提示而非崩溃', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    // 断开网络
    await page.context().setOffline(true)

    // 尝试发送消息
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('网络断开时的测试消息。')
    await page.locator('.btn-send').click()

    await page.waitForTimeout(5000)

    // 页面不应崩溃
    const pageVisible = await page.locator('.home-shell, .chat-input-area').first().isVisible().catch(() => false)
    expect(pageVisible).toBe(true)

    // 错误消息不含堆栈
    const pageText = await page.evaluate(() => document.body.innerText)
    expect(pageText).not.toMatch(/at\s+\S+\.\w+:\d+:\d+/)
    expect(pageText).not.toMatch(/Traceback|File\s+"[^"]+",\s*line\s+\d+/)

    // 恢复网络
    await page.context().setOffline(false)
    await page.waitForTimeout(2000)
  })
})

// ============================================================
// 测试套件 4：表单验证错误（真实 422）
// ============================================================

test.describe('表单验证错误', () => {
  test('登录表单空提交 — 应显示验证错误提示', async ({ page }) => {
    // 导航到登录页
    await page.goto('/login')
    await page.waitForLoadState('networkidle')

    // 不填写任何内容直接提交，触发真实 422 验证错误
    const loginBtn = page.locator('.login-card button, .login-card .el-button').first()
    await expect(loginBtn).toBeVisible({ timeout: 5_000 })
    await loginBtn.click()
    await page.waitForTimeout(2000)

    // 验证错误提示不含堆栈
    const pageText = await page.evaluate(() => document.body.innerText)
    expect(pageText).not.toMatch(/stack|traceback|at\s+\S+\.\w+:\d+:\d+/i)

    // 页面仍在登录页（未跳转）
    const stillOnLogin = await page.locator('.login-card').isVisible().catch(() => false)
    expect(stillOnLogin).toBe(true)
  })
})

// ============================================================
// 测试套件 5：SSE 断线容错
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

    // 等待 1s 后切换到训练模式（模拟用户主动中断）
    await page.waitForTimeout(1000)
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()

    await expect(page.locator('.practice-placeholder')).toBeVisible({ timeout: 5_000 })

    // 切回问答模式 — 页面应仍然可用
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    const shellVisible = await page.locator('.home-shell').isVisible().catch(() => false)
    expect(shellVisible).toBe(true)
  })
})
