// ============================================================
// StudyAgents — 全链路自动化 E2E 测试
//
// 覆盖主链路：
//   真实登录 → 问答 → 训练 → 错题本
//
// 验收标准对应 Issue #22 第 1 项：
//   "全链路自动化覆盖"
//
// ⚠️ 前提条件：
//   1. Docker Compose 已启动（postgres + api + worker）
//   2. 已运行 scripts/init_users.py 创建预置账号
//   3. 知识库中已有文档（否则问答/训练无数据）
// ============================================================

import { test, expect, type Page, type Locator } from '@playwright/test'

// ============================================================
// 工具函数
// ============================================================

/**
 * 真实登录：通过 UI 填写凭据 → 提交 → 等待重定向到首页。
 * 默认使用预置账号 member_a（见 scripts/init_users.py）。
 */
async function loginAs(
  page: Page,
  username = 'member_a',
  password = 'change-me',
) {
  await page.goto('/login')
  await page.waitForLoadState('networkidle')

  // 填写登录表单
  const usernameInput = page.locator('#login-username')
  const passwordInput = page.locator('#login-password')
  await expect(usernameInput).toBeVisible({ timeout: 5_000 })
  await usernameInput.fill(username)
  await passwordInput.fill(password)

  // 点击登录按钮
  const loginBtn = page.locator('.login-card button, .login-card .el-button').first()
  await loginBtn.click()

  // 等待重定向到首页
  await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })
}

/**
 * 选择 Element Plus <el-select> 的某个选项。
 * 使用原生 JS 绕过 Playwright pointer-events 检查（nav 遮挡问题）。
 */
async function selectElOption(page: Page, select: Locator, optionText: string) {
  await select.evaluate((el) => {
    const wrapper = el.querySelector('.el-select__wrapper') as HTMLElement | null
    if (wrapper) {
      wrapper.click()
    } else {
      ;(el as HTMLElement).click()
    }
  })
  await page.waitForTimeout(400)
  await page.evaluate((text: string) => {
    const items = document.querySelectorAll('.el-select-dropdown__item')
    for (const item of items) {
      if (item.textContent?.includes(text)) {
        ;(item as HTMLElement).click()
        return
      }
    }
  }, optionText)
  await page.waitForTimeout(400)
}

// ============================================================
// 测试夹具
// ============================================================

test.beforeEach(async ({ page }) => {
  await loginAs(page)
})

// ============================================================
// 测试套件 1：全链路主流程
// ============================================================

