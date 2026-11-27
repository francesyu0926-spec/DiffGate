"""Remove moved-to-RepositoryFormView code from RepositoriesView."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
vue = root / "src/views/RepositoriesView.vue"
text = vue.read_text(encoding="utf-8")
s0 = text.index("<script setup")
s1 = text.index("</script>") + len("</script>")
script = text[s0:s1]

import_block_old = """import type { VForm } from 'vuetify/components'
import {
  createMonorepoBundle,
  createRepository,
  deleteRepository,
  detectRepositoryProfile,
  fetchRepoOverview,
  fetchRepositories,
  fetchRepoTypeOptions,
  fetchTestSuitePresets,
  readApiError,
  reindexRepository,
  triggerRepoAnalysis,
  testRepositoryNotify,
  updateRepository,
  type DetectRepositoryProfile,
} from '@/api/client'
import type {
  AuthMethod,
  RepoOverviewStats,
  RepoProvider,
  RepositoryItem,
  RepositoryPayload,
} from '@/api/types'
import { parseFullNameFromCloneUrl } from '@/utils/git'"""

import_block_new = """import {
  deleteRepository,
  fetchRepoOverview,
  fetchRepositories,
  readApiError,
  reindexRepository,
  triggerRepoAnalysis,
  updateRepository,
} from '@/api/client'
import type { RepoOverviewStats, RepoProvider, RepositoryItem } from '@/api/types'"""

script = script.replace(import_block_old, import_block_new)

# Remove form-only state at top (keep deleteDialog onward)
script = script.replace(
    """const dialogVisible = ref(false)
const editingId = ref<string | null>(null)
const formRef = ref<VForm | null>(null)
const actionLoading = ref<string | null>(null)
""",
    "const actionLoading = ref<string | null>(null)\n",
)
script = script.replace(
    """const submitPhase = ref<'idle' | 'saving' | 'indexing'>('idle')
const fullNameManual = ref(false)
const testSuiteOptions = ref<string[]>([])
const accessToken = ref('')
const sshPrivateKey = ref('')
const editingTokenConfigured = ref(false)
const editingSshConfigured = ref(false)
""",
    "",
)
script = script.replace(
    """const submitLoading = ref(false)
""",
    "",
)

# submitButtonLabel
i = script.find("const submitButtonLabel = computed")
j = script.find("function isRowReindexing")
if i >= 0 and j > i:
    script = script[:i] + script[j:]

# repoLinkedMenuProps through authItems (before headers)
i = script.find("/** 关联仓库下拉")
if i < 0:
    i = script.find("const repoLinkedMenuProps")
j = script.find("const headers = [")
if i >= 0 and j > i:
    script = script[:i] + script[j:]

# buildPayload through submit (after openEdit)
i = script.find("function buildPayload()")
j = script.find("function askDelete")
if i >= 0 and j > i:
    script = script[:i] + script[j:]

# onMounted: drop test suite / repo type fetch
script = script.replace(
    """onMounted(async () => {
  testSuiteOptions.value = await fetchTestSuitePresets()
  try {
    const meta = await fetchRepoTypeOptions()
    repoTypeItems.value = [
      {
        title: '自动识别（根据仓库地址探测）',
        value: AUTO_REPO_TYPE,
        icon: REPO_TYPE_OPTION_ICONS.auto,
      },
      ...meta.map((row) => {
        const comingSoon = Boolean(row.coming_soon) && !row.index_supported
        return repoTypeItem({
          id: row.id,
          label: comingSoon ? `${row.label}（敬请期待）` : row.label,
          comingSoon,
        })
      }),
    ]
  } catch {
    /* 保留本地默认项 */
  }
  await load()
})""",
    "onMounted(async () => {\n  await load()\n})",
)

vue.write_text(text[:s0] + script + text[s1:], encoding="utf-8")
print("slimmed RepositoriesView")