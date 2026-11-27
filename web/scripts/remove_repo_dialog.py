from pathlib import Path

p = Path(__file__).resolve().parents[1] / "src/views/RepositoriesView.vue"
text = p.read_text(encoding="utf-8")
needle = '    <v-dialog v-model="dialogVisible" max-width="760" class="repo-dialog">'
start = text.find(needle)
if start < 0:
    raise SystemExit("dialog start not found")
end = text.find("    </v-dialog>", start) + len("    </v-dialog>")
p.write_text(text[:start] + text[end:], encoding="utf-8")
print("removed", end - start, "chars")