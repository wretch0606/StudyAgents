// ============================================================
// StudyAgents — KaTeX 混合文本渲染工具
//
// 可被 KaTeXEditor 和任何需要渲染内联公式的视图复用。
//
// 用法：
//   import { renderMixedHtml } from '@/utils/katex-renderer'
//   const html = renderMixedHtml('慢启动公式 $cwnd_{n+1}=2 \\cdot cwnd_n$')
// ============================================================

import katex from 'katex'

// ============================================================
// 类型定义
// ============================================================

interface TextChunk {
  kind: 'text'
  content: string
}

interface MathChunk {
  kind: 'math'
  latex: string
  displayMode: boolean
}

type Chunk = TextChunk | MathChunk

// ============================================================
// 解析：将原始输入拆分为 text / math 交替序列
// ============================================================

/**
 * 规则（按优先级）：
 *   1. `$$...$$` → 块级公式（displayMode: true）
 *   2. `$...$`    → 行内公式（displayMode: false）
 *   3. 其余        → 纯文本
 *
 * 未闭合的 `$` 视为普通文本，不会导致解析异常。
 */
export function parseChunks(source: string): Chunk[] {
  // 先匹配 $$...$$（惰性），再匹配 $...$（单行内非贪婪）
  const regex = /(\$\$[\s\S]*?\$\$|\$[^$\n]+?\$)/g
  const chunks: Chunk[] = []

  let cursor = 0
  let m: RegExpExecArray | null

  while ((m = regex.exec(source)) !== null) {
    // 匹配前的纯文本
    if (m.index > cursor) {
      chunks.push({ kind: 'text', content: source.slice(cursor, m.index) })
    }

    const raw = m[0]
    if (raw.startsWith('$$') && raw.endsWith('$$')) {
      chunks.push({
        kind: 'math',
        latex: raw.slice(2, -2),
        displayMode: true,
      })
    } else if (raw.startsWith('$') && raw.endsWith('$')) {
      chunks.push({
        kind: 'math',
        latex: raw.slice(1, -1),
        displayMode: false,
      })
    } else {
      // 兜底：未闭合的单个 $ → 纯文本
      chunks.push({ kind: 'text', content: raw })
    }

    cursor = regex.lastIndex
  }

  // 尾部剩余纯文本
  if (cursor < source.length) {
    chunks.push({ kind: 'text', content: source.slice(cursor) })
  }

  return chunks
}

// ============================================================
// 渲染：单个公式 → KaTeX HTML
// ============================================================

/**
 * 调用 KaTeX 渲染单个公式。
 * throwOnError: false → 语法错误时 KaTeX 自行生成 .katex-error 标记，不抛异常。
 */
export function renderMath(latex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(latex, {
      output: 'html', // 只输出 HTML，抑制 MathML 后备文本
      displayMode,
      throwOnError: false,
      strict: false,
      trust: false,
    })
  } catch {
    return `<span class="katex-editor-error" title="公式渲染失败">⚠ 公式语法错误</span>`
  }
}

// ============================================================
// 工具函数
// ============================================================

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

// ============================================================
// 组合导出：渲染混合文本为 HTML
// ============================================================

/**
 * 将包含 $...$ / $$...$$ 的混合文本渲染为 HTML 字符串。
 *
 * 空 / 空白输入返回空字符串。
 *
 * @param source 包含可选 LaTeX 公式的原始文本
 * @returns 可直接用于 v-html 的 HTML 字符串
 */
export function renderMixedHtml(source: string): string {
  if (!source || !source.trim()) return ''

  const chunks = parseChunks(source)
  if (chunks.length === 0) return escapeHtml(source)

  const parts: string[] = []

  for (const c of chunks) {
    if (c.kind === 'text') {
      const escaped = escapeHtml(c.content)
      const withBreaks = escaped.replace(/\n/g, '<br>')
      parts.push(`<span class="ke-text-span">${withBreaks}</span>`)
    } else {
      parts.push(renderMath(c.latex, c.displayMode))
    }
  }

  return parts.join('')
}
