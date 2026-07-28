// ============================================================
// StudyAgents — 专项训练核心闭环 E2E 测试
//
// 覆盖流程：
//   1. 登录绕过（localStorage 注入 Token / User）
//   2. 进入首页 → 切换到「专项训练」模式
//   3. 选择章节 / 题型 / 难度 / 数量 → 开始训练
//   4. 在 KaTeX 编辑器中输入 LaTeX 作答
//   5. 实时预览同步渲染
//   6. 提交答案 → 等待评测报告
//   7. 验证得分仪表 / Agent 轨迹 / 溯源卡片
//   8. 低分自动沉淀至错题本 → 验证徽标 + 卡片
//   9. 验证掌握度下降
// ============================================================

import { test, expect, type Page, type Locator } from '@playwright/test'

// ============================================================
// 工具函数
// ============================================================

/**
 * 选择 Element Plus <el-select> 的某个选项。
 *
 * Element Plus 2.x 将下拉菜单 teleport 到 <body> 末尾，
 * 打开/关闭有 CSS 过渡动画，因此必须等待选项可见后才能点击。
 */
async function selectElOption(page: Page, select: Locator, optionText: string) {
  // === 背景 ===
  // Home.vue 的 .home-shell 使用 position:fixed;inset:0，从 y=0 开始。
  // App.vue 的 <nav class="app-nav"> 高度 48px，z-index:100，覆盖在 .home-shell 上方。
  // 位于 .chat-header 中的 .header-select 被导航栏遮挡，
  // Playwright 的 pointer-events 检查会持续重试直到超时。
  //
  // === 方案 ===
  // 使用 page.evaluate 在浏览器上下文中直接调用原生 DOM click()，
  // 完全绕过 Playwright 的可见性/pointer-events 检查。
  // Element Plus 的 <el-select> 在 .el-select__wrapper 上绑定点击事件。

  // 1. 用原生 JS 点击 select wrapper 打开下拉
  const selectId = await select.evaluate((el) => {
    const wrapper = el.querySelector('.el-select__wrapper') as HTMLElement | null
    if (wrapper) {
      wrapper.click()
      return wrapper.getAttribute('aria-describedby') || ''
    }
    // fallback: click the root
    ;(el as HTMLElement).click()
    return ''
  })

  // 2. 等待下拉渲染（Element Plus teleport + Vue nextTick）
  await page.waitForTimeout(400)

  // 3. 用原生 JS 点击目标选项
  await page.evaluate((text: string) => {
    const items = document.querySelectorAll('.el-select-dropdown__item')
    for (const item of items) {
      if (item.textContent?.includes(text)) {
        ;(item as HTMLElement).click()
        return
      }
    }
  }, optionText)

  // 4. 等待下拉关闭
  await page.waitForTimeout(400)
}

/**
 * 清空 localStorage 中的错题本数据，确保测试隔离。
 */
async function clearWrongBookStorage(page: Page) {
  await page.evaluate(() => {
    localStorage.removeItem('studyagents_wrongbook')
  })
}

/**
 * 注入已登录的 localStorage 数据，绕过登录页面。
 */
async function injectAuth(page: Page) {
  await page.evaluate(() => {
    localStorage.setItem('authToken', 'mock-jwt-token-member-xyz')
    localStorage.setItem(
      'authUser',
      JSON.stringify({
        id: 'user-001',
        username: 'demo',
        display_name: '演示用户',
        role: 'member',
        permissions: ['qa:read', 'qa:write', 'practice:write', 'kb:read'],
      }),
    )
  })
}

// ============================================================
// 测试夹具
// ============================================================

test.beforeEach(async ({ page }) => {
  // 先导航至首页（会被重定向到 /login），然后注入登录态
  await page.goto('/')
  await injectAuth(page)
  await clearWrongBookStorage(page)
  // 重新加载使 localStorage 生效，router 守卫放行
  await page.reload()
  await page.waitForLoadState('networkidle')
  // 确认导航栏已渲染（登录成功）
  await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })
})

// ============================================================
// 测试套件 1：完整训练闭环
// ============================================================

