// ============================================================
// StudyAgents — 前端 API 类型定义（纯类型文件 / 方案 A）
//
// 对应文档：
//   《多 Agent 知识问答复习系统开发文档》V1.0 第 8、9 章 + 附录 B/D
//   《前端 API 接口文档修正说明》第 3–6 节
//   《前端 API 类型契约二次修正说明》
//   《api.ts 最终全量审核报告》
//   《api(3).ts V1.0 最终固定整改清单》
//
// 架构定位：
//   本文件只包含 export interface / export type，绝不包含
//   Axios 实例、请求函数或任何业务逻辑。实际请求函数放在
//   src/api/auth.ts、src/api/documents.ts、src/api/chat.ts 等模块中。
//
// 字段命名使用 snake_case，与后端 JSON 完全一致。
// 幂等键通过 HTTP Header（X-Idempotency-Key）传递，不出现在请求体中。
// ============================================================

// ============================================================
// 0. 全局联合类型
// ============================================================

/** 用户角色 */
export type UserRole = 'member' | 'admin';

/** 文档处理状态 */
export type DocumentStatus =
  | 'pending'
  | 'processing'
  | 'active'
  | 'failed'
  | 'deleted';

/** 导入任务阶段 */
export type IngestionStage =
  | 'validate'
  | 'extract'
  | 'ocr'
  | 'structure'
  | 'chunk'
  | 'embed'
  | 'complete';

/** 导入任务状态 */
export type IngestionJobStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed_retryable'
  | 'failed';

/** 通用异步任务状态（清理、重建等非导入类任务） */
export type JobStatus = 'pending' | 'running' | 'succeeded' | 'failed';

/** 复核类别 */
export type ReviewItemKind = 'ocr' | 'answer' | 'grade';

/** 复核项状态 */
export type ReviewItemStatus = 'pending' | 'reviewed' | 'passed' | 'rejected';

/** Agent Run 状态 */
export type AgentRunStatus =
  | 'queued'
  | 'running'
  | 'waiting_user'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

/** Agent Run 运行模式（顶层分类） */
export type AgentRunMode = 'qa' | 'practice';

/** Agent Run 精细任务类型 */
export type AgentRunKind =
  | 'qa_answer'
  | 'practice_generate'
  | 'practice_grade';

/** Agent 事件类型（SSE event 字段） */
export type AgentEventType =
  | 'run.started'
  | 'agent.started'
  | 'agent.summary'
  | 'agent.completed'
  | 'run.waiting_user'
  | 'run.completed'
  | 'run.failed'
  | 'heartbeat';

/** Agent 角色 */
export type AgentRole =
  | 'coordinator'
  | 'knowledge'
  | 'questioner'
  | 'evaluator'
  | 'system';

/** 题目来源类型 */
export type SourceKind = 'past_exam' | 'generated_variant';

/** 题型 */
export type QuestionType =
  | 'choice'
  | 'fill_blank'
  | 'calculation'
  | 'short_answer';

/** 难度等级 */
export type DifficultyLevel = 1 | 2 | 3;

/** 评分项判定结果 */
export type StepScoreStatus = 'met' | 'partial' | 'not_met';

/** 评分状态 */
export type GradeStatus = 'confirmed' | 'provisional';

/** 申诉状态 */
export type AppealStatus = 'pending' | 'reviewed';

/** 错题状态 */
export type WrongBookStatus = 'pending' | 'reviewing' | 'mastered';

/** 训练会话状态 */
export type PracticeSessionStatus = 'active' | 'completed' | 'cancelled';

/** 对话消息角色 */
export type ChatMessageRole = 'user' | 'assistant' | 'system';

// ============================================================
// 1. 通用类型
// ============================================================

/** 分页查询参数 */
export interface PaginationParams {
  /** 页码，从 1 开始 */
  page: number;
  /** 每页条数，默认 20，最大 100 */
  page_size: number;
}

/** 分页响应包装（统一字段，所有列表接口复用） */
export interface PaginatedResponse<T> {
  /** 当前页数据列表 */
  items: T[];
  /** 总条数 */
  total: number;
  /** 当前页码 */
  page: number;
  /** 每页条数 */
  page_size: number;
  /** 总页数 */
  total_pages: number;
}

/** 通用写请求配置（非幂等操作使用） */
export interface WriteRequestOptions {
  /** 请求取消信号 */
  signal?: AbortSignal;
}

/** 幂等写请求配置（关键写操作必须使用，idempotency_key 通过 X-Idempotency-Key 头传递） */
export interface IdempotentWriteRequestOptions extends WriteRequestOptions {
  /** 幂等键，由前端生成唯一值 */
  idempotency_key: string;
}

