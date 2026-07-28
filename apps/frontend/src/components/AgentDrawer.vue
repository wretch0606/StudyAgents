<script setup lang="ts">
// ============================================================
// StudyAgents — Agent 协同工作流可视化抽屉
//
// 数据来源：直接通过 storeToRefs(useChatStore()) 读取，
// 避免 props 多层传递导致响应式丢失。
// ============================================================

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '../stores/useChatStore'

// ============================================================
// 直接从 Store 读取状态 —— 保证响应式
// ============================================================

const chatStore = useChatStore()
const { currentAgentTraces, agentSteps, sourceRefs, isStreaming } = storeToRefs(chatStore)

// ============================================================
// Props & Emits（仅保留 v-model 控制面板显隐，不再传递数据）
// ============================================================

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

// ============================================================
// 移动端检测
// ============================================================

const isMobile = ref(false)
function checkMobile(): void {
  isMobile.value = window.innerWidth <= 768
}
onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})
onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})

// ============================================================
// 内部状态
// ============================================================

const drawerTab = ref<'agents' | 'sources'>('agents')

/** 双向绑定：PC 端折叠 / 移动端 Drawer 开关 */
const visible = computed({
  get: () => props.modelValue,
  set: (val: boolean) => emit('update:modelValue', val),
})

/** 是否存在实时 Agent 轨迹（流式回复期间） */
const hasLiveTraces = computed(
  () => isStreaming.value && currentAgentTraces.value.length > 0,
)

/** Agent 视图是否有任何可展示的数据 */
const hasAnyAgentData = computed(
  () => hasLiveTraces.value || agentSteps.value.length > 0,
)

/** 溯源引用是否为空 */
const hasSourceRefs = computed(() => sourceRefs.value.length > 0)

/**
 * 统一数据源：根据 isStreaming 自动切换
 * - 流式回复期间 → currentAgentTraces（实时轨迹）
 * - 非流式期间   → agentSteps（历史记录）
 */
const displayAgents = computed(() =>
  isStreaming.value ? currentAgentTraces.value : agentSteps.value,
)

// ============================================================
// 帮助函数
// ============================================================

function traceStatusLabel(s: string): string {
  switch (s) {
    case 'succeeded': return '已完成'
    case 'running': return '执行中'
    case 'failed': return '失败'
    default: return '待命'
  }
}

