<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">海洋科考航次管理系统</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">首席科学家、调查队员和船长共同规划航次站位，记录海洋观测数据，签认样品移交后按标准流程归档。</span>
        <span class="head-user">当前值班：应用开发组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "航次计划", path: "/cruise_plan" }, { label: "站位布设", path: "/station_deploy" }, { label: "设备清单", path: "/equipment_manifest" }, { label: "采样记录", path: "/sampling_record" }, { label: "水文测量", path: "/hydro_measure" }, { label: "生物拖网", path: "/bio_trawl" }, { label: "沉积物采样", path: "/sediment_sample" }, { label: "数据质控", path: "/data_qc" }, { label: "队员排班", path: "/crew_schedule" }, { label: "气象观测", path: "/weather_obs" }, { label: "样品登记", path: "/sample_registry" }, { label: "分析申请", path: "/analysis_request" }, { label: "航次日志", path: "/cruise_log" }, { label: "仪器校准", path: "/instrument_calib" }, { label: "潜水作业", path: "/diving_ops" }, { label: "值班确认", path: "/duty_confirmation" }, { label: "数据传输", path: "/data_transfer" }, { label: "航迹记录", path: "/track_record" }, { label: "成果汇编", path: "/results_compile" }]
</script>
