<template>
  <div class="st-root">
    <!-- ======================================================== -->
    <!-- 页面标题                                              -->
    <!-- ======================================================== -->
    <div class="st-header">
      <h1 class="st-title">🧪 KaTeXEditor 组件测试台</h1>
      <p class="st-subtitle">
        验证：v-model 双向绑定 · 混合文本+公式解析 · displayMode 追踪 · 异常降级 · defineExpose API
      </p>
    </div>

    <!-- ======================================================== -->
    <!-- KaTeXEditor 组件实例                                    -->
    <!-- ======================================================== -->
    <section class="st-section">
      <h2 class="st-section-title">📐 公式编辑器</h2>
      <KaTeXEditor
        ref="editorRef"
        v-model="formulaText"
        :min-height="'280px'"
      />
    </section>

    <!-- ======================================================== -->
    <!-- 实时 renderedHtml 输出（验证 defineExpose）              -->
    <!-- ======================================================== -->
    <section class="st-section">
      <h2 class="st-section-title">🔍 renderedHtml 输出（defineExpose 验证）</h2>
      <div class="st-output-bar">
        <span class="st-output-label">editorRef.value.renderedHtml 当前值：</span>
        <span class="st-output-meta">{{ renderedLength }} 字符</span>
      </div>
      <pre class="st-pre"><code>{{ renderedHtmlPreview }}</code></pre>
    </section>

    <!-- ======================================================== -->
    <!-- 实时预览区（二次渲染，验证 HTML 可用性）                -->
    <!-- ======================================================== -->
    <section class="st-section">
      <h2 class="st-section-title">👁️ 渲染结果预览（二次 v-html）</h2>
      <div class="st-preview-box" v-html="renderedHtmlPreview" />
    </section>

    <!-- ======================================================== -->
    <!-- 原始输入对照                                          -->
    <!-- ======================================================== -->
    <section class="st-section">
      <h2 class="st-section-title">📝 原始输入（v-model 绑定值）</h2>
      <pre class="st-pre st-pre-raw"><code>{{ formulaText }}</code></pre>
    </section>
  </div>
</template>

<script setup lang="ts">
// ============================================================
// SpecialTraining — KaTeXEditor 专项测试页
// ============================================================

import { ref, computed } from 'vue'
import KaTeXEditor from '../components/KaTeXEditor.vue'

// ============================================================
// 组件引用 & 双向绑定
// ============================================================

const editorRef = ref<InstanceType<typeof KaTeXEditor>>()

const formulaText = ref(`# 多重积分与矩阵测试

## 1. 二重积分

$$
\\iint_D f(x, y)\\,dA = \\int_{a}^{b} \\int_{g_1(x)}^{g_2(x)} f(x, y)\\,dy\\,dx
$$

## 2. 三重积分（球坐标）

$$
\\iiint_E f(x, y, z)\\,dV = \\int_{0}^{2\\pi} \\int_{0}^{\\pi} \\int_{0}^{\\rho} f(\\rho, \\phi, \\theta)\\,\\rho^2 \\sin\\phi\\,d\\rho\\,d\\phi\\,d\\theta
$$

## 3. 2×2 矩阵

$$
A = \\begin{bmatrix}
a_{11} & a_{12} \\\\
a_{21} & a_{22}
\\end{bmatrix}
$$

## 4. 行内公式测试

已知 $E = mc^2$ 和 $a^2 + b^2 = c^2$，求 $\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}$。

## 5. 语法容错测试

故意写一个未闭合的括号：$\\frac{a + b{ = ?$

没闭合的块级：$$
\\begin{cases
x + y = 1 \\\\
`)

// ============================================================
// 实时读取 renderedHtml
// ============================================================

const renderedLength = computed(() => {
  const html = editorRef.value?.renderedHtml
  return html ? html.length : 0
})

const renderedHtmlPreview = computed(() => {
  return editorRef.value?.renderedHtml ?? '(等待编辑器初始化…)'
})
</script>

<style scoped>
/* ============================================================
   SpecialTraining — 测试页样式
   ============================================================ */

.st-root {
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 24px 80px;
  font-family: var(--sans, system-ui, sans-serif);
  color: var(--text-h, #08060d);
}

/* ---- 页面标题 ---- */

.st-header {
  margin-bottom: 36px;
  text-align: center;
}

.st-title {
  font-size: 32px;
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.5px;
}

.st-subtitle {
  font-size: 14px;
  color: var(--text, #6b6375);
  margin: 0;
}

/* ---- 区块 ---- */

.st-section {
  margin-bottom: 32px;
}

.st-section-title {
  font-size: 16px;
  font-weight: 700;
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border, #e5e4e7);
}

/* ---- 输出信息栏 ---- */

.st-output-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.st-output-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text, #6b6375);
}

.st-output-meta {
  font-size: 11px;
  font-family: var(--mono, monospace);
  color: var(--accent, #aa3bff);
}

/* ---- 代码块 ---- */

.st-pre {
  padding: 16px;
  border-radius: 8px;
  background: var(--code-bg, #f4f3ec);
  border: 1px solid var(--border, #e5e4e7);
  overflow-x: auto;
  overflow-y: auto;
  max-height: 320px;
  margin: 0;
}

.st-pre code {
  font-family: var(--mono, 'Courier New', monospace);
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-h, #08060d);
  background: none;
  padding: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.st-pre-raw {
  max-height: 400px;
}

/* ---- 二次渲染预览区 ---- */

.st-preview-box {
  padding: 20px 24px;
  border-radius: 8px;
  background: var(--bg, #fff);
  border: 1px solid var(--border, #e5e4e7);
  min-height: 60px;
  font-size: 15px;
  line-height: 1.75;
  color: var(--text-h, #08060d);
  overflow-x: auto;
}

/* :deep() 穿透预览区内 KaTeX 样式 */
.st-preview-box :deep(.katex-display) {
  margin: 12px 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.st-preview-box :deep(.katex) {
  font-size: 1.05em;
}

.st-preview-box :deep(.katex-error) {
  color: #dc2626 !important;
  border-bottom: 1px dashed #dc2626;
}

/* ---- 响应式 ---- */

@media (max-width: 768px) {
  .st-root {
    padding: 20px 12px 60px;
  }

  .st-title {
    font-size: 24px;
  }

  .st-section-title {
    font-size: 14px;
  }
}

/* ---- 深色模式 ---- */

@media (prefers-color-scheme: dark) {
  .st-preview-box {
    background: var(--bg, #16171d);
    border-color: var(--border, #2e303a);
    color: var(--text-h, #f3f4f6);
  }

  .st-pre {
    background: var(--code-bg, #1f2028);
    border-color: var(--border, #2e303a);
  }

  .st-pre code {
    color: var(--text-h, #f3f4f6);
  }

  .st-preview-box :deep(.katex-error) {
    color: #fca5a5 !important;
    border-bottom-color: #fca5a5;
  }
}
</style>