function traceDuration(ms?: number): string {
  if (ms === undefined || ms === 0) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function stepStatusLabel(s: string): string {
  switch (s) {
    case 'succeeded': return '已完成'
    case 'running': return '运行中'
    case 'failed': return '失败'
    default: return '待命'
  }
}
</script>

<template>
  <!-- ====================================================== -->
  <!-- PC 端：右侧内联侧边栏                                    -->
  <!-- ====================================================== -->
  <aside
    v-if="!isMobile"
    :class="['sidebar-right', { collapsed: !visible }]"
  >
    <div class="drawer-inner">
      <!-- 头部 -->
      <header class="drawer-header">
        <h3 class="drawer-title">Agent 协作面板</h3>
        <div class="drawer-tabs">
          <button
            :class="['drawer-tab', { active: drawerTab === 'agents' }]"
            @click="drawerTab = 'agents'"
          >
            Agent 流程
          </button>
          <button
            :class="['drawer-tab', { active: drawerTab === 'sources' }]"
            @click="drawerTab = 'sources'"
          >
            溯源引用
          </button>
        </div>
      </header>

      <el-scrollbar class="drawer-scroll">
        <!-- ================================================ -->
        <!-- Agent 流程标签页                                   -->
        <!-- ================================================ -->
        <template v-if="drawerTab === 'agents'">
          <div class="drawer-section">
            <p class="section-desc">
              <template v-if="hasLiveTraces">
                以下展示当前消息的四类 Agent 协同工作实时轨迹。各阶段通过 setTimeout 模拟接力执行。
              </template>
              <template v-else-if="hasAnyAgentData">
                以下展示四类 Agent 在当前问答中的协同工作状态。所有 Agent 思考步骤通过 SSE 事件实时推送给前端。
              </template>
              <template v-else>
                暂无 Agent 执行数据。发送一条消息后，右侧面板将展示多 Agent 协同的实时工作流轨迹。
              </template>
            </p>

            <!-- ============================================ -->
            <!-- 空状态：无任何 Agent 数据                       -->
            <!-- ============================================ -->
            <div v-if="!hasLiveTraces && !hasAnyAgentData" class="agent-empty-state">
              <svg class="empty-state-icon" viewBox="0 0 48 48" fill="none">
                <circle cx="24" cy="24" r="20" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" />
                <path d="M16 20h16M16 28h10" stroke="var(--border)" stroke-width="2" stroke-linecap="round" />
                <circle cx="36" cy="36" r="6" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
                <path d="M36 33v6m-3-3h6" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <p class="empty-state-text">发送消息后<br>查看 Agent 工作流</p>
            </div>

            <!-- ============================================ -->
            <!-- 实时 Agent 执行轨迹（流式回复期间）              -->
            <!-- ============================================ -->
            <template v-if="hasLiveTraces">
              <div class="timeline">
                <div
                  v-for="(trace, idx) in displayAgents"
                  :key="trace.agentRole"
                  class="timeline-item"
                >
                  <!-- 连接线 -->
                  <div v-if="idx > 0" class="timeline-connector">
                    <div
                      :class="['tl-line-segment', {
                        done: displayAgents[idx - 1].status === 'succeeded',
                        flowing: displayAgents[idx - 1].status === 'succeeded' && trace.status === 'running',
                      }]"
                    ></div>
                  </div>

                  <!-- 节点 -->
                  <div :class="['tl-node', trace.status]">
                    <!-- 时间轴圆点 -->
                    <div :class="['tl-dot', trace.status]">
                      <span v-if="trace.status === 'running'" class="tl-dot-ring"></span>
                      <svg v-else-if="trace.status === 'succeeded'" class="tl-dot-check" viewBox="0 0 12 12" fill="currentColor">
                        <path fill-rule="evenodd" d="M10.28 2.22a.75.75 0 010 1.06l-5.5 5.5a.75.75 0 01-1.06 0l-2-2a.75.75 0 011.06-1.06L4.2 7.14l4.97-4.97a.75.75 0 011.06 0z" clip-rule="evenodd" />
                      </svg>
                      <svg v-else-if="trace.status === 'failed'" class="tl-dot-x" viewBox="0 0 12 12" fill="currentColor">
                        <path fill-rule="evenodd" d="M3.22 3.22a.75.75 0 011.06 0L6 4.94l1.72-1.72a.75.75 0 111.06 1.06L7.06 6l1.72 1.72a.75.75 0 11-1.06 1.06L6 7.06l-1.72 1.72a.75.75 0 11-1.06-1.06L4.94 6 3.22 4.28a.75.75 0 010-1.06z" clip-rule="evenodd" />
                      </svg>
                    </div>

                    <!-- 卡片内容 -->
                    <div :class="['tl-card', trace.status]">
                      <div class="tl-card-head">
                        <span class="tl-role">{{ trace.agentLabel }}</span>
                        <span :class="['tl-badge', trace.status]">
                          {{ traceStatusLabel(trace.status) }}
                        </span>
                        <span v-if="trace.durationMs" class="tl-duration">{{ traceDuration(trace.durationMs) }}</span>
                      </div>
                      <p class="tl-action">{{ trace.summary }}</p>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <!-- ============================================ -->
            <!-- 历史 Agent 步骤（非流式期间，从 API 加载）       -->
            <!-- ============================================ -->
            <template v-else-if="hasAnyAgentData">
              <div v-for="(step, idx) in displayAgents" :key="step.agentRole" class="agent-step-card">
                <!-- 连接线 -->
                <div v-if="idx > 0" class="step-connector">
                  <svg viewBox="0 0 2 20" class="connector-line">
                    <line x1="1" y1="0" x2="1" y2="20" stroke="var(--border)" stroke-width="2" stroke-dasharray="2 3" />
                  </svg>
                </div>

                <div :class="['step-card-inner', step.status]">
                  <!-- 状态指示与角色 -->
                  <div class="step-head">
                    <span :class="['step-dot', step.status]"></span>
                    <span class="step-role">{{ step.agentLabel }}</span>
                    <span :class="['step-badge', step.status]">
                      {{ stepStatusLabel(step.status) }}
                    </span>
                    <span v-if="step.durationMs" class="step-duration">{{ step.durationMs }}ms</span>
                  </div>

                  <!-- 摘要 -->
                  <p class="step-summary">{{ step.summary }}</p>

                  <!-- 详情（展开） -->
                  <details v-if="step.detail" class="step-detail">
                    <summary>查看详细步骤</summary>
                    <p class="step-detail-text">{{ step.detail }}</p>
                  </details>
                </div>
              </div>
            </template>

            <!-- 工作流说明 -->
            <div class="workflow-legend">
              <p class="legend-title">Agent 协同流程</p>
              <div class="legend-flow">
                <span class="flow-node">用户提问</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Coordinator</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Knowledge</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Evaluator</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node">回答 / 拒答</span>
              </div>
              <div class="legend-flow practice-flow">
                <span class="flow-node">开始训练</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Questioner</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node">提交答案</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Evaluator</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node">评分讲解</span>
              </div>
            </div>
          </div>
        </template>

        <!-- ================================================ -->
        <!-- 溯源引用标签页                                     -->
        <!-- ================================================ -->
        <template v-else>
          <div class="drawer-section">
            <p class="section-desc">
              所有回答均引用自已导入的课程资料。每条引用精确到文档名、页码和证据片段，确保可复核、可溯源。
            </p>

            <!-- 空状态 -->
            <div v-if="!hasSourceRefs" class="agent-empty-state">
              <svg class="empty-state-icon" viewBox="0 0 48 48" fill="none">
                <rect x="8" y="6" width="32" height="36" rx="3" stroke="var(--border)" stroke-width="2" />
                <path d="M16 18h16M16 24h12M16 30h8" stroke="var(--border)" stroke-width="2" stroke-linecap="round" />
              </svg>
              <p class="empty-state-text">暂无溯源引用<br>等待对话开始</p>
            </div>

            <div v-for="ref in sourceRefs" :key="ref.refId" class="source-card">
              <div class="source-head">
                <span class="source-ref-badge">[{{ ref.refId }}]</span>
                <span class="source-doc">{{ ref.documentName }}</span>
                <span class="source-page">第 {{ ref.pageNumber }} 页</span>
              </div>
              <blockquote class="source-excerpt">
                "{{ ref.excerpt }}"
              </blockquote>
              <div class="source-footer">
                <svg class="icon-svg source-link-icon" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M12.586 4.586a2 2 0 112.828 2.828l-3 3a2 2 0 01-2.828 0 1 1 0 00-1.414 1.414 4 4 0 005.656 0l3-3a4 4 0 00-5.656-5.656l-1.5 1.5a1 1 0 101.414 1.414l1.5-1.5zm-5.172 6.828a2 2 0 012.828 0 1 1 0 101.414-1.414 4 4 0 00-5.656 0l-3 3a4 4 0 105.656 5.656l1.5-1.5a1 1 0 10-1.414-1.414l-1.5 1.5a2 2 0 11-2.828-2.828l3-3z" clip-rule="evenodd" />
                </svg>
                <span class="source-chunk-id">chunk: {{ ref.refId === 'S1' ? 'a1b2c3' : ref.refId === 'S2' ? 'd4e5f6' : 'g7h8i9' }}</span>
              </div>
            </div>
          </div>
        </template>
      </el-scrollbar>
    </div>
  </aside>

  <!-- ====================================================== -->
  <!-- 移动端：ElDrawer 浮层                                    -->
  <!-- ====================================================== -->
  <el-drawer
    v-else
    v-model="visible"
    direction="rtl"
    size="88%"
    :with-header="false"
    :close-on-press-escape="true"
    custom-class="agent-mobile-drawer"
  >
    <div class="drawer-inner mobile">
      <!-- 头部 -->
      <header class="drawer-header">
        <div class="drawer-header-row">
          <h3 class="drawer-title">💡 Agent 协作面板</h3>
          <button class="drawer-close-btn" @click="visible = false" title="关闭">
            <svg viewBox="0 0 20 20" fill="currentColor" class="close-icon">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
        <div class="drawer-tabs">
          <button
            :class="['drawer-tab', { active: drawerTab === 'agents' }]"
            @click="drawerTab = 'agents'"
          >
            Agent 流程
          </button>
          <button
            :class="['drawer-tab', { active: drawerTab === 'sources' }]"
            @click="drawerTab = 'sources'"
          >
            溯源引用
          </button>
        </div>
      </header>

      <el-scrollbar class="drawer-scroll">
        <!-- ================================================ -->
        <!-- Agent 流程（移动端）                                -->
        <!-- ================================================ -->
        <template v-if="drawerTab === 'agents'">
          <div class="drawer-section">
            <p class="section-desc">
              <template v-if="hasLiveTraces">
                以下展示当前消息的四类 Agent 协同工作实时轨迹。
              </template>
              <template v-else-if="hasAnyAgentData">
                以下展示四类 Agent 在当前问答中的协同工作状态。
              </template>
              <template v-else>
                暂无 Agent 执行数据。发送消息后查看实时工作流。
              </template>
            </p>

            <!-- 空状态 -->
            <div v-if="!hasLiveTraces && !hasAnyAgentData" class="agent-empty-state">
              <svg class="empty-state-icon" viewBox="0 0 48 48" fill="none">
                <circle cx="24" cy="24" r="20" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" />
                <path d="M16 20h16M16 28h10" stroke="var(--border)" stroke-width="2" stroke-linecap="round" />
                <circle cx="36" cy="36" r="6" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
                <path d="M36 33v6m-3-3h6" stroke="var(--accent)" stroke-width="1.5" stroke-linecap="round" />
              </svg>
              <p class="empty-state-text">发送消息后<br>查看 Agent 工作流</p>
            </div>

            <!-- 实时轨迹 -->
            <template v-if="hasLiveTraces">
              <div class="timeline">
                <div
                  v-for="(trace, idx) in displayAgents"
                  :key="trace.agentRole"
                  class="timeline-item"
                >
                  <div v-if="idx > 0" class="timeline-connector">
                    <div
                      :class="['tl-line-segment', {
                        done: displayAgents[idx - 1].status === 'succeeded',
                        flowing: displayAgents[idx - 1].status === 'succeeded' && trace.status === 'running',
                      }]"
                    ></div>
                  </div>
                  <div :class="['tl-node', trace.status]">
                    <div :class="['tl-dot', trace.status]">
                      <span v-if="trace.status === 'running'" class="tl-dot-ring"></span>
                      <svg v-else-if="trace.status === 'succeeded'" class="tl-dot-check" viewBox="0 0 12 12" fill="currentColor">
                        <path fill-rule="evenodd" d="M10.28 2.22a.75.75 0 010 1.06l-5.5 5.5a.75.75 0 01-1.06 0l-2-2a.75.75 0 011.06-1.06L4.2 7.14l4.97-4.97a.75.75 0 011.06 0z" clip-rule="evenodd" />
                      </svg>
                      <svg v-else-if="trace.status === 'failed'" class="tl-dot-x" viewBox="0 0 12 12" fill="currentColor">
                        <path fill-rule="evenodd" d="M3.22 3.22a.75.75 0 011.06 0L6 4.94l1.72-1.72a.75.75 0 111.06 1.06L7.06 6l1.72 1.72a.75.75 0 11-1.06 1.06L6 7.06l-1.72 1.72a.75.75 0 11-1.06-1.06L4.94 6 3.22 4.28a.75.75 0 010-1.06z" clip-rule="evenodd" />
                      </svg>
                    </div>
                    <div :class="['tl-card', trace.status]">
                      <div class="tl-card-head">
                        <span class="tl-role">{{ trace.agentLabel }}</span>
                        <span :class="['tl-badge', trace.status]">{{ traceStatusLabel(trace.status) }}</span>
                        <span v-if="trace.durationMs" class="tl-duration">{{ traceDuration(trace.durationMs) }}</span>
                      </div>
                      <p class="tl-action">{{ trace.summary }}</p>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <!-- 历史步骤 -->
            <template v-else-if="hasAnyAgentData">
              <div v-for="(step, idx) in displayAgents" :key="step.agentRole" class="agent-step-card">
                <div v-if="idx > 0" class="step-connector">
                  <svg viewBox="0 0 2 20" class="connector-line">
                    <line x1="1" y1="0" x2="1" y2="20" stroke="var(--border)" stroke-width="2" stroke-dasharray="2 3" />
                  </svg>
                </div>
                <div :class="['step-card-inner', step.status]">
                  <div class="step-head">
                    <span :class="['step-dot', step.status]"></span>
                    <span class="step-role">{{ step.agentLabel }}</span>
                    <span :class="['step-badge', step.status]">{{ stepStatusLabel(step.status) }}</span>
                    <span v-if="step.durationMs" class="step-duration">{{ step.durationMs }}ms</span>
                  </div>
                  <p class="step-summary">{{ step.summary }}</p>
                  <details v-if="step.detail" class="step-detail">
                    <summary>查看详细步骤</summary>
                    <p class="step-detail-text">{{ step.detail }}</p>
                  </details>
                </div>
              </div>
            </template>

            <div class="workflow-legend">
              <p class="legend-title">Agent 协同流程</p>
              <div class="legend-flow">
                <span class="flow-node">用户提问</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Coordinator</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Knowledge</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node accent">Evaluator</span>
                <span class="flow-arrow">→</span>
                <span class="flow-node">回答 / 拒答</span>
              </div>
            </div>
          </div>
        </template>

        <!-- 溯源引用（移动端） -->
        <template v-else>
          <div class="drawer-section">
            <p class="section-desc">所有回答均引用自已导入的课程资料。</p>
            <div v-if="!hasSourceRefs" class="agent-empty-state">
              <p class="empty-state-text">暂无溯源引用</p>
            </div>
            <div v-for="ref in sourceRefs" :key="ref.refId" class="source-card">
              <div class="source-head">
                <span class="source-ref-badge">[{{ ref.refId }}]</span>
                <span class="source-doc">{{ ref.documentName }}</span>
                <span class="source-page">第 {{ ref.pageNumber }} 页</span>
              </div>
              <blockquote class="source-excerpt">"{{ ref.excerpt }}"</blockquote>
            </div>
          </div>
        </template>
      </el-scrollbar>
    </div>
  </el-drawer>
