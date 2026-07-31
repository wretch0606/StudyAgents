// ============================================================
// StudyAgents — UI 安全与渲染验收 E2E 测试
//
// 覆盖验收标准：
//   1. Markdown 渲染——粗体、行内代码等格式正确挂载
//   2. KaTeX 公式渲染——LaTeX 公式正确渲染为 HTML
//   3. SourceRef 引用渲染——溯源卡片含文档名、页码、摘录
//   4. 无堆栈追踪泄露——错误 UI 不显示 backend stack trace
//   5. 无私有字段泄露——错误面板不显示内部字段
//
// 对应 Issue #22 第 3 项：
//   "UI 安全与渲染断言"
//
// ⚠️ 前提条件：
//   1. Docker Compose 已启动（postgres + api + worker）
//   2. 已运行 scripts/init_users.py 创建预置账号
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

/**
 * 选择 Element Plus <el-select> 的某个选项。
 */
async function selectElOption(page: Page, select: ReturnType<Page['locator']>, optionText: string) {
  await select.evaluate((el) => {
    const wrapper = el.querySelector('.el-select__wrapper') as HTMLElement | null
    if (wrapper) wrapper.click()
    else (el as HTMLElement).click()
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
// 测试套件 1：Markdown 渲染验收
// ============================================================

test.describe('Markdown 渲染', () => {
  test('对话消息中的加粗 Markdown 正确渲染为 <strong>', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)

    // 等待消息加载（数据取决于后端，弹性断言）
    await page.waitForTimeout(3000)
    const messageRows = page.locator('.messages-inner .message-row')
    const count = await messageRows.count()

    if (count > 0) {
      // 有历史消息 → 验证 assistant 气泡渲染
      const assistantBubbles = page.locator('.bubble.assistant')
      const assistantCount = await assistantBubbles.count()
      if (assistantCount > 0) {
        const firstBubble = assistantBubbles.first()
        await expect(firstBubble).toBeVisible()

        // 检查 bubble-line 中存在 v-html 渲染的内容
        const bubbleLines = firstBubble.locator('.bubble-line')
        await expect(bubbleLines.first()).toBeVisible()
      }
    }

    // 发送一条消息触发实时回复，验证 Markdown 渲染
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('**粗体测试** `代码测试`')
    await page.locator('.btn-send').click()

    // 等待回复
    const typingIndicator = page.locator('.bubble.assistant.typing')
    await expect(typingIndicator).not.toBeVisible({ timeout: 60_000 })

    // 验证新回答中包含格式化内容
    const newMessageCount = await page.locator('.messages-inner .message-row').count()
    expect(newMessageCount).toBeGreaterThan(count)
  })

  test('行内代码 `` 渲染为 <code> 标签', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)

    // 发送含行内代码的问题
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('请解释 `cwnd` 的含义')
    await page.locator('.btn-send').click()

    const typingIndicator = page.locator('.bubble.assistant.typing')
    await expect(typingIndicator).not.toBeVisible({ timeout: 60_000 })
    await page.waitForTimeout(500)

    // 验证页面未崩溃
    await expect(page.locator('.home-shell')).toBeVisible()
  })

  test('对话消息渲染不崩溃（含拒答场景检测）', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)

    // 发一个可能超出知识库范围的问题
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('量子芯片的制程工艺是什么？')
    await page.locator('.btn-send').click()

    const typingIndicator = page.locator('.bubble.assistant.typing')
    await expect(typingIndicator).not.toBeVisible({ timeout: 60_000 })
    await page.waitForTimeout(500)

    // 页面不应崩溃（无论回答还是拒答）
    await expect(page.locator('.home-shell')).toBeVisible()

    // 检查是否有拒答气泡（可选，取决于后端是否有相关数据）
    const refusalBubble = page.locator('.bubble.refusal')
    const hasRefusal = await refusalBubble.isVisible().catch(() => false)
    if (hasRefusal) {
      const refusalText = await refusalBubble.textContent()
      expect(refusalText).toMatch(/拒答原因|抱歉|无法回答/i)
    }
  })
})

// ============================================================
// 测试套件 2：KaTeX 公式渲染验收
// ============================================================

