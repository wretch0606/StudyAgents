// ============================================================
// StudyAgents — 聊天状态管理（Pinia Store）
//
// 职责：
//   1. 持有对话消息、Agent 工作流状态、文档溯源引用
//   2. 通过 fetchHistory() 从 GET /api/chat/history 获取初始数据
//      （dev 模式下由本地 Vite Mock 插件拦截，production 由后端提供）
//   3. 预留 addMessage / appendStreamChunk / finishStream 为
//      SSE 流式输出接口
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

  /** 待发送的附件列表（上传完成后暂存，随下次用户提问一起发送） */
  const attachments = ref<ChatAttachment[]>([])

  /** 当前消息的 Agent 实时执行轨迹（流式回复期间逐阶段更新） */
  const currentAgentTraces = ref<AgentTrace[]>([])

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
   * dev 模式下被本地 vite-plugin-mock.ts 拦截，
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
      ElMessage.error('对话历史加载失败，请刷新页面重试')
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
   * 模拟 SSE 流式打字机效果 + 多 Agent 协同轨迹（纯前端演示）。
   *
   * 1. 在 messages 末尾追加一条空的 assistant 消息，
   *    然后通过 setInterval 逐字追加测试文本，直到全部输出完毕。
   * 2. 同时通过 setTimeout 模拟四类 Agent 的接力过程：
   *    Coordinator（意图解析）→ Knowledge（资料检索）→ Evaluator（证据验证）
   *    各阶段状态更新写入 currentAgentTraces，驱动 AgentDrawer 时间轴渲染。
   *
   * 真实 SSE 接入后，替换为 EventSource / fetch 流读取。
   *
   * @returns Promise，流式输出完毕后 resolve
   */
  function simulateStreamingResponse(): Promise<void> {
    return new Promise((resolve) => {
      // ========================================================
      // 阶段 0：清理上轮轨迹 + 初始化 Agent 执行轨迹
      // ========================================================

      // 清除上一轮残留的 Agent 轨迹，避免新旧数据混杂
      clearAgentTraces()

      const traces: AgentTrace[] = [
        {
          agentRole: 'coordinator',
          agentLabel: '🧠 Coordinator',
          status: 'running',
          summary: '正在解析用户意图，拆解为可检索的知识点…',
          action: '解析用户意图，拆解为可检索的知识点…',
          durationMs: 0,
        },
        {
          agentRole: 'knowledge',
          agentLabel: '📚 Knowledge',
          status: 'idle',
          summary: '等待检索请求',
          action: '等待检索请求',
          durationMs: 0,
        },
        {
          agentRole: 'questioner',
          agentLabel: '❓ Questioner',
          status: 'idle',
          summary: '当前为自由问答模式，出题 Agent 处于待命状态',
          action: '当前为自由问答模式，出题 Agent 处于待命状态',
          durationMs: 0,
        },
        {
          agentRole: 'evaluator',
          agentLabel: '⚖️ Evaluator',
          status: 'idle',
          summary: '等待验证任务',
          action: '等待验证任务',
          durationMs: 0,
        },
      ]
      currentAgentTraces.value = [...traces]

      // 提前标记 isStreaming = true，确保 AgentDrawer 的 hasLiveTraces
      // 在轨迹初始化后立即为 true，不再等待首个 appendStreamChunk（50ms 延迟）
      isStreaming.value = true

      // ========================================================
      // 阶段 1：t ≈ 600ms — Coordinator 完成 → Knowledge 启动
      // ========================================================
      setTimeout(() => {
        traces[0].status = 'succeeded'
        traces[0].summary = '意图解析完成：识别为计算机网络课程问题，拆解出 TCP 拥塞控制、滑动窗口、慢启动 3 个子主题'
        traces[0].action = '意图解析完成：识别为计算机网络课程问题，拆解出 TCP 拥塞控制、滑动窗口、慢启动 3 个子主题'
        traces[0].durationMs = 600
        traces[1].status = 'running'
        traces[1].summary = '正在课程资料库中检索相关文档片段…'
        traces[1].action = '在课程资料库中检索相关文档片段…'
        currentAgentTraces.value = [...traces]
      }, 600)

      // ========================================================
      // 阶段 2：t ≈ 1600ms — Knowledge 完成 → Evaluator 启动
      // ========================================================
      setTimeout(() => {
        traces[1].status = 'succeeded'
        traces[1].summary = '检索完成：命中 3 个相关文档片段（TCP 拥塞控制 §3.2、滑动窗口 §3.3、慢启动算法 §3.1）'
        traces[1].action = '检索完成：命中 3 个相关文档片段（TCP 拥塞控制 §3.2、滑动窗口 §3.3、慢启动算法 §3.1）'
        traces[1].durationMs = 1000
        // Questioner 始终 idle（自由问答模式不激活）
        traces[2].status = 'idle'
        traces[2].summary = '当前为自由问答模式，出题 Agent 处于待命状态'
        traces[2].action = '当前为自由问答模式，出题 Agent 处于待命状态'
        traces[2].durationMs = 0
        traces[3].status = 'running'
        traces[3].summary = '正在验证检索结果的相关性与证据充分性…'
        traces[3].action = '验证检索结果的相关性与证据充分性…'
        currentAgentTraces.value = [...traces]
      }, 1600)

      // ========================================================
      // 阶段 3：t ≈ 2400ms — Evaluator 完成，全部 Agent 就绪
      // ========================================================
      setTimeout(() => {
        traces[3].status = 'succeeded'
        traces[3].summary = '验证通过：3 个片段均与用户问题高度相关，证据充分可作答'
        traces[3].action = '验证通过：3 个片段均与用户问题高度相关，证据充分可作答'
        traces[3].durationMs = 800
        currentAgentTraces.value = [...traces]
      }, 2400)

      // ========================================================
      // 文本流式输出（与 Agent 轨迹并行，立即开始）
      // ========================================================
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

  /**
   * 添加附件到待发送列表（上传中状态）。
   *
   * @param att 附件信息
   */
  function addAttachment(att: ChatAttachment): void {
    attachments.value.push(att)
  }

  /**
   * 更新附件状态（上传完成后 → done / failed）。
   *
   * @param localId 附件本地 ID
   * @param updates 要更新的字段
   */
  function updateAttachment(
    localId: string,
    updates: Partial<ChatAttachment>,
  ): void {
    const idx = attachments.value.findIndex((a) => a.localId === localId)
    if (idx !== -1) {
      attachments.value[idx] = { ...attachments.value[idx], ...updates }
    }
  }

  /**
   * 从待发送列表中移除指定附件。
   *
   * @param localId 附件本地 ID
   */
  function removeAttachment(localId: string): void {
    attachments.value = attachments.value.filter((a) => a.localId !== localId)
  }

  /**
   * 清空所有待发送附件。
   */
  function clearAttachments(): void {
    attachments.value = []
  }

  /**
   * 清空当前 Agent 实时执行轨迹。
   *
   * 在开始新一轮流式回复前调用，避免残留上一轮的轨迹数据。
   */
  function clearAgentTraces(): void {
    currentAgentTraces.value = []
  }

  /**
   * 专项训练模式 — 初始化 Agent 执行轨迹。
   *
   * 训练生命周期：
   *   Coordinator → Knowledge → Questioner → (用户作答) → Evaluator
   *
   * 调用时机：用户点击「开始训练」后立即调用。
   * 此时前三个 Agent 已完成（生成了题目），Evaluator 处于待命状态。
   */
  function initPracticeTraces(): void {
    clearAgentTraces()

    const traces: AgentTrace[] = [
      {
        agentRole: 'coordinator',
        agentLabel: '🧠 Coordinator',
        status: 'succeeded',
        summary: '意图解析完成：识别为专项训练请求，已调度 Knowledge Agent 检索课程资料',
        action: '意图解析完成：识别为专项训练请求，已调度 Knowledge Agent 检索课程资料',
        durationMs: 420,
      },
      {
        agentRole: 'knowledge',
        agentLabel: '📚 Knowledge',
        status: 'succeeded',
        summary: '检索完成：已从课程资料库提取 3 个相关知识点，交由 Questioner 生成题目',
        action: '检索完成：已从课程资料库提取 3 个相关知识点，交由 Questioner 生成题目',
        durationMs: 850,
      },
      {
        agentRole: 'questioner',
        agentLabel: '❓ Questioner',
        status: 'succeeded',
        summary: '题目生成完毕：已基于检索材料生成 1 道综合问答题，等候用户作答',
        action: '题目生成完毕：已基于检索材料生成 1 道综合问答题，等候用户作答',
        durationMs: 610,
      },
      {
        agentRole: 'evaluator',
        agentLabel: '⚖️ Evaluator',
        status: 'idle',
        summary: '待命中：等待用户提交答案后进行评测与打分',
        action: '待命中：等待用户提交答案后进行评测与打分',
        durationMs: 0,
      },
    ]

    currentAgentTraces.value = [...traces]
    // 训练模式下不设置 isStreaming（不触发消息流式输出动画）
  }

  /**
   * 专项训练模式 — 提交答案触发 Evaluator 评测。
   *
   * 时序：
   *   1. 立即将 Evaluator 设为 running（摘要：「正在分析作答…」）
   *   2. ~1.5s 后将 Evaluator 设为 succeeded（摘要含得分 + 解析）
   *   3. 将成功的 traces 归档到 agentSteps（供历史回放）
   *
   * @returns Promise，评测完成后 resolve 评测报告对象
   */
  function submitAnswerForEvaluation(): Promise<{
    score: number
    total: number
    analysis: string
    highlights: string[]
    /** 评测置信度 (0–1)，表示 Evaluator 对评分的把握 */
    confidence: number
    /** 评测引用的文档溯源卡片 */
    sourceRefs: SourceRefDisplay[]
  }> {
    return new Promise((resolve) => {
      const traces = currentAgentTraces.value.length > 0
        ? [...currentAgentTraces.value]
        : []

      // 确保 Evaluator 存在
      const evaluator = traces.find((t) => t.agentRole === 'evaluator')
      if (!evaluator) return

      // ---- 阶段 1：立即切换 Evaluator → running ----
      evaluator.status = 'running'
      evaluator.summary = '正在分析作答内容，比对课程知识点，评估回答质量…'
      evaluator.action = '正在分析作答内容，比对课程知识点，评估回答质量…'
      evaluator.durationMs = 0
      currentAgentTraces.value = [...traces]
      isStreaming.value = true

      // ---- 阶段 2：~1.5s 后 Evaluator → succeeded ----
      setTimeout(() => {
        evaluator.status = 'succeeded'
        evaluator.summary = '评测完成：得分 85/100，回答涵盖了核心概念，公式推导存在一处符号错误'
        evaluator.action = '评测完成：得分 85/100，回答涵盖了核心概念，公式推导存在一处符号错误'
        evaluator.durationMs = 1500
        currentAgentTraces.value = [...traces]

        // 归档到 agentSteps（供历史回放）
        agentSteps.value = traces.map((t) => ({
          agentRole: t.agentRole,
          agentLabel: t.agentLabel,
          status: t.status as 'idle' | 'running' | 'succeeded' | 'failed',
          summary: t.summary,
          detail: t.action,
          durationMs: t.durationMs,
        }))

        isStreaming.value = false

        // 填充 Mock 溯源引用（供评测报告展示）
        sourceRefs.value = [
          {
            refId: 'S1',
            documentName: '计算机网络·第3章 运输层',
            pageNumber: 42,
            excerpt:
              '慢启动算法在连接建立或超时后启动，cwnd 初始值为 1 MSS，每收到一个 ACK，cwnd 加倍，呈指数增长，直至达到 ssthresh 阈值后切换至拥塞避免阶段。',
          },
          {
            refId: 'S2',
            documentName: 'TCP/IP 协议详解·卷1',
            pageNumber: 287,
            excerpt:
              '拥塞避免阶段中，cwnd 每 RTT 线性增长 1 MSS，即 $cwnd_{new} = cwnd + MSS \\cdot (MSS / cwnd)$。当检测到丢包时，ssthresh 设为当前 cwnd 的一半。',
          },
          {
            refId: 'S3',
            documentName: '计算机网络·第3章 运输层',
            pageNumber: 45,
            excerpt:
              'TCP Tahoe 版本在丢包后 cwnd 降为 1 MSS 重新慢启动；TCP Reno 引入了快速恢复机制，在收到 3 个重复 ACK 时 cwnd 减半而非重置。',
          },
        ]

        resolve({
          score: 85,
          total: 100,
          confidence: 0.88,
          analysis:
            '你的回答正确阐述了慢启动（cwnd 指数增长）与拥塞避免（cwnd 线性增长）的核心区别。' +
            '慢启动阶段 cwnd 公式 $cwnd_{n+1} = 2 \\cdot cwnd_n$ 表意基本正确。' +
            '建议补充：慢启动阈值（ssthresh）的作用，以及拥塞避免阶段的具体公式 $cwnd_{new} = cwnd + MSS$。' +
            '整体结构清晰，关键概念准确，达到 85 分水平。',
          highlights: [
            '✅ 慢启动与拥塞避免的核心区别表述准确',
            '✅ cwnd 增长率公式方向正确',
            '⚠️ 缺少 ssthresh 阈值的说明',
            '⚠️ 拥塞避免阶段线性增长公式未给出',
            '📝 建议补充 TCP Tahoe 与 Reno 版本差异',
          ],
          sourceRefs: [
            {
              refId: 'S1',
              documentName: '计算机网络·第3章 运输层',
              pageNumber: 42,
              excerpt:
                '慢启动算法在连接建立或超时后启动，cwnd 初始值为 1 MSS，每收到一个 ACK，cwnd 加倍，呈指数增长，直至达到 ssthresh 阈值后切换至拥塞避免阶段。',
            },
            {
              refId: 'S2',
              documentName: 'TCP/IP 协议详解·卷1',
              pageNumber: 287,
              excerpt:
                '拥塞避免阶段中，cwnd 每 RTT 线性增长 1 MSS。当检测到丢包时，ssthresh 设为当前 cwnd 的一半。',
            },
            {
              refId: 'S3',
              documentName: '计算机网络·第3章 运输层',
              pageNumber: 45,
              excerpt:
                'TCP Tahoe 版本在丢包后 cwnd 降为 1 MSS 重新慢启动；TCP Reno 引入了快速恢复机制。',
            },
          ],
        })
      }, 1500)
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
    attachments,
    currentAgentTraces,
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
    addAttachment,
    updateAttachment,
    removeAttachment,
    clearAttachments,
    clearAgentTraces,
    initPracticeTraces,
    submitAnswerForEvaluation,
  }
})
