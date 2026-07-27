// ============================================================
// StudyAgents — 聊天状态管理（Pinia Store）
//
// 职责：
//   1. 持有对话消息、Agent 工作流状态、文档溯源引用
//   2. 通过 fetchHistory() 从 GET /api/chat/history 获取初始数据
//      （dev 模式下由 vite-plugin-mock 拦截，production 由后端提供）
//   3. 预留 addMessage / appendStreamChunk / finishStream 为
//      SSE 流式输出接口
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ============================================================
// 公开类型（供视图层使用）
// ============================================================

/** 单条聊天消息 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  /** 关联的引用 ID 列表（仅 assistant 消息） */
  citationIds?: string[]
  /** 是否为拒答消息 */
  isRefusal?: boolean
}

/** Agent 工作流步骤 */
export interface AgentStep {
  agentRole: 'coordinator' | 'knowledge' | 'questioner' | 'evaluator'
  agentLabel: string
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  summary: string
  detail?: string
  durationMs?: number
}

/** 文档溯源引用（SourceRef） */
export interface SourceRefDisplay {
  refId: string
  documentName: string
  pageNumber: number
  excerpt: string
}

/** GET /api/chat/history 响应体 */
interface ChatHistoryResponse {
  messages: ChatMessage[]
  agent_steps: AgentStep[]
  source_refs: SourceRefDisplay[]
}

// ============================================================
// Store 定义
// ============================================================

export const useChatStore = defineStore('chat', () => {
  // ==========================================================
  // State
  // ==========================================================

  /** 对话消息列表（初始为空，由 fetchHistory 填充） */
  const messages = ref<ChatMessage[]>([])

  /** 四类 Agent 协同工作流状态 */
  const agentSteps = ref<AgentStep[]>([])

  /** 文档溯源引用卡片 */
  const sourceRefs = ref<SourceRefDisplay[]>([])

  /** 历史数据是否已加载 */
  const loaded = ref(false)

  /** 是否正在加载历史数据 */
  const loading = ref(false)

  /** 是否正在流式生成（供 SSE 阶段使用） */
  const isStreaming = ref(false)

  /** 当前正在流式追加的助手消息 ID */
  const streamingMessageId = ref<string | null>(null)

  // ==========================================================
  // Getters
  // ==========================================================

  /** 最近一条消息 */
  const lastMessage = computed<ChatMessage | null>(() =>
    messages.value.length > 0 ? messages.value[messages.value.length - 1] : null,
  )

  /** 根据 refId 查找引用详情 */
  function getRefById(refId: string): SourceRefDisplay | undefined {
    return sourceRefs.value.find((r) => r.refId === refId)
  }

  // ==========================================================
  // Actions
  // ==========================================================

  /**
   * 从后端获取对话历史初始化 Store。
   *
   * dev 模式下被 vite-plugin-mock（mock/chat.ts）拦截，
   * production 模式下请求真实的 GET /api/chat/history。
   *
   * 幂等：多次调用不会重复加载（loaded === true 时直接返回）。
   */
  async function fetchHistory(): Promise<void> {
    if (loaded.value || loading.value) return
    loading.value = true

    try {
      const response = await fetch('/api/chat/history')
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      const data: ChatHistoryResponse = await response.json()

      messages.value = data.messages
      agentSteps.value = data.agent_steps
      sourceRefs.value = data.source_refs
      loaded.value = true
    } catch (err) {
      console.error('[useChatStore] fetchHistory 失败:', err)
      // 失败时保持空状态，视图层展示空提示
    } finally {
      loading.value = false
    }
  }

  /**
   * 添加单条消息到对话列表。
   *
   * 后续接入 SSE 流式输出时，调用方可以直接 push 完整消息，
   * 也可以通过 appendStreamChunk / finishStream 实现逐 token 追加。
   *
   * @param msg 要添加的消息对象
   */
  function addMessage(msg: ChatMessage): void {
    messages.value.push(msg)
  }

  /**
   * 清空当前对话消息并重新从服务端拉取历史。
   */
  async function resetMessages(): Promise<void> {
    messages.value = []
    agentSteps.value = []
    sourceRefs.value = []
    loaded.value = false
    await fetchHistory()
  }

  /**
   * 预留：追加流式生成文本片段到当前 assistant 消息。
   *
   * SSE 接入时，每次收到 token 调用此方法：
   * - 若 streamingMessageId 为 null，先创建新 assistant 消息占位
   * - 否则追加 token 到对应消息的 content
   *
   * @param token 单个文本片段
   */
  function appendStreamChunk(token: string): void {
    if (streamingMessageId.value === null) {
      const id = `stream-${Date.now()}`
      streamingMessageId.value = id
      isStreaming.value = true
      messages.value.push({
        id,
        role: 'assistant',
        content: token,
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
      })
    } else {
      const msg = messages.value.find((m) => m.id === streamingMessageId.value)
      if (msg) {
        msg.content += token
      }
    }
  }

  /**
   * 预留：结束流式生成，绑定引用并清理流式状态。
   *
   * @param citationIds 最终关联的引用 ID 列表
   */
  function finishStream(citationIds?: string[]): void {
    if (streamingMessageId.value) {
      const msg = messages.value.find((m) => m.id === streamingMessageId.value)
      if (msg && citationIds) {
        msg.citationIds = citationIds
      }
    }
    isStreaming.value = false
    streamingMessageId.value = null
  }

  /**
   * 模拟 SSE 流式打字机效果（纯前端演示）。
   *
   * 在 messages 末尾追加一条空的 assistant 消息，
   * 然后通过 setInterval 逐字追加测试文本，
   * 直到全部输出完毕。
   *
   * 真实 SSE 接入后，替换为 EventSource / fetch 流读取。
   *
   * @returns Promise，流式输出完毕后 resolve
   */
  function simulateStreamingResponse(): Promise<void> {
    return new Promise((resolve) => {
      const testText =
        '您好！这是由纯前端模拟的 SSE 流式打字机效果。' +
        '在未来的真实对接中，这里将替换为浏览器原生的 EventSource 或 Fetch API 接收流数据。' +
        '\n\n' +
        '**关键技术点**：\n' +
        '1. Coordinator Agent 解析用户意图并调度下游 Agent\n' +
        '2. Knowledge Agent 在课程资料库中检索相关文档片段\n' +
        '3. 所有回答均附带 SourceRef 溯源引用，确保可复核\n' +
        '4. 证据不足时主动拒答，不使用模型通识补全课程事实'

      let index = 0
      const timer = setInterval(() => {
        if (index < testText.length) {
          appendStreamChunk(testText[index])
          index++
        } else {
          clearInterval(timer)
          finishStream()
          resolve()
        }
      }, 50)
    })
  }

  // ==========================================================
  // 导出
  // ==========================================================

  return {
    // state
    messages,
    agentSteps,
    sourceRefs,
    loaded,
    loading,
    isStreaming,
    streamingMessageId,
    // getters
    lastMessage,
    getRefById,
    // actions
    fetchHistory,
    addMessage,
    resetMessages,
    appendStreamChunk,
    finishStream,
    simulateStreamingResponse,
  }
})
