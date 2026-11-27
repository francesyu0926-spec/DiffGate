import type { InjectionKey } from 'vue'

/** 用例集 / 仓库全页表单：启用统一表单项规范（标签在上、44px、间距 token） */
export const DG_FORM_FIELD_SPEC_KEY: InjectionKey<boolean> = Symbol('dgFormFieldSpec')