/** 统一错误响应（文档 9.8 / 附录 D） */
export interface ApiError {
  /** 机器可读错误码，如 AGENT_MODEL_TIMEOUT */
  code: string;
  /** 面向用户的中文错误描述 */
  message: string;
  /** 是否允许客户端重试 */
  retryable: boolean;
  /** 全链路追踪 ID，用于排查问题 */
  trace_id: string;
  /** 可选的附加错误详情 */
  details?: unknown;
}

/** Agent Run 结构化错误信息 */
export interface RunError {
  /** 机器可读错误码 */
  code: string;
  /** 面向用户的中文错误描述 */
  message: string;
  /** 是否允许重试 */
  retryable: boolean;
  /** 失败的节点名称（用于检查点恢复定位） */
  failed_node?: string;
  /** 可选的附加错误详情 */
  details?: unknown;
}

/** 活动异步 Run 引用（run_id 与 event_url 成对出现或同时不存在） */
export interface ActiveRunRef {
  /** Run 唯一 ID */
  run_id: string;
  /** SSE 事件流地址 */
  event_url: string;
}

/** 作答快照（完整表达文本、选项与"不确定"状态） */
export interface AnswerSnapshot {
  /** 用户作答文本，支持 Markdown 与 LaTeX */
  raw_text?: string;
  /** 客观题选项 ID 列表 */
  selected_option_ids?: string[];
  /** 用户是否标记"不确定" */
  is_uncertain: boolean;
}

// ---- 分页列表响应别名（P0-3：统一所有列表接口） ----

/** GET /api/documents */
export type DocumentListResponse = PaginatedResponse<DocumentInfo>;

/** GET /api/review-items */
export type ReviewItemListResponse = PaginatedResponse<ReviewItem>;

/** GET /api/chat/sessions */
export type ChatSessionListResponse = PaginatedResponse<ChatSession>;

/** GET /api/practice/sessions */
export type PracticeSessionListResponse = PaginatedResponse<PracticeSession>;

/** GET /api/wrong-book */
export type WrongBookListResponse = PaginatedResponse<WrongBookEntry>;

/** GET /api/grade-appeals */
export type GradeAppealListResponse = PaginatedResponse<GradeAppeal>;

// ============================================================
// 2. 身份认证
// ============================================================

/** POST /api/auth/login — 登录请求 */
export interface LoginRequest {
  /** 预置用户名 */
  username: string;
  /** 预置密码 */
  password: string;
}

/** 用户公开信息（含权限列表） */
export interface UserInfo {
  /** 用户唯一 ID */
  id: string;
  /** 登录用户名 */
  username: string;
  /** 展示名称 */
  display_name: string;
  /** 角色 */
  role: UserRole;
  /** 权限标识列表，如 ["qa:read","practice:write","kb:manage"] */
  permissions: string[];
}

/** POST /api/auth/login — 登录成功响应 */
export interface LoginResponse {
  /** 用户公开信息 */
  user: UserInfo;
  /** CSRF Token，后续写请求需通过 X-CSRF-Token 头携带 */
  csrf_token: string;
}

/** GET /api/auth/me — 当前用户信息（与 UserInfo 结构一致） */
export type CurrentUserResponse = UserInfo;

/** POST /api/auth/logout — 注销响应 */
export interface LogoutResponse {
  /** 固定为 true */
  success: true;
}

/** GET /api/auth/csrf-token — 获取或刷新 CSRF Token */
export interface CsrfTokenResponse {
  /** CSRF Token，写入 X-CSRF-Token 请求头 */
  csrf_token: string;
}

// ============================================================
// 3. 知识库与资料管理（P0-2：文档完整生命周期）
// ============================================================

/** 文档资料 */
export interface DocumentInfo {
  /** 文档唯一 ID */
  id: string;
  /** 文档展示名称 */
  name: string;
  /** 文件 SHA-256 哈希 */
  sha256: string;
  /** 文件 MIME 类型 */
  mime: string;
  /** 文档处理状态 */
  status: DocumentStatus;
  /** 当前激活的内容版本号 */
  version: number;
  /** 文档所含页数 */
  page_count?: number;
  /** 文档年份（如 2024） */
  year?: number;
  /** 扩展元数据 */
  metadata?: Record<string, unknown>;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 更新时间（ISO 8601 UTC） */
  updated_at: string;
}

/** POST /api/documents — 上传响应（可辨识联合类型：首次接受 或 重复文件提示） */
export type UploadDocumentResponse =
  | {
      /** 文件已接受，开始导入 */
      state: 'accepted';
      /** 创建的文档信息 */
      document: DocumentInfo;
      /** 关联的导入任务 */
      ingestion_job: IngestionJob;
    }
  | {
      /** 检测到重复文件 */
      state: 'duplicate';
      /** 重复文件信息 */
      duplicate: DuplicateDocumentInfo;
      /** 允许用户执行的操作 */
      allowed_actions: Array<'cancel' | 'replace'>;
    };

