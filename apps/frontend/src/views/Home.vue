<script setup lang="ts">
// ============================================================
// StudyAgents — 知识问答主界面（业务重构版）
//
// 核心差异点：
//   1. 左侧：专项训练 / 错题本入口 + 知识掌握度可视化
//   2. 中间：PDF/OCR 导入入口 + 含拒答场景的 Mock 对话
//   3. 右侧：四类 Agent 协同工作流 + 文档溯源卡片（SourceRef）
// ============================================================
import { ref, nextTick } from 'vue'
import { tokenizeMarkdownLine } from '../utils/markdown'

// =========================================================
// 导航模式（对话 / 训练 / 错题本）
// =========================================================
type NavMode = 'chat' | 'practice' | 'wrongbook'

const navMode = ref<NavMode>('chat')

function switchMode(mode: NavMode) {
  navMode.value = mode
  if (mode === 'chat') {
    drawerOpen.value = true
  }
}

// =========================================================
// 历史会话（Mock）
// =========================================================
interface HistoryItem {
  id: string
  title: string
  updatedAt: string
}

const historyList = ref<HistoryItem[]>([
  { id: 'h1', title: 'TCP 三次握手与四次挥手详解', updatedAt: '10 分钟前' },
  { id: 'h2', title: 'IP 子网划分与路由聚合', updatedAt: '2 小时前' },
  { id: 'h3', title: 'HTTP/2 多路复用机制', updatedAt: '昨天' },
  { id: 'h4', title: '操作系统进程调度算法', updatedAt: '昨天' },
  { id: 'h5', title: '数据库索引 B+ 树结构', updatedAt: '3 天前' },
])

const activeHistoryId = ref('h1')

// =========================================================
// 知识掌握度（Mock — 来自 GET /api/learning-summary）
// =========================================================
interface MasteryRecord {
  kpId: string
  kpName: string
  mastery: number // 0–1
}

const masteryRecords = ref<MasteryRecord[]>([
  { kpId: 'kp1', kpName: 'TCP 协议', mastery: 0.82 },
  { kpId: 'kp2', kpName: 'IP 与路由', mastery: 0.65 },
  { kpId: 'kp3', kpName: 'HTTP/HTTPS', mastery: 0.91 },
  { kpId: 'kp4', kpName: '进程调度', mastery: 0.48 },
  { kpId: 'kp5', kpName: 'B+ 树索引', mastery: 0.34 },
])

const overallMastery = ref(0.64)
const pendingWrongCount = ref(7)

// =========================================================
// 四类 Agent 协同工作流（Mock 状态）
// =========================================================
interface AgentStep {
  agentRole: 'coordinator' | 'knowledge' | 'questioner' | 'evaluator'
  agentLabel: string
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  summary: string
  detail?: string
  durationMs?: number
}

const agentSteps = ref<AgentStep[]>([
  {
    agentRole: 'coordinator',
    agentLabel: 'Coordinator · 协调调度',
    status: 'succeeded',
    summary: '接收用户问题，分析意图为"计算机网络概念问答"，调度 Knowledge Agent 检索课程资料',
    detail: '意图分类 → 关键词提取 → 调度 Knowledge Agent → 等待检索结果',
    durationMs: 320,
  },
  {
    agentRole: 'knowledge',
    agentLabel: 'Knowledge · 检索溯源',
    status: 'succeeded',
    summary: '在《计算机网络.pdf》中检索到 3 条相关证据块，页码覆盖第 45–52 页',
    detail: '向量检索 (pgvector) → 全文检索交叉验证 → 返回 SourceRef 列表 → 置信度评估',
    durationMs: 1850,
  },
  {
    agentRole: 'questioner',
    agentLabel: 'Questioner · 出题组卷',
    status: 'idle',
    summary: '当前为问答模式，Questioner Agent 处于待命状态',
    detail: '进入"专项训练"模式后自动激活，基于课程资料生成针对练习题',
  },
  {
    agentRole: 'evaluator',
    agentLabel: 'Evaluator · 分步评分',
    status: 'idle',
    summary: '当前为问答模式，Evaluator Agent 处于待命状态',
    detail: '进入"专项训练"模式并提交答案后自动激活，按评分点分步评判并生成讲解',
  },
])

// =========================================================
// 文档溯源卡片（SourceRef — Mock 数据）
// =========================================================
interface SourceRefDisplay {
  refId: string
  documentName: string
  pageNumber: number
  excerpt: string
}

const sourceRefs = ref<SourceRefDisplay[]>([
  {
    refId: 'S1',
    documentName: '计算机网络.pdf',
    pageNumber: 45,
    excerpt: 'TCP 连接建立需要三次握手：客户端发送 SYN 报文（seq=x），服务端回复 SYN-ACK（seq=y, ack=x+1），客户端再发送 ACK（ack=y+1）完成连接建立。',
  },
  {
    refId: 'S2',
    documentName: '计算机网络.pdf',
    pageNumber: 47,
    excerpt: 'TCP 状态转换：CLOSED → LISTEN → SYN-RCVD → ESTABLISHED。四次挥手涉及 FIN 报文和 TIME-WAIT 状态，持续 2MSL 时间以确保最后的 ACK 能够到达。',
  },
  {
    refId: 'S3',
    documentName: '计算机网络.pdf',
    pageNumber: 52,
    excerpt: '拥塞控制算法包含四个阶段：慢启动（Slow Start）、拥塞避免（Congestion Avoidance）、快速重传（Fast Retransmit）和快速恢复（Fast Recovery）。',
  },
])

