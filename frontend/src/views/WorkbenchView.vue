<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="meta.key === 'duty_confirmation'" class="signoff-bar" data-testid="signoff-bar">
      <label class="filter-item">
        <span>办理人（排班本人姓名）</span>
        <input v-model="signContext.operator" data-testid="sign-operator" placeholder="如：张涛" />
      </label>
      <label class="filter-item">
        <span>所持排班ID</span>
        <input v-model.number="signContext.scheduleId" data-testid="sign-schedule-id" placeholder="如：5" inputmode="numeric" />
      </label>
      <p class="signoff-hint">岗位签认只认排班本人：请选择与动作角色、作业时段匹配的排班行ID，同名队员不能代签。</p>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button v-for="action in meta.actions" :key="action" class="link" type="button"
              :data-testid="`action-${row.id}-${action}`" @click="runAction(action, row)">{{ action }}</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">暂无{{ meta.name }}数据，可先登记{{ meta.entity }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showOperationLogs" class="log-panel" data-testid="operation-log-panel">
      <div class="log-head">
        <h3>值班核验操作日志</h3>
        <button class="btn ghost" type="button" @click="reloadLogs">刷新日志</button>
      </div>
      <table class="data-table log-table">
        <thead>
          <tr><th>时间</th><th>结果</th><th>动作</th><th>办理人/岗位</th><th>说明（谁可继续 / 谁需补签）</th></tr>
        </thead>
        <tbody>
          <tr v-for="log in operationLogs" :key="log.id" :data-result="log.result">
            <td>{{ log.time }}</td>
            <td>{{ log.result }}</td>
            <td>{{ log.action }}</td>
            <td>{{ log.operator || '—' }}<span v-if="log.role"> / {{ log.role }}</span></td>
            <td class="log-message">
              {{ log.message }}
              <span v-if="log.can_continue?.length" class="log-continue">可继续：{{ log.can_continue.join('；') }}</span>
              <span v-if="log.need_resign?.length" class="log-resign">需补签：{{ log.need_resign.join('；') }}</span>
            </td>
          </tr>
          <tr v-if="!operationLogs.length">
            <td colspan="5" class="empty-state">暂无值班核验操作日志</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}<em v-if="systemFields.has(field)" class="system-tag">系统生成/选填</em></span>
          <input
            v-model="createValues[field]"
            :data-testid="`create-${field}`"
            :required="!systemFields.has(field)"
            :placeholder="systemFields.has(field) ? '由系统按规则生成，可留空' : ''"
          />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  createEntry,
  downloadEntries,
  fetchOperationLogs,
  listEntries,
  moduleMeta,
  runAction as applyAction,
  type OperationLog,
} from '@/api/backend-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const signContext = ref<{ operator: string; scheduleId: number | null }>({ operator: '', scheduleId: null })
const operationLogs = ref<OperationLog[]>([])

// 值班确认单与潜水作业需要展示值班核验操作日志
const showOperationLogs = computed(() =>
  props.moduleKey === 'duty_confirmation' || props.moduleKey === 'diving_ops',
)

// 值班确认单的动作需要办理人+排班ID作为签认上下文
const needsSignContext = computed(() => props.moduleKey === 'duty_confirmation')
const roleByAction: Record<string, string> = {
  潜水员签认: '潜水员',
  安全员在途确认: '安全员',
  领队交接: '值班领队',
}

// 由后端按规则生成或非必填的字段，登记表单不强制填写
const SYSTEM_FIELDS: Record<string, string[]> = {
  duty_confirmation: ['确认单编号', '潜水员', '安全员', '值班领队', '关联排班', '备注说明'],
  diving_ops: ['值班确认单', '作业内容', '下水时间', '备注说明'],
}
const systemFields = computed(() => new Set(SYSTEM_FIELDS[props.moduleKey] ?? []))

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((r) => r.status === meta.statuses[1]).length },
  { label: meta.metrics[2], value: rows.value.filter((r) => r.status === meta.statuses[meta.statuses.length - 1]).length },
])

