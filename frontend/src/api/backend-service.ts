import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type { ActionResult, EntryRow, OverviewResult, PageResult } from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export type ActionContext = {
  operator?: string
  role?: string
  scheduleId?: number
}

export async function runAction(
  key: string,
  id: number,
  action: string,
  context: ActionContext = {},
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      operator: context.operator || null,
      role: context.role || null,
      schedule_id: context.scheduleId ?? null,
    }),
  })
  return await response.json()
}

export type OperationLog = {
  id: number
  time: string
  module: string
  entry_id: number | null
  action: string
  result: string
  shift: string | null
  operator: string | null
  role: string | null
  schedule_id: number | null
  message: string
  can_continue?: string[]
  need_resign?: string[]
}

export async function fetchOperationLogs(
  filters: Record<string, string> = {},
): Promise<OperationLog[]> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/operation-logs?${query}`)
  if (!response.ok) throw new Error('操作日志读取失败')
  const payload = await response.json()
  return payload.items ?? []
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export async function fetchSnapshot(key: string): Promise<Record<string, any>> {
  const response = await request(`/api/snapshot/${key}`)
  if (!response.ok) throw new Error('跨模块快照读取失败')
  return await response.json()
}