// =========================================================
// 聊天消息（Mock — 含拒答场景）
// =========================================================
interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  /** 关联的引用 ID 列表（仅 assistant 消息） */
  citationIds?: string[]
  /** 是否为拒答消息 */
  isRefusal?: boolean
}

const messages = ref<ChatMessage[]>([
  {
    id: 'm1',
    role: 'user',
    content: '请帮我详细解释一下 TCP 协议的三次握手过程，以及为什么需要三次而不是两次？',
    timestamp: '14:32',
  },
  {
    id: 'm2',
    role: 'assistant',
    content: '**TCP 三次握手（Three-Way Handshake）**是建立可靠传输连接的核心机制。\n\n### 三次握手流程\n\n1. **第一次握手**：客户端发送 SYN 报文，`seq = x`，客户端进入 `SYN-SENT` 状态。\n2. **第二次握手**：服务端收到后回复 SYN-ACK 报文，`seq = y, ack = x + 1`，服务端进入 `SYN-RCVD` 状态。\n3. **第三次握手**：客户端发送 ACK 报文，`ack = y + 1`，双方进入 `ESTABLISHED` 状态。[S1]\n\n### 为什么需要三次？\n\n- **防止历史连接初始化**：如果只有两次握手，服务端无法区分一个过期的 SYN 报文。三次握手让客户端有能力确认连接的时效性。[S2]\n- **同步初始序列号（ISN）**：双方需要确认对方的初始序列号，这是可靠传输的基础。[S1]\n\n### 状态机视角\n\n服务端经历 `CLOSED → LISTEN → SYN-RCVD → ESTABLISHED` 的状态变迁，而 `TIME-WAIT` 状态在连接关闭时确保最后的 ACK 可达。[S2]',
    timestamp: '14:33',
    citationIds: ['S1', 'S2'],
  },
  {
    id: 'm3',
    role: 'user',
    content: '那请帮我对比一下 GPT-4 和 Claude 的大模型架构设计原理，哪个更适合做代码生成？',
    timestamp: '14:35',
  },
  {
    id: 'm4',
    role: 'assistant',
    content: '⚠️ **抱歉，我无法回答这个问题。**\n\n### 拒答原因\n\n当前已导入的课程资料（《计算机网络.pdf》等）中**未检索到任何与 "GPT-4 架构" 或 "Claude 模型设计" 相关的内容**。\n\nStudyAgents 严格遵循**文档溯源原则**：\n- 所有回答均须引用课程资料中的具体证据（SourceRef）\n- 不会使用模型通识或外部知识来补全课程中不存在的事实\n- 证据不足时主动拒答，确保信息的可靠性与可复核性\n\n### 您可以尝试\n\n- **导入相关资料**：点击输入框左侧的「导入 PDF」按钮，上传包含大模型架构知识的课程 PDF 或文档\n- **换个问题**：询问当前课程范围内的内容，例如计算机网络、操作系统、数据结构等\n- **专项训练**：进入左侧「专项训练」模式，基于已有资料进行针对性练习',
    timestamp: '14:35',
    isRefusal: true,
  },
  {
    id: 'm5',
    role: 'user',
    content: '明白了，那请解释一下 TCP 的拥塞控制算法有哪些阶段？',
    timestamp: '14:37',
  },
  {
    id: 'm6',
    role: 'assistant',
    content: '**TCP 拥塞控制（Congestion Control）**是保证网络稳定性的关键机制，由 Van Jacobson 于 1988 年提出。[S3]\n\n### 四个核心阶段\n\n| 阶段 | 机制 | 特点 |\n|------|------|------|\n| **慢启动** | 拥塞窗口 `cwnd` 从 1 MSS 开始，每收到一个 ACK 指数增长（×2） | 快速探测可用带宽 |\n| **拥塞避免** | `cwnd` 达到慢启动阈值 `ssthresh` 后，改为线性增长（每 RTT +1 MSS） | 避免过度注入 |\n| **快速重传** | 收到 3 个重复 ACK 时，不等超时直接重传丢失报文 | 减少等待时间 |\n| **快速恢复** | 重传后不进入慢启动，而是将 `ssthresh` 设为 `cwnd/2`，直接进入拥塞避免 | 避免不必要的慢启动 |\n\n### 关键参数\n\n- **拥塞窗口 (cwnd)**：发送方维护的拥塞控制窗口\n- **慢启动阈值 (ssthresh)**：切换增长模式的临界值\n- **RTO (Retransmission Timeout)**：超时重传计时器\n\n当发生超时重传（RTO 超时），说明网络严重拥塞，`ssthresh` 被设为 `cwnd/2`，`cwnd` 重置为 1 MSS，重新进入慢启动。[S3]',
    timestamp: '14:38',
    citationIds: ['S3'],
  },
])