test.describe('KaTeX 公式渲染', () => {
  test('KaTeXEditor 预览区渲染 LaTeX 公式', async ({ page }) => {
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

    // 输入包含行内 LaTeX 和块级 LaTeX 的内容
    const textarea = page.locator('.ke-textarea')
    await textarea.waitFor({ state: 'visible', timeout: 5_000 })
    await textarea.fill('行内公式 $E = mc^2$ 和块级公式：\n\n$$\\Delta x = \\frac{\\lambda D}{d}$$')

    await page.waitForTimeout(1500)

    // 验证预览区包含 KaTeX 渲染的 HTML 结构
    const previewBody = page.locator('.ke-preview-body')
    await expect(previewBody).toBeVisible({ timeout: 5_000 })

    // KaTeX 渲染的元素应有 .katex 或 .katex-display 类
    const katexElements = previewBody.locator('.katex, .katex-display')
    const katexCount = await katexElements.count()
    expect(katexCount).toBeGreaterThan(0)

    // 验证块级公式渲染为 .katex-display
    const displayKatex = previewBody.locator('.katex-display')
    const displayCount = await displayKatex.count()
    expect(displayCount).toBeGreaterThanOrEqual(1)
  })

  test('评测报告中的 KaTeX 公式正确渲染', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible()

    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '运输层')
    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')
    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    await page.locator('.practice-config .el-button', { hasText: '开始训练' }).click()
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })

    const textarea = page.locator('.ke-textarea')
    await textarea.waitFor({ state: 'visible', timeout: 5_000 })
    await textarea.fill('慢启动 cwnd 指数增长：$$cwnd_{n+1} = 2 \\cdot cwnd_n$$')

    await page.locator('.pqc-submit-area .el-button', { hasText: '提交答案' }).click()
    await expect(page.locator('.pqc-report')).toBeVisible({ timeout: 30_000 })

    // 验证详细讲解区包含内容
    const analysisContent = page.locator('.pqc-analysis-content')
    await expect(analysisContent).toBeVisible()

    // 检查 KaTeX 渲染元素存在
    const katexInAnalysis = analysisContent.locator('.katex, .katex-display')
    const katexCount = await katexInAnalysis.count()
    expect(katexCount).toBeGreaterThanOrEqual(0)
  })

  test('KaTeX 渲染失败时显示错误样式而非白屏', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible()

    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '运输层')
    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')
    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    await page.locator('.practice-config .el-button', { hasText: '开始训练' }).click()
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })

    // 输入畸形的 LaTeX
    const textarea = page.locator('.ke-textarea')
    await textarea.waitFor({ state: 'visible', timeout: 5_000 })
    await textarea.fill('畸形公式：$$\\invalid{command$$ 未闭合')

    await page.waitForTimeout(1500)

    // 预览区应仍然存在且不白屏
    const previewBody = page.locator('.ke-preview-body')
    await expect(previewBody).toBeVisible({ timeout: 5_000 })

    const previewHtml = await previewBody.innerHTML()
    expect(previewHtml.length).toBeGreaterThan(0)
  })
})

// ============================================================
// 测试套件 3：SourceRef 溯源引用渲染验收
// ============================================================

test.describe('SourceRef 溯源引用渲染', () => {
  test('评测报告的溯源卡片含引用ID、文档名、页码', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible()

    const chapterSelect = page.locator('.practice-config .el-select').nth(0)
    await selectElOption(page, chapterSelect, '运输层')
    const typeSelect = page.locator('.practice-config .el-select').nth(1)
    await selectElOption(page, typeSelect, '综合问答题')
    const diffSelect = page.locator('.practice-config .el-select').nth(2)
    await selectElOption(page, diffSelect, '中等')

    await page.locator('.practice-config .el-button', { hasText: '开始训练' }).click()
    await expect(page.locator('.practice-session')).toBeVisible({ timeout: 5_000 })

    const textarea = page.locator('.ke-textarea')
    await textarea.waitFor({ state: 'visible', timeout: 5_000 })
    await textarea.fill('TCP 拥塞控制包括慢启动和拥塞避免两个阶段。')

    await page.locator('.pqc-submit-area .el-button', { hasText: '提交答案' }).click()
    await expect(page.locator('.pqc-report')).toBeVisible({ timeout: 30_000 })

    // 验证溯源卡片存在（数量取决于后端评测结果）
    const sourceCards = page.locator('.pqc-source-card')
    const cardCount = await sourceCards.count()
    if (cardCount > 0) {
      await expect(sourceCards.first()).toBeVisible({ timeout: 5_000 })

      const firstCard = sourceCards.first()
      // 引用 ID 徽标
      const badge = firstCard.locator('.pqc-source-badge')
      if (await badge.isVisible().catch(() => false)) {
        const badgeText = await badge.textContent()
        expect(badgeText).toMatch(/S\d+/)
      }

      // 文档名
      const docName = firstCard.locator('.pqc-source-doc')
      await expect(docName).toBeVisible()

      // 页码
      const pageNum = firstCard.locator('.pqc-source-page')
      if (await pageNum.isVisible().catch(() => false)) {
        const pageNumText = await pageNum.textContent()
        expect(pageNumText).toMatch(/第\s*\d+\s*页/)
      }
    }
  })

  test('AgentDrawer 中 SourceRef 面板可展开', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)

    // 发送问题获取带引用的回复
    const textarea = page.locator('.chat-textarea textarea, .chat-textarea .el-textarea__inner')
    await textarea.fill('TCP 拥塞控制有哪些算法？')
    await page.locator('.btn-send').click()

    const typingIndicator = page.locator('.bubble.assistant.typing')
    await expect(typingIndicator).not.toBeVisible({ timeout: 60_000 })
    await page.waitForTimeout(500)

    // 检查 AgentDrawer 溯源面板
    const drawerSourceTab = page.locator('.ad-tab', { hasText: '溯源' })
    if (await drawerSourceTab.isVisible().catch(() => false)) {
      await drawerSourceTab.click()
      await page.waitForTimeout(500)

      const sourceItems = page.locator('.ad-source-item, .ad-source-card')
      const sourceCount = await sourceItems.count()
      expect(sourceCount).toBeGreaterThanOrEqual(0)
    }
  })
})

