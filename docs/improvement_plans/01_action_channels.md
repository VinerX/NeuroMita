# 01. Каналы действий и capabilities

## Проблема

Модель видит одно и то же действие описанным до **трёх раз разными способами**,
и списки противоречат друг другу.

- Статический `Crazy/Default/Structural/response_structure.txt` перечисляет
  анимации `SnapFingers, ClapHands, WaveHello, Hug…`
- Рантаймовый `[Unity Runtime Capabilities]` в том же запросе присылает другой
  список: `wave_hip_hop_dance, kiss, backflip, terrified…` — пересечения почти нет.
- Нож-охота живёт как `startknifehunt` в commands (в `mainCrazy.txt` **и**
  `response_structure.txt`, с разными формулировками) **и** как typed intent
  `actor.start_knife_hunt` в `[Unity Intent Contract]`.
- Синтаксис света расходится: `light:color:255,100,50` (`available_actions.txt`)
  против `light:color,<R>,<G>,<B>` (`response_structure.txt`).
- `Crazy/Default/Main/available_actions.txt` и `response_structure.txt` дублируют
  ~80% контента (эмоции/анимации/команды/одежда/музыка) на двух языках с расхождениями.

Итог: на слабых моделях — форматный дрейф, вызовы несуществующих ID, «сказала, но
не сделала».

## Предложения

- [ ] **P0.** Единый источник правды — рантайм. Из статических промптов убрать
      хардкод-списки конкретных ID (анимации/эмоции/интеракции/одежда), оставить
      только *семантику полей* («анимации — через `animations`, вот формат»).
      Конкретные ID приходят из `[Unity Runtime Capabilities]` (они уже приходят).
- [ ] **P0.** Свести расхождения синтаксиса (свет, нож-охота) к одной формулировке;
      выбрать канон (лучше — как в рантайм-контракте) и удалить остальные.
- [ ] **P1.** Добить дедупликацию «commands vs intents vs dedicated fields»: если
      действие имеет typed intent или dedicated-поле — убрать legacy-команду из
      промпта совсем, а не писать «prefer dedicated fields». Оставить `commands`
      только для того, у чего нет типизированного канала.
- [ ] **P2.** Удалить/схлопнуть `available_actions.txt` как дубль
      `response_structure.txt` — не держать два списка одного и того же.
- [ ] **P2.** Линтер промптов (см. 02): правило — детект упоминаний команд/ID,
      которых нет в каталоге действий.

## Затрагиваемые файлы

- `extra/Prompts/Crazy/Default/Structural/response_structure.txt`
- `extra/Prompts/Crazy/Default/Main/available_actions.txt`
- `extra/Prompts/Crazy/Default/Main/mainCrazy.txt`
- `extra/Prompts/Structural/response_format_json.script`
- Аналоги во всех остальных персонажах (`*/Structural/response_structure.txt`)
- Источник рантайм-капабилити: NeuroMita-Unity6 (DialoguePromptContext / Prompting)
- `src/controllers/prompt_controller.py` (сборка Unity-блоков, уже есть)

## Заметки

- Разделение Unity-контекста на статический (Rules/Intent Contract) и динамический
  (Capabilities/World State/Events) уже реализовано в `prompt_controller.py` и
  сделано правильно — это фундамент, на который ложится вынос списков в рантайм.
