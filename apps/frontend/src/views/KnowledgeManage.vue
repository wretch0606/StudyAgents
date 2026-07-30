<script setup lang="ts">
// ============================================================
// StudyAgents — 资料管理页（管理员）
//
// 场景一：管理员全局资料上传
//   - 拖拽 / 点击上传区域
//   - 上传后展示进度列表，调用 uploadKnowledgeBase
//   - 成功后状态更新为"解析中"
//
// 严格区分于问答页附件上传（场景二：Home.vue 📎）
// ============================================================

import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadKnowledgeBase } from '../api/upload'
import type { KnowledgeUploadResponse } from '../api/upload'

// ============================================================
// 上传任务项
// ============================================================

interface UploadTask {
  /** 本地唯一 ID（用于列表 key 和状态更新） */
  localId: string
  /** 原始文件名 */
  fileName: string
  /** 文件大小（字节） */
  fileSize: number
  /** 文件 MIME 类型 */
  fileType: string
  /** 上传状态 */
  status: 'uploading' | 'processing' | 'failed'
  /** 上传进度 0–100（模拟） */
  progress: number
  /** 服务端返回的 file_id（成功后可用） */
  fileId?: string
  /** 错误信息 */
  error?: string
}

// ============================================================
// 状态
// ============================================================

const uploadTasks = ref<UploadTask[]>([])
const isDragOver = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)

// ============================================================
// 工具函数
// ============================================================

