import { createRouter, createWebHistory } from 'vue-router'
import { hasAppSession } from '@/api/client'
import DashboardView from '@/views/DashboardView.vue'
import JobDetailView from '@/views/JobDetailView.vue'
import LoginView from '@/views/LoginView.vue'
import QualityDashboardView from '@/views/QualityDashboardView.vue'
import RegressionView from '@/views/RegressionView.vue'
import RepositoriesView from '@/views/RepositoriesView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', name: 'quality-dashboard', component: QualityDashboardView },
    { path: '/analysis', name: 'analysis', component: DashboardView },
    { path: '/regression', name: 'regression', component: RegressionView },
    { path: '/repositories', name: 'repositories', component: RepositoriesView },
    { path: '/jobs/:id', name: 'job-detail', component: JobDetailView, props: true },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  ],
})

router.beforeEach((to) => {
  if (to.meta.public || to.path === '/login') return true
  if (hasAppSession()) return true
  return { path: '/login', query: { redirect: to.fullPath } }
})

export default router