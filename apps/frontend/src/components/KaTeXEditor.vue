<template>
  <div class="katex-editor">
    <!-- ======================================================== -->
    <!-- 左侧：编辑区                                            -->
    <!-- ======================================================== -->
    <div class="ke-pane ke-pane-input">
      <div class="ke-pane-header">
        <span class="ke-pane-label">📝 编辑区</span>
        <span class="ke-pane-hint">$…$ 行内 &nbsp;|&nbsp; $$…$$ 块级</span>
      </div>
      <textarea
        v-model="rawText"
        :placeholder="placeholder"
        :style="{ minHeight }"
        :readonly="readonly"
        class="ke-textarea"
        spellcheck="false"
        autocomplete="off"
        autocorrect="off"
        autocapitalize="off"
      />
      <div v-if="!readonly" class="ke-pane-footer">
        <span>{{ charCount }} 字符</span>
      </div>
    </div>

    <!-- ======================================================== -->
    <!-- 右侧：实时预览区                                        -->
    <!-- ======================================================== -->
    <div class="ke-pane ke-pane-preview">
      <div class="ke-pane-header">
        <span class="ke-pane-label">🔍 实时预览</span>
        <span class="ke-pane-badge">KaTeX</span>
      </div>
      <div class="ke-preview-body" v-html="renderedHtml" />
    </div>
  </div>
</template>

<script setup lang="ts">
// ============================================================
// StudyAgents — KaTeXEditor
// 文本 + LaTeX 混合输入，实时 KaTeX 预览，异常降级
//
// 父组件用法：
//   <KaTeXEditor ref="editorRef" v-model="raw" />
//   const html = editorRef.value.renderedHtml
// ============================================================

import { computed } from 'vue'
import 'katex/dist/katex.min.css'
import { renderMixedHtml } from '../utils/katex-renderer'

// ============================================================
// Props & Emits
// ============================================================

const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    minHeight?: string
    /** 只读模式（提交后锁定编辑器） */
    readonly?: boolean
  }>(),
  {
    modelValue: '',
    placeholder:
      '在此输入文本 + LaTeX 公式…\n\n行内公式：$E = mc^2$\n块级公式：\n$$\n\\int_{a}^{b} f(x)\\,dx\n$$',
    minHeight: '240px',
    readonly: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

// ============================================================
// v-model 双向绑定
// ============================================================

const rawText = computed({
  get: () => props.modelValue,
  set: (val: string) => emit('update:modelValue', val),
})

// ============================================================
// 解析 → 渲染 管线（复用 katex-renderer.ts 共享工具）
// ============================================================

const renderedHtml = computed<string>(() => {
  const src = rawText.value
  if (!src.trim()) {
    return '<p class="ke-empty-hint">在左侧输入内容，预览将实时显示在此…</p>'
  }
  return renderMixedHtml(src) || '<p class="ke-empty-hint">在左侧输入内容，预览将实时显示在此…</p>'
})

// ============================================================
// 字符计数
// ============================================================

const charCount = computed(() => rawText.value.length)

// ============================================================
// 暴露给父组件
// ============================================================

defineExpose({
  /** 渲染后的 HTML 字符串（可直接用于 v-html） */
  renderedHtml,
  /** 当前字符数 */
  charCount,
})
</script>

<style scoped>
/* ============================================================
   组件根容器
   ============================================================ */

.katex-editor {
  display: flex;
  gap: 16px;
  width: 100%;
  font-family: var(--sans, system-ui, sans-serif);
}

/* 移动端：上下堆叠 */
@media (max-width: 768px) {
  .katex-editor {
    flex-direction: column;
    gap: 12px;
  }
}

/* ============================================================
   面板通用
   ============================================================ */

.ke-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.ke-pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.ke-pane-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-h, #08060d);
}

.ke-pane-hint {
  font-size: 11px;
  color: var(--text, #6b6375);
  opacity: 0.6;
  font-family: var(--mono, monospace);
}

.ke-pane-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--accent-bg, rgba(170, 59, 255, 0.1));
  color: var(--accent, #aa3bff);
  font-family: var(--mono, monospace);
  letter-spacing: 0.5px;
}

.ke-pane-footer {
  margin-top: 6px;
  text-align: right;
  font-size: 11px;
  color: var(--text, #6b6375);
  opacity: 0.5;
}

/* ============================================================
   textarea 编辑区
   ============================================================ */

.ke-textarea {
  flex: 1;
  width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--border, #e5e4e7);
  border-radius: 10px;
  background: var(--bg, #fff);
  color: var(--text-h, #08060d);
  font-family: var(--mono, 'Courier New', monospace);
  font-size: 14px;
  line-height: 1.65;
  resize: vertical;
  outline: none;
  box-sizing: border-box;
  tab-size: 2;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.ke-textarea:focus {
  border-color: var(--accent, #aa3bff);
  box-shadow: 0 0 0 3px var(--accent-bg, rgba(170, 59, 255, 0.1));
}

.ke-textarea::placeholder {
  color: var(--text, #6b6375);
  opacity: 0.4;
}

/* ============================================================
   预览区
   ============================================================ */

.ke-preview-body {
  flex: 1;
  padding: 14px 16px;
  border: 1px solid var(--border, #e5e4e7);
  border-radius: 10px;
  background: var(--code-bg, #f4f3ec);
  overflow-y: auto;
  font-size: 15px;
  line-height: 1.75;
  color: var(--text-h, #08060d);
  word-wrap: break-word;
  box-sizing: border-box;
}

/* ============================================================
   预览区内部元素（v-html → :deep() 穿透 scoped）
   ============================================================ */

:deep(.ke-empty-hint) {
  color: var(--text, #6b6375);
  opacity: 0.5;
  font-style: italic;
  margin: 0;
  text-align: center;
  padding-top: 48px;
}

:deep(.ke-text-span) {
  white-space: pre-wrap;
}

/* ---- KaTeX 渲染微调 ---- */

:deep(.katex) {
  font-size: 1.05em;
  line-height: 1.2;
}

:deep(.katex-display) {
  margin: 12px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

:deep(.katex-display > .katex) {
  white-space: nowrap;
}

/* ---- KaTeX throwOnError: false 时的内置错误标记 ---- */

:deep(.katex-error) {
  color: #dc2626 !important;
  border-bottom: 1px dashed #dc2626;
}

/* ---- 自定义降级错误标签（catch 兜底） ---- */

:deep(.katex-editor-error) {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(248, 113, 113, 0.12);
  color: #dc2626;
  font-size: 0.9em;
  font-weight: 600;
  border: 1px dashed rgba(248, 113, 113, 0.4);
  cursor: help;
}

/* ============================================================
   深色模式
   ============================================================ */

@media (prefers-color-scheme: dark) {
  .ke-textarea {
    background: var(--bg, #16171d);
    color: var(--text-h, #f3f4f6);
    border-color: var(--border, #2e303a);
  }

  .ke-preview-body {
    background: var(--code-bg, #1f2028);
    color: var(--text-h, #f3f4f6);
    border-color: var(--border, #2e303a);
  }

  :deep(.katex-error) {
    color: #fca5a5 !important;
    border-bottom-color: #fca5a5;
  }

  :deep(.katex-editor-error) {
    background: rgba(248, 113, 113, 0.18);
    color: #fca5a5;
    border-color: rgba(248, 113, 113, 0.5);
  }
}
</style>
