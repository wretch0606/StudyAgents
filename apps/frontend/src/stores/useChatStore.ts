// ============================================================
// StudyAgents — 聊天状态管理（Pinia Store）
//
// 职责：
//   1. 持有对话消息、Agent 工作流状态、文档溯源引用
//   2. 通过 fetchHistory() 从 GET /api/sessions 获取会话历史
//   3. 通过 startQa() 调用 POST /api/sessions/{id}/qa 发起问答，
//      再通过 EventSource 连接 GET /api/agent-runs/{run_id}/events
//      接收 SSE 流式输出
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'

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
  /** 关联的附件信息（仅 user 消息，随提问一起发送） */
  attachments?: ChatAttachment[]
}

/** 问答附件（聊天输入框上传，暂存后随用户提问发送） */
export interface ChatAttachment {
  /** 附件临时 ID（本地生成，用于删除操作） */
  localId: string
  /** 服务端返回的文件 URL */
  fileUrl: string
  /** 原始文件名 */
  fileName: string
  /** 文件大小（字节） */
  fileSize: number
  /** 上传状态 */
  uploadStatus: 'uploading' | 'done' | 'failed'
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

/** Agent 实时执行轨迹（当前消息的 Agent 接力过程） */
export interface AgentTrace {
  agentRole: 'coordinator' | 'knowledge' | 'questioner' | 'evaluator'
  agentLabel: string
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  /** 用于 AgentDrawer 卡片展示的摘要文案，随 Agent 状态动态更新 */
  summary: string
  /** 原始动作描述（保留用于调试 / 详情） */
  action: string
  /** 可选详情（与 AgentStep.detail 对齐，历史回放时可展开） */
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

// ============================================================
// 后端 API 响应类型
// ============================================================

interface SessionItem {
  id: string
  title: string | null
  thread_id: string
  created_at: string
  updated_at: string
}

interface MessageItem {
  id: string
  role: string
  content: string
  run_id: string | null
  sequence_no: number
  created_at: string
}

interface SseEvent {
  id: string
  run_id: string
  sequence_no: number
  agent: string
  event_type: string
  status: string
  summary: string
  source_refs: SourceRefDisplay[]
  duration_ms: number | null
}

/** 训练作答提交结果 */
export interface PracticeSubmitResult {
  run_id: string
  event_url: string
}

/** 训练总结（来自 GET /api/practice/sessions/{id}/summary） */
export interface PracticeSummary {
  session_id: string
  grade_info: {
    score: number
    max_score: number
    confidence: number
    explanation: string | null
    source_refs: SourceRefDisplay[]
  } | null
  knowledge_points: Array<{
    knowledge_point_id: string
    knowledge_point_name: string
    mastery: number
    mastery_change: number
  }>
}

// ============================================================
// 常量
// ============================================================

const AGENT_LABEL_MAP: Record<string, string> = {
  coordinator: '🧠 Coordinator',
  knowledge: '📚 Knowledge',
  questioner: '❓ Questioner',
  evaluator: '⚖️ Evaluator',
}

const AGENT_DEFAULT_SUMMARIES: Record<string, string> = {
  coordinator: '等待意图解析…',
  knowledge: '等待检索请求…',
  questioner: '等待出题请求…',
  evaluator: '等待评测请求…',
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

  /** 是否正在流式生成（SSE 连接活跃） */
  const isStreaming = ref(false)

  /** 当前正在流式追加的助手消息 ID */
  const streamingMessageId = ref<string | null>(null)

  /** 待发送的附件列表（上传完成后暂存，随下次用户提问一起发送） */
  const attachments = ref<ChatAttachment[]>([])

  /** 当前消息的 Agent 实时执行轨迹（SSE 流式回复期间逐事件更新） */
  const currentAgentTraces = ref<AgentTrace[]>([])

  /** 当前活跃的会话 ID（用于 QA 和消息追加） */
  const currentSessionId = ref<string | null>(null)

  /** 当前活跃的训练会话 ID（用于提交答案） */
  const currentPracticeSessionId = ref<string | null>(null)

  /** 当前训练题目 ID（来自创建训练响应） */
  const currentPracticeItemId = ref<string | null>(null)

  /** 当前训练题目版本号 */
  const currentPracticeQuestionVersion = ref<string>('1.0')

  /** SSE EventSource 实例（用于中断连接） */
  let activeEventSource: EventSource | null = null

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
  // Actions — 初始化
  // ==========================================================

  /**
   * 从后端获取对话历史初始化 Store。
   *
   * 请求 GET /api/sessions 获取会话列表，再取最近会话的消息。
   * 幂等：多次调用不会重复加载（loaded === true 时直接返回）。
   */
  async function fetchHistory(): Promise<void> {
    if (loaded.value || loading.value) return
    loading.value = true

    try {
      // 1. 获取会话列表
      const sessionsResp = await fetch('/api/sessions')
      if (!sessionsResp.ok) {
        throw new Error(`HTTP ${sessionsResp.status}: ${sessionsResp.statusText}`)
      }
      const sessionsData: { items: SessionItem[] } = await sessionsResp.json()

      if (sessionsData.items.length > 0) {
        const session = sessionsData.items[0]
        currentSessionId.value = session.id

        // 2. 获取最近会话的消息
        const msgsResp = await fetch(`/api/sessions/${session.id}/messages`)
        if (msgsResp.ok) {
          const msgsData: { items: MessageItem[] } = await msgsResp.json()
          messages.value = msgsData.items.map((m) => ({
            id: m.id,
            role: m.role as ChatMessage['role'],
            content: m.content,
            timestamp: m.created_at
              ? new Date(m.created_at).toLocaleTimeString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : '',
          }))
        }
      }

      loaded.value = true
    } catch (err) {
      console.error('[useChatStore] fetchHistory 失败:', err)
      ElMessage.error('对话历史加载失败，请刷新页面重试')
    } finally {
      loading.value = false
    }
  }

  // ==========================================================
  // Actions — 消息操作
  // ==========================================================

  /**
   * 添加单条消息到对话列表。
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
   * 追加流式生成文本片段到当前 assistant 消息。
   *
   * SSE 收到 token 事件时调用此方法：
   * - 若 streamingMessageId 为 null，先创建新 assistant 消息占位
   * - 否则追加 token 到对应消息的 content
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
        timestamp: new Date().toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        }),
      })
    } else {
      const msg = messages.value.find((m) => m.id === streamingMessageId.value)
      if (msg) {
        msg.content += token
      }
    }
  }

  /**
   * 结束流式生成，绑定引用并清理流式状态。
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

  // ==========================================================
  // Actions — SSE 流式问答（真实后端）
  // ==========================================================

  /** 断开当前 SSE 连接 */
  function disconnectSSE(): void {
    if (activeEventSource) {
      activeEventSource.close()
      activeEventSource = null
    }
  }

  /**
   * 发起真实问答：POST /api/sessions/{id}/qa → SSE 流式接收。
   *
   * 流程：
   *   1. 确保存在当前会话（没有则创建）
   *   2. POST /api/sessions/{id}/qa 发起问答，获得 run_id
   *   3. EventSource 连接 GET /api/agent-runs/{run_id}/events
   *   4. 解析 SSE 事件：agent 状态更新 → currentAgentTraces
   *                     token → appendStreamChunk
   *                     source_refs → sourceRefs
   *                     run.completed / run.failed → 收尾
   *
   * @param userInput 用户输入文本
   */
  async function startQa(userInput: string): Promise<void> {
    // 断开上一轮 SSE（如果有）
    disconnectSSE()

    // 初始化 Agent 轨迹
    clearAgentTraces()
    const traces: AgentTrace[] = [
      {
        agentRole: 'coordinator',
        agentLabel: AGENT_LABEL_MAP.coordinator,
        status: 'idle',
        summary: AGENT_DEFAULT_SUMMARIES.coordinator,
        action: AGENT_DEFAULT_SUMMARIES.coordinator,
        durationMs: 0,
      },
      {
        agentRole: 'knowledge',
        agentLabel: AGENT_LABEL_MAP.knowledge,
        status: 'idle',
        summary: AGENT_DEFAULT_SUMMARIES.knowledge,
        action: AGENT_DEFAULT_SUMMARIES.knowledge,
        durationMs: 0,
      },
      {
        agentRole: 'questioner',
        agentLabel: AGENT_LABEL_MAP.questioner,
        status: 'idle',
        summary: AGENT_DEFAULT_SUMMARIES.questioner,
        action: AGENT_DEFAULT_SUMMARIES.questioner,
        durationMs: 0,
      },
      {
        agentRole: 'evaluator',
        agentLabel: AGENT_LABEL_MAP.evaluator,
        status: 'idle',
        summary: AGENT_DEFAULT_SUMMARIES.evaluator,
        action: AGENT_DEFAULT_SUMMARIES.evaluator,
        durationMs: 0,
      },
    ]
    currentAgentTraces.value = [...traces]

    try {
      // 1. 确保有会话
      if (!currentSessionId.value) {
        const createResp = await fetch('/api/sessions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
          body: JSON.stringify({ title: userInput.slice(0, 50) }),
        })
        if (!createResp.ok) {
          throw new Error(`创建会话失败: HTTP ${createResp.status}`)
        }
        const session: SessionItem = await createResp.json()
        currentSessionId.value = session.id
      }

      // 2. 发起 QA
      const qaResp = await fetch(`/api/sessions/${currentSessionId.value}/qa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify({ user_input: userInput, mode: 'qa' }),
      })
      if (!qaResp.ok) {
        throw new Error(`QA 启动失败: HTTP ${qaResp.status}`)
      }
      const qaData: { run_id: string; thread_id: string; trace_id: string } = await qaResp.json()

      // 3. 连接 SSE
      await connectAndStreamSSE(qaData.run_id)
    } catch (err) {
      console.error('[useChatStore] startQa 失败:', err)
      ElMessage.error('问答请求失败，请重试')
      finishStream()
    }
  }

  /**
   * 连接 SSE 端点并处理事件流。
   */
  function connectAndStreamSSE(runId: string): Promise<void> {
    return new Promise((resolve) => {
      const eventSource = new EventSource(`/api/agent-runs/${runId}/events`)
      activeEventSource = eventSource

      eventSource.onmessage = (event) => {
        try {
          const evt: SseEvent = JSON.parse(event.data)

          // 更新 Agent 轨迹
          updateAgentTraceFromSSE(evt)

          // token 事件 → 追加流式文本
          if (evt.event_type === 'token' && evt.summary) {
            appendStreamChunk(evt.summary)
          }

          // source_refs 更新
          if (evt.source_refs && evt.source_refs.length > 0) {
            sourceRefs.value = evt.source_refs
          }

          // 终止事件
          if (evt.event_type === 'run.completed' || evt.event_type === 'run.failed') {
            // 归档 agentSteps
            agentSteps.value = currentAgentTraces.value.map((t) => ({
              agentRole: t.agentRole,
              agentLabel: t.agentLabel,
              status: t.status as 'idle' | 'running' | 'succeeded' | 'failed',
              summary: t.summary,
              detail: t.action,
              durationMs: t.durationMs,
            }))
            finishStream()
            eventSource.close()
            activeEventSource = null
            resolve()
          }
        } catch {
          // 非 JSON 消息（如心跳注释），忽略
        }
      }

      eventSource.onerror = () => {
        // SSE 连接异常 — 可能是 run 已完成但事件丢失
        // 回退：从 /api/sessions/{id}/messages 拉取最新消息
        eventSource.close()
        activeEventSource = null
        pullLatestMessages().finally(() => {
          finishStream()
          resolve()
        })
      }
    })
  }

  /**
   * 根据 SSE 事件更新对应 Agent 的轨迹状态。
   */
  function updateAgentTraceFromSSE(evt: SseEvent): void {
    const traces = currentAgentTraces.value
    const agentRole = evt.agent as AgentTrace['agentRole']
    const trace = traces.find((t) => t.agentRole === agentRole)
    if (!trace) return

    trace.status = evt.status as AgentTrace['status']
    trace.summary = evt.summary || trace.summary
    trace.action = evt.summary || trace.action
    if (evt.duration_ms != null) {
      trace.durationMs = evt.duration_ms
    }
    currentAgentTraces.value = [...traces]
  }

  /**
   * 回退方案：SSE 异常时从 REST API 拉取最新消息。
   */
  async function pullLatestMessages(): Promise<void> {
    if (!currentSessionId.value) return
    try {
      const resp = await fetch(`/api/sessions/${currentSessionId.value}/messages`)
      if (!resp.ok) return
      const data: { items: MessageItem[] } = await resp.json()

      // 替换或追加消息（以 sequence_no 去重）
      const existingIds = new Set(messages.value.map((m) => m.id))
      for (const m of data.items) {
        if (!existingIds.has(m.id)) {
          messages.value.push({
            id: m.id,
            role: m.role as ChatMessage['role'],
            content: m.content,
            timestamp: m.created_at
              ? new Date(m.created_at).toLocaleTimeString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : '',
          })
        }
      }
    } catch (err) {
      console.error('[useChatStore] pullLatestMessages 失败:', err)
    }
  }

  // ==========================================================
  // Actions — 附件管理
  // ==========================================================

  function addAttachment(att: ChatAttachment): void {
    attachments.value.push(att)
  }

  function updateAttachment(localId: string, updates: Partial<ChatAttachment>): void {
    const idx = attachments.value.findIndex((a) => a.localId === localId)
    if (idx !== -1) {
      attachments.value[idx] = { ...attachments.value[idx], ...updates }
    }
  }

  function removeAttachment(localId: string): void {
    attachments.value = attachments.value.filter((a) => a.localId !== localId)
  }

  function clearAttachments(): void {
    attachments.value = []
  }

  // ==========================================================
  // Actions — Agent 轨迹
  // ==========================================================

  function clearAgentTraces(): void {
    currentAgentTraces.value = []
  }

  // ==========================================================
  // Actions — 专项训练（真实后端）
  // ==========================================================

  /**
   * 创建专项训练会话并获取首题。
   *
   * 调用 POST /api/practice/sessions，后端同步出题。
   *
   * @param chapterIds 章节 ID 列表
   * @param questionTypes 题型列表
   * @param difficulty 难度
   * @param count 出题数量
   * @returns 训练会话信息（含首题）
   */
  async function createPracticeSession(params: {
    chapterIds: string[]
    questionTypes: string[]
    difficulty: string
    count: number
  }): Promise<{
    sessionId: string
    itemId: string
    questionVersion: string
    questionText: string
    runId: string | null
    eventUrl: string | null
  } | null> {
    clearAgentTraces()

    try {
      const resp = await fetch('/api/practice/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrfToken() },
        body: JSON.stringify({
          chapter_ids: params.chapterIds,
          question_types: params.questionTypes,
          difficulty: params.difficulty,
          target_count: params.count,
        }),
      })
      if (!resp.ok) {
        throw new Error(`创建训练失败: HTTP ${resp.status}`)
      }
      const data = await resp.json()

      currentPracticeSessionId.value = data.session?.id ?? null
      currentPracticeItemId.value = data.session?.current_item?.item_id ?? null
      currentPracticeQuestionVersion.value = data.session?.current_item?.question_version ?? '1.0'

      // 从训练会话中提取题目信息
      const currentItem = data.session?.current_item
      const questionText = currentItem?.question?.text ?? currentItem?.question?.content ?? ''

      return {
        sessionId: data.session?.id ?? '',
        itemId: currentPracticeItemId.value ?? '',
        questionVersion: currentPracticeQuestionVersion.value,
        questionText,
        runId: data.run_id ?? null,
        eventUrl: data.event_url ?? null,
      }
    } catch (err) {
      console.error('[useChatStore] createPracticeSession 失败:', err)
      ElMessage.error('创建训练失败，请重试')
      return null
    }
  }

  /**
   * 提交训练答案并获取评测结果。
   *
   * 调用 POST /api/practice/sessions/{sessionId}/answers，
   * 然后通过 SSE 连接获取评测事件，最后拉取总结。
   *
   * @param answerText 用户作答的原始文本
   * @param isUncertain 是否标记为不确定
   */
  async function submitPracticeAnswer(answerText: string, isUncertain = false): Promise<{
    score: number
    total: number
    analysis: string
    highlights: string[]
    confidence: number
    sourceRefs: SourceRefDisplay[]
  } | null> {
    if (!currentPracticeSessionId.value || !currentPracticeItemId.value) {
      ElMessage.error('训练会话状态异常，请重新开始训练')
      return null
    }

    // 为当前 Evaluator 标记为运行中
    const traces = currentAgentTraces.value
    const evaluator = traces.find((t) => t.agentRole === 'evaluator')
    if (evaluator) {
      evaluator.status = 'running'
      evaluator.summary = '正在分析作答内容，比对课程知识点，评估回答质量…'
      evaluator.action = '正在分析作答内容，比对课程知识点，评估回答质量…'
      currentAgentTraces.value = [...traces]
    }
    isStreaming.value = true

    try {
      // 1. 提交答案
      const idempotencyKey = `${currentPracticeSessionId.value}-${currentPracticeItemId.value}-${Date.now()}`
      const resp = await fetch(
        `/api/practice/sessions/${currentPracticeSessionId.value}/answers`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCsrfToken(),
            'X-Idempotency-Key': idempotencyKey,
          },
          body: JSON.stringify({
            item_id: currentPracticeItemId.value,
            question_version: currentPracticeQuestionVersion.value,
            raw_text: answerText,
            is_uncertain: isUncertain,
          }),
        },
      )
      if (!resp.ok) {
        throw new Error(`提交答案失败: HTTP ${resp.status}`)
      }
      const submitResult: PracticeSubmitResult = await resp.json()

      // 2. 连接 SSE 接收评测事件
      if (submitResult.event_url) {
        await connectAndStreamSSE(submitResult.run_id)
      }

      // 3. 拉取训练总结
      const summaryResp = await fetch(
        `/api/practice/sessions/${currentPracticeSessionId.value}/summary`,
      )
      if (!summaryResp.ok) {
        throw new Error(`获取总结失败: HTTP ${summaryResp.status}`)
      }
      const summary: PracticeSummary = await summaryResp.json()

      // 4. 整理返回到视图层
      const gradeInfo = summary.grade_info
      if (gradeInfo) {
        // 更新 sourceRefs
        if (gradeInfo.source_refs && gradeInfo.source_refs.length > 0) {
          sourceRefs.value = gradeInfo.source_refs
        }

        // 标记 Evaluator 完成
        if (evaluator) {
          evaluator.status = 'succeeded'
          evaluator.summary = `评测完成：得分 ${gradeInfo.score}/${gradeInfo.max_score}`
          evaluator.action = evaluator.summary
          currentAgentTraces.value = [...currentAgentTraces.value]
        }

        // 归档 agentSteps
        agentSteps.value = currentAgentTraces.value.map((t) => ({
          agentRole: t.agentRole,
          agentLabel: t.agentLabel,
          status: t.status as 'idle' | 'running' | 'succeeded' | 'failed',
          summary: t.summary,
          detail: t.action,
          durationMs: t.durationMs,
        }))

        return {
          score: gradeInfo.score,
          total: gradeInfo.max_score,
          analysis: gradeInfo.explanation ?? '',
          highlights: summary.knowledge_points.map(
            (kp) =>
              `${kp.mastery_change >= 0 ? '✅' : '⚠️'} ${kp.knowledge_point_name}: ${Math.round(kp.mastery * 100)}%`,
          ),
          confidence: gradeInfo.confidence,
          sourceRefs: gradeInfo.source_refs ?? [],
        }
      }

      return null
    } catch (err) {
      console.error('[useChatStore] submitPracticeAnswer 失败:', err)
      ElMessage.error('提交答案失败，请重试')
      return null
    } finally {
      isStreaming.value = false
    }
  }

  // ==========================================================
  // 内部工具
  // ==========================================================

  /** 从 cookie 或 localStorage 获取 CSRF Token */
  function getCsrfToken(): string {
    // 优先从 localStorage 读取（useUserStore 在登录时写入）
    return localStorage.getItem('authToken') || ''
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
    attachments,
    currentAgentTraces,
    currentSessionId,
    currentPracticeSessionId,
    // getters
    lastMessage,
    getRefById,
    // actions
    fetchHistory,
    addMessage,
    resetMessages,
    appendStreamChunk,
    finishStream,
    startQa,
    createPracticeSession,
    submitPracticeAnswer,
    addAttachment,
    updateAttachment,
    removeAttachment,
    clearAttachments,
    clearAgentTraces,
  }
})