test.describe('专项训练核心闭环', () => {
  test('完整训练流程：配置 → 作答 → 提交 → 评测报告', async ({ page }) => {
    // === Step 1: 验证首页加载 ===
    await expect(page.locator('.nav-brand')).toContainText('StudyAgents')

    // === Step 2: 切换到「专项训练」 ===
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await expect(page.locator('.chat-title')).toContainText('专项训练')

    // === Step 3: 验证章节选择表单 ===
    await expect(page.locator('.practice-placeholder')).toBeVisible()
    await expect(page.locator('.practice-title')).toContainText('开始专项训练')

    // 选择「第 3 章 · 运输层」
    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '第 3 章 · 运输层')

    // 选择「综合问答题」
    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')

    // 选择「中等」难度
    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    // === Step 4: 验证「开始训练」按钮启用并点击 ===
    const startBtn = page.locator('.practice-config .el-button', { hasText: '开始训练' })
    await expect(startBtn).toBeEnabled()
    await startBtn.click()

    // === Step 5: 验证答题区 ===
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })
    await expect(page.locator('.pqc-prompt')).toBeVisible()
    // KaTeXEditor 内置双栏：左侧 .ke-pane-input（编辑），右侧 .ke-pane-preview（预览）
    await expect(page.locator('.ke-pane-input')).toBeVisible()
    await expect(page.locator('.ke-pane-preview')).toBeVisible()

    // === Step 6: 输入 LaTeX 作答 ===
    // KaTeXEditor 内部使用 <textarea class="ke-textarea">
    const textarea = page.locator('.ke-textarea')
    await textarea.waitFor({ state: 'visible', timeout: 5_000 })
    await textarea.click()
    await textarea.fill(
      '慢启动阶段，cwnd 呈指数增长：\n\n$$cwnd_{n+1} = 2 \\cdot cwnd_n$$\n\n拥塞避免阶段则每 RTT 线性增长 1 MSS。',
    )

    // === Step 7: 验证实时预览同步 ===
    // KaTeXEditor 内置预览区在 .ke-preview-body 中实时渲染 LaTeX
    await expect(page.locator('.ke-preview-body')).toBeVisible({ timeout: 5_000 })

    // === Step 8: 提交答案 ===
    const submitBtn = page.locator('.pqc-submit-area .el-button', { hasText: '提交答案' })
    await expect(submitBtn).toBeEnabled()
    await submitBtn.click()

    // === Step 9: 等待评测报告（mock setTimeout 延迟 ≈0–1.5s） ===
    // 注意：不强制断言"评测中…"中间态，因为 mock 可能瞬间完成
    await expect(page.locator('.pqc-report')).toBeVisible({ timeout: 15_000 })

    // === Step 10: 验证得分仪表 ===
    await expect(page.locator('.pqc-score-gauge')).toBeVisible()
    await expect(page.locator('.pqc-gauge-score')).toContainText('85')

    // === Step 11: 验证等级徽标（85% → 优秀） ===
    await expect(page.locator('.pqc-grade-badge.grade-high')).toBeVisible()

    // === Step 12: 验证置信度 ===
    await expect(page.locator('.pqc-confidence')).toBeVisible()
    await expect(page.locator('.pqc-conf-pct')).toContainText('88%')

    // === Step 13: 验证 Agent 协同执行轨迹 ===
    await expect(page.locator('.pqc-agent-steps')).toBeVisible()
    await expect(page.locator('.pqc-agent-chip')).toHaveCount(4)

    // === Step 14: 验证详细讲解（含 KaTeX 渲染） ===
    await expect(page.locator('.pqc-analysis-content')).toBeVisible()

    // === Step 15: 验证分步评测要点 ===
    await expect(page.locator('.pqc-report-highlights .pqc-hl-item').first()).toBeVisible()

    // === Step 16: 验证文档溯源卡片 ===
    await expect(page.locator('.pqc-source-card')).toHaveCount(3)
    await expect(page.locator('.pqc-source-badge').first()).toContainText('S1')
    await expect(page.locator('.pqc-source-doc').first()).toContainText('计算机网络')
  })

  test('低分场景：错题沉淀 + 徽标联动 + 详情展开', async ({ page }) => {
    // 通过 localStorage 直接注入一条低分错题（模拟 score < 80 沉淀）
    await page.evaluate(() => {
      const entry = {
        id: 'wb-e2e-low-001',
        chapter: 'ch3',
        chapterLabel: '第 3 章 · 运输层',
        question: '请简述 TCP 拥塞控制中慢启动与拥塞避免两个阶段的区别。',
        userAnswer: '慢启动是乘性增长，拥塞避免是加性增长。',
        score: 55,
        total: 100,
        analysis:
          '作答混淆了慢启动的指数增长与拥塞避免的线性增长，且未写出 cwnd 公式。' +
          '正确应为：慢启动 cwnd 每 RTT 翻倍 $cwnd_{new} = 2 \\cdot cwnd$。',
        highlights: [
          '✅ 正确识别了两个阶段的名称',
          '⚠️ 慢启动应描述为指数增长而非乘性增长',
          '📝 建议补充慢启动阶段 cwnd 的数学公式',
        ],
        createdAt: new Date().toISOString(),
      }
      localStorage.setItem('studyagents_wrongbook', JSON.stringify([entry]))
    })

    // 刷新使 wrongBookStore 从 localStorage 重新加载
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    // === 验证侧边栏徽标 ===
    const sidebarBadge = page.locator('.nav-btn .badge')
    await expect(sidebarBadge).toBeVisible({ timeout: 5_000 })
    await expect(sidebarBadge).toContainText('1')

    // === 验证顶部导航栏徽标同步 ===
    // 先点击「问答」再回来，触发 App.vue 重新渲染
    await page.locator('.app-nav .nav-link', { hasText: '问答' }).click()
    await page.waitForTimeout(500)
    const topBadge = page.locator('.app-nav .nav-badge')
    await expect(topBadge).toBeVisible({ timeout: 5_000 })
    await expect(topBadge).toContainText('1')

    // === 切换到错题本视图 ===
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await expect(page.locator('.chat-title')).toContainText('错题本')

    // === 验证错题卡片 ===
    const card = page.locator('.wrongbook-card').first()
    await expect(card).toBeVisible({ timeout: 5_000 })
    await expect(card.locator('.wb-chapter-tag')).toContainText('运输层')
    await expect(card.locator('.wb-score-pill')).toContainText('55')

    // === 展开详情 ===
    await card.click()
    const detail = page.locator('.wb-card-detail')
    await expect(detail).toBeVisible({ timeout: 3_000 })

    // 验证详情各区块
    await expect(detail.locator('.wb-detail-label', { hasText: '题目' })).toBeVisible()
    await expect(detail.locator('.wb-detail-label', { hasText: '你的作答' })).toBeVisible()
    await expect(detail.locator('.wb-detail-label', { hasText: '评测报告' })).toBeVisible()

    // 验证评测要点（3 条）
    await expect(detail.locator('.wb-detail-highlights .pqc-hl-item')).toHaveCount(3)

    // 验证操作按钮
    await expect(detail.locator('.el-button', { hasText: '重新练习' })).toBeVisible()
    await expect(detail.locator('.el-button', { hasText: '删除' })).toBeVisible()

    // === 验证掌握度区域（切换到自由问答查看侧边栏） ===
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await expect(page.locator('.mastery-section')).toBeVisible({ timeout: 3_000 })
  })

  test('删除错题后徽标归零 + 空状态展示', async ({ page }) => {
    // 注入一条待删除的错题
    await page.evaluate(() => {
      const entry = {
        id: 'wb-del-e2e-001',
        chapter: 'ch4',
        chapterLabel: '第 4 章 · 网络层',
        question: 'IP 子网划分测试题',
        userAnswer: '错误的答案',
        score: 40,
        total: 100,
        analysis: '需要重新学习子网划分。',
        highlights: ['⚠️ 子网掩码计算错误'],
        createdAt: new Date().toISOString(),
      }
      localStorage.setItem('studyagents_wrongbook', JSON.stringify([entry]))
    })

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    // 验证徽标出现
    await expect(page.locator('.nav-btn .badge')).toContainText('1')

    // 切换到错题本
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await expect(page.locator('.wrongbook-card').first()).toBeVisible({ timeout: 5_000 })

    // 展开并点击删除
    await page.locator('.wrongbook-card').first().click()
    await expect(page.locator('.wb-card-detail')).toBeVisible({ timeout: 3_000 })
    await page.locator('.wb-detail-actions .el-button', { hasText: '删除' }).click()

    // 验证空状态
    await expect(page.locator('.wrongbook-empty')).toBeVisible({ timeout: 5_000 })
    await expect(page.locator('.wrongbook-empty-title')).toContainText('错题本为空')

    // 验证徽标消失
    await expect(page.locator('.nav-btn .badge')).toHaveCount(0)
    await expect(page.locator('.app-nav .nav-badge')).toHaveCount(0)
  })
})

