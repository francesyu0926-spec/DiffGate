import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import { md3 } from 'vuetify/blueprints'
import { aliases, mdi } from 'vuetify/iconsets/mdi'
import { zhHans } from 'vuetify/locale'

const zhCN = {
  ...zhHans,
  noDataText: '暂无数据',
}

export default createVuetify({
  locale: {
    locale: 'zh-Hans',
    fallback: 'zh-Hans',
    messages: { 'zh-Hans': zhCN },
  },
  components,
  directives,
  blueprint: md3,
  icons: {
    defaultSet: 'mdi',
    aliases,
    sets: { mdi },
  },
  theme: {
    defaultTheme: 'darkMonochrome',
    themes: {
      diffgateLight: {
        dark: false,
        colors: {
          primary: '#0B57D0',
          secondary: '#5f6368',
          success: '#1E8E3E',
          warning: '#E37400',
          error: '#C5221F',
          info: '#0B57D0',
          background: '#EDF2FA',
          surface: '#FFFFFF',
          primaryContainer: '#D3E3FD',
          onPrimaryContainer: '#041E49',
        },
      },
      darkMonochrome: {
        dark: true,
        colors: {
          background: '#0B0C0E',
          surface: '#1E2126',
          'surface-variant': '#24282E',
          primary: '#8AB4F8',
          'on-primary': '#111315',
          secondary: '#8E9299',
          'on-surface': '#F1F3F5',
          'on-background': '#F1F3F5',
          success: '#81C995',
          warning: '#FDD663',
          error: '#F28B82',
          info: '#8AB4F8',
          outline: '#2C3036',
        },
        variables: {
          'border-color': '#26292E',
          'border-opacity': 1,
          'high-emphasis-opacity': 0.95,
          'medium-emphasis-opacity': 0.72,
        },
      },
      diffgateDark: {
        dark: true,
        colors: {
          primary: '#8AB4F8',
          surface: '#1A1D21',
          background: '#111315',
        },
      },
    },
  },
  defaults: {
    VBtn: { rounded: 'lg', class: 'text-none' },
    VCard: { rounded: 'xl', elevation: 0, border: false },
    VTextField: { variant: 'outlined', density: 'comfortable' },
    VSelect: { variant: 'outlined', density: 'comfortable' },
    VDataTable: { hover: true, noDataText: '暂无数据' },
  },
})