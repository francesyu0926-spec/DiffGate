<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  fetchAuthMembers,
  patchAuthMemberRole,
  type AuthMember,
} from '@/api/client'
import Md3LoadState from '@/components/Md3LoadState.vue'

const open = defineModel<boolean>({ default: false })

const loading = ref(false)
const savingId = ref<string | null>(null)
const error = ref('')
const members = ref<AuthMember[]>([])

const roleItems = [
  { title: '研发 (dev)', value: 'dev' },
  { title: '测试 / QA', value: 'qa' },
  { title: '项目负责人 (pm)', value: 'pm' },
  { title: '管理员 (admin)', value: 'admin' },
]

async function loadMembers() {
  loading.value = true
  error.value = ''
  try {
    members.value = await fetchAuthMembers()
  } catch (e: unknown) {
    error.value =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '加载成员失败'
    members.value = []
  } finally {
    loading.value = false
  }
}

async function onRoleChange(member: AuthMember, role: string) {
  savingId.value = member.user_id
  error.value = ''
  try {
    await patchAuthMemberRole(member.user_id, role, true)
    member.role = role
    member.role_locked = true
  } catch (e: unknown) {
    error.value =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '保存失败'
  } finally {
    savingId.value = null
  }
}

watch(
  () => open.value,
  (v) => {
    if (v) void loadMembers()
  },
)
</script>

<template>
  <v-dialog v-model="open" max-width="640" scrollable>
    <v-card class="members-dialog" rounded="xl">
      <v-card-title class="d-flex align-center justify-space-between">
        <span>成员与角色</span>
        <v-btn icon="mdi-close" variant="text" size="small" aria-label="关闭" @click="open = false" />
      </v-card-title>
      <v-card-subtitle class="members-dialog__sub">
        将测试同学设为 QA 后系统会锁定身份；重新登录时不会覆盖手动分配。
      </v-card-subtitle>
      <v-card-text>
        <Md3LoadState v-if="loading" mode="overlay" label="加载成员…" min-height="160px" />
        <p v-else-if="error" class="members-dialog__error">{{ error }}</p>
        <v-list v-else density="comfortable" class="members-list">
          <v-list-item v-for="m in members" :key="m.user_id" class="members-list__item">
            <template #prepend>
              <v-avatar size="36" :image="m.avatar_url || undefined" color="surface-variant">
                <span v-if="!m.avatar_url" class="text-caption">{{ m.username.slice(0, 1).toUpperCase() }}</span>
              </v-avatar>
            </template>
            <v-list-item-title class="font-weight-medium">
              {{ m.display_name || m.username }}
            </v-list-item-title>
            <v-list-item-subtitle class="members-list__meta">
              {{ m.email || m.username }} · {{ m.provider }}
              <span v-if="m.role_locked" class="members-lock">已锁定</span>
            </v-list-item-subtitle>
            <template #append>
              <v-select
                :model-value="m.role"
                :items="roleItems"
                density="compact"
                variant="outlined"
                hide-details
                rounded="lg"
                class="members-role-select"
                :loading="savingId === m.user_id"
                @update:model-value="(v: string) => onRoleChange(m, v)"
              />
            </template>
          </v-list-item>
        </v-list>
        <p v-if="!loading && !members.length && !error" class="text-medium-emphasis text-body-2 mb-0">
          尚无登录用户，首位 PAT 登录者将自动成为管理员。
        </p>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.members-dialog {
  border: 1px solid #2e333b;
  background: #1e2124;
}
.members-dialog__sub {
  color: rgba(255, 255, 255, 0.58) !important;
  white-space: normal;
  padding-inline: 24px;
}
.members-dialog__error {
  color: #f28b82;
  font-size: 13px;
}
.members-list {
  background: transparent;
}
.members-list__item {
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.members-list__meta {
  color: rgba(255, 255, 255, 0.5) !important;
}
.members-lock {
  margin-left: 8px;
  color: #fbbf24;
}
.members-role-select {
  min-width: 148px;
  max-width: 168px;
}
</style>