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
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "航次计划", "created": 0, "pending": 0, "abnormal": 0}, {"name": "站位布设", "created": 0, "pending": 0, "abnormal": 0}, {"name": "设备清单", "created": 0, "pending": 0, "abnormal": 0}, {"name": "采样记录", "created": 0, "pending": 0, "abnormal": 0}, {"name": "水文测量", "created": 0, "pending": 0, "abnormal": 0}, {"name": "生物拖网", "created": 0, "pending": 0, "abnormal": 0}, {"name": "沉积物采样", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据质控", "created": 0, "pending": 0, "abnormal": 0}, {"name": "队员排班", "created": 0, "pending": 0, "abnormal": 0}, {"name": "气象观测", "created": 0, "pending": 0, "abnormal": 0}, {"name": "样品登记", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析申请", "created": 0, "pending": 0, "abnormal": 0}, {"name": "航次日志", "created": 0, "pending": 0, "abnormal": 0}, {"name": "仪器校准", "created": 0, "pending": 0, "abnormal": 0}, {"name": "潜水作业", "created": 0, "pending": 0, "abnormal": 0}, {"name": "值班确认", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据传输", "created": 0, "pending": 0, "abnormal": 0}, {"name": "航迹记录", "created": 0, "pending": 0, "abnormal": 0}, {"name": "成果汇编", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