/** 重复文件信息 */
export interface DuplicateDocumentInfo {
  /** 已存在的文档信息 */
  existing_document: DocumentInfo;
  /** 匹配方式 */
  matched_by: 'content_hash' | 'filename';
}

/** POST /api/documents（replace 操作）— 替换重复文档请求 */
export interface ReplaceDuplicateDocumentRequest {
  /** 要替换的已有文档 ID */
  existing_document_id: string;
  /** 期望的当前版本号（乐观并发控制） */
  expected_version: number;
}

/** GET /api/documents — 资料列表查询参数 */
export interface DocumentListParams extends Partial<PaginationParams> {
  /** 按状态筛选 */
  status?: DocumentStatus;
  /** 按 MIME 类型筛选 */
  mime?: string;
  /** 按年份筛选 */
  year?: number;
}

/** 文档变更请求（删除 / 重建通用版本校验） */
export interface DocumentMutationRequest {
  /** 期望的当前文档版本号（乐观并发控制；使用请求体或 If-Match 头二选一） */
  expected_version: number;
}

/** DELETE /api/documents/{document_id} — 删除文档响应 */
export interface DeleteDocumentResponse {
  /** 被删除的文档 ID */
  document_id: string;
  /** 删除请求已受理 */
  accepted: true;
  /** 关联的清理任务（前端可据此轮询清理进度） */
  cleanup_job: DocumentCleanupJob;
}

/** 文档清理任务（向量、切片、索引清理） */
export interface DocumentCleanupJob {
  /** 任务唯一 ID */
  job_id: string;
  /** 关联文档 ID */
  document_id: string;
  /** 被清理的文档版本 */
  document_version: number;
  /** 任务状态 */
  status: JobStatus;
  /** 结构化错误信息（仅失败时） */
  error?: RunError;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 最后更新时间（ISO 8601 UTC） */
  updated_at: string;
  /** 完成时间（ISO 8601 UTC，仅 succeeded/failed 时有值） */
  completed_at?: string;
}

/** GET /api/document-cleanup-jobs/{job_id} — 查询清理任务状态 */
export type GetDocumentCleanupJobResponse = DocumentCleanupJob;

/** POST /api/documents/{id}/reindex — 重建索引响应 */
export interface ReindexDocumentResponse {
  /** 关联文档 ID */
  document_id: string;
  /** 新建的导入任务 */
  ingestion_job: IngestionJob;
}

/** 导入任务（持久化异步任务） */
export interface IngestionJob {
  /** 任务唯一 ID */
  id: string;
  /** 关联文档 ID */
  document_id: string;
  /** 当前处理阶段 */
  stage: IngestionStage;
  /** 任务状态 */
  status: IngestionJobStatus;
  /** 进度百分比 0–100 */
  progress: number;
  /** Worker 租约过期时间（ISO 8601 UTC） */
  lease_until?: string;
  /** 已重试次数 */
  attempts: number;
  /** 最近错误摘要 */
  error?: string;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
}

/** POST /api/ingestion-jobs/{id}/retry — 重试响应 */
export interface RetryIngestionJobResponse {
  /** 重试后的导入任务 */
  ingestion_job: IngestionJob;
}

/** 课程章节 */
export interface ChapterInfo {
  /** 章节唯一 ID，作为 chapter_ids 的实际取值 */
  id: string;
  /** 章节编号，如 CH03 */
  code: string;
  /** 章节展示名称 */
  name: string;
  /** 前端展示顺序 */
  order_no: number;
  /** 可选的章节简介 */
  description?: string;
}

/** GET /api/chapters */
export type ChapterListResponse = ChapterInfo[];

/** 课程知识点 */
export interface KnowledgePoint {
  /** 知识点唯一 ID */
  id: string;
  /** 知识点编号（如 "CH03-01"） */
  code: string;
  /** 知识点名称 */
  name: string;
  /** 所属章节唯一 ID */
  chapter_id: string;
  /** 章节展示名称（只读快照，筛选和提交必须使用 chapter_id） */
  chapter_name?: string;
  /** 知识点描述 */
  description?: string;
  /** 父节点 ID（树形结构） */
  parent_id?: string;
}

/** GET /api/chapters/{chapter_id}/knowledge-points */
export type KnowledgePointListResponse = KnowledgePoint[];

/** 复核项 */
export interface ReviewItem {
  /** 复核项唯一 ID */
  id: string;
  /** 复核类别 */
  kind: ReviewItemKind;
  /** 关联目标类型 */
  target_type: string;
  /** 关联目标 ID */
  target_id: string;
  /** 置信度值 0–1 */
  confidence: number;
  /** 复核状态 */
  status: ReviewItemStatus;
  /** 复核负载数据 */
  payload?: Record<string, unknown>;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
}

