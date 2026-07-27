// ============================================================
// StudyAgents — Vue Router 配置
//
// 职责：
//   1. 定义全部页面路由映射（Login / Home / Admin / Training / WrongBook）
//   2. beforeEach 全局前置守卫：
//      - 未登录（useUserStore.token 为空）→ 重定向到 /login
//      - 非 admin 访问 /admin → 重定向到首页 /
//   3. 路由 meta 标记是否需要认证和管理员权限
//
// 认证依据：
//   - useUserStore.token（Bearer JWT）从 localStorage 同步初始化，
//     页面刷新后无需等待异步 init() 即可判断登录状态
//   - 角色信息同样在 login 时写入 localStorage，确保守卫同步可用
// ============================================================

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useUserStore } from '../stores/useUserStore'

// ============================================================
// 路由表
// ============================================================

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('../views/Admin.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
  },
  {
    path: '/training',
    name: 'Training',
    component: () => import('../views/Training.vue'),
    meta: { requiresAuth: true },
  },
  {
    path: '/wrong-book',
    name: 'WrongBook',
    component: () => import('../views/WrongBook.vue'),
    meta: { requiresAuth: true },
  },
]

// ============================================================
// Router 实例
// ============================================================

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ============================================================
// 全局前置守卫
// ============================================================

router.beforeEach((to, _from) => {
  // Pinia 在 router 之前注册（main.ts），此处可安全使用
  const userStore = useUserStore()

  // ---- 公开路由：/login ----
  if (to.path === '/login') {
    // 已登录用户访问登录页 → 重定向到首页
    if (userStore.isLoggedIn) {
      return '/'
    }
    return true
  }

  // ---- 受保护路由：未登录 → /login ----
  if (!userStore.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // ---- Admin 路由：非 admin 角色 → 首页 ----
  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    return '/'
  }

  // ---- 已登录 + 权限通过 → 放行 ----
  return true
})

export default router
