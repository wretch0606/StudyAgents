<script setup lang="ts">
// ============================================================
// StudyAgents — 根组件
//
// 提供顶部导航栏 + <router-view> 出口。
// 路由逻辑由 src/router/index.ts 的 beforeEach 守卫控制。
//
// 认证状态通过 useUserStore 管理（Bearer Token + localStorage），
// 页面刷新后同步恢复，无需等待异步 init()。
// ============================================================

import { onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from './stores/useUserStore'
import { setLoginRedirectHandler } from './utils/request'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// ---- 应用启动：会话恢复 + 注册 401 重定向 ----

onMounted(() => {
  // 从 localStorage 恢复 Token → 调用后端验证 → 写入 user info
  userStore.init()

  // 注册 401 会话过期回调：清除状态并跳转登录页
  setLoginRedirectHandler(() => {
    userStore.logout()
    router.push('/login')
  })
})

// ---- 响应式状态 ----

/** 是否在登录页（登录页不显示导航栏） */
const isLoginPage = computed(() => route.path === '/login')

/** 当前用户角色（响应式，来自 Store） */
const userRole = computed(() => userStore.user?.role ?? null)

// ---- 退出登录 ----

function handleLogout() {
  userStore.logout()
  router.replace('/login')
}
</script>

<template>
  <!-- 登录页：不显示导航，仅渲染登录表单 -->
  <template v-if="isLoginPage">
    <router-view />
  </template>

  <!-- 已登录：显示导航栏 + 页面内容 -->
  <template v-else>
    <nav class="app-nav">
      <div class="nav-left">
        <span class="nav-brand">🧠 StudyAgents</span>
      </div>

      <div class="nav-center">
        <router-link to="/" class="nav-link" active-class="nav-link--active" exact>
          问答
        </router-link>
        <router-link to="/?mode=practice" class="nav-link" active-class="nav-link--active">
          训练
        </router-link>
        <router-link to="/?mode=wrongbook" class="nav-link" active-class="nav-link--active">
          错题本
        </router-link>
        <router-link
          v-if="userRole === 'admin'"
          to="/admin"
          class="nav-link"
          active-class="nav-link--active"
        >
          资料管理
        </router-link>
      </div>

      <div class="nav-right">
        <span class="nav-role" :class="{ 'is-admin': userRole === 'admin' }">
          {{ userRole === 'admin' ? '管理员' : '普通用户' }}
        </span>
        <button class="btn-logout" @click="handleLogout">退出</button>
      </div>
    </nav>

    <main class="app-main">
      <router-view />
    </main>
  </template>
</template>

<style>
/* ============================================================
   全局重置 — 覆盖默认 #app 容器约束
   ============================================================ */

html, body, #app {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

#app {
  display: flex;
  flex-direction: column;
  max-width: none;
  border: none;
  text-align: left;
}
</style>

<style scoped>
/* ============================================================
   顶部导航栏
   ============================================================ */

.app-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 20px;
  background: #16213e;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  flex-shrink: 0;
  z-index: 100;
}

.nav-left {
  display: flex;
  align-items: center;
}

.nav-brand {
  font-size: 16px;
  font-weight: 700;
  color: #a78bfa;
  letter-spacing: 0.5px;
}

.nav-center {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-link {
  padding: 6px 16px;
  border-radius: 6px;
  font-size: 13px;
  color: #888;
  text-decoration: none;
  transition: color 0.15s, background 0.15s;
}

.nav-link:hover {
  color: #e0e0e0;
  background: rgba(255, 255, 255, 0.04);
}

.nav-link--active {
  color: #a78bfa;
  background: rgba(167, 139, 250, 0.1);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.nav-role {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  color: #888;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.nav-role.is-admin {
  color: #f0a060;
  background: rgba(240, 160, 96, 0.08);
  border-color: rgba(240, 160, 96, 0.2);
}

.btn-logout {
  padding: 5px 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  font-size: 12px;
  color: #999;
  background: transparent;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.btn-logout:hover {
  color: #ff6b6b;
  background: rgba(255, 107, 107, 0.08);
  border-color: rgba(255, 107, 107, 0.25);
}

/* ============================================================
   主内容区
   ============================================================ */

.app-main {
  flex: 1;
  overflow: hidden;
  background: #1a1a2e;
}

/* ============================================================
   移动端响应式适配（≤768px，覆盖 390px 场景）
   ============================================================ */
@media (max-width: 768px) {
  .app-nav {
    padding: 0 8px;
    height: 42px;
    gap: 4px;
  }

  .nav-brand {
    font-size: 13px;
    letter-spacing: 0;
  }

  .nav-center {
    gap: 1px;
  }

  .nav-link {
    padding: 4px 6px;
    font-size: 11px;
    border-radius: 4px;
  }

  .nav-right {
    gap: 6px;
  }

  .nav-role {
    display: none;
  }

  .btn-logout {
    padding: 3px 8px;
    font-size: 11px;
    border-radius: 4px;
    white-space: nowrap;
  }
}
</style>