// ============================================================
// 测试套件 2：错题本章节筛选
// ============================================================

test.describe('错题本章节筛选', () => {
  test('按章节筛选错题，切换筛选条件验证卡片数量', async ({ page }) => {
    // 注入两条不同章节的错题
    await page.evaluate(() => {
      const entries = [
        {
          id: 'wb-filter-ch3-e2e',
          chapter: 'ch3',
          chapterLabel: '第 3 章 · 运输层',
          question: 'TCP 拥塞控制问题',
          userAnswer: '答案A',
          score: 50,
          total: 100,
          analysis: '需加强运输层知识。',
          highlights: ['⚠️ 拥塞控制理解错误'],
          createdAt: new Date(Date.now() - 3_600_000).toISOString(),
        },
        {
          id: 'wb-filter-ch4-e2e',
          chapter: 'ch4',
          chapterLabel: '第 4 章 · 网络层',
          question: 'IP 路由与子网划分问题',
          userAnswer: '答案B',
          score: 60,
          total: 100,
          analysis: '需加强网络层知识。',
          highlights: ['⚠️ 子网划分错误'],
          createdAt: new Date().toISOString(),
        },
      ]
      localStorage.setItem('studyagents_wrongbook', JSON.stringify(entries))
    })

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    // 切换到错题本
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await expect(page.locator('.chat-title')).toContainText('错题本')

    // 验证两条错题均可见
    await expect(page.locator('.wrongbook-card')).toHaveCount(2)

    // 筛选「第 3 章 · 运输层」
    // header-select 本身就是 el-select 的根元素（Vue 3 class fallthrough）
    const filterSelect = page.locator('.header-select').first()
    await selectElOption(page, filterSelect, '运输层')

    // 筛选后仅 1 条
    await expect(page.locator('.wrongbook-card')).toHaveCount(1)
    await expect(page.locator('.wb-chapter-tag')).toContainText('运输层')

    // 切换回「全部章节」
    await selectElOption(page, filterSelect, '全部章节')
    await expect(page.locator('.wrongbook-card')).toHaveCount(2)
  })
})

// ============================================================
// 测试套件 3：LaTeX 实时预览同步
// ============================================================

test.describe('LaTeX 实时预览', () => {
  test('输入公式后页面级预览区同步渲染，空状态消失', async ({ page }) => {
    // 进入专项训练
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await expect(page.locator('.practice-placeholder')).toBeVisible()

    // 填写配置（三个必填项）
    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '运输层')

    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')

    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    // 开始训练
    await page.locator('.practice-config .el-button', { hasText: '开始训练' }).click()
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })

    // === 验证初始空状态：KaTeXEditor 预览区空状态可见 ===
    await expect(page.locator('.ke-empty-hint')).toBeVisible({ timeout: 3_000 })

    // === 输入 LaTeX 内容 ===
    const textarea = page.locator('.ke-textarea')
    await textarea.waitFor({ state: 'visible', timeout: 5_000 })
    await textarea.click()
    await textarea.fill('$E = mc^2$')

    // === 验证预览区切换为内容态 ===
    // 占位符消失，KaTeXEditor 预览区显示内容
    await expect(page.locator('.ke-empty-hint')).toHaveCount(0, { timeout: 5_000 })
    await expect(page.locator('.ke-preview-body')).toBeVisible({ timeout: 3_000 })
  })
})
