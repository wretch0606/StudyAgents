// ============================================================
// StudyAgents — 错题本状态管理（Pinia Store）
//
// 职责：
//   1. 持有错题列表（localStorage 持久化）
//   2. 提供 addEntry / removeEntry / clearAll 操作
//   3. 专项训练提交后自动沉淀低分答案（score < 80）
//
// 持久化策略：
//   - 写入：每次 mutation 后同步写入 localStorage
//   - 读取：Store 初始化时从 localStorage 恢复
//   - key: 'studyagents_wrongbook'
// ============================================================

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ============================================================
// 类型定义
// ============================================================

/** 单条错题记录 */
export interface WrongBookEntry {
  /** 唯一 ID（时间戳 + 随机数） */
  id: string
  /** 章节 key（ch3 / ch4 / ch5） */
  chapter: string
  /** 章节中文标签 */
  chapterLabel: string
  /** 题目题干（含 LaTeX 标记） */
  question: string
  /** 用户原始作答（含 LaTeX 标记） */
  userAnswer: string
  /** 评测得分 */
  score: number
  /** 满分 */
  total: number
  /** 评测分析文本 */
  analysis: string
  /** 评测细项（✅ / ⚠️ / 📝） */
  highlights: string[]
  /** 创建时间 ISO 字符串 */
  createdAt: string
}

// ============================================================
// localStorage 读写工具
// ============================================================

const STORAGE_KEY = 'studyagents_wrongbook'

function loadFromStorage(): WrongBookEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
  } catch {
    return []
  }
}

function saveToStorage(entries: WrongBookEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries))
  } catch {
    // localStorage 满或不可用，静默降级
    console.warn('[useWrongBookStore] localStorage 写入失败')
  }
}

// ============================================================
// Store 定义
// ============================================================

export const useWrongBookStore = defineStore('wrongBook', () => {
  // ==========================================================
  // State
  // ==========================================================

  /** 错题列表（从 localStorage 恢复） */
  const entries = ref<WrongBookEntry[]>(loadFromStorage())

  // ==========================================================
  // Getters
  // ==========================================================

  /** 错题总数 */
  const count = computed(() => entries.value.length)

  /** 各章节错题数 */
  const countByChapter = computed(() => {
    const map: Record<string, number> = {}
    for (const e of entries.value) {
      map[e.chapter] = (map[e.chapter] || 0) + 1
    }
    return map
  })

  /** 按时间倒序排列（最新在前） */
  const sortedEntries = computed(() =>
    [...entries.value].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    ),
  )

  // ==========================================================
  // Actions
  // ==========================================================

  /**
   * 添加一条错题记录。
   * 自动生成 id 和 createdAt。
   */
  function addEntry(entry: Omit<WrongBookEntry, 'id' | 'createdAt'>): void {
    const newEntry: WrongBookEntry = {
      ...entry,
      id: `wb-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      createdAt: new Date().toISOString(),
    }
    entries.value.push(newEntry)
    saveToStorage(entries.value)
  }

  /**
   * 删除指定错题。
   */
  function removeEntry(id: string): void {
    entries.value = entries.value.filter((e) => e.id !== id)
    saveToStorage(entries.value)
  }

  /**
   * 清空全部错题。
   */
  function clearAll(): void {
    entries.value = []
    saveToStorage(entries.value)
  }

  // ==========================================================
  // 导出
  // ==========================================================

  return {
    // state
    entries,
    // getters
    count,
    countByChapter,
    sortedEntries,
    // actions
    addEntry,
    removeEntry,
    clearAll,
  }
})