/** GET /api/review-items — 复核项列表查询参数 */
export interface ReviewItemListParams extends Partial<PaginationParams> {
  /** 按类别筛选 */
  kind?: ReviewItemKind;
  /** 按状态筛选 */
  status?: ReviewItemStatus;
  /** 置信度上限筛选（仅返回 ≤ 此值的项） */
  max_confidence?: number;
}

/** PATCH /api/review-items/{id} — 提交复核结论（可辨识联合类型，P1-2） */
export type UpdateReviewItemRequest =
  | {
      /** 通过复核 */
      action: 'approve';
      /** 可选备注 */
      comment?: string;
    }
  | {
      /** 驳回 */
      action: 'reject';
      /** 驳回原因（必填） */
      reason: string;
    }
  | {
      /** 修正 */
      action: 'correct';
      /** 修正后的内容（必填） */
      corrected_payload: ReviewCorrectedPayload;
      /** 可选备注 */
      comment?: string;
    };

/** 复核修正内容联合类型 */
export type ReviewCorrectedPayload =
  | OcrReviewCorrectedPayload
  | QuestionReviewCorrectedPayload
  | GradeReviewCorrectedPayload;

/** OCR 复核修正内容 */
export interface OcrReviewCorrectedPayload {
  /** 修正后的文本 */
  corrected_text: string;
  /** 受影响的证据块 ID 列表 */
  affected_chunk_ids?: string[];
}

/** 题目复核修正内容 */
export interface QuestionReviewCorrectedPayload {
  /** 修正后的题干 */
  stem?: string;
  /** 修正后的选项 */
  options?: OptionItem[];
  /** 修正后的答案 */
  answer?: string;
  /** 修正后的解析 */
  explanation?: string;
}

/** 评分复核修正内容 */
export interface GradeReviewCorrectedPayload {
  /** 修正后的分项分数 */
  adjusted_step_scores: StepScore[];
  /** 修正后的讲解 */
  explanation?: string;
}

// ---- 文档详情与版本 ----

/** 文档历史版本信息 */
export interface DocumentVersionInfo {
  /** 版本号 */
  version: number;
  /** 该版本创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 该版本页数 */
  page_count?: number;
  /** 该版本文件 SHA-256 */
  sha256: string;
}

/** 复核汇总统计 */
export interface ReviewSummary {
  /** 复核项总数 */
  total: number;
  /** 待复核数 */
  pending: number;
  /** 已复核数 */
  reviewed: number;
}

/** 索引汇总统计 */
export interface IndexSummary {
  /** 证据块总数 */
  chunk_count: number;
  /** 关联的知识点数量 */
  knowledge_point_count?: number;
}

/** GET /api/documents/{document_id} — 文档详情响应（含版本、任务与统计） */
export interface DocumentDetailResponse {
  /** 文档基本信息 */
  document: DocumentInfo;
  /** 历史版本列表 */
  versions: DocumentVersionInfo[];
  /** 最近一次导入任务（运行中或已完成） */
  latest_ingestion_job?: IngestionJob;
  /** 复核统计 */
  review_summary: ReviewSummary;
  /** 索引统计 */
  index_summary: IndexSummary;
}

// ============================================================
// 4. 公开来源引用（含内联标记与原页安全规则）
// ============================================================

/** 来源引用公共字段（不含 page_image_url / page_image_expires_at） */
export interface BaseSourceRef {
  /** 引用唯一标识，对应正文中的 [S1]、[S2] 等内联标记 */
  ref_id: string;
  /** 文档唯一 ID */
  document_id: string;
  /** 文档版本号（保证文档更新后历史引用仍可复核） */
  document_version: number;
  /** 文档展示名称 */
  document_name: string;
  /** 所在页码（从 1 开始） */
  page_number: number;
  /** 题号（若来源于真题） */
  question_no?: string;
  /** 证据块唯一 ID */
  chunk_id: string;
  /** 证据文本摘录 */
  excerpt: string;
}

/** 原页图片访问约束：url 与 expires_at 必须成对出现或同时不存在 */
export type PageImageAccess =
  | {
      /** 原页图片短期签名 URL */
      page_image_url: string;
      /** 签名 URL 过期时间（ISO 8601 UTC） */
      page_image_expires_at: string;
    }
  | {
      page_image_url?: never;
      page_image_expires_at?: never;
    };

/** 统一来源引用 —— 指向文档、页码、题号、证据块，支持正文内联标记 */
export type SourceRef = BaseSourceRef & PageImageAccess;

// ============================================================
// 5. Agent 事件（SSE text/event-stream）
// ============================================================

