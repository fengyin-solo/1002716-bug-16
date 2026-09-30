import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Berth = () => import('@/views/berth/index.vue')
const Vessel = () => import('@/views/vessel/index.vue')
const Quaycrane = () => import('@/views/quaycrane/index.vue')
const Yardplan = () => import('@/views/yardplan/index.vue')
const Rtg = () => import('@/views/rtg/index.vue')
const Truck = () => import('@/views/truck/index.vue')
const Container = () => import('@/views/container/index.vue')
const Gate = () => import('@/views/gate/index.vue')
const Dangerous = () => import('@/views/dangerous/index.vue')
const Coldchain = () => import('@/views/coldchain/index.vue')
const Lashing = () => import('@/views/lashing/index.vue')
const Shift = () => import('@/views/shift/index.vue')
const Repair = () => import('@/views/repair/index.vue')
const Tally = () => import('@/views/tally/index.vue')
const Customs = () => import('@/views/customs/index.vue')
const Feeder = () => import('@/views/feeder/index.vue')
const Oog = () => import('@/views/oog/index.vue')
const Emptystack = () => import('@/views/emptystack/index.vue')
const Energy = () => import('@/views/energy/index.vue')
const Safetycheck = () => import('@/views/safetycheck/index.vue')
const Packinglist = () => import('@/views/packinglist/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/berth', name: 'berth', component: Berth },
    { path: '/vessel', name: 'vessel', component: Vessel },
    { path: '/quaycrane', name: 'quaycrane', component: Quaycrane },
    { path: '/yardplan', name: 'yardplan', component: Yardplan },
    { path: '/rtg', name: 'rtg', component: Rtg },
    { path: '/truck', name: 'truck', component: Truck },
    { path: '/container', name: 'container', component: Container },
    { path: '/gate', name: 'gate', component: Gate },
    { path: '/dangerous', name: 'dangerous', component: Dangerous },
    { path: '/coldchain', name: 'coldchain', component: Coldchain },
    { path: '/lashing', name: 'lashing', component: Lashing },
    { path: '/shift', name: 'shift', component: Shift },
    { path: '/repair', name: 'repair', component: Repair },
    { path: '/tally', name: 'tally', component: Tally },
    { path: '/customs', name: 'customs', component: Customs },
    { path: '/feeder', name: 'feeder', component: Feeder },
    { path: '/oog', name: 'oog', component: Oog },
    { path: '/emptystack', name: 'emptystack', component: Emptystack },
    { path: '/energy', name: 'energy', component: Energy },
    { path: '/safetycheck', name: 'safetycheck', component: Safetycheck },
    { path: '/packinglist', name: 'packinglist', component: Packinglist },
  ],
})

export default router