const statusSummary = computed(() =>
  meta.statuses.map((s) => ({ status: s, count: rows.value.filter((r) => String(r.status) === s).length })),
)

function resetFilters() { filters.value = {}; void reload() }

async function exportRows() {
  errorMessage.value = ''
  try { await downloadEntries(meta.key, filters.value) }
  catch (e) { errorMessage.value = e instanceof Error ? e.message : '导出失败' }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((f) => [f, '']))
  errorMessage.value = ''; showCreate.value = true
}

async function submitCreate() {
  creating.value = true; errorMessage.value = ''
  try {
    const r = await createEntry(meta.key, createValues.value)
    if (!r.ok) throw new Error(r.message)
    showCreate.value = false; await reload()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '登记失败' }
  finally { creating.value = false }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    let context = {}
    if (needsSignContext.value && action !== '核销确认单') {
      if (!signContext.value.operator.trim() || signContext.value.scheduleId == null) {
        throw new Error('值班签认必须填写办理人姓名和所持排班ID')
      }
      context = {
        operator: signContext.value.operator.trim(),
        role: roleByAction[action],
        scheduleId: Number(signContext.value.scheduleId),
      }
    } else if (needsSignContext.value && action === '核销确认单') {
      context = { operator: signContext.value.operator.trim() || '值班领队' }
    }
    const r = await applyAction(meta.key, Number(row.id), action, context)
    if (!r.ok) throw new Error(r.message)
    await reload()
    if (showOperationLogs.value) await reloadLogs()
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '操作失败' }
}

async function reloadLogs() {
  try {
    operationLogs.value = await fetchOperationLogs(
      showOperationLogs.value ? { module: props.moduleKey } : {},
    )
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '操作日志读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items; total.value = payload.total
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '业务列表读取失败' }
}

onMounted(() => {
  void reload()
  if (showOperationLogs.value) void reloadLogs()
})
</script>

<style scoped>
.modal-backdrop { position:fixed; inset:0; background:rgba(0,0,0,.35); display:flex; align-items:center; justify-content:center; z-index:100; }
.modal { background:#fff; border-radius:8px; padding:24px; width:480px; max-height:80vh; overflow-y:auto; }
.create-field { display:flex; flex-direction:column; gap:4px; margin-bottom:12px; }
.create-field span { font-size:13px; color:var(--text-secondary,#4a5568); }
.create-field input { padding:6px 8px; border:1px solid var(--border-color,#e2e8f0); border-radius:4px; font-size:13px; }
.system-tag { margin-left:6px; font-style:normal; font-size:11px; color:#3182ce; }
.signoff-bar { display:flex; flex-wrap:wrap; align-items:flex-end; gap:16px; padding:12px 16px; margin-bottom:12px; background:#f0f7ff; border:1px solid #bee3f8; border-radius:8px; }
.signoff-bar .filter-item { display:flex; flex-direction:column; gap:4px; }
.signoff-bar input { min-width:180px; padding:6px 8px; border:1px solid var(--border-color,#e2e8f0); border-radius:4px; font-size:13px; }
.signoff-hint { flex-basis:100%; margin:0; font-size:12px; color:var(--text-secondary,#4a5568); }
.log-panel { margin-top:20px; border-top:2px solid var(--border-color,#e2e8f0); padding-top:12px; }
.log-head { display:flex; align-items:center; justify-content:space-between; }
.log-table { font-size:12px; }
.log-message { max-width:520px; line-height:1.6; }
.log-continue, .log-resign { display:block; margin-top:2px; }
.log-continue { color:#2f855a; }
.log-resign { color:#c05621; }
.log-table tr[data-result='拒绝'], .log-table tr[data-result='冲突'] { background:#fff5f5; }
.log-table tr[data-result='核销'] { background:#fffff0; }
.log-table tr[data-result='通过'] { background:#f0fff4; }
</style>