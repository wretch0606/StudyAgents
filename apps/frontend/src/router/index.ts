// ============================================================
// StudyAgents — Vue Router 配置
//
// 职责：
//   1. 定义全部页面路由映射（Login / Home / Admin / Training / WrongBook）
//   2. beforeEach 全局前置守卫：
//      - 未登录（localStorage['userRole'] 为空）→ 重定向到 /login
//      - 非 admin 访问 /admin → 重定向到首页 /
//   3. 路由 meta 标记是否需要认证和管理员权限
//
// 注意：当前使用 localStorage['userRole'] 作为临时权限判断，
//       后续将替换为 Pinia useAuthStore。
// ============================================================

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

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
  const role = localStorage.getItem('userRole')

  // ---- 公开路由：/login ----
  if (to.path === '/login') {
    // 已登录用户访问登录页 → 重定向到首页
    if (role) {
      return '/'
    }
    return true
  }

  // ---- 受保护路由：未登录 → /login ----
  if (!role) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // ---- Admin 路由：非 admin 角色 → 首页 ----
  if (to.meta.requiresAdmin && role !== 'admin') {
    return '/'
  }

  // ---- 已登录 + 权限通过 → 放行 ----
  return true
})

export default router