// =========================================================
// 用户输入 & 发送（Mock）
// =========================================================
const inputText = ref('')
const isStreaming = ref(false)
const chatContainerRef = ref<InstanceType<typeof import('element-plus').ElScrollbar> | null>(null)

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value) return

  messages.value.push({
    id: `m${Date.now()}`,
    role: 'user',
    content: text,
    timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
  })
  inputText.value = ''

  isStreaming.value = true
  await new Promise((r) => setTimeout(r, 1800))

  // 简易拒答判断：含 "GPT"、"Claude"、"大模型" 等关键词
  const refusalKeywords = ['GPT', 'Claude', '大模型', 'LLM', 'ChatGPT', 'Gemini', '文心一言']
  const shouldRefuse = refusalKeywords.some((kw) => text.includes(kw))

  if (shouldRefuse) {
    messages.value.push({
      id: `m${Date.now() + 1}`,
      role: 'assistant',
      content:
        '⚠️ **抱歉，我无法回答这个问题。**\n\n当前已导入的课程资料中未检索到与此问题相关的内容。StudyAgents 严格遵循文档溯源原则，证据不足时主动拒答，不使用模型通识补全课程事实。\n\n您可以尝试：导入相关资料、换个课程范围内的问题、或进入专项训练模式进行练习。',
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      isRefusal: true,
    })
  } else {
    messages.value.push({
      id: `m${Date.now() + 1}`,
      role: 'assistant',
      content:
        '这是一个模拟的 AI 回复。在实际部署中，Coordinator Agent 将调度 Knowledge Agent 检索课程资料，所有回答均附带文档名、页码和证据片段的引用（SourceRef），确保每一句话都可溯源、可复核。\n\n引用示例：[S1] 《计算机网络.pdf》第 45 页。',
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      citationIds: ['S1'],
    })
  }

  isStreaming.value = false
  await nextTick()
  scrollToBottom()
}

function scrollToBottom() {
  const wrap = (chatContainerRef.value as any)?.wrapRef
  if (wrap) {
    wrap.scrollTop = wrap.scrollHeight
  }
}

// =========================================================
// PDF 导入
// =========================================================
const pdfUploading = ref(false)

function handlePdfImport() {
  pdfUploading.value = true
  setTimeout(() => {
    pdfUploading.value = false
  }, 2000)
}

// =========================================================
// 右侧 Agent 抽屉
// =========================================================
const drawerOpen = ref(true)
const drawerTab = ref<'agents' | 'sources'>('agents')

function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
}

// =========================================================
// 获取引用详情
// =========================================================
function getRefById(refId: string): SourceRefDisplay | undefined {
  return sourceRefs.value.find((r) => r.refId === refId)
}

// =========================================================
// 快捷提示词
// =========================================================
const quickPrompts = ['解释 TCP 拥塞控制', '对比 HTTP/1.1 与 HTTP/2', '子网划分计算题', '操作系统进程状态转换']
</script>

