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
      // 启动后端服务（postgres + 迁移 + 测试账号 + api + worker）
      //
      // CI 首次运行时数据库为空，需依次：
      //   a) 启动 postgres 并等待就绪
      //   b) 运行 alembic upgrade head（数据库迁移）
      //   c) 运行 init_users.py（创建 member_a 等预置测试账号）
      //   d) 启动 api + worker
      //
      // 本地开发环境可复用已有服务（reuseExistingServer）。
      command: process.env.CI
        ? 'bash apps/frontend/e2e/setup-backend.sh && docker compose up -d api worker'
        : 'docker compose up -d postgres api worker',
      url: 'http://localhost:8080/api/health/live',
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
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