/** 格式化文件大小为可读字符串 */
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** 格式化时间 */
function formatTime(): string {
  return new Date().toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** 检查文件类型是否允许 */
function isFileAllowed(file: File): boolean {
  const allowed = [
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/png',
    'image/jpeg',
    'text/plain',
    'text/markdown',
    'text/x-markdown',
  ]
  // 也检查扩展名（某些系统可能缺少 MIME）
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  const allowedExt = ['pdf', 'doc', 'docx', 'png', 'jpg', 'jpeg', 'txt', 'md']
  return allowed.includes(file.type) || allowedExt.includes(ext)
}

// ============================================================
// 上传流程
// ============================================================

/**
 * 处理单个文件的上传：
 *   1. 添加到列表（uploading 状态，progress = 0）
 *   2. 模拟进度增长到 90%
 *   3. 调用 uploadKnowledgeBase API
 *   4. 成功后 progress → 100%，status → 'processing'
 *   5. 失败后 status → 'failed'
 */
async function processFile(file: File): Promise<void> {
  const localId = `kb-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

  const task: UploadTask = {
    localId,
    fileName: file.name,
    fileSize: file.size,
    fileType: file.type || 'unknown',
    status: 'uploading',
    progress: 0,
  }

  uploadTasks.value.unshift(task)

  // ---- 模拟进度 0% → 90%（后端真实对接后替换为 onUploadProgress） ----
  const progressTimer = setInterval(() => {
    const t = uploadTasks.value.find((u) => u.localId === localId)
    if (!t || t.status !== 'uploading') {
      clearInterval(progressTimer)
      return
    }
    // 减速逼近 90%
    if (t.progress < 90) {
      const increment = Math.max(1, Math.floor((90 - t.progress) / 6))
      t.progress = Math.min(90, t.progress + increment)
    }
  }, 200)

  try {
    const res: KnowledgeUploadResponse = await uploadKnowledgeBase(file)

    clearInterval(progressTimer)

    // 更新任务状态
    const t = uploadTasks.value.find((u) => u.localId === localId)
    if (t) {
      t.progress = 100
      t.status = 'processing'
      t.fileId = res.document.id
    }
  } catch (err: any) {
    clearInterval(progressTimer)

    const t = uploadTasks.value.find((u) => u.localId === localId)
    if (t) {
      t.status = 'failed'
      t.error = err?.response?.data?.message ?? err?.message ?? '上传失败'
    }
  }
}

/** 处理拖拽 / 文件选择入口 */
function handleFiles(files: FileList | File[]) {
  const fileArr = Array.from(files)
  for (const file of fileArr) {
    if (!isFileAllowed(file)) {
      ElMessage.warning(`不支持的文件类型 "${file.name}"，已跳过。支持的格式：PDF、DOCX、TXT、Markdown、PNG、JPG`)
      continue
    }
    processFile(file)
  }
}

// ============================================================
// 事件处理
// ============================================================

/** 点击上传区域 → 触发隐藏 input */
function triggerFileInput() {
  fileInputRef.value?.click()
}

/** 文件选择 */
function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    handleFiles(input.files)
    input.value = ''
  }
}

/** 拖拽进入 */
function onDragOver(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = true
}

/** 拖拽离开 */
function onDragLeave() {
  isDragOver.value = false
}

/** 放下文件 */
function onDrop(e: DragEvent) {
  e.preventDefault()
  isDragOver.value = false
  if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
    handleFiles(e.dataTransfer.files)
  }
}

/** 从列表中移除任务 */
function removeTask(localId: string) {
  uploadTasks.value = uploadTasks.value.filter((t) => t.localId !== localId)
}
</script>

<template>
  <div class="km-shell">
    <!-- ======================================== -->
    <!-- 页面标题 -->
    <!-- ======================================== -->
    <header class="km-header">
      <h1 class="km-title">📂 资料管理</h1>
      <p class="km-subtitle">上传课程资料 · 监控导入解析 · 管理知识库</p>
    </header>

    <!-- ======================================== -->
    <!-- 上传区域（拖拽 + 点击） -->
    <!-- ======================================== -->
    <input
      ref="fileInputRef"
      type="file"
      class="km-file-hidden"
      multiple
      accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.txt,.md"
      @change="onFileChange"
    />

    <div
      :class="['km-dropzone', { 'drag-over': isDragOver }]"
      @click="triggerFileInput"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <svg class="km-drop-icon" viewBox="0 0 48 48" fill="none">
        <rect x="8" y="8" width="32" height="32" rx="6" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3" opacity="0.5" />
        <path d="M24 16v16M16 24h16" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.6" />
      </svg>
      <p class="km-drop-text">
        <template v-if="isDragOver">释放文件以上传</template>
        <template v-else>拖拽文件到此处，或 <span class="km-drop-link">点击选择文件</span></template>
      </p>
      <p class="km-drop-hint">支持 PDF、Word、PNG/JPG、TXT、Markdown — 单次可选多个文件</p>
    </div>

    <!-- ======================================== -->
    <!-- 上传任务列表 -->
    <!-- ======================================== -->
    <section v-if="uploadTasks.length > 0" class="km-tasks">
      <h2 class="km-section-title">
        上传任务
        <span class="km-task-count">{{ uploadTasks.length }}</span>
      </h2>

      <div class="km-task-list">
        <div
          v-for="task in uploadTasks"
          :key="task.localId"
          :class="['km-task-card', task.status]"
        >
          <!-- 文件图标 -->
          <div class="km-task-icon">
            <svg v-if="task.status !== 'failed'" viewBox="0 0 40 40" fill="none" class="km-file-svg">
              <rect x="6" y="2" width="28" height="36" rx="4" fill="var(--code-bg)" stroke="var(--border)" stroke-width="1.5" />
              <path d="M14 14h12M14 20h12M14 26h8" stroke="var(--text)" stroke-width="1.5" stroke-linecap="round" opacity="0.5" />
            </svg>
            <svg v-else viewBox="0 0 40 40" fill="none" class="km-file-svg error">
              <rect x="6" y="2" width="28" height="36" rx="4" fill="rgba(248,113,113,0.06)" stroke="rgba(248,113,113,0.3)" stroke-width="1.5" />
              <path d="M16 22l8-8M24 22l-8-8" stroke="#f87171" stroke-width="1.5" stroke-linecap="round" />
            </svg>
          </div>

          <!-- 文件信息 -->
          <div class="km-task-info">
            <p class="km-task-name">{{ task.fileName }}</p>
            <p class="km-task-meta">
              <span>{{ formatFileSize(task.fileSize) }}</span>
              <span class="km-meta-sep">·</span>
              <span>{{ formatTime() }}</span>
            </p>

            <!-- 进度条 -->
            <div v-if="task.status === 'uploading'" class="km-progress">
              <div class="km-progress-track">
                <div
                  class="km-progress-fill"
                  :style="{ width: task.progress + '%' }"
                ></div>
              </div>
              <span class="km-progress-pct">{{ task.progress }}%</span>
            </div>

            <!-- 错误信息 -->
            <p v-if="task.status === 'failed' && task.error" class="km-task-error">
              {{ task.error }}
            </p>
          </div>

          <!-- 状态标签 -->
          <div class="km-task-status">
            <span v-if="task.status === 'uploading'" class="km-status-badge uploading">
              <span class="km-status-dot pulse"></span>
              上传中
            </span>
            <span v-else-if="task.status === 'processing'" class="km-status-badge processing">
              <span class="km-status-dot"></span>
              解析中
            </span>
            <span v-else class="km-status-badge failed">
              失败
            </span>
          </div>

          <!-- 操作 -->
          <button
            class="km-task-remove"
            :disabled="task.status === 'uploading'"
            @click.stop="removeTask(task.localId)"
            title="移除"
          >
            <svg viewBox="0 0 20 20" fill="currentColor" class="km-remove-icon">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
            </svg>
          </button>
        </div>
      </div>
    </section>

    <!-- ======================================== -->
    <!-- 空状态（无上传任务时） -->
    <!-- ======================================== -->
    <section v-else class="km-empty">
      <svg class="km-empty-icon" viewBox="0 0 64 64" fill="none">
        <rect x="12" y="8" width="40" height="48" rx="8" stroke="currentColor" stroke-width="1.5" opacity="0.3" />
        <path d="M24 22h16M24 30h16M24 38h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" opacity="0.25" />
        <circle cx="44" cy="44" r="12" fill="var(--accent-bg)" stroke="var(--accent)" stroke-width="1.5" />
        <path d="M44 38v12M38 44h12" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" />
      </svg>
      <p class="km-empty-text">暂无上传任务</p>
      <p class="km-empty-desc">拖拽文件到上方区域，或点击选择文件开始上传</p>
    </section>
  </div>
</template>

<style scoped>
/* ============================================================
   全局变量引用
   ============================================================ */
.km-shell {
  --accent: #a78bfa;
  --accent-bg: rgba(167, 139, 250, 0.08);
  --accent-border: rgba(167, 139, 250, 0.25);
  --bg: #1a1a2e;
  --code-bg: #16213e;
  --border: rgba(255, 255, 255, 0.08);
  --text: #888;
  --text-h: #e0e0e0;

  height: 100%;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 32px 40px;
  box-sizing: border-box;
}

/* ============================================================
   页面标题
   ============================================================ */
.km-header {
  margin-bottom: 24px;
}

.km-title {
  font-family: var(--heading, 'Inter', sans-serif);
  font-size: 24px;
  font-weight: 700;
  color: var(--text-h);
  margin: 0 0 6px;
  letter-spacing: -0.3px;
}

.km-subtitle {
  font-size: 13px;
  color: var(--text);
  margin: 0;
}

/* ============================================================
   上传区域（Dropzone）
   ============================================================ */
.km-file-hidden {
  display: none;
}

.km-dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 48px 32px;
  border: 2px dashed var(--border);
  border-radius: 14px;
  background: var(--code-bg);
  cursor: pointer;
  transition: all 0.25s ease;
  flex-shrink: 0;
}

.km-dropzone:hover {
  border-color: var(--accent-border);
  background: var(--accent-bg);
}

.km-dropzone.drag-over {
  border-color: var(--accent);
  background: var(--accent-bg);
  box-shadow: 0 0 0 4px var(--accent-bg);
}

.km-drop-icon {
  width: 56px;
  height: 56px;
  color: var(--text);
  opacity: 0.5;
}

.km-dropzone.drag-over .km-drop-icon {
  color: var(--accent);
  opacity: 0.8;
}

.km-drop-text {
  font-size: 15px;
  color: var(--text-h);
  margin: 0;
  font-weight: 500;
}

.km-drop-link {
  color: var(--accent);
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.km-drop-hint {
  font-size: 12px;
  color: var(--text);
  opacity: 0.55;
  margin: 0;
}

/* ============================================================
   任务列表
   ============================================================ */
.km-tasks {
  margin-top: 28px;
  flex: 1;
}

.km-section-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-h);
  margin: 0 0 14px;
}

.km-task-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 20px;
  padding: 0 7px;
  border-radius: 10px;
  background: var(--accent-bg);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

.km-task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* --- 任务卡片 --- */
.km-task-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--code-bg);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.km-task-card.uploading {
  border-left: 3px solid var(--accent);
}

.km-task-card.processing {
  border-left: 3px solid #f0a060;
  background: rgba(240, 160, 96, 0.03);
}

.km-task-card.failed {
  border-left: 3px solid #f87171;
  background: rgba(248, 113, 113, 0.03);
}

/* --- 文件图标 --- */
.km-task-icon {
  flex-shrink: 0;
}

.km-file-svg {
  width: 44px;
  height: 44px;
}

.km-file-svg.error {
  opacity: 0.7;
}

/* --- 文件信息 --- */
.km-task-info {
  flex: 1;
  min-width: 0;
}

.km-task-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.km-task-meta {
  font-size: 11px;
  color: var(--text);
  opacity: 0.55;
  margin: 0 0 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.km-meta-sep {
  opacity: 0.4;
}

/* --- 进度条 --- */
.km-progress {
  display: flex;
  align-items: center;
  gap: 10px;
}

.km-progress-track {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--border);
  overflow: hidden;
}

.km-progress-fill {
  height: 100%;
  border-radius: 2px;
  background: var(--accent);
  transition: width 0.3s ease;
}

.km-progress-pct {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  font-family: var(--mono, 'Consolas', monospace);
  min-width: 32px;
  text-align: right;
}

/* --- 错误 --- */
.km-task-error {
  font-size: 11px;
  color: #f87171;
  margin: 4px 0 0;
}

/* --- 状态标签 --- */
.km-task-status {
  flex-shrink: 0;
}

.km-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
}

.km-status-badge.uploading {
  background: var(--accent-bg);
  color: var(--accent);
}

.km-status-badge.processing {
  background: rgba(240, 160, 96, 0.1);
  color: #f0a060;
}

.km-status-badge.failed {
  background: rgba(248, 113, 113, 0.1);
  color: #f87171;
}

.km-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.km-status-dot.pulse {
  animation: km-pulse 1.2s infinite;
}

@keyframes km-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}

/* --- 删除按钮 --- */
.km-task-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0.35;
  transition: all 0.15s;
}

.km-task-remove:hover:not(:disabled) {
  opacity: 1;
  color: #f87171;
  background: rgba(248, 113, 113, 0.1);
}

.km-task-remove:disabled {
  cursor: not-allowed;
  opacity: 0.15;
}

.km-remove-icon {
  width: 16px;
  height: 16px;
}

/* ============================================================
   空状态
   ============================================================ */
.km-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.km-empty-icon {
  width: 80px;
  height: 80px;
  color: var(--text);
  margin-bottom: 16px;
}

.km-empty-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-h);
  margin: 0 0 6px;
}

.km-empty-desc {
  font-size: 13px;
  color: var(--text);
  opacity: 0.5;
  margin: 0;
}

/* ============================================================
   移动端响应式适配（≤768px）
   ============================================================ */
@media (max-width: 768px) {
  .km-shell {
    padding: 20px 16px;
  }

  .km-dropzone {
    padding: 32px 20px;
  }

  .km-task-card {
    flex-wrap: wrap;
    gap: 10px;
    padding: 14px 16px;
  }

  .km-task-info {
    min-width: 100%;
  }
}
</style>
