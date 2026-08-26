export type DiffRow = {
  type: 'ctx' | 'add' | 'del'
  a: number | null
  b: number | null
  text: string
}

/** Minimal LCS line diff — files here are tiny. */
export function diffLines(a: string[], b: string[]): DiffRow[] {
  const n = a.length
  const m = b.length
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const rows: DiffRow[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: 'ctx', a: i + 1, b: j + 1, text: a[i] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ type: 'del', a: i + 1, b: null, text: a[i] })
      i++
    } else {
      rows.push({ type: 'add', a: null, b: j + 1, text: b[j] })
      j++
    }
  }
  while (i < n) rows.push({ type: 'del', a: ++i, b: null, text: a[i - 1] })
  while (j < m) rows.push({ type: 'add', a: null, b: ++j, text: b[j - 1] })
  return rows
}
