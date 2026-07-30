// ============================================================
// StudyAgents — Mock API: /api/chat/*
//
// 由 vite-plugin-mock 在 dev server 中加载；
// 拦截匹配的 HTTP 请求，直接返回 JSON，不经过后端代理。
// ============================================================

import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { MockMethod } from 'vite-plugin-mock'

// ============================================================
// 路径常量
// ============================================================

const __dirname = dirname(fileURLToPath(import.meta.url))
const CONTRACTS_ROOT = resolve(__dirname, '../../../contracts/mock')

// ============================================================
// 类型定义（对齐 contracts/mock/*.json Schema）
// ============================================================

interface MockSourceRefRaw {
  document_id: string
  document_name: string
  page_number: number
  chunk_id: string
  excerpt: string
  page_image_url?: string
  score?: number
}

interface MockAgentEventRaw {
  id: string
  agent: string
  event_type: string
  status: string
  summary: string
  duration_ms?: number
}

interface MockPublicResponse {
  run_id: string
  status: string
  mode?: string
  answer?: {
    conclusion: string
    reasoning: string[]
    note: string
  }
  refusal?: {
    reason: string
    message: string
    searched_scope: string
    suggestion: string
    retry_hint: string
  }
  source_refs?: MockSourceRefRaw[]
  agent_events: MockAgentEventRaw[]
  created_at: string
}

interface MockQaData {
  scenario: { mode: string; user_input: string }
  public_response: MockPublicResponse
}

// ============================================================
// 响应类型（返回给前端的格式）
// ============================================================

interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  citationIds?: string[]
  isRefusal?: boolean
}

interface AgentStep {
  agentRole: 'coordinator' | 'knowledge' | 'questioner' | 'evaluator'
  agentLabel: string
  status: 'idle' | 'running' | 'succeeded' | 'failed'
  summary: string
  detail?: string
  durationMs?: number
}

interface SourceRefDisplay {
  refId: string
  documentName: string
  pageNumber: number
  excerpt: string
}

interface ChatHistoryResponse {
  messages: ChatMessage[]
  agent_steps: AgentStep[]
  source_refs: SourceRefDisplay[]
}

// ============================================================
// 工具函数
// ============================================================

function loadJson(filename: string): MockQaData {
  const fullPath = resolve(CONTRACTS_ROOT, filename)
  return JSON.parse(readFileSync(fullPath, 'utf-8')) as MockQaData
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '--:--'
  }
}

// ============================================================
// 数据变换
// ============================================================

const AGENT_LABEL_MAP: Record<string, { role: AgentStep['agentRole']; label: string }> = {
  coordinator: { role: 'coordinator', label: 'Coordinator · 协调调度' },
  knowledge: { role: 'knowledge', label: 'Knowledge · 检索溯源' },
  questioner: { role: 'questioner', label: 'Questioner · 出题组卷' },
  evaluator: { role: 'evaluator', label: 'Evaluator · 分步评分' },
}

function mapAgentEvents(events: MockAgentEventRaw[]): AgentStep[] {
  const eventByAgent = new Map(events.map((e) => [e.agent, e]))
  const allRoles: AgentStep['agentRole'][] = ['coordinator', 'knowledge', 'questioner', 'evaluator']

  return allRoles.map((role) => {
    const evt = eventByAgent.get(role)
    if (evt) {
      return {
        agentRole: role,
        agentLabel: AGENT_LABEL_MAP[role]?.label ?? role,
        status: (
          evt.status === 'succeeded' ? 'succeeded'
          : evt.status === 'running' ? 'running'
          : evt.status === 'failed' ? 'failed'
          : 'idle'
        ) as AgentStep['status'],
        summary: evt.summary,
        durationMs: evt.duration_ms,
      }
    }
    return {
      agentRole: role,
      agentLabel: AGENT_LABEL_MAP[role]?.label ?? role,
      status: 'idle' as const,
      summary:
        role === 'questioner'
          ? '当前为问答模式，Questioner Agent 处于待命状态'
          : role === 'evaluator'
            ? '当前为问答模式，Evaluator Agent 处于待命状态'
            : '待命',
    }
  })
}

