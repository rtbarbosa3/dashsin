# dashsin — Phase 4a v2 (refinements patch + hydrology multi-year)

Patch package on top of Phase 4a v1 (already deployed). Four major refinements
in this drop.

## What's new in v2

### 1. Bandeira tarifária — valor monetário cobrado
- Card "active flag" mostra agora **valor adicional cobrado** (R$/100 kWh)
  - Verde → `Sem adicional`
  - Amarela → `+R$ 1,885/100 kWh`
  - Vermelha P1 → `+R$ 4,463/100 kWh`
  - Vermelha P2 → `+R$ 7,877/100 kWh`
- Abaixo do histórico, 4 cartões com o valor vigente de cada bandeira.
- Tabela `BANDEIRA_VALOR_HISTORICO` no pipeline cobre 2015→2026 (Resoluções
  homologadas anualmente pela ANEEL).

### 2. Tarifas — TODAS as componentes
- Captura completa por distribuidora:
  - **B1 Convencional**: TE + TUSD consumo (R$/kWh)
  - **A4 Horosazonal Verde**: TE consumo Ponta/FP + TUSD consumo Ponta/FP + TUSD demanda única (R$/kW)
  - **A4 Horosazonal Azul**: TE consumo Ponta/FP + TUSD consumo Ponta/FP + TUSD demanda Ponta/FP (R$/kW)
- Tabela de reajustes ganha chevron ▸ no início. Clique pra ver os cartões
  de cada modalidade com todas as componentes.

### 3. MMGD — acumulado anual + filtro de modalidade
- Toggle no topo: Todas / Geração na própria UC / Autoconsumo remoto /
  Compartilhada / Condomínio — todos os gráficos recalculam.
- Novo gráfico "Crescimento anual desde 2015": barras (MW adicionado por
  ano) + linha (GW acumulado), eixo Y duplo, tooltip ao passar o mouse.
- **Seed corrigido**: percentuais realistas separados para kW e count.
  Autoconsumo remoto representa ~22% do kW total (não só ~2%) porque
  envolve usinas maiores servindo múltiplas UCs.

### 4. Hidrologia — histórico desde 2010 + seletor de anos
- Pipelines `ons_ear_ena.py` e `ons_ena_bacia.py` agora puxam 2010→corrente
  (17 anos vs 3 anos antes). Anos faltantes falham gracefully.
- Nova barra **"Comparar anos"** acima das seções de sazonalidade:
  - Cada ano disponível é um chip clicável (toggle on/off)
  - 5 presets: **Últ. 3 anos** / **Últ. 5 anos** / **Anos de seca** (2014/15/17/21 + corrente) / **Todos** / **Limpar**
  - Padrão: últimos 3 anos selecionados
- Cores dinâmicas:
  - Ano corrente: cor do subsistema (SECO azul, Sul laranja, NE verde, N roxo) — linha mais grossa + dots
  - Penúltimo: cinza médio claro
  - Anteriores: gradiente progressivamente mais escuro (mais antigos = mais transparentes)
- Tooltip mostra agora todos os anos selecionados na coluna.

## Files in this patch

```
pipelines/
  common.py           ← upload again
  aneel_bandeira.py   ← reescrito v2
  aneel_tarifas.py    ← reescrito v2
  aneel_mmgd.py       ← reescrito v2
  ons_ear_ena.py      ← MODIFICADO: years_to_fetch = 2010..now
  ons_ena_bacia.py    ← MODIFICADO: years_to_fetch = 2010..now

tabs/
  acl.html            ← modificado
  mmgd.html           ← modificado
  hydrology.html      ← MODIFICADO: chips de ano, presets, cores dinâmicas

data/
  bandeira.json       ← seed v2
  tarifas.json        ← seed v2
  mmgd.json           ← seed v2 (splits realistas, ~34 GW)

README.md
```

## How to deploy on GitHub web

1. **pipelines/** — substituir os 6 arquivos
2. **tabs/** — substituir 3 arquivos (acl, mmgd, hydrology)
3. **data/** — substituir 3 arquivos
4. **README.md** (raiz) — substituir
5. **Actions → "update-data" → Run workflow**

## Performance expectations

Primeira rodada após deploy vai demorar mais:
- EAR/ENA: 17 CSVs cada (vs 3 antes) ≈ 5-8 min
- Tarifas v2: mais processamento por linha ≈ 5-10 min
- MMGD v2: cross-tabs adicionais ≈ 8-15 min

Total esperado: **25-45 min na primeira rodada completa**.

## Modalidades MMGD — splits realistas

| Modalidade | Descrição | % kW | % count |
|---|---|---:|---:|
| propria_uc | Geração na própria UC | 68% | 93% |
| autoconsumo_remoto | Geração em local diferente, mesmo titular | 22% | 4% |
| compartilhada | Consórcio/cooperativa | 7% | 2% |
| condominio | Empreendimento em condomínio | 2% | 0.7% |
| multipla_uc | Múltiplas UCs vinculadas | 0.6% | 0.2% |

A diferença entre kW e count reflete que autoconsumo remoto + compartilhada
tipicamente têm usinas maiores (minigeração) servindo várias UCs, enquanto
propria_uc domina em unidades pelo mercado residencial micro.

## Anos de seca (preset "Drought yrs")

Default do preset:
- **2014**: crise hídrica SE/CO (Cantareira <5%)
- **2015**: continuação, NE crítico
- **2017**: nova seca, mais branda
- **2021**: bandeira Escassez Hídrica criada (set/21 a abr/22)
- **Ano corrente**: pra comparar

## Live URLs (não mudam)
- Site: https://rtbarbosa3.github.io/dashsin/
- Actions: https://github.com/rtbarbosa3/dashsin/actions
- Repo: https://github.com/rtbarbosa3/dashsin
