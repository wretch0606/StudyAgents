export type MarkdownTokenType = 'text' | 'strong' | 'code'

export interface MarkdownToken {
  type: MarkdownTokenType
  content: string
}

/**
 * Split the small supported Markdown subset into renderable tokens.
 *
 * The caller must render `content` with Vue text interpolation. Returning
 * tokens instead of HTML keeps user-controlled chat text out of `v-html`.
 */
export function tokenizeMarkdownLine(line: string): MarkdownToken[] {
  const tokens: MarkdownToken[] = []
  const inlinePattern = /(\*\*(.+?)\*\*|`([^`]+)`)/g
  let cursor = 0
  let match: RegExpExecArray | null

  while ((match = inlinePattern.exec(line)) !== null) {
    if (match.index > cursor) {
      tokens.push({
        type: 'text',
        content: line.slice(cursor, match.index),
      })
    }

    tokens.push({
      type: match[2] !== undefined ? 'strong' : 'code',
      content: match[2] ?? match[3] ?? '',
    })
    cursor = match.index + match[0].length
  }

  if (cursor < line.length) {
    tokens.push({
      type: 'text',
      content: line.slice(cursor),
    })
  }

  return tokens
}