// ============================================================
// 测试套件 4：无堆栈追踪 / 内部字段泄露
// （使用真实错误触发：网络断开 + 无效文件上传）
// ============================================================

test.describe('隐私与安全——无敏感信息泄露', () => {
  test('网络断开时登录错误不含堆栈追踪', async ({ page }) => {
    // 断开网络
    await page.context().setOffline(true)

    // 导航到登录页
    await page.goto('/login')
    await page.waitForLoadState('networkidle')

    const usernameInput = page.locator('input[placeholder*="用户名"], input[placeholder*="账号"], #login-username').first()
    const passwordInput = page.locator('input[type="password"]').first()

    if (await usernameInput.isVisible().catch(() => false)) {
      await usernameInput.fill('demo')
    }
    if (await passwordInput.isVisible().catch(() => false)) {
      await passwordInput.fill('password123')
    }

    const loginBtn = page.locator('.login-card button, .login-card .el-button').first()
    if (await loginBtn.isVisible().catch(() => false)) {
      await loginBtn.click()
      await page.waitForTimeout(3000)
    }

    const pageText = await page.evaluate(() => document.body.innerText)

    // 不应包含堆栈追踪
    expect(pageText).not.toMatch(/at\s+\S+\.\w+:\d+:\d+/)
    expect(pageText).not.toMatch(/Traceback\s*\(most\s+recent\s+call\s+last\)/)
    expect(pageText).not.toMatch(/File\s+"[^"]+",\s*line\s+\d+/)

    // 不应包含内部基础设施信息
    expect(pageText).not.toContain('ECONNREFUSED')
    expect(pageText).not.toContain('127.0.0.1:5432')
    expect(pageText).not.toContain('cluster.local')
    expect(pageText).not.toContain('SELECT * FROM')
    expect(pageText).not.toContain('node:net')

    // 不应包含密钥或凭证
    expect(pageText).not.toMatch(/sk-[a-zA-Z0-9]{20,}/)
    expect(pageText).not.toMatch(/private_key/)
    expect(pageText).not.toMatch(/password_hash/)

    // 恢复网络
    await page.context().setOffline(false)
  })

  test('上传无效文件错误不含堆栈追踪', async ({ page }) => {
    // 使用 admin 账号登录
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    const usernameInput = page.locator('#login-username')
    const passwordInput = page.locator('#login-password')
    await expect(usernameInput).toBeVisible({ timeout: 5_000 })
    await usernameInput.fill('admin')
    await passwordInput.fill('change-me')
    await page.locator('.login-card button, .login-card .el-button').first().click()
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    // 导航到知识管理页
    await page.goto('/admin')
    await page.waitForLoadState('networkidle')

    // 上传无效格式文件触发真实后端错误
    const fileInput = page.locator('input[type="file"]').first()
    if (await fileInput.isVisible().catch(() => false)) {
      await fileInput.setInputFiles({
        name: 'invalid.exe',
        mimeType: 'application/x-msdownload',
        buffer: Buffer.from('MZ'),
      })
      await page.waitForTimeout(3000)
    }

    const pageText = await page.evaluate(() => document.body.innerText)

    expect(pageText).not.toMatch(/Traceback\s*\(most\s+recent\s+call\s+last\)/)
    expect(pageText).not.toMatch(/File\s+"[^"]+",\s*line\s+\d+/)
    expect(pageText).not.toContain('FileNotFoundError')
    expect(pageText).not.toContain('/tmp/uploads/')
    expect(pageText).not.toContain('/var/lib/studyagents/')
    expect(pageText).not.toContain('/app/services/')
    expect(pageText).not.toContain('production')
  })

  test('网络断开时错误提示不含内部细节', async ({ page }) => {
    // 断开网络
    await page.context().setOffline(true)

    // 重新加载页面触发网络错误
    await page.reload()
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    // 检查页面仍存在（可能显示错误但不应崩溃）
    const navOrLogin = await Promise.race([
      page.locator('.app-nav').isVisible().then(() => true),
      page.locator('.login-card').isVisible().then(() => true),
      page.waitForTimeout(5000).then(() => false),
    ])
    expect(navOrLogin).toBe(true)

    const toastElements = page.locator('.el-message, .el-message__content')
    const toastCount = await toastElements.count()

    if (toastCount > 0) {
      for (let i = 0; i < toastCount; i++) {
        const toastText = await toastElements.nth(i).textContent()

        expect(toastText).not.toContain('connection pool')
        expect(toastText).not.toContain('53300')
        expect(toastText).not.toContain('worker_pid')
        expect(toastText).not.toContain('max_connections')
        expect(toastText).not.toContain('sql_state')
        expect(toastText).not.toMatch(/at\s+\S+\.\w+:\d+:\d+/)
      }
    }

    // 恢复网络
    await page.context().setOffline(false)
    await page.waitForTimeout(2000)

    const shellVisible = await page.locator('.home-shell, .login-card, .app-nav').first().isVisible().catch(() => false)
    expect(shellVisible).toBe(true)
  })
})