</template>

<style scoped>
/* ============================================================
   PC 侧边栏
   ============================================================ */
.sidebar-right {
  --drawer-w: 380px;

  width: var(--drawer-w);
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  background: var(--code-bg);
  transition: width 0.3s ease, border-width 0.3s ease;
  overflow: hidden;
}

.sidebar-right.collapsed {
  width: 0;
  border-left-width: 0;
}

.drawer-inner {
  width: var(--drawer-w);
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* 移动端内边距微调 */
.drawer-inner.mobile {
  width: 100%;
}

.drawer-header {
  padding: 16px 18px 0;
  flex-shrink: 0;
}

.drawer-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2px;
}

.drawer-title {
  font-family: var(--heading);
  font-size: 15px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 10px;
}

.drawer-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
}

.drawer-close-btn:hover {
  background: var(--accent-bg);
  color: var(--accent);
  border-color: var(--accent-border);
}

.close-icon {
  width: 16px;
  height: 16px;
}

.drawer-tabs {
  display: flex;
  gap: 0;
  border-bottom: 2px solid var(--border);
}

.drawer-tab {
  flex: 1;
  padding: 8px 0;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: all 0.15s;
}

.drawer-tab:hover {
  color: var(--accent);
}

.drawer-tab.active {
  color: var(--accent);
  font-weight: 700;
  border-bottom-color: var(--accent);
}

