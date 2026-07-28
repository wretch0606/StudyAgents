<script setup lang="ts">
// ============================================================
// StudyAgents — 知识问答主界面（业务重构版）
//
// 核心差异点：
//   1. 左侧：专项训练 / 错题本入口 + 知识掌握度可视化
//   2. 中间：PDF/OCR 导入入口 + 含拒答场景的 Mock 对话
//   3. 右侧：四类 Agent 协同工作流 + 文档溯源卡片（SourceRef）
// ============================================================
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useChatStore } from '../stores/useChatStore'
import { useWrongBookStore } from '../stores/useWrongBookStore'
import type { WrongBookEntry } from '../stores/useWrongBookStore'
import type { SourceRefDisplay } from '../stores/useChatStore'
import { uploadChatAttachment } from '../api/upload'
import AgentDrawer from '../components/AgentDrawer.vue'
import KaTeXEditor from '../components/KaTeXEditor.vue'
import { renderMixedHtml } from '../utils/katex-renderer'
import { tokenizeMarkdownLine } from '../utils/markdown'

// =========================================================
// 聊天状态（Pinia Store）
// =========================================================

const chatStore = useChatStore()
const wrongBookStore = useWrongBookStore()
// 仅提取 Home.vue 模板直接使用的状态（AgentDrawer 自行从 Store 读取）
const { messages, isStreaming, attachments, agentSteps } = storeToRefs(chatStore)

// ---- 页面挂载时发起网络请求获取对话历史 ----
onMounted(() => {
  chatStore.fetchHistory()
})

// =========================================================
// 导航模式（对话 / 训练 / 错题本）
// =========================================================
type NavMode = 'chat' | 'practice' | 'wrongbook'

const navMode = ref<NavMode>('chat')

// 从路由 query 同步初始模式（顶部导航栏 "训练" 跳转 → /?mode=practice）
const route = useRoute()
if (route.query.mode === 'practice') {
  navMode.value = 'practice'
} else if (route.query.mode === 'wrongbook') {
  navMode.value = 'wrongbook'
}

// 监听路由 query 变化，同步导航模式
watch(
  () => route.query.mode,
  (mode) => {
    if (mode === 'practice') navMode.value = 'practice'
    else if (mode === 'wrongbook') navMode.value = 'wrongbook'
    else navMode.value = 'chat'
  },
)

const router = useRouter()

function switchMode(mode: NavMode) {
  navMode.value = mode

  // 同步路由 query，确保顶部导航栏与左侧菜单栏路由一致
  if (mode === 'chat') {
    drawerOpen.value = true
    router.replace({ path: '/', query: {} })
  } else if (mode === 'practice') {
    router.replace({ path: '/', query: { mode: 'practice' } })
  } else if (mode === 'wrongbook') {
    router.replace({ path: '/', query: { mode: 'wrongbook' } })
  }
}

// =========================================================
// 专项训练 — 答题状态
// =========================================================

/** 是否已进入答题模式（false = 章节选择，true = 答题区） */
const isTraining = ref(false)

/** 选中的章节 */
const selectedChapter = ref('')

/** 选中的题型 */
const selectedType = ref('')

/** 选中的难度 */
const selectedDifficulty = ref('')

/** 选中的题目数量 */
const selectedCount = ref('5')

/** 开始训练：收集配置参数 → 初始化 Agent 轨迹 → 切换至答题编辑器 */
function startTraining() {
  const config = {
    chapter: selectedChapter.value,
    type: selectedType.value,
    difficulty: selectedDifficulty.value,
    count: selectedCount.value,
  }
  console.log('[专项训练] 训练配置参数：', config)

  isTraining.value = true
  isSubmitted.value = false
  evaluationReport.value = null
  trainingAnswer.value = ''
  chatStore.initPracticeTraces()
}

/** 返回章节选择 */
function backToSelect() {
  isTraining.value = false
  isSubmitted.value = false
  evaluationReport.value = null
  trainingAnswer.value = ''
  selectedType.value = ''
  selectedDifficulty.value = ''
  chatStore.clearAgentTraces()
}

/** 答题区 v-model 绑定的用户输入 */
const trainingAnswer = ref('')


/** 是否已提交答案 */
const isSubmitted = ref(false)

/** 是否正在评测中（Evaluator running） */
const isEvaluating = ref(false)

/** 评测报告 */
const evaluationReport = ref<{
  score: number
  total: number
  analysis: string
  highlights: string[]
  /** 评测置信度 (0–1) */
  confidence: number
  /** 评测引用的文档溯源卡片 */
  sourceRefs: SourceRefDisplay[]
} | null>(null)

/** 得分率 (0–100)，用于圆环仪表 */
const scorePercent = computed(() => {
  if (!evaluationReport.value) return 0
  return Math.round((evaluationReport.value.score / evaluationReport.value.total) * 100)
})

/** 得分等级（CSS class） */
const scoreGrade = computed(() => {
  const p = scorePercent.value
  if (p >= 80) return 'grade-high'
  if (p >= 60) return 'grade-mid'
  return 'grade-low'
})

/** 得分圆环 SVG stroke-dash 参数 */
const scoreRingDash = computed(() => {
  const circumference = 2 * Math.PI * 54 // r=54
  const p = scorePercent.value
  const filled = (p / 100) * circumference
  return { circumference, filled }
})

/** 章节中文标签（computed） */
const chapterLabel = computed(() => {
  switch (selectedChapter.value) {
    case 'ch3': return '第 3 章 · 运输层'
    case 'ch4': return '第 4 章 · 网络层'
    case 'ch5': return '第 5 章 · 链路层'
    default: return ''
  }
})

/** 章节 → 知识点映射（用于掌握度联动更新） */
const CHAPTER_KP_MAP: Record<string, string[]> = {
  ch3: ['kp1'],           // 运输层 → TCP 协议
  ch4: ['kp2'],           // 网络层 → IP 与路由
  ch5: [],                // 链路层暂无直接对应知识点（后续扩展）
}

/** 根据得分降低对应章节的知识点掌握度（模拟训练反馈闭环） */
function applyMasteryDegradation(chapter: string, score: number, total: number) {
  const kpIds = CHAPTER_KP_MAP[chapter]
  if (!kpIds || kpIds.length === 0) return

  const scoreRate = score / total
  // 得分率越低，掌握度衰减越大（0.02–0.15）
  const decay = Math.round((1 - scoreRate) * 0.15 * 100) / 100

  for (const kpId of kpIds) {
    const record = masteryRecords.value.find((r) => r.kpId === kpId)
    if (record) {
      record.mastery = Math.max(0, Math.round((record.mastery - decay) * 100) / 100)
    }
  }

  // 重新计算总体掌握度
  const sum = masteryRecords.value.reduce((acc, r) => acc + r.mastery, 0)
  overallMastery.value = Math.round((sum / masteryRecords.value.length) * 100) / 100
}

