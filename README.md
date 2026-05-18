<!-- LANG SELECTOR -->

[🇬🇧 English](#english) · [🇨🇳 中文](#chinese) · [🇯🇵 日本語](#japanese) · [🇰🇷 한국어](#korean) · [🇪🇸 Español](#spanish) · [🇫🇷 Français](#french) · [🇩🇪 Deutsch](#german) · [🇷🇺 Русский](#russian)

---

<h1 align="center">ContextFlow <code>/cf</code></h1>

<p align="center">
  <b>Save & load AI coding session context across tools.</b><br>
  <sub>Switch between OpenCode, Claude Code, Codex, Cursor, Copilot CLI — without losing context.</sub>
</p>

---

<a name="english"></a>

## 🇬🇧 English

**ContextFlow** persists your AI coding session (conversation, file changes, decisions, intent) to disk and restores it in another tool. No more repeating yourself when you hit rate limits, need a cheaper model, or switch to a specialized tool.

### Supported Tools
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### Commands

| Command | Description | Requires LLM |
|---------|-------------|:---:|
| `/cf save` | Save current session to `.session-bridge/` | ✗ |
| `/cf load <id>` | Restore a saved session | ✓ |
| `/cf status` | List all saved snapshots | ✗ |
| `/cf diff <id1> [id2]` | Compare two snapshots | ✗ |
| `/cf validate <id>` | Validate snapshot against USF schema | ✗ |

### Quick Install

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

**Any tool** — copy `cf/` into the tool's configured skills path.

### Quick Start
```bash
# Save your current session
/cf save

# List saved snapshots
/cf status

# Restore the latest snapshot in another tool
/cf load latest
```

Works during rate limits. Secrets are automatically redacted. Full docs at [`cf/SKILL.md`](cf/SKILL.md).

---

<a name="chinese"></a>

## 🇨🇳 中文

**ContextFlow** 将会话上下文（对话、文件变更、决策、意图）持久化到磁盘，并在另一个工具中无缝恢复。遇到 API 限流、需要更经济的模型、或切换专业工具时，无需重复描述已做的工作。

### 支持的工具
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### 命令

| 命令 | 说明 | 需要 LLM |
|------|------|:---:|
| `/cf save` | 保存当前会话到 `.session-bridge/` | ✗ |
| `/cf load <id>` | 恢复已保存的会话 | ✓ |
| `/cf status` | 列出所有快照 | ✗ |
| `/cf diff <id1> [id2]` | 对比两个快照 | ✗ |
| `/cf validate <id>` | 按 USF 模式校验快照 | ✗ |

### 快速安装

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

**其他工具** — 将 `cf/` 复制到技能目录即可。

### 快速上手
```bash
# 保存当前会话
/cf save

# 列出所有快照
/cf status

# 在另一个工具中恢复最新会话
/cf load latest
```

限流时也可使用。敏感信息自动脱敏。完整文档：[`cf/SKILL.md`](cf/SKILL.md)。

---

<a name="japanese"></a>

## 🇯🇵 日本語

**ContextFlow** は、AI コーディングセッションのコンテキスト（会話、ファイル変更、決定、意図）をディスクに保存し、別のツールでシームレスに復元します。レート制限に達したとき、より安価なモデルが必要なとき、または専門ツールに切り替えるときに、同じ説明を繰り返す必要はありません。

### 対応ツール
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### コマンド

| コマンド | 説明 | LLM 必要 |
|----------|------|:---:|
| `/cf save` | 現在のセッションを `.session-bridge/` に保存 | ✗ |
| `/cf load <id>` | 保存したセッションを復元 | ✓ |
| `/cf status` | スナップショット一覧 | ✗ |
| `/cf diff <id1> [id2]` | スナップショットの差分表示 | ✗ |
| `/cf validate <id>` | USF スキーマで検証 | ✗ |

### インストール

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

### クイックスタート
```bash
/cf save     # セッションを保存
/cf status   # スナップショット一覧
/cf load latest  # 最新を復元
```

レート制限中でも動作。機密情報は自動マスク。詳細: [`cf/SKILL.md`](cf/SKILL.md)。

---

<a name="korean"></a>

## 🇰🇷 한국어

**ContextFlow**는 AI 코딩 세션의 컨텍스트(대화, 파일 변경, 결정, 의도)를 디스크에 저장하고 다른 도구에서 원활히 복원합니다. API 속도 제한에 도달했거나, 더 저렴한 모델이 필요하거나, 전문 도구로 전환할 때 작업 내용을 다시 설명할 필요가 없습니다.

### 지원 도구
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### 명령어

| 명령어 | 설명 | LLM 필요 |
|--------|------|:---:|
| `/cf save` | 현재 세션을 `.session-bridge/`에 저장 | ✗ |
| `/cf load <id>` | 저장된 세션 복원 | ✓ |
| `/cf status` | 스냅샷 목록 보기 | ✗ |
| `/cf diff <id1> [id2]` | 두 스냅샷 비교 | ✗ |
| `/cf validate <id>` | USF 스키마로 검증 | ✗ |

### 설치

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

### 빠른 시작
```bash
/cf save          # 세션 저장
/cf status        # 스냅샷 목록
/cf load latest   # 최신 세션 복원
```

속도 제한 중에도 작동합니다. 민감 정보는 자동 마스킹됩니다. 전체 문서: [`cf/SKILL.md`](cf/SKILL.md).

---

<a name="spanish"></a>

## 🇪🇸 Español

**ContextFlow** guarda el contexto de tu sesión de codificación con IA (conversación, cambios de archivos, decisiones, intenciones) en disco y lo restaura en otra herramienta sin esfuerzo. No más repetirte cuando alcanzas límites de velocidad, necesitas un modelo más barato o cambias a una herramienta especializada.

### Herramientas compatibles
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### Comandos

| Comando | Descripción | ¿Requiere LLM? |
|---------|-------------|:---:|
| `/cf save` | Guardar sesión actual en `.session-bridge/` | ✗ |
| `/cf load <id>` | Restaurar una sesión guardada | ✓ |
| `/cf status` | Listar todas las instantáneas | ✗ |
| `/cf diff <id1> [id2]` | Comparar dos instantáneas | ✗ |
| `/cf validate <id>` | Validar instantánea contra esquema USF | ✗ |

### Instalación rápida

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

### Inicio rápido
```bash
/cf save          # Guardar sesión
/cf status        # Listar instantáneas
/cf load latest   # Restaurar la más reciente
```

Funciona durante límites de velocidad. Secretos redactados automáticamente. Documentación completa: [`cf/SKILL.md`](cf/SKILL.md).

---

<a name="french"></a>

## 🇫🇷 Français

**ContextFlow** persiste le contexte de votre session de codage IA (conversation, modifications de fichiers, décisions, intentions) sur le disque et le restaure dans un autre outil. Fini de vous répéter quand vous atteignez les limites de débit, que vous avez besoin d'un modèle moins cher, ou que vous passez à un outil spécialisé.

### Outils supportés
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### Commandes

| Commande | Description | Nécessite LLM |
|----------|-------------|:---:|
| `/cf save` | Sauvegarder la session dans `.session-bridge/` | ✗ |
| `/cf load <id>` | Restaurer une session sauvegardée | ✓ |
| `/cf status` | Lister tous les instantanés | ✗ |
| `/cf diff <id1> [id2]` | Comparer deux instantanés | ✗ |
| `/cf validate <id>` | Valider l'instantané avec le schéma USF | ✗ |

### Installation rapide

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

### Démarrage rapide
```bash
/cf save          # Sauvegarder la session
/cf status        # Lister les instantanés
/cf load latest   # Restaurer le plus récent
```

Fonctionne pendant les limites de débit. Les secrets sont automatiquement masqués. Documentation : [`cf/SKILL.md`](cf/SKILL.md).

---

<a name="german"></a>

## 🇩🇪 Deutsch

**ContextFlow** speichert den Kontext Ihrer KI-Codierungs-Sitzung (Gespräch, Dateiänderungen, Entscheidungen, Absichten) auf der Festplatte und stellt ihn in einem anderen Tool nahtlos wieder her. Schluss mit Wiederholungen, wenn Sie Rate-Limits erreichen, ein günstigeres Modell benötigen oder zu einem spezialisierten Tool wechseln.

### Unterstützte Tools
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### Befehle

| Befehl | Beschreibung | LLM nötig |
|--------|-------------|:---:|
| `/cf save` | Aktuelle Sitzung in `.session-bridge/` speichern | ✗ |
| `/cf load <id>` | Gespeicherte Sitzung wiederherstellen | ✓ |
| `/cf status` | Alle Snapshots auflisten | ✗ |
| `/cf diff <id1> [id2]` | Zwei Snapshots vergleichen | ✗ |
| `/cf validate <id>` | Snapshot gegen USF-Schema validieren | ✗ |

### Schnellinstallation

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

### Schnellstart
```bash
/cf save          # Sitzung speichern
/cf status        # Snapshots anzeigen
/cf load latest   # Neueste Sitzung wiederherstellen
```

Funktioniert während Rate-Limits. Geheimnisse werden automatisch geschwärzt. Vollständige Dokumentation: [`cf/SKILL.md`](cf/SKILL.md).

---

<a name="russian"></a>

## 🇷🇺 Русский

**ContextFlow** сохраняет контекст вашего сеанса ИИ-кодинга (диалог, изменения файлов, решения, намерения) на диск и восстанавливает его в другом инструменте. Больше не нужно повторять всё заново при достижении лимитов, необходимости более дешёвой модели или переходе на специализированный инструмент.

### Поддерживаемые инструменты
OpenCode · Claude Code · Codex (VS Code) · Cursor · GitHub Copilot CLI

### Команды

| Команда | Описание | Требует LLM |
|---------|----------|:---:|
| `/cf save` | Сохранить сессию в `.session-bridge/` | ✗ |
| `/cf load <id>` | Восстановить сохранённую сессию | ✓ |
| `/cf status` | Список всех снимков | ✗ |
| `/cf diff <id1> [id2]` | Сравнить два снимка | ✗ |
| `/cf validate <id>` | Проверить снимок по схеме USF | ✗ |

### Быстрая установка

**OpenCode** (Unix)
```bash
ln -s "$(pwd)/cf" ~/.config/opencode/skills/cf
```

**Claude Code**
```bash
ln -s "$(pwd)/cf" /path/to/project/.claude/skills/cf
```

**Любой инструмент** — скопируйте `cf/` в папку навыков.

### Быстрый старт
```bash
/cf save          # Сохранить сессию
/cf status        # Список снимков
/cf load latest   # Восстановить последний снимок
```

Работает во время лимитов. Конфиденциальные данные автоматически скрываются. Полная документация: [`cf/SKILL.md`](cf/SKILL.md).

---

<p align="center"><sub>MIT &bull; Built for the AI coding community</sub></p>