<template>
  <div class="home-shell">
    <!-- ======================================== -->
    <!-- 左侧：历史会话侧边栏                        -->
    <!-- ======================================== -->
    <aside class="sidebar-left">
      <!-- Logo -->
      <div class="sidebar-brand">
        <svg class="brand-logo" viewBox="0 0 32 32" fill="none">
          <rect width="32" height="32" rx="8" fill="var(--accent)" />
          <path
            d="M8 16C8 11.58 11.58 8 16 8c2.53 0 4.79 1.23 6.25 3.12l-1.55 1.18C19.63 10.78 17.92 9.78 16 9.78c-3.24 0-5.88 2.5-6.12 5.67L8 16Z"
            fill="white" fill-opacity="0.9"
          />
          <path
            d="M24 16c0 4.42-3.58 8-8 8-2.53 0-4.79-1.23-6.25-3.12l1.55-1.18C12.37 21.22 14.08 22.22 16 22.22c3.24 0 5.88-2.5 6.12-5.67L24 16Z"
            fill="white" fill-opacity="0.7"
          />
          <circle cx="16" cy="16" r="3" fill="white" />
        </svg>
        <span class="brand-text">StudyAgents</span>
      </div>

      <!-- ============================================ -->
      <!-- 核心导航：专项训练 / 错题本                     -->
      <!-- ============================================ -->
      <nav class="core-nav">
        <button
          :class="['nav-btn', { active: navMode === 'chat' }]"
          @click="switchMode('chat')"
        >
          <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M18 10c0 3.866-3.582 7-8 7a8.84 8.84 0 01-4.083-.98L2 17l1.262-3.391A6.474 6.474 0 012 10c0-3.866 3.582-7 8-7s8 3.134 8 7zM7 9H5v2h2V9zm8 0h-2v2h2V9zM9 9h2v2H9V9z" clip-rule="evenodd" />
          </svg>
          <span>自由问答</span>
        </button>

        <button
          :class="['nav-btn', { active: navMode === 'practice' }]"
          @click="switchMode('practice')"
        >
          <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor">
            <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
            <path fill-rule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z" clip-rule="evenodd" />
          </svg>
          <span>专项训练</span>
        </button>

        <button
          :class="['nav-btn', { active: navMode === 'wrongbook' }]"
          @click="switchMode('wrongbook')"
        >
          <svg class="nav-icon" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clip-rule="evenodd" />
          </svg>
          <span>错题本</span>
          <span v-if="pendingWrongCount > 0" class="badge">{{ pendingWrongCount }}</span>
        </button>
      </nav>

      <div class="sidebar-divider"></div>

      <!-- 新建对话 -->
      <button class="btn-new-chat" @click="switchMode('chat')">
        <svg class="icon-svg" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd" />
        </svg>
        新建对话
      </button>

      <!-- 历史列表 -->
      <div class="history-section">
        <p class="section-label">历史会话</p>
        <el-scrollbar class="history-scroll">
          <div
            v-for="item in historyList"
            :key="item.id"
            :class="['history-item', { active: activeHistoryId === item.id }]"
            @click="activeHistoryId = item.id"
          >
            <svg class="icon-svg history-icon" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clip-rule="evenodd" />
            </svg>
            <div class="history-item-text">
              <span class="history-title">{{ item.title }}</span>
              <span class="history-time">{{ item.updatedAt }}</span>
            </div>
          </div>
        </el-scrollbar>
      </div>

      <!-- 底部：知识掌握度 + 用户信息 -->
      <div class="sidebar-footer">
        <div class="mastery-section">
          <div class="mastery-header">
            <svg class="icon-svg mastery-icon" viewBox="0 0 20 20" fill="currentColor">
              <path d="M2 11a1 1 0 011-1h2a1 1 0 011 1v5a1 1 0 01-1 1H3a1 1 0 01-1-1v-5zm6-4a1 1 0 011-1h2a1 1 0 011 1v9a1 1 0 01-1 1H9a1 1 0 01-1-1V7zm6-3a1 1 0 011-1h2a1 1 0 011 1v12a1 1 0 01-1 1h-2a1 1 0 01-1-1V4z" />
            </svg>
            <span class="mastery-label">知识掌握度</span>
            <span class="mastery-value">{{ Math.round(overallMastery * 100) }}%</span>
          </div>
          <div class="mastery-bar-track">
            <div class="mastery-bar-fill" :style="{ width: overallMastery * 100 + '%' }"></div>
          </div>
          <!-- 知识点迷你列表 -->
          <div class="mastery-detail">
            <div v-for="rec in masteryRecords.slice(0, 3)" :key="rec.kpId" class="mastery-row">
              <span class="mastery-kp-name">{{ rec.kpName }}</span>
              <span class="mastery-kp-bar-track">
                <span
                  class="mastery-kp-bar-fill"
                  :style="{ width: rec.mastery * 100 + '%' }"
                  :class="{
                    high: rec.mastery >= 0.8,
                    mid: rec.mastery >= 0.5 && rec.mastery < 0.8,
                    low: rec.mastery < 0.5,
                  }"
                ></span>
              </span>
              <span class="mastery-kp-pct">{{ Math.round(rec.mastery * 100) }}%</span>
            </div>
            <p class="mastery-more" v-if="masteryRecords.length > 3">
              +{{ masteryRecords.length - 3 }} 个知识点...
            </p>
          </div>
        </div>

        <div class="user-row">
          <el-avatar :size="30" icon="UserFilled" />
          <span class="footer-username">演示用户</span>
        </div>
      </div>
    </aside>

    <!-- ======================================== -->
    <!-- 中间：主对话区                              -->
    <!-- ======================================== -->
    <main class="chat-main">
      <!-- 顶栏 -->
      <header class="chat-header">
        <h2 class="chat-title">
          <template v-if="navMode === 'practice'">🎯 专项训练</template>
          <template v-else-if="navMode === 'wrongbook'">📖 错题本</template>
          <template v-else>{{ historyList.find((h) => h.id === activeHistoryId)?.title ?? '新对话' }}</template>
        </h2>
        <div class="header-actions">
          <!-- 错题本模式下的筛选 -->
          <template v-if="navMode === 'wrongbook'">
            <el-select
              model-value="all"
              size="small"
              class="header-select"
              placeholder="知识点筛选"
            >
              <el-option label="全部知识点" value="all" />
              <el-option label="TCP 协议" value="kp1" />
              <el-option label="IP 与路由" value="kp2" />
            </el-select>
          </template>

          <!-- Agent 抽屉切换 -->
          <button class="btn-drawer-toggle" @click="toggleDrawer" :title="drawerOpen ? '收起 Agent 面板' : '展开 Agent 面板'">
            <svg class="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path v-if="drawerOpen" fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
              <path v-else fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
      </header>

      <!-- 错题本视图 -->
      <template v-if="navMode === 'wrongbook'">
        <el-scrollbar class="wrongbook-scroll">
          <div class="wrongbook-inner">
            <div class="wrongbook-card" v-for="i in 3" :key="'wb-' + i">
              <div class="wb-status" :class="i === 1 ? 'pending' : i === 2 ? 'reviewing' : 'mastered'">
                {{ i === 1 ? '待复习' : i === 2 ? '复习中' : '已掌握' }}
              </div>
              <p class="wb-question">
                {{
                  i === 1
                    ? '某主机 IP 地址为 192.168.1.37/28，请计算该子网的网络地址、广播地址和可用 IP 范围。'
                    : i === 2
                      ? 'TCP 拥塞控制中，若当前 cwnd = 24 MSS，ssthresh = 16 MSS，收到 3 个重复 ACK 后，cwnd 和 ssthresh 分别变为多少？'
                      : 'HTTP/2 相比 HTTP/1.1 在性能方面做了哪些关键改进？请至少列出三项。'
                }}
              </p>
              <div class="wb-meta">
                <span class="wb-source">来源：{{ i === 3 ? '计算机网络.pdf 第 89 页' : '计算机网络.pdf' }}</span>
                <span class="wb-kp">知识点：{{ i === 1 ? 'IP 与路由' : i === 2 ? 'TCP 协议' : 'HTTP/HTTPS' }}</span>
                <span class="wb-count">错误 {{ i === 1 ? 3 : i === 2 ? 2 : 1 }} 次</span>
              </div>
              <div class="wb-actions">
                <el-button size="small" type="primary" plain>重新练习</el-button>
                <el-button size="small" plain>查看解析</el-button>
              </div>
            </div>
          </div>
        </el-scrollbar>
      </template>

      <!-- 专项训练视图（占位） -->
      <template v-else-if="navMode === 'practice'">
        <div class="practice-placeholder">
          <svg class="practice-icon" viewBox="0 0 64 64" fill="none">
            <rect x="8" y="8" width="48" height="48" rx="10" stroke="var(--accent)" stroke-width="2" stroke-dasharray="4 3" />
            <path d="M22 28h20M22 36h14" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" opacity="0.6" />
            <circle cx="46" cy="44" r="10" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
            <path d="M46 40v8m-4-4h8" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
          </svg>
          <h3 class="practice-title">开始专项训练</h3>
          <p class="practice-desc">选择章节和知识点，AI 将基于课程资料生成针对性练习题，完成后由 Evaluator Agent 分步评分并生成详细讲解。</p>
          <div class="practice-config">
            <el-select model-value="" placeholder="选择章节" style="width: 180px">
              <el-option label="第 3 章 · 运输层" value="ch3" />
              <el-option label="第 4 章 · 网络层" value="ch4" />
              <el-option label="第 5 章 · 链路层" value="ch5" />
            </el-select>
            <el-select model-value="" placeholder="题目数量" style="width: 140px">
              <el-option label="3 题" value="3" />
              <el-option label="5 题" value="5" />
              <el-option label="10 题" value="10" />
            </el-select>
            <el-button type="primary" size="large" round>开始训练</el-button>
          </div>
        </div>
      </template>

      <!-- 对话视图 -->
      <template v-else>
        <el-scrollbar ref="chatContainerRef" class="chat-messages">
          <div class="messages-inner">
            <!-- 空状态 -->
            <div v-if="messages.length === 0" class="empty-chat">
              <svg class="empty-icon" viewBox="0 0 48 48" fill="none">
                <rect x="4" y="8" width="40" height="28" rx="4" stroke="var(--text)" stroke-width="1.5" opacity="0.3" />
                <path d="M4 12L24 26L44 12" stroke="var(--text)" stroke-width="1.5" opacity="0.3" />
              </svg>
              <p class="empty-title">开始新的学习对话</p>
              <p class="empty-desc">输入你的问题，AI 将基于课程资料为你解答，每一句回答均可溯源</p>
            </div>

            <!-- 消息气泡 -->
            <template v-for="msg in messages" :key="msg.id">
              <div :class="['message-row', msg.role]">
                <!-- 头像 -->
                <div class="msg-avatar">
                  <template v-if="msg.role === 'assistant'">
                    <svg viewBox="0 0 36 36" fill="none" class="avatar-svg bot">
                      <circle cx="18" cy="18" r="16" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
                      <path d="M12 20c0-3.31 2.69-6 6-6s6 2.69 6 6" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
                      <circle cx="14" cy="17" r="1.5" fill="var(--accent)" />
                      <circle cx="22" cy="17" r="1.5" fill="var(--accent)" />
                    </svg>
                  </template>
                  <template v-else-if="msg.role === 'system'">
                    <svg viewBox="0 0 36 36" fill="none" class="avatar-svg system">
                      <rect x="2" y="2" width="32" height="32" rx="8" fill="var(--border)" stroke="var(--text)" stroke-width="1" opacity="0.5" />
                      <path d="M18 10v8m0 4v.01" stroke="var(--text)" stroke-width="2.5" stroke-linecap="round" opacity="0.6" />
                    </svg>
                  </template>
                  <template v-else>
                    <el-avatar :size="36" icon="UserFilled" />
                  </template>
                </div>

                <!-- 气泡 -->
                <div class="msg-body">
                  <div :class="['bubble', msg.role, { refusal: msg.isRefusal }]">
                    <p v-for="(line, li) in msg.content.split('\n')" :key="li" class="bubble-line">
                      <template
                        v-for="(token, ti) in tokenizeMarkdownLine(line)"
                        :key="`${li}-${ti}`"
                      >
                        <strong v-if="token.type === 'strong'">{{ token.content }}</strong>
                        <code v-else-if="token.type === 'code'" class="inline-code">{{ token.content }}</code>
                        <template v-else>{{ token.content }}</template>
                      </template>
                    </p>
                  </div>

                  <!-- 引用标签 -->
                  <div v-if="msg.citationIds && msg.citationIds.length > 0" class="citation-tags">
                    <span
                      v-for="cid in msg.citationIds"
                      :key="cid"
                      class="citation-chip"
                      :title="getRefById(cid)?.excerpt"
                    >
                      [{{ cid }}] {{ getRefById(cid)?.documentName }} 第{{ getRefById(cid)?.pageNumber }}页
                    </span>
                  </div>

                  <span class="msg-time">{{ msg.timestamp }}</span>
                </div>
              </div>
            </template>

            <!-- 流式生成指示 -->
            <div v-if="isStreaming" class="message-row assistant">
              <div class="msg-avatar">
                <svg viewBox="0 0 36 36" fill="none" class="avatar-svg bot">
                  <circle cx="18" cy="18" r="16" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
                  <path d="M12 20c0-3.31 2.69-6 6-6s6 2.69 6 6" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
                  <circle cx="14" cy="17" r="1.5" fill="var(--accent)" />
                  <circle cx="22" cy="17" r="1.5" fill="var(--accent)" />
                </svg>
              </div>
              <div class="msg-body">
                <div class="bubble assistant typing">
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                  <span class="typing-dot"></span>
                </div>
              </div>
            </div>
          </div>
        </el-scrollbar>
      </template>

      <!-- 底部输入区（仅对话模式显示） -->
      <footer v-if="navMode === 'chat'" class="chat-input-area">
        <div class="quick-prompts">
          <button v-for="qp in quickPrompts" :key="qp" class="chip" @click="inputText = qp">
            {{ qp }}
          </button>
        </div>
        <div class="input-row">
          <!-- PDF/OCR 导入按钮 -->
          <button class="btn-import" @click="handlePdfImport" :disabled="pdfUploading" title="导入 PDF / OCR">
            <svg class="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
            <span class="btn-import-label">PDF</span>
          </button>

          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            placeholder="输入问题，基于课程资料获取可信回答（Ctrl+Enter 发送）..."
            class="chat-textarea"
            :disabled="isStreaming"
            @keydown.enter.exact="handleSend"
          />
          <button class="btn-send" :disabled="!inputText.trim() || isStreaming" @click="handleSend" title="发送">
            <svg class="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z" />
            </svg>
          </button>
        </div>
        <p class="input-hint">
          🛡️ StudyAgents 严格基于课程资料回答 · 证据不足时主动拒答 · 所有回答可溯源至文档页码
        </p>
      </footer>
    </main>

    <!-- ======================================== -->
    <!-- 右侧：Agent 协作抽屉                       -->
    <!-- ======================================== -->
    <aside :class="['sidebar-right', { collapsed: !drawerOpen }]">
      <div class="drawer-inner">
        <header class="drawer-header">
          <h3 class="drawer-title">Agent 协作面板</h3>
          <div class="drawer-tabs">
            <button :class="['drawer-tab', { active: drawerTab === 'agents' }]" @click="drawerTab = 'agents'">
              Agent 流程
            </button>
            <button :class="['drawer-tab', { active: drawerTab === 'sources' }]" @click="drawerTab = 'sources'">
              溯源引用
            </button>
          </div>
        </header>

        <el-scrollbar class="drawer-scroll">
          <!-- ====================================== -->
          <!-- Agent 流程视图                           -->
          <!-- ====================================== -->
          <template v-if="drawerTab === 'agents'">
            <div class="drawer-section">
              <p class="section-desc">
                以下展示四类 Agent 在当前问答中的协同工作状态。所有 Agent 思考步骤通过 SSE 事件实时推送给前端。
              </p>

              <!-- Agent 步骤卡片 -->
              <div v-for="(step, idx) in agentSteps" :key="step.agentRole" class="agent-step-card">
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
                      {{ step.status === 'succeeded' ? '已完成' : step.status === 'running' ? '运行中' : step.status === 'failed' ? '失败' : '待命' }}
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

          <!-- ====================================== -->
          <!-- 溯源引用视图                             -->
          <!-- ====================================== -->
          <template v-else>
            <div class="drawer-section">
              <p class="section-desc">
                所有回答均引用自已导入的课程资料。每条引用精确到文档名、页码和证据片段，确保可复核、可溯源。
              </p>

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
  </div>