/** Agent 事件公开摘要 —— 通过 SSE text/event-stream 推送给前端 */
export interface AgentEvent {
  /** 事件唯一 ID（用于 Last-Event-ID 断线续传） */
  id: string;
  /** 所属 Agent Run ID */
  run_id: string;
  /** 事件序号，保证 SSE 顺序 */
  sequence_no: number;
  /** Agent 角色 */
  agent: AgentRole;
  /** 事件类型 */
  event_type: AgentEventType;
  /** 事件状态 */
  status: AgentEventStatus;
  /** 面向用户的中文摘要描述 */
  summary: string;
  /** 关联的来源引用列表 */
  source_refs: SourceRef[];
  /** 耗时（毫秒） */
  duration_ms?: number;
  /** 事件创建时间（ISO 8601 UTC） */
  created_at: string;
}

/** Agent 事件状态（SSE 推送约定） */
export type AgentEventStatus = 'queued' | 'running' | 'waiting_user' | 'succeeded' | 'failed';

// ============================================================
// 6. 自由问答（含 Agent Run 可辨识联合类型 P1-4）
// ============================================================

/** 对话会话 */
export interface ChatSession {
  /** 会话唯一 ID */
  id: string;
  /** 会话标题 */
  title?: string;
  /** 所属用户 ID */
  user_id: string;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 最后更新时间（ISO 8601 UTC） */
  updated_at: string;
}

/** POST /api/chat/sessions — 创建会话请求 */
export interface CreateChatSessionRequest {
  /** 可选标题；若为空则由服务端根据首条消息自动生成 */
  title?: string;
}

/** POST /api/chat/sessions — 创建会话响应 */
export type CreateChatSessionResponse = ChatSession;

/** GET /api/chat/sessions — 会话列表查询参数 */
export interface ChatSessionListParams extends Partial<PaginationParams> {
  /** 按标题关键词搜索 */
  keyword?: string;
}

/** GET /api/chat/sessions/{id}/messages — 会话消息列表响应 */
export interface ChatSessionMessagesResponse {
  /** 所属会话 */
  session: ChatSession;
  /** 消息列表 */
  messages: ChatMessage[];
}

/** 对话消息 */
export interface ChatMessage {
  /** 消息唯一 ID */
  id: string;
  /** 所属会话 ID */
  session_id: string;
  /** 消息角色 */
  role: ChatMessageRole;
  /** 消息文本内容（正文中使用 [S1]、[S2] 等标记关联 SourceRef.ref_id） */
  content: string;
  /** 关联的 Agent Run ID */
  run_id?: string;
  /** 消息中的引用快照 */
  citations?: SourceRef[];
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
}

/** POST /api/chat/sessions/{id}/messages — 发送消息请求 */
export interface SendMessageRequest {
  /** 消息文本内容 */
  content: string;
  /** 限定检索的章节 ID 列表（可选） */
  chapter_ids?: string[];
}

/** POST /api/chat/sessions/{id}/messages — 发送消息响应 */
export interface SendMessageResponse {
  /** 关联的 Agent Run ID */
  run_id: string;
  /** SSE 事件流地址 */
  event_url: string;
}

/** Agent Run 公共字段（不含 kind / status / grade，由联合类型精确约束） */
export interface BaseAgentRun {
  /** Run 唯一 ID */
  id: string;
  /** 全链路追踪 ID（前端错误页可展示供用户复制） */
  trace_id: string;
  /** 关联线程 ID */
  thread_id: string;
  /** 运行模式（顶层分类） */
  mode: AgentRunMode;
  /** 关联的业务会话 ID（如训练会话 ID） */
  related_session_id?: string;
  /** 公开的最终结果文本 */
  public_response?: string;
  /** 引用列表 */
  source_refs: SourceRef[];
  /** 结构化错误信息（仅失败时） */
  error?: RunError;
  /** 模型调用次数 */
  model_calls: number;
  /** 节点跳转次数 */
  node_hops: number;
  /** 输入 token 数 */
  tokens_input?: number;
  /** 输出 token 数 */
  tokens_output?: number;
  /** 估算费用（元） */
  estimated_cost?: number;
  /** 运行开始时间（ISO 8601 UTC） */
  started_at?: string;
  /** 运行结束时间（ISO 8601 UTC） */
  ended_at?: string;
}

/** Agent Run 公共字段去除 kind / status（供联合类型复用） */
type AgentRunCommon = Omit<BaseAgentRun, 'kind' | 'status'>;

/**
 * Agent Run 联合类型（可辨识联合，基于 kind + status）：
 * - practice_grade + succeeded  → grade 必填，error 不可能
 * - practice_grade + 其他状态   → grade 不存在
 * - 非 practice_grade（qa_answer / practice_generate）→ grade 不存在
 */