.drawer-scroll {
  flex: 1;
  overflow: hidden;
}

.drawer-section {
  padding: 14px 18px 20px;
}

.section-desc {
  font-size: 12px;
  color: var(--text);
  opacity: 0.65;
  margin: 0 0 16px;
  line-height: 1.5;
}

/* ============================================================
   空状态
   ============================================================ */
.agent-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px 32px;
  text-align: center;
}

.empty-state-icon {
  width: 56px;
  height: 56px;
  margin-bottom: 16px;
  opacity: 0.5;
}

.empty-state-text {
  font-size: 13px;
  color: var(--text);
  opacity: 0.55;
  margin: 0;
  line-height: 1.6;
}

/* ============================================================
   时间轴（Timeline）— 实时 Agent 轨迹
   ============================================================ */
.timeline {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.timeline-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

/* ---- 连接线 ---- */
.timeline-connector {
  width: 28px;
  height: 24px;
  display: flex;
  justify-content: center;
  margin-left: 7px;
}

.tl-line-segment {
  width: 2px;
  height: 100%;
  background: var(--border);
  border-radius: 1px;
  transition: background 0.4s ease;
}

.tl-line-segment.done {
  background: #34d399;
}

.tl-line-segment.flowing {
  background: linear-gradient(to bottom, #34d399, var(--accent));
  animation: line-pulse 1.2s infinite;
}

@keyframes line-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ---- 节点行 ---- */
.tl-node {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  width: 100%;
}

/* ---- 时间轴圆点 ---- */
.tl-dot {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

.tl-dot.idle {
  background: transparent;
  border: 2px solid var(--border);
}

.tl-dot.running {
  background: transparent;
  border: none;
}

.tl-dot.succeeded {
  background: #34d399;
  border: none;
}

.tl-dot.failed {
  background: #f87171;
  border: none;
}

/* ---- running: 旋转环 ---- */
.tl-dot-ring {
  display: block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--accent-border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: tl-spin 0.8s linear infinite;
}

@keyframes tl-spin {
  to { transform: rotate(360deg); }
}

/* ---- 对勾 / 叉号 ---- */
.tl-dot-check,
.tl-dot-x {
  width: 10px;
  height: 10px;
  color: #fff;
}

/* ---- 时间轴卡片 ---- */
.tl-card {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg);
  transition: all 0.3s ease;
  margin-bottom: 4px;
}

.tl-card.running {
  border-color: var(--accent-border);
  background: var(--accent-bg);
  box-shadow: 0 0 8px rgba(99, 102, 241, 0.08);
}

.tl-card.succeeded {
  border-left: 3px solid #34d399;
}

.tl-card.failed {
  border-left: 3px solid #f87171;
}

.tl-card.idle {
  border-left: 3px solid var(--border);
  opacity: 0.6;
}

.tl-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.tl-role {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-h);
  flex: 1;
}

.tl-badge {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 8px;
  font-weight: 600;
  flex-shrink: 0;
}

.tl-badge.succeeded { background: rgba(52, 211, 153, 0.12); color: #34d399; }
.tl-badge.running   { background: var(--accent-bg); color: var(--accent); }
.tl-badge.failed    { background: rgba(248, 113, 113, 0.1); color: #f87171; }
.tl-badge.idle      { background: var(--border); color: var(--text); }

.tl-duration {
  font-size: 10px;
  color: var(--text);
  opacity: 0.5;
  font-family: var(--mono);
}

.tl-action {
  font-size: 13px;
  color: var(--text);
  margin: 0;
  line-height: 1.55;
}

/* ============================================================
   历史 Agent 步骤卡片
   ============================================================ */
.agent-step-card {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.step-connector {
  width: 20px;
  height: 16px;
}

.connector-line {
  width: 2px;
  height: 20px;
}

.step-card-inner {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg);
  transition: border-color 0.2s;
}

.step-card-inner.succeeded {
  border-left: 3px solid #34d399;
}

.step-card-inner.running {
  border-left: 3px solid var(--accent);
}

.step-card-inner.failed {
  border-left: 3px solid #f87171;
}

.step-card-inner.idle {
  border-left: 3px solid var(--border);
  opacity: 0.65;
}

.step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.step-dot.succeeded { background: #34d399; }
.step-dot.running { background: var(--accent); animation: pulse 1.2s infinite; }
.step-dot.failed { background: #f87171; }
.step-dot.idle { background: var(--border); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.step-role {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-h);
  flex: 1;
}

.step-badge {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 8px;
  font-weight: 600;
  flex-shrink: 0;
}

.step-badge.succeeded { background: rgba(52, 211, 153, 0.12); color: #34d399; }
.step-badge.running { background: var(--accent-bg); color: var(--accent); }
.step-badge.failed { background: rgba(248, 113, 113, 0.1); color: #f87171; }
.step-badge.idle { background: var(--border); color: var(--text); }

.step-duration {
  font-size: 10px;
  color: var(--text);
  opacity: 0.5;
  font-family: var(--mono);
}

.step-summary {
  font-size: 13px;
  color: var(--text);
  margin: 0;
  line-height: 1.5;
}

.step-detail {
  margin-top: 8px;
}

.step-detail summary {
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  font-weight: 600;
}

.step-detail-text {
  font-size: 12px;
  color: var(--text);
  opacity: 0.7;
  margin: 6px 0 0;
  padding: 8px 10px;
  background: var(--code-bg);
  border-radius: 6px;
  line-height: 1.5;
}

/* ============================================================
   工作流图例
   ============================================================ */
.workflow-legend {
  margin-top: 18px;
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg);
}

.legend-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-h);
  margin: 0 0 10px;
}

.legend-flow {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.legend-flow.practice-flow {
  margin-bottom: 0;
  opacity: 0.55;
}

.flow-node {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 5px;
  background: var(--code-bg);
  color: var(--text);
  font-weight: 500;
  white-space: nowrap;
}

.flow-node.accent {
  background: var(--accent-bg);
  color: var(--accent);
  font-weight: 700;
}

.flow-arrow {
  font-size: 11px;
  color: var(--text);
  opacity: 0.4;
  font-weight: 700;
}

/* ============================================================
   溯源引用卡片
   ============================================================ */
.source-card {
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg);
  margin-bottom: 12px;
}

.source-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.source-ref-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 22px;
  border-radius: 5px;
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}

.source-doc {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-h);
  flex: 1;
}

.source-page {
  font-size: 12px;
  color: var(--accent);
  font-weight: 600;
}

.source-excerpt {
  margin: 0 0 10px;
  padding: 10px 12px;
  background: var(--code-bg);
  border-left: 3px solid var(--accent-border);
  border-radius: 4px;
  font-size: 12.5px;
  color: var(--text);
  line-height: 1.6;
  font-style: italic;
}

.source-footer {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: var(--text);
  opacity: 0.5;
  font-family: var(--mono);
}

.source-link-icon {
  width: 14px;
  height: 14px;
}

.icon-svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

/* ============================================================
   ElDrawer 覆盖样式（移动端）
   ============================================================ */
:deep(.agent-mobile-drawer) {
  background: var(--bg) !important;
  color: var(--text);
}

:deep(.agent-mobile-drawer .el-drawer__body) {
  padding: 0;
  height: 100%;
  overflow: hidden;
}
</style>
