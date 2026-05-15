# dashsin — Phase 4a v3 (hidrologia daily/weekly + MMGD ~46 GW + refinos)

Patch sobre Phase 4a v1. Cinco frentes de mudança.

## What's new

### 1. Bandeira tarifária — valor monetário cobrado (v2)
- Card "active flag" mostra valor adicional (R$/100 kWh)
- 4 cartões com valor vigente de cada bandeira (Verde, Amarela, V1, V2)
- Tabela hardcoded de Resoluções ANEEL 2015→2026 + fallback no CSV

### 2. Tarifas — TODAS componentes (v2)
- B1 Convencional: TE + TUSD consumo
- A4 Verde: TE/TUSD Ponta/FP + TUSD demanda única
- A4 Azul: TE/TUSD Ponta/FP + TUSD demanda Ponta/FP segregada
- Tabela com chevron ▸ expansível ao clique

### 3. MMGD — agora calibrado a ~46 GW (v3)
- Toggle modalidade (Todas/Própria UC/Autoconsumo remoto/etc) — todos os gráficos recalculam
- Gráfico "Crescimento anual desde 2015": barras MW + linha GW acumulado
- **Seed corrigido**: `46.6 GW total` (era 34 GW), aligned com EPE/GESEL 2026
- Splits realistas separados pra kW (~22% autoconsumo remoto) vs count (~4%)

### 4. Hidrologia — daily/weekly híbrido + tooltip interativo (v3 NOVA)

**Granularidade adaptativa**:
- **1 ano selecionado** → modo `daily` (366 pontos, linha "ondulada")
- **2+ anos selecionados** → modo `weekly` (52 pontos por ano, agregação on-the-fly)
- Badge `DAILY` ou `WEEKLY` no canto da seção EAR

**Histórico desde 2010**:
- Pipelines `ons_ear_ena.py` e `ons_ena_bacia.py` puxam 2010→corrente (17 anos)
- Anos faltantes falham gracefully
- Chips de seleção pra cada ano disponível
- Presets: Últ. 3 anos / Últ. 5 anos / Anos de seca (2014/15/17/21+atual) / Todos / Limpar

**Tooltip interativo agora em TODOS os 3 charts (EAR, ENA, Bacias)**:
- Crosshair vertical segue o mouse
- Mostra TODOS os anos selecionados na coluna
- Modo daily: label "15 Mar 2024"; modo weekly: label "Wk 11 · 18 Mar 2024"
- Valor formatado por chart (% pra EAR, MWmed pra ENA/Bacias)

**Cores dinâmicas**:
- Ano corrente: cor do subsistema (SECO azul, Sul laranja, NE verde, N roxo) — linha grossa
- Penúltimo: cinza médio claro
- Anteriores: gradiente de cinza progressivamente mais escuro

### 5. Pipelines — agregação daily preservando monthly

`ons_ear_ena.py` agora gera **ambos**:
- `ear_monthly_pct`, `ena_monthly_mwmed` (compatibilidade)
- `ear_daily_pct`, `ena_daily_mwmed` (366 valores por ano por sub)

`ons_ena_bacia.py` mesma coisa: `monthly_mwmed` + `daily_mwmed`.

JSON cresce de ~50 KB pra ~600 KB combinados — aceitável.

## Files in this patch

```
pipelines/
  common.py           ← upload again
  aneel_bandeira.py   ← v2
  aneel_tarifas.py    ← v2
  aneel_mmgd.py       ← v2
  ons_ear_ena.py      ← MODIFICADO: years 2010+ e agregação daily
  ons_ena_bacia.py    ← MODIFICADO: years 2010+ e agregação daily

tabs/
  acl.html            ← v2
  mmgd.html           ← v2
  hydrology.html      ← MODIFICADO: daily/weekly híbrido, mode badge, tooltip universal

data/
  bandeira.json       ← seed v2
  tarifas.json        ← seed v2
  mmgd.json           ← seed v3 calibrado a 46.6 GW

README.md
```

## How to deploy on GitHub web

1. **pipelines/** — substituir 6 arquivos
2. **tabs/** — substituir 3 arquivos (acl, mmgd, hydrology)
3. **data/** — substituir 3 arquivos
4. **README.md** — substituir
5. **Actions → "update-data" → Run workflow**

## Performance expectations

Primeira rodada após este patch:
- EAR/ENA: 17 CSVs cada + agregação diária ≈ **6-10 min**
- ENA Bacia: 17 CSVs + agregação diária ≈ **5-8 min**
- Tarifas v2: ≈ **5-10 min**
- MMGD v2: ≈ **8-15 min**
- Outros (NASA, NOAA, Bandeira): ≈ **2 min**

Total: **25-45 min na primeira rodada**.

## Como usar a nova interface de hidrologia

1. **Comparar com anos antigos**: clica em chips individuais ou usa preset "Anos de seca" — vê 2014/15/17/21 + atual lado a lado em modo weekly
2. **Investigar um ano específico**: clica em "Limpar" pra deixar só o ano corrente — automaticamente entra em modo **daily** com toda a granularidade
3. **Tooltip**: passa o mouse sobre qualquer chart — crosshair vertical mostra o ponto exato e o valor de todos os anos selecionados na mesma data

## Modalidades MMGD — splits realistas

| Modalidade | % kW | % count |
|---|---:|---:|
| propria_uc | 68% | 93% |
| autoconsumo_remoto | 22% | 4% |
| compartilhada | 7% | 2% |
| condominio | 2% | 0.7% |
| multipla_uc | 0.6% | 0.2% |

## Live URLs (não mudam)
- Site: https://rtbarbosa3.github.io/dashsin/
- Actions: https://github.com/rtbarbosa3/dashsin/actions
- Repo: https://github.com/rtbarbosa3/dashsin