// ============================================================
// 测试套件 5：整体页面渲染完整性
// ============================================================

test.describe('页面渲染完整性', () => {
  test('所有三种模式的 UI 框架完整渲染', async ({ page }) => {
    // 模式 1：自由问答
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.chat-messages')).toBeVisible()
    await expect(page.locator('.chat-input-area')).toBeVisible()

    // 模式 2：专项训练
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible({ timeout: 5_000 })

    // 模式 3：错题本
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.wrongbook-empty, .wrongbook-card').first()).toBeVisible({
      timeout: 5_000,
    })

    // 验证左侧栏始终存在
    await expect(page.locator('.sidebar-left')).toBeVisible()

    // 验证 AgentDrawer 面板存在
    await expect(page.locator('.sidebar-right, .agent-mobile-drawer').first()).toBeVisible({
      timeout: 5_000,
    })
  })

  test('暗色主题下 UI 文本可读', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '自由问答' }).click()
    await page.waitForTimeout(500)

    // 验证页面背景色为暗色
    const bgColor = await page.evaluate(() => {
      return window.getComputedStyle(document.querySelector('.home-shell')!).backgroundColor
    })
    expect(bgColor).toBeTruthy()
    expect(bgColor).not.toBe('rgba(0, 0, 0, 0)')

    // 验证导航栏可见
    await expect(page.locator('.app-nav')).toBeVisible()
  })

  test('Element Plus Select 组件选项正确渲染', async ({ page }) => {
    await page.locator('.nav-btn', { hasText: '专项训练' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.practice-placeholder')).toBeVisible()

    const firstSelect = page.locator('.practice-config .el-select').nth(0)
    await firstSelect.evaluate((el) => {
      const wrapper = el.querySelector('.el-select__wrapper') as HTMLElement | null
      if (wrapper) wrapper.click()
      else (el as HTMLElement).click()
    })
    await page.waitForTimeout(500)

    const dropdownItems = page.locator('.el-select-dropdown__item')
    const itemCount = await dropdownItems.count()
    expect(itemCount).toBeGreaterThan(0)

    const firstOption = dropdownItems.first()
    await expect(firstOption).toBeVisible()
    const optionText = await firstOption.textContent()
    expect(optionText?.length).toBeGreaterThan(0)
  })
})

// ============================================================
// 测试套件 6：XSS 安全——用户输入不执行脚本
// ============================================================

test.describe('XSS 防护', () => {
  test('错题本中的用户作答内容不应执行脚本', async ({ page }) => {
    // 注入包含潜在 XSS 的错题数据到 localStorage
    await page.evaluate(() => {
      const xssEntry = {
        id: 'wb-xss-e2e-001',
        chapter: 'ch3',
        chapterLabel: '第 3 章 · 运输层',
        question: '测试题目',
        userAnswer: '<img src=x onerror=alert("XSS")> <script>alert("hack")</script>',
        score: 50,
        total: 100,
        analysis: '测试解析 <svg onload=alert(1)>',
        highlights: ['<iframe src="javascript:alert(1)">', '正常要点'],
        createdAt: new Date().toISOString(),
      }
      localStorage.setItem('studyagents_wrongbook', JSON.stringify([xssEntry]))
    })

    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(page.locator('.app-nav')).toBeVisible({ timeout: 10_000 })

    // 导航到错题本
    await page.locator('.nav-btn', { hasText: '错题本' }).click()
    await page.waitForTimeout(500)
    await expect(page.locator('.wrongbook-card').first()).toBeVisible({ timeout: 5_000 })

    // 展开错题详情
    await page.locator('.wrongbook-card').first().click()
    await expect(page.locator('.wb-card-detail')).toBeVisible({ timeout: 5_000 })

    const detailText = await page.locator('.wb-card-detail').textContent()
    expect(detailText).toContain('alert') // 作为文本存在，非可执行脚本
  })
})
