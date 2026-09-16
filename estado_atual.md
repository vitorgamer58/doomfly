# Estado atual do fork de nocicepção (handoff)

Documento de situação para quem escreveu o `task.md`. Cobre o que foi
implementado, as decisões que divergiram do plano original, os resultados já
medidos e o que falta.

Data: 15/09/2026. Branch `nociception-snxx29` em `git@github.com:vitorgamer58/doomfly`.

---

## 1. Resumo

Milestones 1 a 3 estão implementados e commitados. O Milestone 4 rodou por
completo e **não foi demonstrado**. Milestones 5 a 8 não começaram.

Três achados principais:

1. **A propagação SNxx29 → ascending neurons existe, é específica da topologia e
   sobrevive ao pareamento de dose**, tanto no probe em malha aberta quanto no
   jogo.
2. **Não há resposta dopaminérgica nem comportamental específica.** O elo que o
   `task.md` §18 considera o mais interessante (dano → nociceptor → ascending →
   DAN endógeno) não apareceu, e o controle aleatório com mesmo drive muda mais
   o comportamento que os próprios SNxx29.
3. **O Controle A é inerte com pesos congelados:** produziu comportamento
   idêntico ao Controle B nos 21.000 tics. Ver seção 5.3.

---

## 2. Commits (a partir do upstream `71ecf53`)

```text
5ae3fd7  Automate fixed-duration nociception experiments
791432b  Record nociception probe, dose calibration and smoke-test results
33c7b6d  Add spike-dose-matched random control and raise default nociception gain
68841cd  Record a completed life when the server stops between death and respawn
70f08c0  Add simulated nociception damage input via SNxx29 leg sensory neurons
```

Há mudanças ainda não commitadas (aguardando a chave GPG do usuário): suporte a
`--learning` e checkpoints no orquestrador, mais testes e documentação.

---

## 3. O que foi implementado

| Arquivo | Função |
| --- | --- |
| `doom/nociception.py` | Seleção das populações no MaleCNS v1.0, transdutor de dano, export de proveniência, validação da calibração de dose |
| `doom/training.py` | `DamageTraining` generalizado: `--damage-input` decide para onde vai o dano |
| `doom/server.py` | Condições, telemetria por tic, `--max-neural-seconds`, registro de fim de corrida |
| `doom/monitor.py` | Grupos fixos de neurônios monitorados (só registro, nunca controle) |
| `doom/life_metrics.py` | Métricas por vida (`task.md` §24) |
| `doom/death_snapshots.py` | Snapshots em −500, −100, 0, +100, +500, +1000 ms (§20) |
| `doom/nociception_probe.py` | Probe de propagação em malha aberta e calibração de dose (Milestone 3) |
| `doom/analyze_nociception.py` | Análise comportamental peri-dano com bootstrap (Milestone 4) |
| `doom/nociception_experiment.py` | Orquestrador das condições, com paralelismo guiado por RAM |
| `tests/test_doom_nociception.py` | 27 testes; a suíte completa relacionada passa |
| `docs/doom-nociception.md` | Documentação de método, dados, suposições e resultados |

### Condições disponíveis

```sh
python -m doom.server --model experimental-v6 --damage-input {ppl101|none|snxx29|random-matched|random-dose-matched}
```

`ppl101` continua sendo o padrão, e o comportamento, a proveniência e os
checkpoints do upstream ficaram byte-idênticos.

---

## 4. Decisões que divergem ou detalham o `task.md`

Estas são as partes que mais interessam para revisar o plano original.

### 4.1 Seleção de SNxx29 (§8)

- `type == "SNxx29"` exato dá **20 neurônios, 10 L / 10 R**, exatamente como o
  `task.md` previa. Todos retidos no grafo de 166.700.
- **O lado vem de `rootSide`, não de `somaSide`**, que está vazio para essas
  células. O código existente do projeto (`circuit.py`, `prepare.py`) usa
  `somaSide` e registraria o lado como `None`.
- Existem **4 corpos com tipo composto `SNxx27,SNxx29`** (2 de perna, 2 de
  notum, neurotransmissor `unclear`). Foram **excluídos**.
- Neurotransmissor por tipo: acetilcolina, confiança 0,674, como o `task.md`
  dizia. Por corpo: 14 acetilcolina, 5 serotonina, 1 unclear. O modelo usa o
  consenso para os 20, logo todos são excitatórios rápidos.
- Conectividade confirmada: 35.140 sinapses de saída, 1.140 parceiros, **46%
  para ascending neurons**. Os parceiros mais fortes batem com a lista do §8.

### 4.2 Identidade nociceptiva é inferência externa (§8)

O paper do MaleCNS (Berg et al.) **não menciona SNxx29 nem nocicepção**, e o
campo `receptorType` está vazio para essas células. A associação ppk+/Gr28b.d+
vem da literatura do MANC. Está documentado como inferência, e a citação exata
ainda precisa ser adicionada.

### 4.3 Ganho do transdutor (§13)

O limiar do modelo é 7 mV acima do repouso. A varredura de ganho mostrou:

