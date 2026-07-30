// ============================================================
// StudyAgents — 文件上传 API
//
//   - uploadKnowledgeBase(file)：管理员资料库上传
//     → POST /api/documents (multipart/form-data) — 仅 admin
//
// 注意：普通成员没有文件上传权限（POST /api/documents 仅限 admin）。
// 问答附件通过 FileReader 读取为 base64 data URL 后内联到 user_input，
// 避免触发 403 错误。大文件可能超出后端 10000 字符限制（422）。
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
