import { createApp } from 'vue'
import vuetify from './plugins/vuetify'
import router from './router'
import './styles/main.css'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'

// Vuetify 须最先注册；JobDetail 等页仍用 Element Plus
createApp(App).use(vuetify).use(router).use(ElementPlus).mount('#app')