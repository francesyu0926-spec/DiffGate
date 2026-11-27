"""Fix RepositoryFormView: single clean template + trim list-only script."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
vue = root / "src/views/RepositoryFormView.vue"
form_path = root / "src/components/_repo_form_template.fragment.vue.txt"

raw = vue.read_text(encoding="utf-8")
form_full = form_path.read_text(encoding="utf-8")
# Keep only form fields (drop stray </v-form>, footer, extra wrappers from dialog extract)
cut = form_full.find("</v-expansion-panels>")
if cut < 0:
    raise SystemExit("expansion-panels end not found in fragment")
form_body = form_full[: cut + len("</v-expansion-panels>")].rstrip() + "\n"

snackbar = """
    <v-snackbar
      v-model="snackbar.show"
      location="bottom"
      position="sticky"
      :timeout="snackbar.loading ? -1 : snackbar.variant === 'error' ? 9000 : 4000"
      :rounded="snackbar.variant === 'error' ? 'lg' : 'pill'"
      elevation="6"
      :color="snackbar.variant === 'error' ? 'error' : undefined"
      :class="[
        'feedback-snackbar',
        snackbar.variant === 'success' && 'feedback-snackbar--success',
        snackbar.variant === 'error' && 'feedback-snackbar--error',
        snackbar.variant === 'info' && 'feedback-snackbar--info',
      ]"
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

new_template = f"""<template>
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
{form_body}
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

t0 = raw.index("<template>")
t1 = raw.index("<style")
vue_body = raw[:t0] + new_template + "\n\n" + raw[t1:]

# --- script cleanup ---
s0 = vue_body.index("<script setup")
s1 = vue_body.index("</script>") + len("</script>")
script = vue_body[s0:s1]

replacements = [
    ("import Md3LoadState from '@/components/Md3LoadState.vue'\n", ""),
    ("  deleteRepository,\n", ""),
    ("  fetchRepoOverview,\n", ""),
    ("  triggerRepoAnalysis,\n", ""),
    ("import type {\n  AuthMethod,\n  RepoOverviewStats,\n  RepoProvider,", "import type {\n  AuthMethod,\n  RepoProvider,"),
    ("const actionLoading = ref<string | null>(null)\n", ""),
    ("/** 正在重建 AST 的仓库行（菜单关闭后仍可见） */\nconst reindexingId = ref<string | null>(null)\n", ""),
    ("const deleteDialog = ref(false)\nconst deleteTarget = ref<RepositoryItem | null>(null)\n", ""),
    ("const kpiTick = ref(0)\n", ""),
    ("const tablePage = ref(1)\nconst tableItemsPerPage = ref(10)\nconst tablePerPageOptions = [10, 25, 50]\n\n", ""),
]

for old, new in replacements:
    script = script.replace(old, new)

# Drop pagination block through paginationNavButtons computed
start = script.find("const tablePageCount = computed")
end = script.find("type SnackbarVariant = 'success'")
if start >= 0 and end > start:
    script = script[:start] + script[end:]

for fn in (
    "function isRowReindexing",
    "function isRowAnalyzeLoading",
    "const repoRowMenuProps",
    "function splitRepoFullName",
    "function repoRowProps",
    "function formatIndexedAt",
):
    i = script.find(fn)
    if i < 0:
        continue
    j = script.find("\n\n", i + 1)
    if j < 0:
        j = len(script)
    script = script[:i] + script[j + 1 :]

# watchers for table
for w in ("watch(tableItemsPerPage", "watch(tablePageCount"):
    i = script.find(w)
    if i < 0:
        continue
    j = script.find(")\n", i)
    if j < 0:
        continue
    script = script[:i] + script[j + 2 :]

i = script.find("const paginationNavButtons")
if i >= 0:
    j = script.find("])\n\n", i)
    if j >= 0:
        script = script[:i] + script[j + 3 :]

# headers + kpi through refreshAfterMutation
i = script.find("const headers = [")
j = script.find("function openCreate()")
if i >= 0 and j > i:
    script = script[:i] + script[j:]

# delete/analyze block
for block_start in ("function askDelete", "let searchDebounce"):
    i = script.find(block_start)
    if i < 0:
        continue
    if block_start.startswith("let searchDebounce"):
        j = script.find("\n\nonMounted", i)
    else:
        j = script.find("\n\nlet searchDebounce", i)
        if j < 0:
            j = script.find("\n\nonMounted", i)
    if j > i:
        script = script[:i] + script[j + 1 :]

script = script.replace(
    "  const backend = rows.value.find(",
    "  const backend = linkedRepoRows.value.find(",
)

vue_body = vue_body[:s0] + script + vue_body[s1:]

# Add page layout styles before </style> if missing
if ".repo-form-page {" not in vue_body:
    vue_body = vue_body.replace(
        "</style>",
        """
.repo-form-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 8px 20px 32px;
  min-height: calc(100vh - 64px);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.repo-form-page__head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.repo-form-page__title {
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0;
  line-height: 1.3;
}

.repo-form-page__subtitle {
  margin: 4px 0 0;
  font-size: 0.875rem;
  color: rgba(255, 255, 255, 0.55);
  line-height: 1.45;
}

.repo-form-page-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.repo-form-page-scroll {
  flex: 1;
  min-height: 0;
  max-height: none;
}
</style>""",
        1,
    )

vue.write_text(vue_body, encoding="utf-8")
print("fixed", vue, "template bytes", len(new_template))