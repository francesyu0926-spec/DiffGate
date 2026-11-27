import { createApp } from 'vue'
import vuetify from './plugins/vuetify'
import router from './router'
import './styles/main.css'
import './styles/status-tokens.css'
import './styles/loading.css'
import './styles/kpi-overview.css'
import './styles/form-dialog.css'
import './styles/form-outlined-md3.css'
import './styles/repo-form-page.css'
import './styles/test-suite-form-page.css'
import './styles/md-field-outlined.css'
import './styles/dg-form-field-spec.css'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
/* 必须晚于 Vuetify 插件样式与 Element Plus，否则表单标签字号会被库样式压回 12px */
import './styles/dg-form-field-spec-force.css'
import './styles/test-suite-create-md3.css'
import './styles/repo-form-create-md3.css'
import App from './App.vue'
import { installScrollOverlayScrollbar } from './utils/scrollOverlayScrollbar'

// Vuetify 须最先注册；JobDetail 等页仍用 Element Plus
installScrollOverlayScrollbar()
createApp(App).use(vuetify).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')