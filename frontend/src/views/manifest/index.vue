<template>
  <section class="page" data-module="manifests">
    <header class="page-head">
      <div>
        <h2>箱单对单</h2>
        <p class="page-desc">
          按箱号归并同一次导出的箱单：空值行跳过并回行号，列序与模板不符整批打回，
          同一批次号重复提交只认第一次。出单按当前勾选的箱状态，危品等级、铅封号一并带出。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showImport = !showImport">
          {{ showImport ? '收起导入' : '导入箱单' }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showImport" class="filter-bar" style="flex-wrap: wrap; align-items: flex-start">
      <label class="filter-item">
        <span>批次号（同一次导出共用）</span>
        <input v-model="batchNo" placeholder="例如 B20260930-01" />
      </label>
      <div style="flex: 1 1 100%">
        <span class="filter-item"><span>粘贴箱单（首行须为模板表头，支持从 Excel 直接粘贴）</span></span>
        <textarea
          v-model="sheetText"
          rows="8"
          style="width: 100%; font-family: monospace"
          :placeholder="templateHint"
        ></textarea>
        <p style="margin: 4px 0; color: #888; font-size: 12px">
          当前解析到 {{ parsed.columns.length }} 列表头、{{ parsed.rows.length }} 行数据；
          列序必须与模板完全一致，否则整批打回。
        </p>
      </div>
      <button class="btn primary" type="button" :disabled="importing" @click="submitImport">
        {{ importing ? '导入中…' : '提交对单' }}
      </button>
      <button class="btn ghost" type="button" @click="fillSample">填入示例</button>
    </form>

    <div class="filter-bar">
      <span class="filter-item"><span>出单箱状态（勾选后对下方批次导出生效，不勾为全部）</span></span>
      <label v-for="status in template.statuses" :key="status" class="filter-item" style="flex-direction: row; gap: 6px">
        <input type="checkbox" :value="status" v-model="selectedStatuses" style="width: auto" />
        <span>{{ status }}</span>
      </label>
      <button class="btn ghost" type="button" @click="selectedStatuses = []">全不勾</button>
    </div>

    <p v-if="message" :class="importOk ? '' : 'error-text'" style="margin: 8px 0">{{ message }}</p>

    <table class="data-table">
      <thead>
        <tr>
          <th>批次号</th>
          <th>归并后箱量</th>
          <th>跳过空值行</th>
          <th>同箱号归并行</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="batch in batches" :key="batch.batch_no">
          <td><RouterLink :to="{ name: 'manifest-detail', params: { batchNo: batch.batch_no } }">{{ batch.batch_no }}</RouterLink></td>
          <td>{{ batch.box_count }}</td>
          <td>{{ batch.skipped_rows.length ? `第 ${batch.skipped_rows.join('、')} 行` : '—' }}</td>
          <td>{{ batch.merged_duplicates.length ? `第 ${batch.merged_duplicates.join('、')} 行` : '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="exportOne(batch.batch_no)">导出箱单</button>
          </td>
        </tr>
        <tr v-if="!batches.length">
          <td colspan="5" class="empty-state">还没有导入过箱单，点右上角“导入箱单”开始对单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 个箱单批次</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  downloadManifest,
  fetchReconciliation,
  fetchTemplate,
  importManifest,
  listBatches,
  parsePastedSheet,
  type ManifestBatch,
  type Reconciliation,
  type TemplateInfo,
} from '@/api/manifest'

const showImport = ref(false)
const importing = ref(false)
const batchNo = ref('')
const sheetText = ref('')
const message = ref('')
const importOk = ref(true)
const batches = ref<ManifestBatch[]>([])
const total = ref(0)
const reconciliation = ref<Reconciliation | null>(null)
const template = ref<TemplateInfo>({ columns: [], statuses: [] })
const selectedStatuses = ref<string[]>([])

const parsed = computed(() => parsePastedSheet(sheetText.value))
const templateHint = computed(() => template.value.columns.join('\t'))

const stats = computed(() => {
  const rec = reconciliation.value
  return [
    { label: '箱单批次', value: rec?.batch_count ?? 0 },
    { label: '归并后总箱量', value: rec?.box_count ?? 0 },
    { label: '毛重合计', value: rec?.gross_total ?? 0 },
    { label: '净重合计', value: rec?.net_total ?? 0 },
  ]
})

function fillSample() {
  batchNo.value = 'B20260930-01'
  sheetText.value = [
    template.value.columns.join('\t'),
    ['CBHU1234567', '22G1', 'CBHU', '21000', '19000', 'SEAL-001', '', '在场'].join('\t'),
    ['CBHU2345678', '42G1', 'MSKU', '', '18000', 'SEAL-002', '3', '已装船'].join('\t'),
    '',
    ['CBHU1234567', '22G1', 'CBHU', '21000', '19000', 'SEAL-001', '', '在场'].join('\t'),
  ].join('\n')
}

async function submitImport() {
  message.value = ''
  if (!batchNo.value.trim()) {
    importOk.value = false
    message.value = '批次号不能为空，无法按“同一次导出”归并'
    return
  }
  const { columns, rows } = parsed.value
  if (!columns.length) {
    importOk.value = false
    message.value = '没有读到表头：首行须为模板表头'
    return
  }
  importing.value = true
  try {
    const result = await importManifest(batchNo.value.trim(), columns, rows)
    importOk.value = result.ok
    if (result.ok) {
      sheetText.value = ''
      await reload()
    }
    message.value = result.message
  } finally {
    importing.value = false
  }
}

async function exportOne(batchNoValue: string) {
  message.value = ''
  try {
    await downloadManifest(batchNoValue, selectedStatuses.value)
  } catch (error) {
    importOk.value = false
    message.value = error instanceof Error ? error.message : '箱单导出失败'
  }
}

async function reload() {
  const [batchPage, rec] = await Promise.all([listBatches(), fetchReconciliation()])
  batches.value = batchPage.items
  total.value = batchPage.total
  reconciliation.value = rec
}

onMounted(async () => {
  template.value = await fetchTemplate()
  await reload()
})
</script>