</template>

<style scoped>
/* ============================================================
   CSS 变量
   ============================================================ */
.home-shell {
  --chat-user-bubble: var(--accent);
  --chat-user-text: #fff;
  --chat-ai-bg: var(--code-bg);
  --refusal-border: rgba(245, 158, 11, 0.4);
  --refusal-bg: rgba(245, 158, 11, 0.06);
  --sidebar-w: 280px;
  --drawer-w: 380px;

  position: fixed;
  inset: 0;
  display: flex;
  background: var(--bg);
  color: var(--text);
  font-size: 15px;
  line-height: 1.6;
  overflow: hidden;
}

/* ============================================================
   左侧边栏
   ============================================================ */
.sidebar-left {
  width: var(--sidebar-w);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  background: var(--code-bg);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 18px 8px;
}

.brand-logo {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.brand-text {
  font-family: var(--heading);
  font-size: 18px;
  font-weight: 600;
  color: var(--text-h);
  letter-spacing: -0.3px;
}

/* ---------- 核心导航 ---------- */
.core-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
}

.nav-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--text);
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.nav-btn:hover {
  background: var(--accent-bg);
  color: var(--accent);
}

.nav-btn.active {
  background: var(--accent-bg);
  color: var(--accent);
  font-weight: 700;
  outline: 1px solid var(--accent-border);
}

