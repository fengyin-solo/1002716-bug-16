<template>
  <section class="page" data-module="manifest-detail">
    <header class="page-head">
      <div>
        <h2>箱单批次 {{ batch?.batch_no ?? batchNo }}</h2>
        <p class="page-desc">
          导出的是入库时的冻结快照：同一批重复导出逐条一样；列表页与本页共用同一导出口径。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" :to="{ name: 'manifest' }">返回批次列表</RouterLink>
      </div>
    </header>

    <div v-if="batch" class="stat-row">
      <article class="stat-card">
        <span class="stat-label">归并后箱量</span>
        <strong class="stat-value">{{ batch.box_count }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">跳过空值行</span>
        <strong class="stat-value">{{ batch.skipped_rows.length ? `第 ${batch.skipped_rows.join('、')} 行` : '无' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">同箱号归并行</span>
        <strong class="stat-value">{{ batch.merged_duplicates.length ? `第 ${batch.merged_duplicates.join('、')} 行` : '无' }}</strong>
      </article>
    </div>

    <div class="filter-bar">
      <span class="filter-item"><span>出单箱状态（不勾为全部）</span></span>
      <label v-for="status in statuses" :key="status" class="filter-item" style="flex-direction: row; gap: 6px">
        <input type="checkbox" :value="status" v-model="selectedStatuses" style="width: auto" />
        <span>{{ status }}</span>
      </label>
      <button class="btn ghost" type="button" @click="selectedStatuses = []">全不勾</button>
      <button class="btn primary" type="button" @click="exportOne">导出箱单</button>
    </div>

    <p v-if="message" class="error-text">{{ message }}</p>

    <table v-if="exportData" class="data-table">
      <thead>
        <tr>
          <th v-for="column in exportData.columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in exportData.items" :key="String(row['箱号']) + index">
          <td v-for="column in exportData.columns" :key="column">{{ row[column] ?? (column === '毛重' || column === '净重' ? '空（未计合计）' : '—') }}</td>
        </tr>
        <tr v-if="!exportData.items.length">
          <td :colspan="exportData.columns.length" class="empty-state">当前勾选的箱状态下没有箱</td>
        </tr>
      </tbody>
    </table>

    <footer v-if="exportData" class="page-foot">
      <span>
        出单 {{ exportData.summary.box_count }} 箱 · 毛重合计 {{ exportData.summary.gross_total }} ·
        净重合计 {{ exportData.summary.net_total }}
      </span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import {
  downloadManifest,
  exportManifest,
  fetchTemplate,
  getBatch,
  type ManifestBatch,
  type ManifestExport,
} from '@/api/manifest'

const route = useRoute()
const batchNo = String(route.params.batchNo)

const batch = ref<ManifestBatch | null>(null)
const exportData = ref<ManifestExport | null>(null)
const statuses = ref<string[]>([])
const selectedStatuses = ref<string[]>([])
const message = ref('')

async function refreshExport() {
  message.value = ''
  try {
    exportData.value = await exportManifest(batchNo, selectedStatuses.value)
  } catch (error) {
    message.value = error instanceof Error ? error.message : '箱单读取失败'
  }
}

async function exportOne() {
  message.value = ''
  try {
    // 与列表页完全相同的下载函数和接口，保证两处对上。
    await downloadManifest(batchNo, selectedStatuses.value)
    await refreshExport()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '箱单导出失败'
  }
}

watch(selectedStatuses, () => {
  void refreshExport()
})

onMounted(async () => {
  const [template, batchInfo] = await Promise.all([fetchTemplate(), getBatch(batchNo)])
  statuses.value = template.statuses
  batch.value = batchInfo
  await refreshExport()
})
</script>
