// ============================================================
// StudyAgents — 文件上传 API
//
// 双轨制说明：
//   - uploadKnowledgeBase(file)：管理员资料库上传
//     → POST /api/documents (multipart/form-data) — 仅 admin
//   - uploadChatAttachment(file)：问答附件（客户端处理）
//     → 将文件读取为 base64 Data URL，不经过服务端上传
//     → 附件信息随 QA 消息的 user_input 文本一起发送
//
// 注意：后端目前仅有管理员专用上传端点，
// 普通用户聊天附件通过客户端内联处理（Data URL）。
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

/** 聊天附件上传响应（客户端处理，无服务端上传） */
export interface ChatUploadResponse {
  /** 文件 Data URL（客户端本地生成） */
  file_url: string
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
 * 问答附件处理：将文件读取为客户端 Data URL（不经过服务端上传）。
 *
 * 后端目前仅有管理员上传端点，普通用户附件通过 base64 Data URL
 * 嵌入到 QA 消息文本中发送，避免 403 鉴权错误。
 *
 * @param file 要处理的文件对象
 * @returns 包含 data URL、文件名和大小的响应
 */
export async function uploadChatAttachment(
  file: File,
): Promise<ChatUploadResponse> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      resolve({
        file_url: reader.result as string,
        file_name: file.name,
        file_size: file.size,
      })
    }
    reader.onerror = () => {
      reject(new Error(`文件读取失败: ${file.name}`))
    }
    reader.readAsDataURL(file)
  })
}
