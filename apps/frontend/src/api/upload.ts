// ============================================================
// StudyAgents — 文件上传 API（双轨制）
//
// 双轨制说明：
//   - uploadKnowledgeBase(file)：管理员资料库上传
//     → POST /api/documents (multipart/form-data)
//   - uploadChatAttachment(file)：问答附件上传
//     → POST /api/documents (multipart/form-data)
//
// 两个链路职责严格分离：
//   - 管理员上传 → 资料解析、切片、向量化、入库（长期存储）
//   - 问答附件 → 临时上传、仅关联当前对话消息（暂存）
// ============================================================

import http from '../utils/request'

// ============================================================
// 上传响应类型
// ============================================================

/** POST /api/documents 响应 */
export interface KnowledgeUploadResponse {
  /** 资料文件唯一 ID */
  file_id: string
  /** 处理状态（异步任务） */
  status: 'processing'
}

/** POST /api/chat/upload 响应 */
export interface ChatUploadResponse {
  /** 附件临时 URL */
  file_url: string
  /** 附件原始文件名 */
  file_name: string
}

// ============================================================
// API 方法
// ============================================================

/**
 * 管理员资料库上传：将文件提交到后端进行解析入库。
 *
 * @param file 要上传的文件对象
 * @returns 包含 file_id 与处理状态的响应
 */
export async function uploadKnowledgeBase(
  file: File,
): Promise<KnowledgeUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await http.post<KnowledgeUploadResponse>(
    '/documents',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    },
  )

  return response.data
}

/**
 * 问答附件上传：在聊天过程中临时上传文件（如截图、参考文档）。
 *
 * @param file 要上传的文件对象
 * @returns 包含 file_url 与 file_name 的响应
 */
export async function uploadChatAttachment(
  file: File,
): Promise<ChatUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await http.post<ChatUploadResponse>(
    '/documents',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    },
  )

  return response.data
}
