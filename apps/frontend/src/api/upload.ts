// ============================================================
// StudyAgents — 文件上传 API
//
// 统一上传：
//   - uploadKnowledgeBase(file)：管理员资料库上传
//     → POST /api/documents (multipart/form-data) — 仅 admin
//   - uploadChatAttachment(file)：问答附件上传
//     → POST /api/documents (multipart/form-data)
//     → 返回 document_id，随后通过 QA 请求的 file_ids 字段引用
//
// 注意：附件不再使用 Base64 Data URL 内联到 user_input，
// 避免触发后端 10000 字符限制（422 错误）。
// ============================================================

// ============================================================
// 上传响应类型
// ============================================================

/** POST /api/documents 响应（仅管理员）
 *  后端实际返回：{ state, document: {id, name, ...}, ingestion_job: {...} } */
export interface KnowledgeUploadResponse {
  state: string
  document: {
    id: string
    name: string
    sha256?: string
    mime?: string
    status?: string
    version?: number
    size_bytes?: number
    page_count?: number
    year?: string
    metadata?: Record<string, unknown>
    created_at?: string
    updated_at?: string
  }
  ingestion_job?: {
    id: string
    document_id: string
    stage: string
    status: string
    progress: number
    error_code: string | null
    error_summary: string | null
    attempts: number
    retry_count: number
    started_at: string | null
    finished_at: string | null
    created_at: string
    updated_at: string
  }
}

/** 聊天附件上传响应 — 调用 POST /api/documents 返回 */
export interface ChatUploadResponse {
  /** 后端返回的 document_id */
  document_id: string
  /** 原始文件名 */
  file_name: string
  /** 文件大小（字节） */
  file_size: number
}

// ============================================================
// API 方法
// ============================================================

/**
 * 管理员资料库上传：将文件提交到后端进行解析入库。
 * 需要 admin 权限，普通用户调用会返回 403。
 *
 * @param file 要上传的文件对象
 * @returns 包含 id 与处理状态的响应
 */
export async function uploadKnowledgeBase(
  file: File,
): Promise<KnowledgeUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const csrfToken = localStorage.getItem('authToken') || ''
  const resp = await fetch('/api/documents', {
    method: 'POST',
    headers: {
      'X-CSRF-Token': csrfToken,
    },
    body: formData,
    credentials: 'include',
  })

  if (!resp.ok) {
    throw new Error(`上传失败: HTTP ${resp.status}`)
  }

  return resp.json()
}

/**
 * 问答附件上传：将文件提交到后端进行存储。
 *
 * 调用 POST /api/documents (multipart/form-data) 获取 document_id，
 * 随后在 QA 请求中通过 file_ids 字段引用，避免将文件内容嵌入
 * user_input 触发 10000 字符限制（422）。
 *
 * @param file 要上传的文件对象
 * @returns 包含 document_id、文件名和大小的响应
 */
export async function uploadChatAttachment(
  file: File,
): Promise<ChatUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const csrfToken = localStorage.getItem('authToken') || ''
  const resp = await fetch('/api/documents', {
    method: 'POST',
    headers: {
      'X-CSRF-Token': csrfToken,
    },
    body: formData,
    credentials: 'include',
  })

  if (!resp.ok) {
    throw new Error(`附件上传失败: HTTP ${resp.status}`)
  }

  const data: KnowledgeUploadResponse = await resp.json()
  return {
    document_id: data.document.id,
    file_name: file.name,
    file_size: file.size,
  }
}