export type AgentRun =
  | (AgentRunCommon & {
      kind: 'practice_grade';
      status: 'succeeded';
      /** 完整评分结果（必填） */
      grade: GradeInfo;
      error?: never;
    })
  | (AgentRunCommon & {
      kind: 'practice_grade';
      status: Exclude<AgentRunStatus, 'succeeded'>;
      grade?: never;
    })
  | (AgentRunCommon & {
      kind: Exclude<AgentRunKind, 'practice_grade'>;
      status: AgentRunStatus;
      grade?: never;
    });

/** GET /api/agent-runs/{run_id} */
export type GetAgentRunResponse = AgentRun;

/** POST /api/agent-runs/{run_id}/retry — 重试或从检查点恢复失败任务响应 */
export interface RetryAgentRunResponse {
  /** 恢复后的 Agent Run（可能是新 Run 或复用原 Run） */
  run: AgentRun;
  /** SSE 事件流地址 */
  event_url: string;
}

// ============================================================
// 7. 专项训练（含训练历史与作答历史 P0-1）
// ============================================================

/** 客观题选项 */
export interface OptionItem {
  /** 选项 ID，如 A、B、C、D */
  id: string;
  /** 选项文本，可含 LaTeX */
  text: string;
}

/** 训练进度 */
export interface PracticeProgress {
  /** 当前题号 */
  current: number;
  /** 总题数 */
  total: number;
}

/** 专项训练公开题目响应 —— 不含 answer、rubric 等私有字段 */
export interface PracticeItem {
  /** 题目唯一 ID（用于答案提交关联） */
  item_id: string;
  /** 题目版本号（防止并发冲突，答案提交时必须匹配） */
  question_version: number;
  /** 在当前训练中的序号 */
  order_no: number;
  /** 来源类型 */
  source_kind: SourceKind;
  /** 题型 */
  question_type: QuestionType;
  /** 难度等级 */
  difficulty: DifficultyLevel;
  /** 题干文本，公式使用 LaTeX */
  stem: string;
  /** 选项列表（客观题时有值） */
  options: OptionItem[];
  /** 来源说明文字（如 "2024 年真题，第 3 题"） */
  source_label: string;
  /** 当前进度信息 */
  progress: PracticeProgress;
}

/** 创建训练会话的配置（同时作为 POST 请求体） */
export interface PracticeSessionConfig {
  /** 章节 ID 列表（空数组表示全部章节；与 knowledge_point_ids 同时存在时取交集） */
  chapter_ids?: string[];
  /** 知识点 ID 列表（空数组表示全部知识点；与 chapter_ids 同时存在时取交集） */
  knowledge_point_ids?: string[];
  /** 题型列表（空数组表示全部题型） */
  question_types?: QuestionType[];
  /** 初始难度，默认 2 */
  difficulty?: DifficultyLevel;
  /** 题目数量 1–10，默认 5 */
  target_count?: number;
}

/** 训练会话（P1-5 B：active_run 替代松散字段对） */
export interface PracticeSession {
  /** 会话唯一 ID */
  id: string;
  /** 所属用户 ID */
  user_id: string;
  /** 训练筛选条件快照 */
  filters: PracticeSessionConfig;
  /** 目标题数 */
  target_count: number;
  /** 训练状态 */
  status: PracticeSessionStatus;
  /** 当前题目（公开，无私有字段） */
  current_item?: PracticeItem;
  /** 会话进度 */
  progress: PracticeProgress;
  /** 当前进行中的异步任务引用（页面刷新后据此恢复 SSE 连接或查询状态；无任务时整体不存在） */
  active_run?: ActiveRunRef;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 最后更新时间（ISO 8601 UTC） */
  updated_at: string;
}

/** GET /api/practice/sessions/{session_id} */
export type GetPracticeSessionResponse = PracticeSession;

/** POST /api/practice/sessions — 创建训练会话响应（可辨识联合类型） */
export type CreatePracticeSessionResponse =
  | {
      /** 首题已同步生成，可直接展示 */
      state: 'ready';
      /** 训练会话（current_item 必须存在） */
      session: PracticeSession & {
        current_item: PracticeItem;
      };
      run_id?: never;
      event_url?: never;
    }
  | {
      /** 首题正在异步生成，需连接 SSE 等待 */
      state: 'generating';
      /** 训练会话（current_item 尚不存在） */
      session: PracticeSession & {
        current_item?: never;
      };
      /** 异步生成 Run ID */
      run_id: string;
      /** SSE 事件流地址 */
      event_url: string;
    };

/** GET /api/practice/sessions — 训练历史查询参数 */
export interface PracticeSessionListParams extends PaginationParams {
  /** 按状态筛选 */
  status?: PracticeSessionStatus;
  /** 按章节 ID 筛选 */
  chapter_id?: string;
  /** 按知识点 ID 筛选 */
  knowledge_point_id?: string;
  /** 开始时间下限（ISO 8601 UTC） */
  started_from?: string;
  /** 开始时间上限（ISO 8601 UTC） */
  started_to?: string;
}