| Ganho | SNxx29 | AN09B018 |
| --- | --- | --- |
| 5 e 7,5 mV-eq | 0 Hz (silencioso) | 0 |
| 10 | 1,5 Hz | 0 |
| 20 | 8,5 Hz | 0,6 Hz |
| **30 (escolhido)** | **26 Hz** | **8 Hz** |
| 40 | 55 Hz | 41 Hz |

O padrão ficou **30 mV-eq**, o menor ganho que recruta os dois principais
parceiros ascendentes. `damage_reference = 20 HP`, pulso de 200 ms, sem decay.

### 4.4 O controle aleatório precisou de duas versões (§7)

O `task.md` pede amplitude, duração e número de neurônios equivalentes. Fizemos
isso, e o resultado foi desigual: **com o mesmo estímulo, as células de controle
disparam 4 a 10 vezes mais que os SNxx29** (116,5 Hz contra 26,25 Hz a
30 mV-eq).

A causa é topológica e interessante por si só: **AN05B004, o parceiro que mais
responde aos SNxx29, é também a maior fonte de inibição sobre eles** (peso 838
de 1.185 de inibição recebida). Existe um laço de retroalimentação inibitória
que segura os SNxx29; as células de controle não têm esse laço.

Por isso existem duas condições de controle:

- `random-matched`: mesma amplitude, conforme o `task.md`;
- `random-dose-matched`: mesmas células, ganho calibrado para **9,5 mV-eq**, de
  modo que a taxa de disparo da população iguale a dos SNxx29 (25,5 contra
  26,25 Hz, erro de 2,9%).

A calibração está em `outputs/doom/nociception/dose-calibration-v1.json` e o
servidor recusa um registro feito com outra seed, outro pulso ou outro decay.

### 4.5 Dano letal e respawn (§5 e §21)

Diferente do caminho PPL101 do upstream, que exclui dano letal e cancela pulsos
no reset, **o dano letal ativa os nociceptores e o pulso continua atravessando o
respawn**. Isso segue o espírito do §5: a morte não é um evento neural especial,
e o cérebro experimenta nocicepção intensa seguida de troca abrupta de imagem.
Cada sobreposição é contada em `pulses_spanning_respawn`.

### 4.6 O que não mudou

- A corrente tônica calibrada do PPL101 (11,3125 mV-eq) permanece em todas as
  condições. Ela define a taxa basal e não é sinal de dano.
- O decoder continua sendo DNp20 e DNpe017 (§16).
- Nenhuma recompensa de dano existe; v6 exige `--reward off`.
- O grafo completo é mantido, sem poda (§15).
- Estado neural preservado na morte (§3): já era assim no upstream, e agora há
  teste garantindo que `new_round` não toca em nenhum campo do cérebro.

---

## 5. Resultados

### 5.1 Milestone 3 — propagação (probe v2, ganho 30, `probe-snxx29-v2`)

Cinco pulsos de 200 ms, frame fixo, pesos congelados, valores em relação ao
braço sham, por célula, durante 50–200 ms do pulso:

| Grupo | SNxx29 | Aleatório, mesmo drive | Aleatório, mesma dose |
| --- | --- | --- | --- |
| Células estimuladas | +28,1 Hz | +118,7 Hz | +28,8 Hz |
| **AN05B004** | **+43,3** | +0,7 | −2,0 |
| **AN09B018** | **+8,5** (5/5 pulsos, 40 ms) | 0 | 0 |
| **ANXXX196** | **+10,0** (5/5) | 0 | 0 |
| AN05B097 | +1,7 (5/5) | 0 | 0 |
| AN17A018 | 0 | 0 | 0 |
| DAN, PAM, MBON, KC, DN | sinal misto, IC cruza zero | igual | igual |

**Conclusão:** os SNxx29 recrutam quatro dos seus parceiros ascendentes em todos
os pulsos, e nenhum dos controles faz isso, nem com 4,5 vezes mais disparos.
Esse é o resultado positivo do Milestone 3.

**Limite:** as populações do cérebro central, dopaminérgicas e descendentes mudam
em todos os braços, inclusive nas janelas anteriores ao pulso. Isso é divergência
caótica da rede recorrente determinística, não resposta específica. Portanto
`SNxx29 → ascending → cérebro → DN` **não** está demonstrado, e o Milestone 8
(dopamina endógena) tem evidência preliminar **negativa**.

### 5.2 Milestone 4 — comportamento (concluído, `m4-v1`)

Cinco condições, um cérebro cada, 600 s de tempo neural, pesos congelados, mesma
seed de jogo, sem recompensa. Entre 85 e 102 vidas e entre 527 e 602 eventos de
dano analisados por condição.

| Condição | Vidas | Sobrevivência mediana | Dano/min | Kills/vida |
| --- | --- | --- | --- | --- |
| `none` | 85 | 6,49 s | 921 | 0,91 |
| `ppl101` | 85 | 6,49 s | 921 | 0,91 |
| `random-dose-matched` | 95 | 6,00 s | 997 | 0,76 |
| `snxx29` | 101 | 5,66 s | 1.045 | 0,57 |
| `random-matched` | 102 | 5,61 s | 1.057 | 0,66 |

