// ============================================================
// StudyAgents — Vue Router 配置
//
// 职责：
//   1. 定义 /login（公开）与 /（受保护）路由
//   2. beforeEach 全局前置守卫：未登录重定向到 /login
//   3. 路由 meta.auth 标记是否需要登录
// ============================================================

import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import type { RouteRecordRaw } from 'vue-router'

/** 路由表 */
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { auth: false },
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: { auth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ============================================================
// 全局前置守卫 — 未登录重定向
// ============================================================

router.beforeEach(async (to, _from, next) => {
  // 目标路由不需要认证 → 放行
  if (to.meta.auth === false) {
    return next()
  }

  // 需要认证的路由 → 查 Pinia store
  const auth = useAuthStore()

  // Store 尚未初始化 → 尝试恢复会话
  if (!auth.initialized) {
    try {
      await auth.init()
    } catch {
      // init 失败（无有效会话）→ 重定向到 login
      return next({ name: 'Login', query: { redirect: to.fullPath } })
    }
  }

  // 初始化后仍未登录 → 重定向
  if (!auth.isLoggedIn) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  // 已登录 → 放行
  next()
})

export default router