.nav-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  opacity: 0.65;
}

.nav-btn.active .nav-icon {
  opacity: 1;
}

.badge {
  margin-left: auto;
  background: #ef4444;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 10px;
  line-height: 1.5;
}

.sidebar-divider {
  height: 1px;
  background: var(--border);
  margin: 6px 18px;
}

.btn-new-chat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin: 4px 16px 12px;
  padding: 11px 0;
  border: 1px dashed var(--accent-border);
  border-radius: 10px;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-new-chat:hover {
  background: var(--accent);
  color: #fff;
}

.history-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 12px;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text);
  opacity: 0.5;
  padding: 0 8px 8px;
  margin: 0;
}

.history-scroll {
  flex: 1;
}

.history-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 1px;
}

.history-item:hover {
  background: var(--accent-bg);
}

.history-item.active {
  background: var(--accent-bg);
  outline: 1px solid var(--accent-border);
}

.history-icon {
  flex-shrink: 0;
  margin-top: 2px;
  opacity: 0.4;
  width: 16px;
  height: 16px;
}

.history-item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.history-title {
  font-size: 13px;
  color: var(--text-h);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-time {
  font-size: 11px;
  color: var(--text);
  opacity: 0.55;
  margin-top: 2px;
}

/* ---------- 底部知识掌握度 ---------- */
.sidebar-footer {
  border-top: 1px solid var(--border);
  padding: 12px 16px 10px;
}

.mastery-section {
  margin-bottom: 10px;
}

.mastery-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.mastery-icon {
  width: 16px;
  height: 16px;
  opacity: 0.5;
}

.mastery-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  flex: 1;
}

