"""Poll the ntfy topic and open one GitHub issue per new crash report (dedup by ntfy message id)."""
import json, os, subprocess, urllib.request

topic, repo = os.environ["NTFY_TOPIC"], os.environ["REPO"]
raw = urllib.request.urlopen(f"https://ntfy.sh/{topic}/json?poll=1&since=12h", timeout=30).read().decode()
msgs = [json.loads(l) for l in raw.splitlines() if l.strip()]
msgs = [m for m in msgs if m.get("event") == "message"]
known = subprocess.run(["gh", "issue", "list", "-R", repo, "--label", "crash", "--state", "all", "--limit", "300",
                        "--json", "body", "--jq", ".[].body"], capture_output=True, text=True, check=True).stdout
for m in msgs:
    if f"ntfy-id: {m['id']}" in known:
        continue
    try:
        s = json.loads(m.get("message", "{}"))
    except ValueError:
        s = {"raw": m.get("message", "")}
    links = "\n".join(f"- **{k}**: {v}" for k, v in (s.get("links") or {}).items()) or "- (логи не загрузились)"
    body = f"""**Игрок:** `{s.get('nick')}` · **код выхода:** {s.get('exit_code')} · **время:** {s.get('time')}
**Сборка:** {s.get('pack')} · **лаунчер:** {s.get('launcher')} · **память:** {s.get('ram_gb')} ГБ · **видеокарта:** {s.get('gpu') or '—'}

**Автодиагноз:** {s.get('hint')}
{('**Ошибка лаунчера:** ' + s['error']) if s.get('error') else ''}

### Логи (mclo.gs)
{links}

<details><summary>JSON</summary>

```json
{json.dumps(s, ensure_ascii=False, indent=1)}
```
</details>

<!-- ntfy-id: {m['id']} -->"""
    subprocess.run(["gh", "issue", "create", "-R", repo, "--title", m.get("title") or f"Вылет: {s.get('nick')}",
                    "--label", "crash", "--body", body], check=True)
    print("issue created for", m["id"])
print(f"{len(msgs)} messages checked")