Mudança peri-dano contra `none`, 0–200 ms após um tiro não letal, bootstrap com
IC de 95%. Só o que não cruza zero:

- **`snxx29`:** ascending neurons +1,51 [+0,64, +2,37] spikes/tic; DNp20 R−L
  +0,91 [+0,03, +1,81] Hz. Nenhuma mudança distinguível em virar, andar ou atirar.
- **`random-matched`** (dispara 4,5× mais): ascending +1,77; descending +1,34;
  forward −0,21; attack −0,019; DNpe017 −0,54 na janela de 200–1000 ms.
- **`random-dose-matched`:** nada mensurável.
- **`ppl101`:** nada.

**O Milestone 4 não foi demonstrado.** Não houve alteração comportamental
imediata específica da nocicepção. O que move o comportamento aqui é a
quantidade de estímulo sensorial, não a identidade nociceptiva: o controle
aleatório com mesmo drive muda mais o comportamento que os SNxx29. Com a dose
casada, sobra apenas a resposta dos ascending neurons nos SNxx29, que é
justamente o efeito que resiste ao pareamento. Nenhuma condição alterou a
atividade dos DAN, então o Milestone 8 segue negativo também em malha fechada.

Sobreviver menos nas condições estimuladas **não** é evidência de esquiva. É
compatível com estímulo sensorial extra atrapalhando um controlador já frágil.

### 5.3 Achado metodológico: o Controle A é inerte com pesos congelados

`ppl101` e `none` produziram **ações, HP e kills idênticos nos 21.000 tics**. A
única diferença está nas contagens de spikes dos próprios PPL101 (+1.542).

A razão é estrutural: no v6, as células moduladoras não entregam excitação
rápida, apenas alimentam o traço usado pela regra de plasticidade. Com os pesos
congelados, o mecanismo de dano do upstream **não tem como alterar o
comportamento**.

Consequência prática para o `task.md` §7: o Controle A só é uma comparação
informativa depois que a plasticidade estiver ligada (Milestone 6). Em qualquer
experimento de pesos congelados ele é redundante com o Controle B.

## 6. Reprodutibilidade (§28)

Cada corrida grava:

- `run-<id>.json`: commit do fork, commit base do upstream, todos os argumentos,
  proveniência completa (hashes do grafo e do kernel, calibração, população
  estimulada com body IDs, parâmetros do transdutor), definição dos grupos
  monitorados.
- `run-<id>-end.json`: motivo do fim, tics, tempo de jogo e neural, número de
  mortes, hash final dos pesos, estado final da memória e do transdutor.
- `audit.jsonl` por tic, mais arquivo morto comprimido por hora.
- `lives.jsonl` por vida e `death-snapshots.jsonl` por morte.
- `outputs/doom/nociception/populations-malecns_v1.json`: body_id, type, class,
  superclass, side, predições de neurotransmissor, dataset e versão, conforme §27.

---

## 7. O que falta

**Imediato:**
1. Commitar os resultados e a documentação (aguardando a chave GPG do usuário).

**Amanhã (Milestone 6, corrida longa):**
3. Ligar plasticidade e rodar o dia e a noite, com checkpoints. O orquestrador já
   aceita `--learning` e `--checkpoint-seconds`; falta escolher as condições.
4. **Controle E do §25 ainda não existe:** falta uma opção no servidor para
   resetar o estado neural na morte preservando os pesos. Sem ele não dá para
   responder se preservar o estado entre mortes importa.
5. **Curvas por idade da simulação ainda não existem:** sobrevivência, dano por
   minuto e evolução dos pesos plásticos ao longo das vidas (§24). É o que
   distingue "os pesos mudaram" de "houve aprendizado".

**Depois:** Milestone 5 (md abdominais), 7 (aprendizado aversivo) e 8 (dopamina
endógena).

---

## 8. Avaliação honesta sobre aprendizado

A cadeia necessária é `dano → SNxx29 → ascending → DAN → plasticidade KC→MBON11
→ DN → comportamento`. Dois elos estão frágeis:

- **DAN:** o probe não encontrou resposta dopaminérgica específica à nocicepção.
  Sem isso, a regra de plasticidade não tem sinal de ensino. Vale testar ganho
  40 mV-eq e os md abdominais, que alcançam outros alvos.
- **Efeito motor:** a plasticidade cobre apenas 4.184 conexões KC→MBON11, e o
  MBON11 não fala diretamente com DNp20/DNpe017. Qualquer influência atravessa o
  grafo inteiro e tende a se diluir.

Some-se a isso que o próprio v6 do upstream falhou nas validações de visão,
condicionamento e sobrevivência **com** a dopamina artificial ligada, que é
justamente o que desligamos.

Um resultado negativo aqui é informativo e está previsto pelo `AGENTS.md`, que
exige preservar experimentos falhos e controles.
