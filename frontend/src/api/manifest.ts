/**
 * 箱单对单接口封装。
 *
 * 列表页和详情页的“导出”都走 downloadManifest 同一个函数、打同一个后端口径，
 * 保证两处导出同一批数据对得上；后端按箱号稳定排序，重复下载字节也一致。
 */
import { request } from '@/api/client'

const ENDPOINT = '/api/manifests'

export type ManifestBatch = {
  id: number
  batch_no: string
  imported_rows: number
  skipped_rows: number[]
  merged_duplicates: number[]
  box_count: number
}

export type ManifestExport = {
  module: string
  batch_no: string
  columns: string[]
  statuses: string[]
  total: number
  items: Record<string, string | number | null>[]
  summary: { box_count: number; gross_total: number; net_total: number }
}

export type Reconciliation = {
  batch_count: number
  box_count: number
  gross_total: number
  net_total: number
  by_status: Record<string, number>
}

export type TemplateInfo = { columns: string[]; statuses: string[] }

export type ImportResult = {
  ok: boolean
  message: string
  entry?: Record<string, unknown>
}

export async function fetchTemplate(): Promise<TemplateInfo> {
  const response = await request(`${ENDPOINT}/template`)
  if (!response.ok) throw new Error('箱单模板读取失败')
  return response.json()
}

export async function fetchReconciliation(): Promise<Reconciliation> {
  const response = await request(`${ENDPOINT}/reconciliation`)
  if (!response.ok) throw new Error('对账合计读取失败')
  return response.json()
}

export async function listBatches(page = 1, size = 50): Promise<{ items: ManifestBatch[]; total: number }> {
  const response = await request(`${ENDPOINT}?page=${page}&size=${size}`)
  if (!response.ok) throw new Error('箱单批次列表读取失败')
  return response.json()
}

export async function getBatch(batchNo: string): Promise<ManifestBatch> {
  const response = await request(`${ENDPOINT}/${encodeURIComponent(batchNo)}`)
  if (!response.ok) throw new Error('箱单批次详情读取失败')
  return response.json()
}

/**
 * 导入一次箱单导出结果。
 * columns 取粘贴内容的表头行，行按表头名称在后端归位（串位列后端会整批打回）。
 */
export async function importManifest(
  batchNo: string,
  columns: string[],
  rows: (string | null)[][],
): Promise<ImportResult> {
  const response = await request(`${ENDPOINT}/import`, {
    method: 'POST',
    body: JSON.stringify({ batch_no: batchNo, columns, rows }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    return { ok: false, message: payload?.detail ?? '箱单导入失败，整批打回' }
  }
  return payload as ImportResult
}

/** 出单：按当前勾选的箱状态过滤；不勾传空数组表示全部状态。 */
export async function exportManifest(batchNo: string, statuses: string[]): Promise<ManifestExport> {
  const query = statuses.map((item) => `status=${encodeURIComponent(item)}`).join('&')
  const response = await request(`${ENDPOINT}/${encodeURIComponent(batchNo)}/export${query ? `?${query}` : ''}`)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(payload?.detail ?? '箱单导出失败')
  }
  return response.json()
}

function toCsvCell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** 两页共用的下载动作：同批、同勾选状态 ⇒ 下载内容逐条一致。 */
export async function downloadManifest(batchNo: string, statuses: string[]): Promise<void> {
  const manifest = await exportManifest(batchNo, statuses)
  const lines = [
    manifest.columns.map(toCsvCell).join(','),
    ...manifest.items.map((row) => manifest.columns.map((col) => toCsvCell(row[col])).join(',')),
  ]
  const blob = new Blob([`﻿${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  const scope = statuses.length ? `_${statuses.join('-')}` : ''
  anchor.download = `箱单_${batchNo}${scope}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

/**
 * 解析粘贴的箱单：第一行是表头，其余是数据行。
 * Excel 粘贴通常是 Tab 分隔，也兼容英文逗号；去掉文本框尾部的空行，
 * 中间的空行保留（后端会跳过并报行号）。
 */
export function parsePastedSheet(text: string): { columns: string[]; rows: (string | null)[][] } {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  if (!lines.length) return { columns: [], rows: [] }
  const splitLine = (line: string) => (line.includes('\t') ? line.split('\t') : line.split(','))
  const normalize = (cell: string) => {
    const value = cell.trim()
    return value === '' ? null : value
  }
  const columns = splitLine(lines[0]).map((cell) => cell.trim())
  const rows = lines.slice(1).map((line) => splitLine(line).map(normalize))
  return { columns, rows }
}
