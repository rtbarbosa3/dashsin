# dashsin — Phase 4a v2 (refinements patch)

Patch package on top of Phase 4a v1 (already deployed). Brings 3 enhancements
without touching the 4 ONS/NASA/NOAA pipelines that are already working.

## What's new in v2

### 1. Bandeira tarifária — agora mostra valor monetário
- Card "active flag" mostra agora **valor adicional cobrado** (R$/100 kWh)
  - Verde → `Sem adicional`
  - Amarela → `+R$ 1,885/100 kWh`
  - Vermelha P1 → `+R$ 4,463/100 kWh`
  - Vermelha P2 → `+R$ 7,877/100 kWh`
- Abaixo do histórico de 24 meses, 4 cartões pequenos mostrando o valor vigente
  de cada bandeira (atualizado quando ANEEL homologa nova resolução anual).
- Valores históricos completos embutidos no pipeline (2015→2026), com
  fallback para coluna do CSV se disponível.

### 2. Tarifas — todas as componentes
- Cada distribuidora agora captura TODAS componentes tarifárias:
  - **B1 Convencional**: TE + TUSD consumo (R$/kWh)
  - **A4 Horosazonal Verde**:
    - TE consumo Ponta + Fora Ponta (R$/kWh)
    - TUSD consumo Ponta + Fora Ponta (R$/kWh)
    - TUSD demanda única (R$/kW)
  - **A4 Horosazonal Azul**:
    - TE consumo Ponta + Fora Ponta (R$/kWh)
    - TUSD consumo Ponta + Fora Ponta (R$/kWh)
    - TUSD demanda Ponta + Fora Ponta (R$/kW)
- Tabela de reajustes ficou com chevron ▸ no início da linha. Clique pra expandir
  uma seção detalhada com cartões para cada modalidade.

### 3. MMGD — acumulado anual + filtro de modalidade
- Toggle no topo: **Todas** / **Geração na própria UC** / **Autoconsumo remoto**
  / **Compartilhada** / **Condomínio** — TODOS os gráficos da aba recalculam.
- Novo gráfico **"Crescimento anual desde 2015"**: barras (MW adicionado por
  ano) + linha (GW acumulado), eixo Y duplo, tooltip ao passar o mouse.
- Histórico anual desde 2015 com 13 pontos (2014-2026 YTD).

## Files in this patch

```
pipelines/
  common.py           ← upload again (same as v1, just in case)
  aneel_bandeira.py   ← reescrito v2
  aneel_tarifas.py    ← reescrito v2
  aneel_mmgd.py       ← reescrito v2

tabs/
  acl.html            ← modificado
  mmgd.html           ← modificado

data/
  bandeira.json       ← seed v2 (será substituído pelo Action)
  tarifas.json        ← seed v2 (será substituído pelo Action)
  mmgd.json           ← seed v2 alinhado com 34.28 GW da ANEEL

README.md             ← este arquivo
```

## How to deploy on GitHub web

1. **pipelines/** — substituir 4 arquivos (sobrescrever os 3 novos + common.py):
   - aneel_bandeira.py, aneel_tarifas.py, aneel_mmgd.py, common.py

2. **tabs/** — substituir 2 arquivos:
   - acl.html, mmgd.html

3. **data/** — substituir 3 arquivos:
   - bandeira.json, tarifas.json, mmgd.json

4. **README.md** (na raiz) — substituir

5. Após upload, **Actions → "update-data" → Run workflow** para rodar todos os
   7 pipelines uma vez. Pode demorar 10-30 min na primeira rodada (MMGD CSV é
   muito grande).

## Pipeline behavior notes

### aneel_bandeira.py v2
- Tem tabela hardcoded `BANDEIRA_VALOR_HISTORICO` com valores das Resoluções
  ANEEL desde 2015. Se o CSV expor coluna "valor adicional", usa do CSV;
  senão, usa a tabela. Quando ANEEL homologar nova resolução em jul/2026,
  adicionar nova linha em `BANDEIRA_VALOR_HISTORICO` no formato:
  `(date(2026, 7, 1), {"verde": 0.0, "amarela": X, ...}),`

### aneel_tarifas.py v2
- Captura cross-product `(distribuidora × subgrupo × data × modalidade × componente)`.
- Reajuste % é calculado entre as 2 últimas datas no total convencional (B1)
  ou TE+TUSD fora ponta (A4 — referência industrial mais utilizada).
- Componentes individuais nunca são truncadas no JSON.

### aneel_mmgd.py v2
- Adiciona 3 agregações novas: `by_modalidade`, `by_year` (com cumulative),
  `cross_tabs` (uf×mod, fonte×mod, year×mod).
- Cross-tabs permitem ao front filtrar dinamicamente sem reload.
- Captura desde 2014/2015 (sem corte de 24 meses).

## Modalidades MMGD

Conforme painel oficial ANEEL:

| Modalidade | Descrição |
|---|---|
| `propria_uc` | Geração na própria UC (autoconsumo no local) |
| `autoconsumo_remoto` | Geração em local diferente do consumo, mesmo titular |
| `compartilhada` | Geração compartilhada entre consumidores agrupados |
| `condominio` | Empreendimento de geração em condomínio |
| `multipla_uc` | Empreendimento com múltiplas UCs vinculadas |

## Live URLs (unchanged)
- Site: https://rtbarbosa3.github.io/dashsin/
- Actions: https://github.com/rtbarbosa3/dashsin/actions
- Repo: https://github.com/rtbarbosa3/dashsin