function mapSourceRefs(refs: MockSourceRefRaw[]): SourceRefDisplay[] {
  return refs.map((ref, i) => ({
    refId: `S${i + 1}`,
    documentName: ref.document_name,
    pageNumber: ref.page_number,
    excerpt: ref.excerpt,
  }))
}

function buildAnswerContent(
  answer: MockPublicResponse['answer'],
  refCount: number,
): string {
  if (!answer) return ''
  const lines: string[] = []
  lines.push(`**${answer.conclusion}** [S1]`)
  if (answer.reasoning.length > 0) {
    lines.push('')
    lines.push('### 论证过程')
    answer.reasoning.forEach((r, i) => {
      lines.push(`${i + 1}. ${r}`)
    })
  }
  if (refCount > 1 && answer.note) {
    lines.push('')
    lines.push(`> ${answer.note} [S${refCount}]`)
  } else if (answer.note) {
    lines.push('')
    lines.push(`> ${answer.note}`)
  }
  return lines.join('\n')
}

function buildRefusalContent(refusal: MockPublicResponse['refusal']): string {
  if (!refusal) return ''
  return [
    '⚠️ **抱歉，我无法回答这个问题。**',
    '',
    `**拒答原因**：${refusal.message}`,
    '',
    `**检索范围**：${refusal.searched_scope}`,
    '',
    `**建议**：${refusal.suggestion}`,
    '',
    `💡 **重试提示**：${refusal.retry_hint}`,
  ].join('\n')
}

// ============================================================
// 构建完整的 /api/chat/history 响应
// ============================================================

function buildChatHistory(): ChatHistoryResponse {
  const successData = loadJson('qa-success.json')
  const refusalData = loadJson('qa-refusal.json')
  const successSrcRefs = successData.public_response.source_refs ?? []

  // messages: 将两套 JSON 合并为对话列表
  const messages: ChatMessage[] = [
    // Q&A 1：成功回答
    {
      id: 'mock-success-u',
      role: 'user',
      content: successData.scenario.user_input,
      timestamp: formatTime(successData.public_response.created_at),
    },
    {
      id: 'mock-success-a',
      role: 'assistant',
      content: buildAnswerContent(successData.public_response.answer, successSrcRefs.length),
      timestamp: formatTime(successData.public_response.created_at),
      citationIds: successSrcRefs.map((_, i) => `S${i + 1}`),
    },
    // Q&A 2：拒答
    {
      id: 'mock-refusal-u',
      role: 'user',
      content: refusalData.scenario.user_input,
      timestamp: formatTime(refusalData.public_response.created_at),
    },
    {
      id: 'mock-refusal-a',
      role: 'assistant',
      content: buildRefusalContent(refusalData.public_response.refusal),
      timestamp: formatTime(refusalData.public_response.created_at),
      isRefusal: true,
    },
  ]

  // agent_steps: 从 qa-success 的 agent_events 映射
  const agent_steps = mapAgentEvents(successData.public_response.agent_events)

  // source_refs: 从 qa-success 的 source_refs 映射
  const source_refs = mapSourceRefs(successSrcRefs)

  return { messages, agent_steps, source_refs }
}

// ============================================================
// 预加载（模块首次导入时执行一次，后续请求复用缓存）
// ============================================================

const cachedHistory: ChatHistoryResponse = buildChatHistory()

// ============================================================
// Mock 路由表
// ============================================================

export default [
  // --------------------------------------------------
  // GET /api/chat/history — 获取对话历史
  // --------------------------------------------------
  {
    url: '/api/chat/history',
    method: 'get',
    response: (): ChatHistoryResponse => {
      return cachedHistory
    },
  },
] as MockMethod[]