.mastery-value {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent);
}

.mastery-bar-track {
  width: 100%;
  height: 5px;
  border-radius: 3px;
  background: var(--border);
  overflow: hidden;
  margin-bottom: 8px;
}

.mastery-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--accent);
  transition: width 0.5s ease;
}

.mastery-detail {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mastery-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.mastery-kp-name {
  width: 68px;
  flex-shrink: 0;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mastery-kp-bar-track {
  flex: 1;
  height: 3px;
  border-radius: 2px;
  background: var(--border);
  overflow: hidden;
}

.mastery-kp-bar-fill {
  display: block;
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}

.mastery-kp-bar-fill.high {
  background: #34d399;
}

.mastery-kp-bar-fill.mid {
  background: var(--accent);
}

.mastery-kp-bar-fill.low {
  background: #f87171;
}

.mastery-kp-pct {
  width: 30px;
  text-align: right;
  font-weight: 600;
  color: var(--text-h);
  flex-shrink: 0;
}

.mastery-more {
  font-size: 11px;
  color: var(--text);
  opacity: 0.5;
  margin: 2px 0 0;
}

.user-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.footer-username {
  font-size: 13px;
  color: var(--text-h);
  font-weight: 500;
}

/* ============================================================
   中间主对话区
   ============================================================ */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg);
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.chat-title {
  font-family: var(--heading);
  font-size: 16px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.header-select {
  width: 160px;
}

.btn-drawer-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}

.btn-drawer-toggle:hover {
  background: var(--accent-bg);
  color: var(--accent);
  border-color: var(--accent-border);
}

/* --- 错题本视图 --- */
.wrongbook-scroll {
  flex: 1;
  overflow: hidden;
}

.wrongbook-inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.wrongbook-card {
  padding: 18px 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--code-bg);
}

.wb-status {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 10px;
  margin-bottom: 10px;
}

.wb-status.pending {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.wb-status.reviewing {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.wb-status.mastered {
  background: rgba(52, 211, 153, 0.12);
  color: #34d399;
}

.wb-question {
  font-size: 15px;
  color: var(--text-h);
  margin: 0 0 12px;
  line-height: 1.65;
}

.wb-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 12px;
}

.wb-source {
  opacity: 0.7;
}

.wb-kp {
  color: var(--accent);
}

.wb-count {
  color: #f87171;
  font-weight: 600;
}

.wb-actions {
  display: flex;
  gap: 8px;
}

/* --- 专项训练占位 --- */
.practice-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  text-align: center;
}

.practice-icon {
  width: 80px;
  height: 80px;
  margin-bottom: 20px;
}

.practice-title {
  font-family: var(--heading);
  font-size: 22px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 8px;
}

.practice-desc {
  font-size: 14px;
  color: var(--text);
  max-width: 480px;
  margin: 0 0 28px;
  line-height: 1.6;
}

.practice-config {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
}

/* --- 消息区 --- */
.chat-messages {
  flex: 1;
  overflow: hidden;
}

.messages-inner {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px 24px 8px;
}

/* 空状态 */
.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  text-align: center;
}

.empty-icon {
  width: 64px;
  height: 64px;
  margin-bottom: 20px;
}

.empty-title {
  font-family: var(--heading);
  font-size: 20px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 8px;
}

.empty-desc {
  font-size: 14px;
  color: var(--text);
  margin: 0;
}

/* 消息行 */
.message-row {
  display: flex;
  gap: 12px;
  margin-bottom: 22px;
}

