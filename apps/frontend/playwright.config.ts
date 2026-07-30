// ============================================================
// StudyAgents — Playwright E2E 测试配置
//
// 覆盖专项训练核心闭环：
//   登录 → 配置训练参数 → 输入 LaTeX 作答 → 提交评测 →
//   查看评测报告 → 低分自动沉淀至错题本
// ============================================================

import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: 'html',

  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: [
    {
      // 启动后端服务（postgres + api + worker）
      // compose.yml 位于 monorepo 根目录
      command: 'docker compose up -d postgres api worker',
      url: 'http://localhost:8080/api/health/live',
      reuseExistingServer: !process.env.CI,
      timeout: 90_000,
      cwd: '../..',
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
})
