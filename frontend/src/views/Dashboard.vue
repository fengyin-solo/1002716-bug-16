<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>

    <h3 style="margin: 16px 0 8px">箱单对账合计（随已导入箱单实时重算）</h3>
    <div class="stat-row">
      <article v-for="card in reconcileCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>箱状态</th><th>箱量</th></tr>
      </thead>
      <tbody>
        <tr v-for="(count, status) in reconciliation?.by_status ?? {}" :key="status">
          <td>{{ status }}</td>
          <td>{{ count }}</td>
        </tr>
      </tbody>
    </table>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'

import { fetchJson } from '@/api/client'
import { fetchReconciliation, type Reconciliation } from '@/api/manifest'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const reconciliation = ref<Reconciliation | null>(null)

const reconcileCards = computed(() => {
  const rec = reconciliation.value
  return [
    { label: '箱单批次', value: rec?.batch_count ?? 0 },
    { label: '归并后总箱量', value: rec?.box_count ?? 0 },
    { label: '毛重合计', value: rec?.gross_total ?? 0 },
    { label: '净重合计', value: rec?.net_total ?? 0 },
  ]
})

onMounted(async () => {
  const [overview, rec] = await Promise.all([
    fetchJson<Overview>('/api/overview').catch(() => null),
    fetchReconciliation().catch(() => null),
  ])
  if (overview) {
    cards.value = overview.cards
    moduleRows.value = overview.modules
  } else {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
  }
  reconciliation.value = rec
})
</script>
