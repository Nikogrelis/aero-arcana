# Aero Arcana

Сборка Minecraft 1.21.1 (NeoForge 21.1.266), ~200 модов: Create и его аддоны, воздушные корабли,
Iron's Spells, Ice and Fire, подземелья. Свой лаунчер ставит игру с нуля и обновляет моды перед каждым запуском.

## Как играть
1. Скачайте `AeroArcana.exe` из раздела [Releases](../../releases/latest).
2. Запустите, введите ник, нажмите «Играть». Java, Minecraft, NeoForge и моды скачаются сами
   (первый раз ~1.5 ГБ). Игра ставится в `%APPDATA%\.aeroarcana` и не трогает другие лаунчеры.

## Что внутри репозитория
- `pack/index.json` — список файлов сборки: моды качаются с Modrinth и CurseForge напрямую,
  наши моды и патчи — из релиза `files`, конфиги и квесты — из `pack/overrides`.
- `launcher/` — исходники лаунчера (Python + pywebview). Установка Minecraft — [PortableMC](https://github.com/theorzr/portablemc) (Apache-2.0).
- `mod-sources/` — исходники наших модов и патчей (Climate Bridge, Creeper Guard, патчи CBC AT и Dragon Care).
- `tools/build_manifest.py` — сборка `pack/index.json`.

Чужие моды принадлежат их авторам и в репозиторий не выкладываются: лаунчер скачивает их с официальных площадок.
Патченые версии выложены по их лицензиям: CBC Advanced Technologies — MIT, Ice and Fire: Dragon Care — LGPL-3.0
(исходник патча — `mod-sources/patches/DragonCarePatch.java`), AERO Railway Planner — WTFPL.
