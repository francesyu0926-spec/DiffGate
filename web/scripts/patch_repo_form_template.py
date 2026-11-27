from pathlib import Path

root = Path(__file__).resolve().parents[1]
p = root / "src/views/RepositoryFormView.vue"
text = p.read_text(encoding="utf-8")
start = text.index("<template>")
end = text.index("</template>") + len("</template>")
form = (root / "src/components/_repo_form_template.fragment.vue.txt").read_text(encoding="utf-8")

snackbar = """
    <v-snackbar
      v-model="snackbar.show"
      location="bottom"
      position="sticky"
      :timeout="snackbar.loading ? -1 : snackbar.variant === 'error' ? 9000 : 4000"
      :rounded="snackbar.variant === 'error' ? 'lg' : 'pill'"
      elevation="6"
      :color="snackbar.variant === 'error' ? 'error' : undefined"
      class="feedback-snackbar"
    >
      <div class="d-flex align-start ga-2 px-1 feedback-snackbar__content">
        <v-progress-circular
          v-if="snackbar.loading"
          indeterminate
          size="20"
          width="2"
          color="primary"
          class="feedback-snackbar__icon"
        />
        <v-icon
          v-else
          :icon="snackbar.variant === 'error' ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline'"
          size="small"
          class="feedback-snackbar__icon"
        />
        <span class="text-body-2 feedback-snackbar__text">{{ snackbar.text }}</span>
      </div>
    </v-snackbar>
"""

new_tpl = f"""<template>
  <div class="repo-form-page">
    <header class="repo-form-page__head">
      <v-btn
        class="text-none repo-form-page__back"
        variant="text"
        prepend-icon="mdi-arrow-left"
        @click="goBack"
      >
        返回仓库列表
      </v-btn>
      <div class="repo-form-page__intro">
        <h1 class="repo-form-page__title">{{{{ pageTitle }}}}</h1>
        <p class="repo-form-page__subtitle">
          配置仓库接入、扫描目录、门禁阈值与 Webhook；
          {{{{ editingId ? '保存后立即生效' : '保存后将初始化 AST 索引' }}}}。
        </p>
      </div>
    </header>

    <v-card class="repo-form-page-card repo-dialog-card dg-dark-form-surface" rounded="xl">
      <div class="repo-form-page-scroll repo-dialog-scroll">
        <v-form
          ref="formRef"
          class="repo-dialog-form dg-dark-form"
          autocomplete="off"
          @submit.prevent="submit"
        >
{form}
        </v-form>
      </div>
      <div class="repo-dialog-footer-fixed repo-dialog-toggles-bar repo-dialog-toggles-bar--separated">
        <div class="repo-dialog-toggles">
          <v-switch
            v-model="repoForm.enabled"
            label="启用分析"
            color="primary"
            density="comfortable"
            hide-details
            class="repo-form-switch dg-switch--dim"
          />
          <v-switch
            v-model="repoForm.webhook_enabled"
            label="接收 Webhook"
            color="primary"
            density="comfortable"
            hide-details
            class="repo-form-switch dg-switch--dim"
          />
          <v-switch
            v-model="repoForm.allow_self_override"
            label="允许提交人自审豁免"
            color="primary"
            density="comfortable"
            hide-details
            class="repo-form-switch dg-switch--dim repo-override-switch"
          />
        </div>
        <p class="repo-dialog-toggles-hint text-caption text-medium-emphasis mb-0">
          开启后 Push / MR 将自动触发分析任务与门禁评估。
        </p>
      </div>
      <v-divider class="repo-dialog-footer-divider" />
      <v-card-actions class="repo-dialog-actions">
        <v-spacer />
        <v-btn class="repo-dialog-cancel text-none" variant="text" @click="goBack">
          取消
        </v-btn>
        <v-btn
          class="repo-dialog-submit text-none"
          variant="flat"
          color="primary"
          :loading="submitLoading"
          @click="submit"
        >
          {{{{ submitButtonLabel }}}}
        </v-btn>
      </v-card-actions>
    </v-card>
{snackbar}
  </div>
</template>""".replace("{{{{", "{{").replace("}}}}", "}}")

p.write_text(text[:start] + new_tpl + text[end:], encoding="utf-8")
print("ok", len(new_tpl))