/** POST /api/practice/sessions/{id}/answers — 提交答案请求 */
export interface AnswerSubmission {
  /** 题目唯一 ID */
  item_id: string;
  /** 题目版本号（必须与 PracticeItem.question_version 一致） */
  question_version: number;
  /** 用户作答文本，支持 Markdown 与 LaTeX */
  raw_text?: string;
  /** 客观题选项 ID 列表（choice 题型使用） */
  selected_option_ids?: string[];
  /** 用户标记"不确定"（即使评分正确也可进入错题复习流程） */
  is_uncertain?: boolean;
}

/** POST /api/practice/sessions/{id}/answers — 提交答案响应 */
export interface SubmitAnswerResponse {
  /** 关联的评分 Run ID */
  run_id: string;
  /** SSE 事件流地址 */
  event_url: string;
}

/** POST /api/practice/sessions/{id}/finish — 提前结束训练响应 */
export interface FinishPracticeSessionResponse {
  /** 训练会话 ID */
  session_id: string;
  /** 结束后的状态 */
  status: 'completed' | 'cancelled';
  /** 训练总结地址 */
  summary_url: string;
}

/** 训练历史作答记录 */
export interface PracticeAttempt {
  /** 作答唯一 ID */
  attempt_id: string;
  /** 所属训练会话 ID */
  session_id: string;
  /** 题目 ID */
  item_id: string;
  /** 题目版本号 */
  question_version: number;
  /** 题干文本摘要 */
  question_stem: string;
  /** 题型 */
  question_type: QuestionType;
  /** 用户作答快照 */
  answer: AnswerSnapshot;
  /** 评分结果 */
  grade?: GradeInfo;
  /** 用户是否标记"不确定" */
  is_uncertain: boolean;
  /** 提交时间（ISO 8601 UTC） */
  submitted_at: string;
}

/** GET /api/practice/sessions/{session_id}/attempts */
export type PracticeAttemptListResponse = PaginatedResponse<PracticeAttempt>;

/** GET /api/wrong-book/{wrong_book_entry_id}/attempts */
export type WrongBookAttemptListResponse = PaginatedResponse<PracticeAttempt>;

// ============================================================
// 8. 评分与申诉（P1-3：申诉复核可辨识联合类型）
// ============================================================

/** 单个评分项结果 */
export interface StepScore {
  /** 关联的评分点 ID */
  rubric_item_id: string;
  /** 判定结果 */
  status: StepScoreStatus;
  /** 该项实际得分 */
  score: number;
  /** 该项满分 */
  max_score: number;
  /** 针对该评分点的反馈说明 */
  feedback: string;
}

/** 评分结果 */
export interface GradeInfo {
  /** 评分唯一 ID */
  id: string;
  /** 关联的答案 ID */
  answer_id: string;
  /** 实际得分 */
  score: number;
  /** 满分 */
  max_score: number;
  /** 分步评分明细 */
  step_scores: StepScore[];
  /** 参考讲解文本 */
  explanation?: string;
  /** 支撑评分讲解的来源引用 */
  source_refs: SourceRef[];
  /** 评分置信度 0–1 */
  confidence: number;
  /** 是否需要人工复核 */
  review_required: boolean;
  /** 评分状态 */
  status: GradeStatus;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
}

/** 评分申诉 */
export interface GradeAppeal {
  /** 申诉唯一 ID */
  id: string;
  /** 关联评分 ID */
  grade_id: string;
  /** 用户填写的异议说明 */
  reason: string;
  /** 管理员复核结论 */
  resolution?: string;
  /** 原始分数（复核前） */
  original_score: number;
  /** 最终分数（复核后） */
  final_score?: number;
  /** 申诉状态 */
  status: AppealStatus;
  /** 申诉创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 复核完成时间（ISO 8601 UTC） */
  reviewed_at?: string;
}

/** POST /api/grades/{id}/appeals — 创建评分申诉请求 */
export interface CreateGradeAppealRequest {
  /** 异议说明 */
  reason: string;
}

/** GET /api/grade-appeals — 申诉列表查询参数（管理员） */
export interface AppealListParams extends Partial<PaginationParams> {
  /** 按状态筛选 */
  status?: AppealStatus;
}

/** PATCH /api/grade-appeals/{id} — 管理员提交复核结论（可辨识联合类型，P1-3） */
export type ReviewGradeAppealRequest =
  | {
      /** 维持原评分 */
      action: 'uphold';
      /** 复核说明（必填） */
      review_comment: string;
    }
  | {
      /** 驳回申诉 */
      action: 'reject';
      /** 驳回说明（必填） */
      review_comment: string;
    }
  | {
      /** 调整分数 */
      action: 'adjust';
      /** 修正后的分项分数（必填） */
      adjusted_step_scores: StepScore[];
      /** 调整说明（必填） */
      review_comment: string;
    };