.message-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex-shrink: 0;
}

.avatar-svg.bot,
.avatar-svg.system {
  width: 36px;
  height: 36px;
}

.msg-body {
  display: flex;
  flex-direction: column;
  max-width: 75%;
}

.message-row.user .msg-body {
  align-items: flex-end;
}

.message-row.assistant .msg-body,
.message-row.system .msg-body {
  align-items: flex-start;
}

/* 气泡 */
.bubble {
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 14.5px;
  line-height: 1.7;
  word-break: break-word;
}

.bubble.assistant {
  background: var(--chat-ai-bg);
  color: var(--text-h);
  border-bottom-left-radius: 4px;
}

.bubble.user {
  background: var(--chat-user-bubble);
  color: var(--chat-user-text);
  border-bottom-right-radius: 4px;
}

/* 拒答气泡 */
.bubble.refusal {
  border: 1px solid var(--refusal-border);
  background: var(--refusal-bg);
  border-bottom-left-radius: 4px;
}

.bubble.system {
  background: var(--code-bg);
  color: var(--text);
  font-style: italic;
  border: 1px solid var(--border);
}

.bubble-line {
  margin: 0 0 6px;
}

.bubble-line:last-child {
  margin-bottom: 0;
}

/* Bubble 内粗体 */
.bubble-line :deep(strong) {
  color: var(--text-h);
  font-weight: 700;
}

.bubble-line :deep(code.inline-code) {
  background: var(--accent-bg);
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-family: var(--mono);
}

.bubble.user .bubble-line :deep(code.inline-code) {
  background: rgba(255, 255, 255, 0.2);
  color: inherit;
}

/* 引用标签 */
.citation-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.citation-chip {
  display: inline-block;
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 6px;
  background: var(--accent-bg);
  color: var(--accent);
  font-weight: 600;
  cursor: help;
  border: 1px solid var(--accent-border);
  transition: all 0.15s;
}

.citation-chip:hover {
  background: var(--accent);
  color: #fff;
}

/* 打字动画 */
.bubble.typing {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px 20px;
}

.typing-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text);
  opacity: 0.4;
  animation: typing-bounce 1.4s infinite ease-in-out both;
}

.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
.typing-dot:nth-child(3) { animation-delay: 0s; }

@keyframes typing-bounce {
  0%, 80%, 100% { opacity: 0.15; transform: scale(0.85); }
  40% { opacity: 0.55; transform: scale(1); }
}

.msg-time {
  font-size: 11px;
  color: var(--text);
  opacity: 0.5;
  margin-top: 4px;
  padding: 0 4px;
}

/* --- 底部输入区 --- */
.chat-input-area {
  flex-shrink: 0;
  padding: 10px 24px 14px;
  border-top: 1px solid var(--border);
  background: var(--bg);
}

.quick-prompts {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.chip {
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: 20px;
  background: transparent;
  color: var(--text);
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.15s;
}

.chip:hover {
  border-color: var(--accent-border);
  color: var(--accent);
  background: var(--accent-bg);
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

/* PDF 导入按钮 */
.btn-import {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  width: 48px;
  height: 48px;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.btn-import:hover:not(:disabled) {
  border-color: var(--accent-border);
  color: var(--accent);
  background: var(--accent-bg);
}

.btn-import:disabled {
  opacity: 0.4;
  cursor: wait;
}

.btn-import-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.chat-textarea {
  flex: 1;
}

.chat-textarea :deep(.el-textarea__inner) {
  background: var(--code-bg);
  border-color: var(--border);
  color: var(--text-h);
  border-radius: 12px;
  padding: 12px 16px;
  font-size: 14.5px;
  line-height: 1.6;
  resize: none;
}

.chat-textarea :deep(.el-textarea__inner:focus) {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 2px var(--accent-bg);
}

.btn-send {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 12px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.btn-send:hover:not(:disabled) {
  filter: brightness(1.15);
  transform: scale(1.05);
}

.btn-send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.input-hint {
  font-size: 11px;
  color: var(--text);
  opacity: 0.45;
  margin: 6px 0 0 56px;
  text-align: left;
}

/* ============================================================
   右侧 Agent 抽屉
   ============================================================ */
.sidebar-right {
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

.drawer-header {
  padding: 16px 18px 0;
  flex-shrink: 0;
}

.drawer-title {
  font-family: var(--heading);
  font-size: 15px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 10px;
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

/* --- Agent 步骤卡片 --- */
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

/* --- 工作流图例 --- */
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

/* --- 溯源引用卡片 --- */
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

/* ============================================================
   通用图标
   ============================================================ */
.icon-svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

/* ============================================================
   Element Plus 组件覆盖
   ============================================================ */
.chat-main :deep(.el-select .el-input__wrapper) {
  background: var(--code-bg);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.chat-main :deep(.el-select .el-input__inner) {
  color: var(--text-h);
}

.wrongbook-card :deep(.el-button) {
  font-size: 12px;
}

.practice-placeholder :deep(.el-select .el-input__wrapper) {
  background: var(--code-bg);
  box-shadow: 0 0 0 1px var(--border) inset;
}

.practice-placeholder :deep(.el-select .el-input__inner) {
  color: var(--text-h);
}
</style>