/** 当前题目题干（纯文本，用于错题本存储） */
const currentQuestionText = computed(() => {
  // 与模板中 .pqc-prompt 内容保持同步（去除 HTML 标签后的纯文本）
  return '请简述 TCP 拥塞控制中慢启动与拥塞避免两个阶段的区别，并用数学公式描述拥塞窗口（cwnd）在慢启动阶段的增长规律。'
})

/** 提交答案 → 触发 Evaluator 评测 + 低分自动沉淀至错题本 */
async function submitAnswer() {
  if (isEvaluating.value || isSubmitted.value) return
  isEvaluating.value = true

  try {
    const report = await chatStore.submitAnswerForEvaluation()
    evaluationReport.value = report
    isSubmitted.value = true

    // ---- 错题沉淀：得分 < 80 自动收录 ----
    if (report.score < 80) {
      wrongBookStore.addEntry({
        chapter: selectedChapter.value,
        chapterLabel: chapterLabel.value,
        question: currentQuestionText.value,
        userAnswer: trainingAnswer.value,
        score: report.score,
        total: report.total,
        analysis: report.analysis,
        highlights: report.highlights,
      })

      // ---- 掌握度联动：低分 → 衰减对应知识点 ----
      applyMasteryDegradation(selectedChapter.value, report.score, report.total)
    }
  } finally {
    isEvaluating.value = false
  }
}

// =========================================================
// 错题本 — 展开/折叠状态
// =========================================================

/** 当前展开查看详情的错题 ID（null = 全部折叠） */
const expandedWrongId = ref<string | null>(null)

/** 切换错题卡片的展开/折叠状态 */
function toggleWrongEntry(id: string) {
  expandedWrongId.value = expandedWrongId.value === id ? null : id
}

/** 截断文本（用于错题卡片简述） */
function truncateText(text: string, maxLen: number): string {
  const cleaned = text.replace(/<[^>]+>/g, '')
  return cleaned.length > maxLen ? cleaned.slice(0, maxLen) + '…' : cleaned
}

/** 格式化 ISO 时间为可读字符串 */
function formatWrongDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr} 小时前`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay} 天前`
  return d.toLocaleDateString('zh-CN')
}

/** 根据得分返回 CSS class */
function wrongScoreClass(score: number): string {
  if (score >= 80) return 'wb-score-high'
  if (score >= 60) return 'wb-score-mid'
  return 'wb-score-low'
}

/** 根据评测细项前缀返回 CSS class */
function wrongHighlightClass(item: string): string {
  if (item.startsWith('✅')) return 'hl-good'
  if (item.startsWith('⚠️')) return 'hl-warn'
  return 'hl-tip'
}

/** 点击错题「重新练习」→ 跳转至专项训练并预填章节 */
function retryWrongQuestion(entry: WrongBookEntry) {
  selectedChapter.value = entry.chapter
  navMode.value = 'practice'
  // 重置表单状态，预填章节但保留题型/难度供用户选择
  nextTick(() => {
    isTraining.value = false
    isSubmitted.value = false
    evaluationReport.value = null
    trainingAnswer.value = ''
    selectedType.value = ''
    selectedDifficulty.value = ''
  })
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

/** 错题本徽标数 — 动态响应 store 实际长度 */
const pendingWrongCount = computed(() => wrongBookStore.count)

/** 错题本章节筛选 */
const wrongBookFilter = ref('all')

/** 筛选后的错题列表 */
const filteredWrongEntries = computed(() => {
  const list = wrongBookStore.sortedEntries
  if (!wrongBookFilter.value || wrongBookFilter.value === 'all') return list
  return list.filter((e) => e.chapter === wrongBookFilter.value)
})

/** 章节 key → 中文标签映射（供筛选下拉和卡片使用） */
const chapterLabelMap: Record<string, string> = {
  ch3: '第 3 章 · 运输层',
  ch4: '第 4 章 · 网络层',
  ch5: '第 5 章 · 链路层',
}

// =========================================================
// 用户输入 & 发送（已接入 SSE 流式打字机模拟）
// =========================================================
const inputText = ref('')
const chatContainerRef = ref<InstanceType<typeof import('element-plus').ElScrollbar> | null>(null)

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value) return

  // 1. 将用户输入作为新消息加入 Store（含附件）
  chatStore.addMessage({
    id: `m${Date.now()}`,
    role: 'user',
    content: text,
    timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    attachments: attachments.value.length > 0 ? [...attachments.value] : undefined,
  })

  // 2. 清空输入框 + 已发送的附件
  inputText.value = ''
  chatStore.clearAttachments()

  // 3. 触发纯前端模拟的 SSE 流式打字机回复
  //    （真实对接后替换为 EventSource / fetch 流读取）
  await chatStore.simulateStreamingResponse()

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
// 问答附件上传（📎 回形针按钮）
// =========================================================
const chatFileInputRef = ref<HTMLInputElement | null>(null)
const chatUploading = ref(false)

/** 格式化文件大小为可读字符串 */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** 点击回形针 → 触发隐藏的 file input */
function triggerChatUpload() {
  chatFileInputRef.value?.click()
}

/** 文件选择后 → 上传 → 暂存到 Store */
async function handleChatFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const localId = `att-${Date.now()}`

  // 先添加到 Store（uploading 状态，显示加载卡片）
  chatStore.addAttachment({
    localId,
    fileUrl: '',
    fileName: file.name,
    fileSize: file.size,
    uploadStatus: 'uploading',
  })

  chatUploading.value = true
  try {
    const res = await uploadChatAttachment(file)
    // 上传成功 → 更新状态
    chatStore.updateAttachment(localId, {
      fileUrl: res.file_url,
      fileName: res.file_name,
      uploadStatus: 'done',
    })
  } catch {
    // 上传失败
    chatStore.updateAttachment(localId, { uploadStatus: 'failed' })
  } finally {
    chatUploading.value = false
    // 重置 input 以便重复选择同一文件
    input.value = ''
  }
}