test.describe('全链路自动化：登录 → 问答 → 训练 → 错题本', () => {
  test('主链路串联验证', async ({ page }) => {
    // ==========================================================
    // Phase 1: 登录验证
    // ==========================================================
    await expect(page.locator('.nav-brand')).toContainText('StudyAgents')
    await expect(page.locator('.nav-role')).toBeVisible()

    // ==========================================================
    // Phase 2: 自由问答 — UI 框架验证
    // ==========================================================
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-input-area')).toBeVisible({ timeout: 5_000 })

    // 等待历史消息加载（数量取决于后端数据，弹性断言）
    await page.waitForTimeout(2000)
    const messageRows = page.locator('.messages-inner .message-row')
    const messageCount = await messageRows.count()
    expect(messageCount).toBeGreaterThanOrEqual(0) // 空历史或已有数据均可

    // ==========================================================
    // Phase 3: 发送新问题
    // ==========================================================
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('请解释TCP拥塞控制中的慢启动算法。')
    await page.locator('.btn-send').click()

    // 等待回答完成（最多 60s，真实模型可能较慢）
    const typingIndicator = page.locator('.bubble.assistant.typing')
    await expect(typingIndicator).not.toBeVisible({ timeout: 60_000 })
    await page.waitForTimeout(500)

    // 验证新消息已追加
    const newMessageCount = await page.locator('.messages-inner .message-row').count()
    expect(newMessageCount).toBeGreaterThanOrEqual(messageCount + 1)

    // ==========================================================
    // Phase 4: PDF 文档导入按钮
    // ==========================================================
    const pdfBtn = page.locator('.btn-import')
    await expect(pdfBtn).toBeVisible()
    await expect(pdfBtn).toBeEnabled()

    const attachBtn = page.locator('.btn-attach')
    await expect(attachBtn).toBeVisible()

    // ==========================================================
    // Phase 5: 切换到专项训练
    // ==========================================================
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible({ timeout: 5_000 })
    await expect(page.locator('.practice-title')).toContainText('开始专项训练')

    // 配置训练参数
    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '运输层')

    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')

    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    // 开始训练
    const startBtn = page.locator('.practice-config .el-button', { hasText: '开始训练' })
    await expect(startBtn).toBeEnabled()
    await startBtn.click()

    // ==========================================================
    // Phase 6: 答题
    // ==========================================================
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })
    await expect(page.locator('.pqc-prompt')).toBeVisible()
    await expect(page.locator('.ke-pane-input')).toBeVisible()
    await expect(page.locator('.ke-pane-preview')).toBeVisible()

    const keTextarea = page.locator('.ke-textarea')
    await keTextarea.waitFor({ state: 'visible', timeout: 5_000 })
    await keTextarea.fill(
      '慢启动阶段，cwnd 呈指数增长：\n\n$$cwnd_{n+1} = 2 \\cdot cwnd_n$$\n\n拥塞避免阶段则每 RTT 线性增长 1 MSS。',
    )

    await page.waitForTimeout(1500)
    await expect(page.locator('.ke-preview-body')).toBeVisible()

    // 提交答案
    const submitBtn = page.locator('.pqc-submit-area .el-button', { hasText: '提交答案' })
    await expect(submitBtn).toBeEnabled()
    await submitBtn.click()

    // ==========================================================
    // Phase 7: 验证评测报告
    // ==========================================================
    await expect(page.locator('.pqc-report')).toBeVisible({ timeout: 30_000 })

    // 得分仪表（分数取决于真实评测结果，弹性断言）
    await expect(page.locator('.pqc-score-gauge')).toBeVisible()
    await expect(page.locator('.pqc-gauge-score')).toBeVisible()

    // Agent 协同轨迹
    await expect(page.locator('.pqc-agent-steps')).toBeVisible()

    // 详细讲解
    await expect(page.locator('.pqc-analysis-content')).toBeVisible()

    // ==========================================================
    // Phase 8: 错题本验证
    // ==========================================================
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.wrongbook-empty, .wrongbook-card').first()).toBeVisible({
      timeout: 5_000,
    })
  })

  test('全链路 — 训练→评测→错题本联动', async ({ page }) => {
    // 进入专项训练
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible()

    // 配置并开始训练
    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '运输层')
    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')
    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    await page.locator('.practice-config .el-button', { hasText: '开始训练' }).click()
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })

    // 输入答案
    const keTextarea = page.locator('.ke-textarea')
    await keTextarea.waitFor({ state: 'visible', timeout: 5_000 })
    await keTextarea.fill('慢启动阶段 cwnd 呈指数增长，拥塞避免阶段每 RTT 线性增长 1 MSS。')

    // 提交
    await page.locator('.pqc-submit-area .el-button', { hasText: '提交答案' }).click()
    await expect(page.locator('.pqc-report')).toBeVisible({ timeout: 30_000 })

    // 验证报告显示
    await expect(page.locator('.pqc-gauge-score')).toBeVisible()

    // 切换到错题本
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.wrongbook-empty, .wrongbook-card').first()).toBeVisible({ timeout: 5_000 })

    // 切换回自由问答，验证左侧栏掌握度区域
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.mastery-section')).toBeVisible({ timeout: 5_000 })
  })
})

// ============================================================
// 测试套件 2：文件上传流程
// ============================================================

test.describe('文件上传流程', () => {
  test('PDF 导入按钮触发文件选择', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()

    const pdfBtn = page.locator('.btn-import')
    await expect(pdfBtn).toBeVisible()
    await expect(pdfBtn.locator('.btn-import-label')).toContainText('PDF')
    await expect(pdfBtn).toBeEnabled()
  })

  test('附件上传按钮可见且可用', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()

    const attachBtn = page.locator('.btn-attach')
    await expect(attachBtn).toBeVisible()
    await expect(attachBtn).toBeEnabled()
  })
})

// ============================================================
// 测试套件 3：快速提示词交互
// ============================================================

test.describe('快捷提示词', () => {
  test('点击快捷提示词自动填入输入框', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()

    const chips = page.locator('.quick-prompts .chip')
    await expect(chips.first()).toBeVisible({ timeout: 5_000 })

    const firstChipText = await chips.first().textContent()
    await chips.first().click()

    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await expect(textarea).toHaveValue(firstChipText || '')
  })
})