/** GET /api/grade-appeals/{id} — 申诉详情响应（含完整复核与审计信息） */
export interface GradeAppealDetailResponse {
  /** 申诉基本信息 */
  appeal: GradeAppeal;
  /** 原题目（含版本信息） */
  question: PracticeItem;
  /** 用户原始作答快照（结构化） */
  answer_snapshot: AnswerSnapshot;
  /** 原始评分结果（复核前） */
  original_grade: GradeInfo;
  /** 评分依据的来源引用 */
  source_refs: SourceRef[];
  /** 复核人信息（管理员已复核时返回） */
  reviewed_by?: UserInfo;
}

// ============================================================
// 9. 错题本与学习状态（P1-5 A：仅保留 knowledge_point_id 单数）
// ============================================================

/** 错题本条目 */
export interface WrongBookEntry {
  /** 条目唯一 ID */
  id: string;
  /** 所属用户 ID */
  user_id: string;
  /** 关联题目 ID */
  question_id: string;
  /** 题干文本摘要 */
  question_stem: string;
  /** 题型 */
  question_type: QuestionType;
  /** 题目来源类型 */
  source_kind: SourceKind;
  /** 来源说明文字（如 "2024 年真题，第 3 题"） */
  source_label: string;
  /** 关联知识点 ID（一道题关联多个知识点时，为每个知识点创建独立错题条目） */
  knowledge_point_id: string;
  /** 错题状态 */
  status: WrongBookStatus;
  /** 首次错误时间（ISO 8601 UTC） */
  first_error_at: string;
  /** 最近错误时间（ISO 8601 UTC） */
  last_error_at: string;
  /** 累计错误次数 */
  error_count: number;
  /** 最近一次得分 */
  last_score?: number;
  /** 最近一次满分 */
  last_max_score?: number;
  /** 建议下次复习时间（ISO 8601 UTC） */
  next_review_at?: string;
  /** 用户个人备注 */
  note?: string;
  /** 创建时间（ISO 8601 UTC） */
  created_at: string;
  /** 更新时间（ISO 8601 UTC） */
  updated_at: string;
}

/** GET /api/wrong-book — 错题本查询参数 */
export interface WrongBookListParams extends Partial<PaginationParams> {
  /** 按状态筛选 */
  status?: WrongBookStatus;
  /** 按章节 ID 筛选 */
  chapter_id?: string;
  /** 按知识点 ID 筛选 */
  knowledge_point_id?: string;
}

/** PATCH /api/wrong-book/{id} — 更新错题条目请求（仅允许标记待复习/添加备注） */
export interface UpdateWrongBookRequest {
  /** 状态变更（仅允许设为 pending 或 reviewing，不允许直接设为 mastered） */
  status?: 'pending' | 'reviewing';
  /** 添加或更新个人备注 */
  note?: string;
}

/** 掌握度记录 */
export interface MasteryRecord {
  /** 用户 ID */
  user_id: string;
  /** 知识点 ID */
  knowledge_point_id: string;
  /** 掌握度值 0–1（初始 0.5，由固定公式更新） */
  mastery: number;
  /** 连续表现计数（连续 ≥80% 次数） */
  streaks?: number;
  /** 最近变更原因 */
  reason?: string;
  /** 更新时间（ISO 8601 UTC） */
  updated_at: string;
}

/** GET /api/learning-summary — 学习概况响应 */
export interface LearningSummary {
  /** 用户 ID */
  user_id: string;
  /** 各知识点掌握度列表 */
  mastery_records: MasteryRecord[];
  /** 待复习错题总数 */
  pending_wrong_count: number;
  /** 复习中错题数 */
  reviewing_wrong_count: number;
  /** 近期正确率 0–1 */
  recent_accuracy?: number;
  /** 近期完成训练次数 */
  recent_session_count?: number;
  /** 训练总结文本 */
  summary_text?: string;
}

/** GET /api/practice/sessions/{id}/summary — 训练会话总结 */
export interface SessionSummary {
  /** 训练会话 ID */
  session_id: string;
  /** 总得分 */
  total_score: number;
  /** 总满分 */
  total_max_score: number;
  /** 各题评分列表 */
  grades: GradeInfo[];
  /** 知识点表现汇总 */
  knowledge_point_performance: KnowledgePointPerformance[];
  /** 错题条目 ID 列表 */
  wrong_book_entry_ids: string[];
  /** 下一步学习建议 */
  suggestion?: string;
}

/** 知识点表现变化 */
export interface KnowledgePointPerformance {
  /** 知识点 ID */
  knowledge_point_id: string;
  /** 知识点名称 */
  knowledge_point_name: string;
  /** 更新后的掌握度 */
  mastery: number;
  /** 掌握度变化量（正值为提升） */
  mastery_change: number;
}