/** 从待发送列表中移除附件 */
function removeChatAttachment(localId: string) {
  chatStore.removeAttachment(localId)
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
// 右侧 Agent 抽屉（PC：侧边栏 / 移动端：ElDrawer 浮层）
// =========================================================
const drawerOpen = ref(true)

function toggleDrawer() {
  drawerOpen.value = !drawerOpen.value
}

// =========================================================
// 获取引用详情（委托给 Store）
// =========================================================
function getRefById(refId: string): SourceRefDisplay | undefined {
  return chatStore.getRefById(refId)
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
              v-model="wrongBookFilter"
              size="small"
              class="header-select"
              placeholder="章节筛选"
              clearable
            >
              <el-option label="全部章节" value="all" />
              <el-option
                v-for="(count, ch) in wrongBookStore.countByChapter"
                :key="ch"
                :value="ch"
                :label="`${chapterLabelMap[ch] || ch} (${count})`"
              />
            </el-select>
          </template>

          <!-- Agent 抽屉切换（PC） -->
          <button class="btn-drawer-toggle" @click="toggleDrawer" :title="drawerOpen ? '收起 Agent 面板' : '展开 Agent 面板'">
            <svg class="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path v-if="drawerOpen" fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
              <path v-else fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Agent 抽屉切换（移动端） -->
          <button class="btn-drawer-toggle-mobile" @click="toggleDrawer" title="查看 Agent 流程">
            <span class="mobile-toggle-icon">💡</span>
          </button>
        </div>
      </header>

      <!-- 错题本视图 -->
      <template v-if="navMode === 'wrongbook'">
        <!-- 完全空状态 -->
        <div v-if="wrongBookStore.count === 0" class="wrongbook-empty">
          <svg class="wrongbook-empty-icon" viewBox="0 0 64 64" fill="none">
            <rect x="12" y="8" width="40" height="48" rx="6" stroke="var(--text)" stroke-width="1.5" opacity="0.3" />
            <path d="M22 24h14M22 32h20M22 40h8" stroke="var(--text)" stroke-width="1.5" stroke-linecap="round" opacity="0.2" />
            <circle cx="46" cy="46" r="12" fill="none" stroke="var(--accent)" stroke-width="1.5" opacity="0.5" />
            <path d="M46 42v8m-4-4h8" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" opacity="0.5" />
          </svg>
          <h3 class="wrongbook-empty-title">错题本为空</h3>
          <p class="wrongbook-empty-desc">完成专项训练后，得分低于 80 分的题目会自动收录到错题本，方便你针对性复习薄弱知识点。</p>
        </div>

        <!-- 筛选无匹配 -->
        <div v-else-if="filteredWrongEntries.length === 0" class="wrongbook-empty">
          <h3 class="wrongbook-empty-title">无匹配结果</h3>
          <p class="wrongbook-empty-desc">当前章节筛选条件下没有错题，请切换筛选或清除筛选条件。</p>
        </div>

        <!-- 错题列表 -->
        <el-scrollbar v-else class="wrongbook-scroll">
          <div class="wrongbook-inner">
            <div
              v-for="entry in filteredWrongEntries"
              :key="entry.id"
              :class="['wrongbook-card', { expanded: expandedWrongId === entry.id }]"
            >
              <!-- 折叠态：一行摘要 -->
              <div class="wb-card-row" @click="toggleWrongEntry(entry.id)">
                <div class="wb-card-left">
                  <span class="wb-chapter-tag">{{ entry.chapterLabel }}</span>
                  <span class="wb-question-brief">{{ truncateText(entry.question, 50) }}</span>
                </div>
                <div class="wb-card-right">
                  <span :class="['wb-score-pill', wrongScoreClass(entry.score)]">
                    {{ entry.score }}<span class="wb-score-sep">/</span>{{ entry.total }}
                  </span>
                  <span class="wb-time">{{ formatWrongDate(entry.createdAt) }}</span>
                  <svg
                    :class="['wb-chevron', { open: expandedWrongId === entry.id }]"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
                  </svg>
                </div>
              </div>

              <!-- 展开态：完整详情 -->
              <div v-if="expandedWrongId === entry.id" class="wb-card-detail">
                <!-- 题目 -->
                <div class="wb-detail-block">
                  <h4 class="wb-detail-label">📋 题目</h4>
                  <div class="wb-detail-content" v-html="renderMixedHtml(entry.question)" />
                </div>

                <!-- 你的作答 -->
                <div class="wb-detail-block">
                  <h4 class="wb-detail-label">✏️ 你的作答</h4>
                  <div class="wb-detail-content" v-html="renderMixedHtml(entry.userAnswer || '（未作答）')" />
                </div>

                <!-- 评测报告 -->
                <div class="wb-detail-block">
                  <h4 class="wb-detail-label">📊 评测报告</h4>
                  <div class="wb-detail-score-row">
                    <span class="wb-detail-score-label">得分：</span>
                    <span :class="['wb-score-pill', 'wb-score-pill-lg', wrongScoreClass(entry.score)]">
                      {{ entry.score }} / {{ entry.total }}
                    </span>
                  </div>
                  <div class="wb-detail-content" v-html="renderMixedHtml(entry.analysis)" />
                  <ul class="wb-detail-highlights">
                    <li
                      v-for="(item, hi) in entry.highlights"
                      :key="hi"
                      :class="['pqc-hl-item', wrongHighlightClass(item)]"
                    >
                      {{ item }}
                    </li>
                  </ul>
                </div>

                <!-- 操作按钮 -->
                <div class="wb-detail-actions">
                  <el-button size="small" type="primary" plain @click.stop="retryWrongQuestion(entry)">
                    🔄 重新练习
                  </el-button>
                  <el-button size="small" type="danger" plain @click.stop="wrongBookStore.removeEntry(entry.id)">
                    🗑 删除
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </el-scrollbar>
      </template>

      <!-- 专项训练视图 -->
      <template v-else-if="navMode === 'practice'">
        <!-- ================================================ -->
        <!-- 阶段 1：章节选择表单                              -->
        <!-- ================================================ -->
        <div v-if="!isTraining" class="practice-placeholder">
          <svg class="practice-icon" viewBox="0 0 64 64" fill="none">
            <rect x="8" y="8" width="48" height="48" rx="10" stroke="var(--accent)" stroke-width="2" stroke-dasharray="4 3" />
            <path d="M22 28h20M22 36h14" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" opacity="0.6" />
            <circle cx="46" cy="44" r="10" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
            <path d="M46 40v8m-4-4h8" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
          </svg>
          <h3 class="practice-title">开始专项训练</h3>
          <p class="practice-desc">配置训练参数，AI 将基于课程资料生成针对性练习题，完成后由 Evaluator Agent 分步评分并生成详细讲解。</p>
          <div class="practice-config">
            <el-select v-model="selectedChapter" placeholder="选择章节" style="width: 180px">
              <el-option label="第 3 章 · 运输层" value="ch3" />
              <el-option label="第 4 章 · 网络层" value="ch4" />
              <el-option label="第 5 章 · 链路层" value="ch5" />
            </el-select>
            <el-select v-model="selectedType" placeholder="选择题型" style="width: 150px">
              <el-option label="单选题" value="single" />
              <el-option label="多选题" value="multiple" />
              <el-option label="综合问答题" value="essay" />
            </el-select>
            <el-select v-model="selectedDifficulty" placeholder="选择难度" style="width: 130px">
              <el-option label="简单" value="easy" />
              <el-option label="中等" value="medium" />
              <el-option label="困难" value="hard" />
            </el-select>
            <el-select v-model="selectedCount" placeholder="题目数量" style="width: 130px">
              <el-option label="3 题" value="3" />
              <el-option label="5 题" value="5" />
              <el-option label="10 题" value="10" />
            </el-select>
            <el-button
              type="primary"
              size="large"
              round
              :disabled="!selectedChapter || !selectedType || !selectedDifficulty"
              @click="startTraining"
            >
              开始训练
            </el-button>
          </div>
        </div>

        <!-- ================================================ -->
        <!-- 阶段 2：答题区（KaTeXEditor）                     -->
        <!-- ================================================ -->
        <div v-else class="practice-session">
          <div class="practice-session-header">
            <el-button text size="small" @click="backToSelect">
              <svg viewBox="0 0 20 20" fill="currentColor" style="width:16px;height:16px">
                <path fill-rule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clip-rule="evenodd" />
              </svg>
              返回章节选择
            </el-button>
            <span class="practice-session-tag">
              {{ chapterLabel }}
              · {{ selectedType === 'single' ? '单选题' : selectedType === 'multiple' ? '多选题' : '综合问答题' }}
              · {{ selectedDifficulty === 'easy' ? '简单' : selectedDifficulty === 'medium' ? '中等' : '困难' }}
              · {{ selectedCount }} 题
            </span>
          </div>

          <!-- 答题主体：flex 列布局，编辑器与评测报告为同级兄弟节点 -->
          <div class="practice-session-body">
            <div class="pqc-header">
              <span class="pqc-num">第 1 题</span>
              <span class="pqc-type">综合问答</span>
            </div>
            <p class="pqc-prompt">
              请简述 TCP 拥塞控制中<strong>慢启动</strong>与<strong>拥塞避免</strong>两个阶段的区别，并用数学公式描述拥塞窗口（cwnd）在慢启动阶段的增长规律。
            </p>

            <!-- 作答区：编辑器 + 实时预览（KaTeXEditor 内置双栏布局） -->
            <KaTeXEditor
              v-model="trainingAnswer"
              :readonly="isSubmitted"
              placeholder="在此作答，可混合文本与 LaTeX 公式…&#10;&#10;例如：慢启动阶段 cwnd 呈指数增长，公式为&#10;&#10;$$cwnd_{n+1} = 2 \\cdot cwnd_n$$&#10;&#10;而拥塞避免阶段 cwnd 每 RTT 线性增长 1 MSS…"
            />

            <!-- 提交按钮（与编辑器、评测报告同级） -->
            <div v-if="!isSubmitted" class="pqc-submit-area">
              <el-button
                type="primary"
                size="large"
                round
                :loading="isEvaluating"
                :disabled="!trainingAnswer.trim() || isEvaluating"
                @click="submitAnswer"
              >
                {{ isEvaluating ? '评测中…' : '提交答案' }}
              </el-button>
            </div>

            <!-- ================================================ -->
            <!-- 评测报告：得分仪表 + Agent 反馈 + 讲解 + 溯源     -->
            <!-- ================================================ -->
            <div v-if="isSubmitted && evaluationReport" class="pqc-report">
              <!-- ---------- 顶部：得分仪表 + 置信度 ---------- -->
              <div class="pqc-report-hero">
                <!-- 得分圆环仪表 -->
                <div class="pqc-score-gauge">
                  <svg class="pqc-gauge-svg" viewBox="0 0 120 120">
                    <circle
                      cx="60" cy="60" r="54"
                      fill="none"
                      stroke="var(--border)"
                      stroke-width="8"
                    />
                    <circle
                      cx="60" cy="60" r="54"
                      fill="none"
                      :stroke="scorePercent >= 80 ? '#34d399' : scorePercent >= 60 ? '#f59e0b' : '#f87171'"
                      stroke-width="8"
                      stroke-linecap="round"
                      :stroke-dasharray="`${scoreRingDash.filled} ${scoreRingDash.circumference - scoreRingDash.filled}`"
                      transform="rotate(-90 60 60)"
                      class="pqc-gauge-arc"
                    />
                    <text x="60" y="56" text-anchor="middle" class="pqc-gauge-score">
                      {{ evaluationReport.score }}
                    </text>
                    <text x="60" y="74" text-anchor="middle" class="pqc-gauge-label">
                      / {{ evaluationReport.total }}
                    </text>
                  </svg>
                </div>

                <!-- 得分元信息 -->
                <div class="pqc-score-meta">
                  <div :class="['pqc-grade-badge', scoreGrade]">
                    {{ scorePercent >= 80 ? '🎯 优秀' : scorePercent >= 60 ? '📖 良好' : '📝 需加强' }}
                  </div>
                  <div class="pqc-confidence">
                    <span class="pqc-conf-label">评测置信度</span>
                    <div class="pqc-conf-bar-track">
                      <div
                        class="pqc-conf-bar-fill"
                        :style="{ width: Math.round(evaluationReport.confidence * 100) + '%' }"
                      ></div>
                    </div>
                    <span class="pqc-conf-pct">{{ Math.round(evaluationReport.confidence * 100) }}%</span>
                  </div>
                </div>
              </div>

              <!-- ---------- Agent 分步反馈 ---------- -->
              <div class="pqc-report-section">
                <h4 class="pqc-section-title">🤖 Agent 协同执行轨迹</h4>
                <div class="pqc-agent-steps">
                  <div
                    v-for="step in agentSteps"
                    :key="step.agentRole"
                    :class="['pqc-agent-chip', step.status]"
                  >
                    <span :class="['pqc-agent-dot', step.status]"></span>
                    <span class="pqc-agent-role">{{ step.agentLabel }}</span>
                    <span class="pqc-agent-summary">{{ step.summary }}</span>
                    <span v-if="step.durationMs" class="pqc-agent-dur">{{ step.durationMs }}ms</span>
                  </div>
                </div>
              </div>

              <!-- ---------- 详细讲解 ---------- -->
              <div class="pqc-report-section">
                <h4 class="pqc-section-title">📖 详细讲解</h4>
                <div class="pqc-analysis-content" v-html="renderMixedHtml(evaluationReport.analysis)" />
              </div>

              <!-- ---------- 分步评测要点 ---------- -->
              <div class="pqc-report-section">
                <h4 class="pqc-section-title">🔍 分步评测要点</h4>
                <ul class="pqc-report-highlights">
                  <li
                    v-for="(item, hi) in evaluationReport.highlights"
                    :key="hi"
                    :class="['pqc-hl-item', item.startsWith('✅') ? 'hl-good' : item.startsWith('⚠️') ? 'hl-warn' : 'hl-tip']"
                  >
                    {{ item }}
                  </li>
                </ul>
              </div>

              <!-- ---------- 文档溯源引用 ---------- -->
              <div v-if="evaluationReport.sourceRefs.length > 0" class="pqc-report-section">
                <h4 class="pqc-section-title">📚 评测依据 · 文档溯源</h4>
                <div class="pqc-source-grid">
                  <div
                    v-for="ref in evaluationReport.sourceRefs"
                    :key="ref.refId"
                    class="pqc-source-card"
                  >
                    <div class="pqc-source-head">
                      <span class="pqc-source-badge">[{{ ref.refId }}]</span>
                      <span class="pqc-source-doc">{{ ref.documentName }}</span>
                      <span class="pqc-source-page">第 {{ ref.pageNumber }} 页</span>
                    </div>
                    <blockquote class="pqc-source-excerpt">
                      "{{ ref.excerpt }}"
                    </blockquote>
                  </div>
                </div>
              </div>
            </div>
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
                    <p v-for="(line, li) in msg.content.split('\n')" :key="li" class="bubble-line" v-html="renderMarkdownLine(line)" />
                    <!-- 附件标签（仅 user 消息） -->
                    <div v-if="msg.role === 'user' && msg.attachments && msg.attachments.length > 0" class="msg-attachments">
                      <span v-for="att in msg.attachments" :key="att.localId" class="msg-att-tag">
                        <svg viewBox="0 0 20 20" fill="currentColor">
                          <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd" />
                        </svg>
                        {{ att.fileName }}
                      </span>
                    </div>
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
        <!-- 隐藏文件上传 input（问答附件） -->
        <input
          ref="chatFileInputRef"
          type="file"
          class="chat-file-hidden"
          accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.txt,.md"
          @change="handleChatFileChange"
        />

        <!-- 附件卡片区（上传中 / 已上传） -->
        <div v-if="attachments.length > 0" class="attachment-cards">
          <div
            v-for="att in attachments"
            :key="att.localId"
            :class="['attachment-mini-card', att.uploadStatus]"
          >
            <!-- 上传中：旋转 spinner -->
            <span v-if="att.uploadStatus === 'uploading'" class="att-spinner"></span>
            <!-- 已上传：文件图标 -->
            <svg v-else-if="att.uploadStatus === 'done'" class="att-file-icon" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd" />
            </svg>
            <!-- 失败：警告图标 -->
            <svg v-else class="att-file-icon att-error" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd" />
            </svg>

            <span class="att-filename">{{ att.fileName }}</span>
            <span v-if="att.uploadStatus === 'uploading'" class="att-size">{{ formatFileSize(att.fileSize) }}</span>

            <!-- 删除按钮 -->
            <button
              class="att-remove"
              :disabled="att.uploadStatus === 'uploading'"
              @click="removeChatAttachment(att.localId)"
              title="移除附件"
            >
              <svg viewBox="0 0 20 20" fill="currentColor" class="att-remove-icon">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>
        </div>

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

          <!-- 📎 附件上传按钮 -->
          <button class="btn-attach" @click="triggerChatUpload" :disabled="isStreaming || chatUploading" title="上传附件">
            <svg class="icon-svg" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M8 4a3 3 0 00-3 3v4a5 5 0 0010 0V7a1 1 0 112 0v4a7 7 0 11-14 0V7a5 5 0 0110 0v4a3 3 0 11-6 0V7a1 1 0 012 0v4a1 1 0 102 0V7a3 3 0 00-3-3z" clip-rule="evenodd" />
            </svg>
          </button>

          <el-input
            v-model="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 5 }"
            placeholder="输入问题，基于课程资料获取可信回答（Ctrl+Enter 发送）..."
            class="chat-textarea"
            :disabled="isStreaming"
            @keydown.enter.exact.prevent="handleSend"
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
    <!-- 右侧：Agent 协作抽屉（自行从 Store 读取状态）  -->
    <!-- ======================================== -->
    <AgentDrawer v-model="drawerOpen" />
  </div>
</template>

<script lang="ts">
// ============================================================
// 简易 Markdown 行内渲染（不引入外部依赖）
// ============================================================
export function renderMarkdownLine(line: string): string {
  let html = line
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 行内代码
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  return html
}
</script>

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

/* 移动端 Agent 抽屉切换按钮（PC 端隐藏） */
.btn-drawer-toggle-mobile {
  display: none;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}

.btn-drawer-toggle-mobile:hover {
  background: var(--accent-bg);
  border-color: var(--accent-border);
}

.mobile-toggle-icon {
  font-size: 18px;
  line-height: 1;
}

/* --- 错题本视图 --- */
.wrongbook-scroll {
  flex: 1;
  overflow: hidden;
}

.wrongbook-inner {
  max-width: 780px;
  margin: 0 auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* ---- 空状态 ---- */
.wrongbook-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 24px;
  text-align: center;
}

.wrongbook-empty-icon {
  width: 72px;
  height: 72px;
  margin-bottom: 18px;
}

.wrongbook-empty-title {
  font-family: var(--heading);
  font-size: 20px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 8px;
}

.wrongbook-empty-desc {
  font-size: 14px;
  color: var(--text);
  max-width: 420px;
  line-height: 1.6;
  margin: 0;
  opacity: 0.6;
}

/* ---- 错题卡片（暗色系列）---- */
.wrongbook-card {
  border: 1px solid var(--border, #2e303a);
  border-radius: 12px;
  background: var(--code-bg, #1f2028);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.wrongbook-card:hover {
  border-color: var(--accent-border, rgba(192, 132, 252, 0.35));
}

.wrongbook-card.expanded {
  border-color: var(--accent-border, rgba(192, 132, 252, 0.55));
  box-shadow: 0 0 0 3px var(--accent-bg, rgba(170, 59, 255, 0.06));
}

/* ---- 折叠行 ---- */
.wb-card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
}

.wb-card-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.wb-chapter-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 6px;
  background: var(--accent-bg, rgba(170, 59, 255, 0.1));
  color: var(--accent, #aa3bff);
  white-space: nowrap;
  flex-shrink: 0;
}

.wb-question-brief {
  font-size: 13.5px;
  color: var(--text-h, #f3f4f6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.wb-card-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.wb-score-pill {
  font-size: 13px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 8px;
  white-space: nowrap;
}

.wb-score-pill.wb-score-high {
  background: rgba(52, 211, 153, 0.12);
  color: #34d399;
}

.wb-score-pill.wb-score-mid {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.wb-score-pill.wb-score-low {
  background: rgba(248, 113, 113, 0.12);
  color: #f87171;
}

.wb-score-pill-lg {
  font-size: 18px;
  padding: 4px 14px;
  border-radius: 10px;
}

.wb-score-sep {
  opacity: 0.45;
  font-weight: 400;
  margin: 0 1px;
}

.wb-time {
  font-size: 11px;
  color: var(--text, #6b6375);
  opacity: 0.55;
  white-space: nowrap;
}

.wb-chevron {
  width: 18px;
  height: 18px;
  color: var(--text, #6b6375);
  opacity: 0.45;
  transition: transform 0.2s;
  flex-shrink: 0;
}

.wb-chevron.open {
  transform: rotate(180deg);
  opacity: 0.7;
}

/* ---- 展开详情 ---- */
.wb-card-detail {
  padding: 4px 18px 18px;
  border-top: 1px solid var(--border, #2e303a);
  display: flex;
  flex-direction: column;
  gap: 16px;
  animation: wb-fade-in 0.2s ease;
}

@keyframes wb-fade-in {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}

.wb-detail-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.wb-detail-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-h, #f3f4f6);
  margin: 0;
}

.wb-detail-content {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-h, #f3f4f6);
  padding: 12px 16px;
  background: var(--bg, #16171d);
  border-radius: 8px;
  border: 1px solid var(--border, #2e303a);
}

/* KaTeX 公式在详情区内的微调 */
.wb-detail-content :deep(.katex-display) {
  margin: 10px 0;
}

.wb-detail-content :deep(.katex) {
  font-size: 1.05em;
}

.wb-detail-content :deep(.katex-error) {
  color: #fca5a5 !important;
  border-bottom-color: #fca5a5;
}

.wb-detail-score-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.wb-detail-score-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text, #9ca3af);
}

.wb-detail-highlights {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.wb-detail-highlights .pqc-hl-item {
  font-size: 13px;
  line-height: 1.5;
  padding: 6px 12px;
  border-radius: 6px;
}

.wb-detail-highlights .pqc-hl-item.hl-good {
  background: rgba(52, 211, 153, 0.08);
  color: #34d399;
}

.wb-detail-highlights .pqc-hl-item.hl-warn {
  background: rgba(245, 158, 11, 0.08);
  color: #f59e0b;
}

.wb-detail-highlights .pqc-hl-item.hl-tip {
  background: rgba(96, 165, 250, 0.08);
  color: #93c5fd;
}

.wb-detail-actions {
  display: flex;
  gap: 8px;
  padding-top: 4px;
}

/* 深色模式 */
@media (prefers-color-scheme: dark) {
  .wrongbook-card {
    background: var(--code-bg, #1f2028);
    border-color: var(--border, #2e303a);
  }

  .wrongbook-card.expanded {
    border-color: rgba(192, 132, 252, 0.45);
  }

  .wb-detail-content {
    background: var(--bg, #16171d);
    border-color: var(--border, #2e303a);
  }

  .wrongbook-empty-icon [stroke],
  .wrongbook-empty-icon [fill] {
    /* SVG 继承 CSS 变量 */
  }
}

/* 移动端 */
@media (max-width: 768px) {
  .wrongbook-inner {
    max-width: 100%;
    padding: 14px 12px;
    gap: 8px;
  }

  .wb-card-row {
    padding: 12px 14px;
    gap: 10px;
    flex-wrap: wrap;
  }

  .wb-card-left {
    flex: 2;
  }

  .wb-card-right {
    gap: 8px;
  }

  .wb-question-brief {
    font-size: 12.5px;
  }

  .wb-score-pill {
    font-size: 11px;
    padding: 2px 8px;
  }

  .wb-card-detail {
    padding: 4px 14px 16px;
    gap: 12px;
  }

  .wb-detail-content {
    font-size: 13px;
    padding: 10px 12px;
  }

  .wrongbook-empty {
    padding: 40px 16px;
  }

  .wrongbook-empty-title {
    font-size: 18px;
  }

  .wrongbook-empty-desc {
    font-size: 13px;
    max-width: 100%;
  }
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

/* --- 专项训练 — 答题阶段 --- */
.practice-session {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.practice-session-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 12px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
  flex-shrink: 0;
}

.practice-session-tag {
  font-size: 13px;
  color: var(--accent);
  font-weight: 600;
  padding: 4px 12px;
  background: var(--accent-bg);
  border-radius: 6px;
}

/* 答题主体：flex 列布局，编辑器 / 提交按钮 / 评测报告自然流式排布 */
.practice-session-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow-y: auto;
  padding-bottom: 24px;
}

.pqc-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}

.pqc-num {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-h);
}

.pqc-type {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 4px;
  background: var(--code-bg);
  color: var(--text);
}

.pqc-prompt {
  font-size: 15px;
  line-height: 1.7;
  color: var(--text-h);
  margin: 0;
  padding: 14px 18px;
  background: var(--code-bg);
  border-radius: 10px;
  border-left: 3px solid var(--accent);
  flex-shrink: 0;
}


/* ---- 提交按钮（流式排布，不脱离文档流）---- */

.pqc-submit-area {
  display: flex;
  justify-content: center;
  flex-shrink: 0;
}

/* ---- 评测报告（流式排布，无绝对定位 / 负 margin）---- */

.pqc-report {
  padding: 24px 28px;
  border-radius: 14px;
  background: var(--code-bg, #f4f3ec);
  border: 1px solid var(--accent-border, rgba(170, 59, 255, 0.3));
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* ---- 得分仪表区 ---- */

.pqc-report-hero {
  display: flex;
  align-items: center;
  gap: 28px;
}

.pqc-score-gauge {
  flex-shrink: 0;
}

.pqc-gauge-svg {
  width: 120px;
  height: 120px;
  display: block;
}

.pqc-gauge-arc {
  transition: stroke-dasharray 0.8s ease;
}

.pqc-gauge-score {
  font-size: 28px;
  font-weight: 800;
  fill: var(--text-h, #08060d);
}

.pqc-gauge-label {
  font-size: 12px;
  fill: var(--text, #6b6375);
  opacity: 0.7;
}

.pqc-score-meta {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.pqc-grade-badge {
  display: inline-flex;
  align-self: flex-start;
  font-size: 18px;
  font-weight: 700;
  padding: 6px 18px;
  border-radius: 10px;
}

.pqc-grade-badge.grade-high {
  background: rgba(52, 211, 153, 0.12);
  color: #34d399;
}

.pqc-grade-badge.grade-mid {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.pqc-grade-badge.grade-low {
  background: rgba(248, 113, 113, 0.12);
  color: #f87171;
}

/* ---- 置信度 ---- */

.pqc-confidence {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pqc-conf-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text, #6b6375);
  white-space: nowrap;
}

.pqc-conf-bar-track {
  flex: 1;
  max-width: 140px;
  height: 6px;
  border-radius: 3px;
  background: var(--border, #e5e4e7);
  overflow: hidden;
}

.pqc-conf-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--accent, #aa3bff);
  transition: width 0.6s ease;
}

.pqc-conf-pct {
  font-size: 14px;
  font-weight: 700;
  color: var(--accent, #aa3bff);
  font-family: var(--mono);
}

/* ---- 报告分区 ---- */

.pqc-report-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pqc-section-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-h, #08060d);
  margin: 0;
}

/* ---- Agent 分步反馈 ---- */

.pqc-agent-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pqc-agent-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 9px;
  background: var(--bg, #fff);
  border: 1px solid var(--border, #e5e4e7);
  font-size: 13px;
  line-height: 1.5;
  transition: border-color 0.2s;
}

.pqc-agent-chip.succeeded {
  border-left: 3px solid #34d399;
}

.pqc-agent-chip.running {
  border-left: 3px solid var(--accent, #aa3bff);
}

.pqc-agent-chip.failed {
  border-left: 3px solid #f87171;
}

.pqc-agent-chip.idle {
  border-left: 3px solid var(--border, #e5e4e7);
  opacity: 0.55;
}

.pqc-agent-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pqc-agent-dot.succeeded { background: #34d399; }
.pqc-agent-dot.running { background: var(--accent, #aa3bff); animation: pulse 1.2s infinite; }
.pqc-agent-dot.failed { background: #f87171; }
.pqc-agent-dot.idle { background: var(--border, #e5e4e7); }

.pqc-agent-role {
  font-weight: 700;
  color: var(--text-h, #08060d);
  white-space: nowrap;
  flex-shrink: 0;
}

.pqc-agent-summary {
  color: var(--text, #6b6375);
  flex: 1;
  min-width: 0;
}

.pqc-agent-dur {
  font-size: 11px;
  color: var(--text, #6b6375);
  opacity: 0.5;
  font-family: var(--mono);
  flex-shrink: 0;
}

/* ---- 详细讲解文本 ---- */

.pqc-analysis-content {
  font-size: 14.5px;
  line-height: 1.85;
  color: var(--text-h, #08060d);
  padding: 14px 18px;
  background: var(--bg, #fff);
  border-radius: 10px;
  border: 1px solid var(--border, #e5e4e7);
}

.pqc-analysis-content :deep(.katex-display) {
  margin: 10px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.pqc-analysis-content :deep(.katex) {
  font-size: 1.05em;
}

.pqc-analysis-content :deep(.katex-error) {
  color: #dc2626 !important;
  border-bottom: 1px dashed #dc2626;
}

.pqc-report-highlights {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pqc-hl-item {
  font-size: 13px;
  line-height: 1.5;
  padding: 6px 12px;
  border-radius: 6px;
}

.pqc-hl-item.hl-good {
  background: rgba(34, 197, 94, 0.08);
  color: #16a34a;
}

.pqc-hl-item.hl-warn {
  background: rgba(245, 158, 11, 0.08);
  color: #d97706;
}

.pqc-hl-item.hl-tip {
  background: rgba(59, 130, 246, 0.08);
  color: #2563eb;
}

/* ---- 文档溯源引用卡片 ---- */

.pqc-source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.pqc-source-card {
  padding: 14px 16px;
  border: 1px solid var(--border, #e5e4e7);
  border-radius: 10px;
  background: var(--bg, #fff);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: border-color 0.2s;
}

.pqc-source-card:hover {
  border-color: var(--accent-border, rgba(170, 59, 255, 0.4));
}

.pqc-source-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.pqc-source-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 22px;
  padding: 0 6px;
  border-radius: 5px;
  background: var(--accent, #aa3bff);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  flex-shrink: 0;
}

.pqc-source-doc {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-h, #08060d);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.pqc-source-page {
  font-size: 11px;
  color: var(--accent, #aa3bff);
  font-weight: 600;
  flex-shrink: 0;
}

.pqc-source-excerpt {
  margin: 0;
  padding: 10px 12px;
  background: var(--code-bg, #f4f3ec);
  border-left: 3px solid var(--accent-border, rgba(170, 59, 255, 0.4));
  border-radius: 4px;
  font-size: 12.5px;
  color: var(--text, #6b6375);
  line-height: 1.6;
  font-style: italic;
}

/* 答题区深色模式 */
@media (prefers-color-scheme: dark) {
  .pqc-prompt {
    background: var(--code-bg, #1f2028);
  }

  .pqc-report {
    background: var(--code-bg, #1f2028);
    border-color: var(--accent-border, rgba(192, 132, 252, 0.4));
  }

  .pqc-gauge-score {
    fill: var(--text-h, #f3f4f6);
  }

  .pqc-gauge-label {
    fill: var(--text, #9ca3af);
  }

  .pqc-section-title {
    color: var(--text-h, #f3f4f6);
  }

  .pqc-agent-chip {
    background: var(--bg, #16171d);
    border-color: var(--border, #2e303a);
  }

  .pqc-agent-role {
    color: var(--text-h, #f3f4f6);
  }

  .pqc-agent-summary {
    color: var(--text, #9ca3af);
  }

  .pqc-analysis-content {
    background: var(--bg, #16171d);
    border-color: var(--border, #2e303a);
    color: var(--text-h, #f3f4f6);
  }

  .pqc-analysis-content :deep(.katex-error) {
    color: #fca5a5 !important;
    border-bottom-color: #fca5a5;
  }

  .pqc-hl-item.hl-good {
    background: rgba(34, 197, 94, 0.1);
    color: #4ade80;
  }

  .pqc-hl-item.hl-warn {
    background: rgba(245, 158, 11, 0.1);
    color: #fbbf24;
  }

  .pqc-hl-item.hl-tip {
    background: rgba(96, 165, 250, 0.1);
    color: #93c5fd;
  }

  .pqc-source-card {
    background: var(--bg, #16171d);
    border-color: var(--border, #2e303a);
  }

  .pqc-source-doc {
    color: var(--text-h, #f3f4f6);
  }

  .pqc-source-excerpt {
    background: var(--code-bg, #1f2028);
    color: var(--text, #9ca3af);
  }

}

/* 答题区响应式：中等屏幕 → 双栏变堆叠 */
@media (max-width: 1024px) {
  .practice-session-header {
    flex-wrap: wrap;
    gap: 8px;
  }

  .pqc-prompt {
    font-size: 14px;
    padding: 12px 14px;
  }

  /* 评测报告 */
  .pqc-report {
    padding: 18px 20px;
    gap: 18px;
  }

  .pqc-report-hero {
    gap: 18px;
  }

  .pqc-source-grid {
    grid-template-columns: 1fr;
  }
}

/* 答题区响应式：手机端 → 进一步压缩间距 */
@media (max-width: 768px) {
  /* 评测报告移动端 */
  .pqc-report {
    padding: 14px 16px;
    gap: 14px;
  }

  .pqc-report-hero {
    gap: 14px;
  }

  .pqc-gauge-svg {
    width: 90px;
    height: 90px;
  }

  .pqc-gauge-score {
    font-size: 22px;
  }

  .pqc-grade-badge {
    font-size: 15px;
    padding: 4px 14px;
  }

  .pqc-agent-chip {
    padding: 8px 10px;
    gap: 6px;
    font-size: 12px;
  }

  .pqc-agent-role {
    font-size: 11px;
  }

  .pqc-agent-summary {
    font-size: 11px;
  }

  .pqc-analysis-content {
    font-size: 13.5px;
    padding: 10px 14px;
  }

  .pqc-source-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .pqc-source-card {
    padding: 10px 12px;
    gap: 8px;
  }

  .pqc-source-excerpt {
    font-size: 11.5px;
    padding: 8px 10px;
  }
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

/* --- 附件上传按钮（📎 回形针） --- */
.btn-attach {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 44px;
  border: 1px dashed var(--border);
  border-radius: 12px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.btn-attach:hover:not(:disabled) {
  border-color: var(--accent-border);
  color: var(--accent);
  background: var(--accent-bg);
}

.btn-attach:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

/* 隐藏文件 input */
.chat-file-hidden {
  display: none;
}

/* --- 附件迷你卡片区 --- */
.attachment-cards {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  padding: 0 2px;
}

.attachment-mini-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px 6px 10px;
  border-radius: 8px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: var(--code-bg);
  color: var(--text-h);
  max-width: 260px;
  transition: border-color 0.2s;
}

.attachment-mini-card.uploading {
  border-color: var(--accent-border);
  background: var(--accent-bg);
}

.attachment-mini-card.done {
  border-color: rgba(52, 211, 153, 0.3);
  background: rgba(52, 211, 153, 0.06);
}

.attachment-mini-card.failed {
  border-color: rgba(248, 113, 113, 0.3);
  background: rgba(248, 113, 113, 0.06);
}

/* 上传旋转器 */
.att-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--accent-border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: att-spin 0.7s linear infinite;
  flex-shrink: 0;
}

@keyframes att-spin {
  to { transform: rotate(360deg); }
}

/* 文件图标 */
.att-file-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--accent);
  opacity: 0.7;
}

.att-file-icon.att-error {
  color: #f87171;
}

/* 文件名 */
.att-filename {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}

/* 文件大小 */
.att-size {
  font-size: 10px;
  color: var(--text);
  opacity: 0.5;
  flex-shrink: 0;
}

/* 删除按钮 */
.att-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0.4;
  transition: all 0.15s;
}

.att-remove:hover:not(:disabled) {
  opacity: 1;
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

.att-remove:disabled {
  cursor: not-allowed;
}

.att-remove-icon {
  width: 14px;
  height: 14px;
}

/* --- 用户消息气泡内的附件展示 --- */
.bubble.user .msg-attachments {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.2);
}

.bubble.user .msg-att-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bubble.user .msg-att-tag svg {
  width: 12px;
  height: 12px;
  flex-shrink: 0;
  opacity: 0.7;
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

/* ============================================================
   移动端响应式适配（≤768px，覆盖 390px 场景）
   ============================================================ */
@media (max-width: 768px) {
  /* ---- 整体容器：禁止横向溢出 ---- */
  .home-shell {
    overflow-x: hidden;
  }

  /* ---- 左侧边栏：隐藏 ---- */
  .sidebar-left {
    display: none;
  }

  /* ---- 右侧 Agent 抽屉：移动端由 AgentDrawer 组件接管（ElDrawer 浮层）---- */
  .btn-drawer-toggle {
    display: none;
  }

  .btn-drawer-toggle-mobile {
    display: flex;
  }

  /* ---- 中间主问答区：占满全宽 ---- */
  .chat-main {
    width: 100%;
    min-width: 100%;
  }

  /* ---- 聊天头部 ---- */
  .chat-header {
    padding: 10px 14px;
  }

  .chat-title {
    font-size: 14px;
  }

  /* ---- 消息列表 ---- */
  .messages-inner {
    max-width: 100%;
    padding: 14px 12px 8px;
  }

  .msg-body {
    max-width: 82%;
  }

  .bubble {
    font-size: 13.5px;
    padding: 10px 14px;
  }

  /* ---- 引用标签 ---- */
  .citation-chip {
    font-size: 10px;
    padding: 2px 8px;
  }

  /* ---- 底部输入区 ---- */
  .chat-input-area {
    padding: 8px 10px 10px;
  }

  .quick-prompts {
    gap: 6px;
    margin-bottom: 6px;
  }

  .chip {
    font-size: 11px;
    padding: 3px 10px;
  }

  .input-row {
    gap: 8px;
  }

  .btn-import {
    width: 40px;
    height: 40px;
    border-radius: 10px;
  }

  .btn-import-label {
    font-size: 8px;
  }

  .btn-send {
    width: 40px;
    height: 40px;
  }

  .input-hint {
    margin-left: 0;
    margin-top: 4px;
    font-size: 10px;
    text-align: center;
  }

  /* ---- 专项训练占位 ---- */
  .practice-placeholder {
    padding: 24px 16px;
  }

  .practice-config {
    flex-direction: column;
    width: 100%;
  }

  .practice-config :deep(.el-select) {
    width: 100% !important;
  }

  .practice-desc {
    font-size: 13px;
    max-width: 100%;
  }
}
</style>
