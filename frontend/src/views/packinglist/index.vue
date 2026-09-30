<template>
  <section class="page" data-module="packinglist">
    <header class="page-head">
      <div>
        <h2>箱单对单</h2>
        <p class="page-desc">按模板列序校正箱单：空行跳过、同箱号只认第一次、空毛重不灌 0；出单按勾选箱状态，带危品等级与铅封号。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="backToList" v-if="currentBatch">返回批次列表</button>
      </div>
    </header>

    <!-- 对账看板：合计数随已落库箱单实时重算 -->
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <!-- 批次列表视图 -->
    <template v-if="!currentBatch">
      <section class="import-panel">
        <h3>导入校正</h3>
        <p class="muted">模板列序：{{ templateColumns.join('、') }}（表头第 1 行，列序对不上整批打回）。可粘贴 Tab/逗号分隔的行，空行会跳过并记录行号。</p>
        <div class="filter-bar">
          <label class="filter-item" style="flex:0 0 220px">
            <span>批次号（同一次导出归并键）</span>
            <input v-model="batchNo" placeholder="例如 EXP-20260930-01" />
          </label>
        </div>
        <textarea v-model="rawText" class="import-textarea" rows="7"
          placeholder="可直接粘含表头或不含表头的数据行，例如：&#10;CBHU1234567,20GP,COSU,18500,3000,SL-0001,,在场&#10;,,,,,,,&#10;TRLU7654321,40HC,MAEU,,4200,SL-0002,3,已装船"></textarea>
        <div class="filter-bar">
          <label class="filter-item" style="flex:0 0 auto;flex-direction:row;align-items:center;gap:6px">
            <input type="checkbox" v-model="firstRowHeader" style="width:auto" />
            <span>首行是表头（已按模板对齐则忽略）</span>
          </label>
          <button class="btn primary" type="button" @click="submitImport">导入并校正</button>
        </div>
        <p v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</p>
      </section>

      <h3>已导出批次</h3>
      <table class="data-table">
        <thead>
          <tr><th>#</th><th>批次号</th><th>箱数</th><th>毛重合计</th><th>跳过行号</th><th>批内重复</th><th>历史重复</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td>{{ b.id }}</td>
            <td>{{ b.batch_no }}</td>
            <td>{{ b.accepted_count }}</td>
            <td>{{ b.gross_total }}</td>
            <td>{{ fmtLines(b.skipped_lines) }}</td>
            <td>{{ fmtDup(b.duplicate_in_batch) }}</td>
            <td>{{ fmtDup(b.duplicate_prior) }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDetail(b.id)">详情</button>
              <button class="link" type="button" @click="downloadExport(b.id)">出单</button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="8" class="empty-state">暂无批次，先导入一批箱单</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- 批次详情视图：导出与列表页同一出口 -->
    <template v-else>
      <section class="import-panel">
        <h3>批次 {{ currentBatch.batch_no }} · 出单</h3>
        <div class="filter-bar">
          <label v-for="s in statuses" :key="s" class="filter-item" style="flex:0 0 auto;flex-direction:row;align-items:center;gap:6px">
            <input type="checkbox" :value="s" v-model="pickedStatuses" style="width:auto" />
            <span>{{ s }}</span>
          </label>
          <button class="btn" type="button" @click="pickedStatuses=[]">不限状态</button>
          <button class="btn primary" type="button" @click="downloadExport(currentBatch.id)">按勾选状态出单</button>
        </div>
        <p v-if="exportInfo" class="ok-text">出单 {{ exportInfo.total }} 条；校验指纹 {{ exportInfo.checksum.slice(0, 12) }}…（同批再导逐条一致）</p>

        <p v-if="currentBatch.skipped_lines.length" class="muted">空值行已跳过（物理行号）：{{ fmtLines(currentBatch.skipped_lines) }}</p>
        <p v-if="Object.keys(currentBatch.duplicate_in_batch).length" class="muted">批内重复箱号：{{ fmtDup(currentBatch.duplicate_in_batch) }}</p>
        <p v-if="Object.keys(currentBatch.duplicate_prior).length" class="muted">更早批次已存在、本次忽略：{{ fmtDup(currentBatch.duplicate_prior) }}</p>

        <table class="data-table">
          <thead>
            <tr><th v-for="col in templateColumns" :key="col">{{ col }}</th><th>来源行</th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in detailRows" :key="row.箱号 + '_' + i">
              <td v-for="col in templateColumns" :key="col">{{ row[col] === null || row[col] === '' ? '—' : row[col] }}</td>
              <td>{{ row.source_line }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Cell = string | number | null
type BatchSummary = {
  id: number
  batch_no: string
  accepted_count: number
  gross_total: number
  skipped_lines: number[]
  duplicate_in_batch: Record<string, number[]>
  duplicate_prior: Record<string, number[]>
}
type Reconciliation = {
  box_count: number
  gross_total: number
  dangerous_boxes: number
  missing_seal_boxes: number
  by_status: Record<string, number>
  batch_count: number
}
type BatchDetail = {
  id: number
  batch_no: string
  rows: Record<string, Cell>[]
  skipped_lines: number[]
  duplicate_in_batch: Record<string, number[]>
  duplicate_prior: Record<string, number[]>
}

const ENDPOINT = '/api/packinglist'
const templateColumns = ref<string[]>([])
const statuses = ref<string[]>([])

const batches = ref<BatchSummary[]>([])
const currentBatch = ref<BatchDetail | null>(null)
const detailRows = ref<Record<string, Cell>[]>([])
const recon = ref<Reconciliation | null>(null)
const exportInfo = ref<{ total: number; checksum: string } | null>(null)

const rawText = ref('')
const batchNo = ref('')
const firstRowHeader = ref(true)
const pickedStatuses = ref<string[]>([])
const message = ref('')
const messageOk = ref(false)

const cards = computed(() => {
  const r = recon.value
  return [
    { label: '已导出批次', value: r?.batch_count ?? 0 },
    { label: '在册箱量', value: r?.box_count ?? 0 },
    { label: '毛重合计', value: r?.gross_total ?? 0 },
    { label: '危品箱', value: r?.dangerous_boxes ?? 0 },
    { label: '缺铅封', value: r?.missing_seal_boxes ?? 0 },
    { label: '在场 / 已装船', value: r ? `${r.by_status['在场'] ?? 0} / ${r.by_status['已装船'] ?? 0}` : '0 / 0' },
  ]
})

function splitLines(text: string): string[][] {
  return text
    .split(/\r?\n/)
    .filter((line, idx, arr) => !(idx === arr.length - 1 && line.trim() === ''))
    .map((line) => (line.includes('\t') ? line.split('\t') : line.split(',')))
    .map((cells) => cells.map((c) => c.trim()))
}

async function submitImport() {
  message.value = ''
  exportInfo.value = null
  if (!batchNo.value.trim()) {
    messageOk.value = false
    message.value = '请先填写批次号'
    return
  }
  let lines = splitLines(rawText.value)
  if (firstRowHeader.value && lines.length) {
    lines = lines.slice(1)
  }
  try {
    const res = await request(`${ENDPOINT}/batches/import`, {
      method: 'POST',
      body: JSON.stringify({ batch_no: batchNo.value.trim(), columns: templateColumns.value, rows: lines }),
    })
    const data = await res.json()
    if (!res.ok) {
      messageOk.value = false
      message.value = data?.detail?.message ? `整批打回：${data.detail.message}` : '导入失败'
      return
    }
    messageOk.value = true
    const dup = Object.keys(data.duplicate_in_batch || {}).length
    const prior = Object.keys(data.duplicate_prior || {}).length
    message.value = `${data.reused ? '该批次已存在，返回首份结果' : '校正完成'}：收 ${data.accepted_count} 箱，跳过空行 ${data.skipped_lines.length} 行，批内重复 ${dup} 箱，历史重复 ${prior} 箱`
    rawText.value = ''
    await reloadAll()
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '导入失败'
  }
}

async function downloadExport(batchId: number) {
  message.value = ''
  try {
    const qs = pickedStatuses.value.map((s) => `status=${encodeURIComponent(s)}`).join('&')
    const res = await request(`${ENDPOINT}/batches/${batchId}/export${qs ? `?${qs}` : ''}`)
    const data = await res.json()
    if (!res.ok) {
      messageOk.value = false
      message.value = data?.detail?.message || '出单失败'
      return
    }
    exportInfo.value = { total: data.total, checksum: data.checksum }
    // 列表页与详情页同一出口：下载内容即接口返回，逐条一致
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `packinglist_${data.batch_no}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '出单失败'
  }
}

async function openDetail(batchId: number) {
  message.value = ''
  exportInfo.value = null
  pickedStatuses.value = []
  try {
    const res = await request(`${ENDPOINT}/batches/${batchId}`)
    const data = await res.json()
    if (!res.ok) {
      messageOk.value = false
      message.value = data?.detail?.message || '详情读取失败'
      return
    }
    currentBatch.value = data
    detailRows.value = data.rows || []
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '详情读取失败'
  }
}

function backToList() {
  currentBatch.value = null
  detailRows.value = []
  void reloadAll()
}

function fmtLines(lines: number[]): string {
  return lines.length ? lines.join('、') : '—'
}

function fmtDup(map: Record<string, number[]>): string {
  const keys = Object.keys(map)
  if (!keys.length) return '—'
  return keys.map((k) => `${k}（行 ${map[k].join('/')}）`).join('；')
}

async function reloadAll() {
  const [tpl, listRes, recRes] = await Promise.all([
    request(`${ENDPOINT}/template`),
    request(`${ENDPOINT}/batches`),
    request(`${ENDPOINT}/reconciliation`),
  ])
  const template = await tpl.json()
  templateColumns.value = template.columns
  statuses.value = template.statuses
  const list = await listRes.json()
  batches.value = list.items || []
  recon.value = await recRes.json()
}

onMounted(reloadAll)
</script>

<style scoped>
.import-panel {
  background: var(--panel-bg, #fff);
  border: 1px solid #e6e8ec;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 20px;
}
.import-textarea {
  width: 100%;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  padding: 10px;
  border: 1px solid #d4d7dd;
  border-radius: 8px;
  box-sizing: border-box;
}
.muted { color: #7a818d; font-size: 13px; }
.ok-text { color: #1a7f4b; }
</style>
