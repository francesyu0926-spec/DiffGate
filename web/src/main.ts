import { createApp } from 'vue'
import vuetify from './plugins/vuetify'
import router from './router'
import './styles/main.css'
import './styles/kpi-overview.css'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import App from './App.vue'

// Vuetify 须最先注册；JobDetail 等页仍用 Element Plus
createApp(App).use(vuetify).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')