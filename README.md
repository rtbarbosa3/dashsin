# dashsin · Patch Fase 4b — PLD pipeline + Market refeita

**Bug original**: a aba Market tinha dados de PLD **hardcoded** (`const MONTHLY = {…}`) que iam só até março/2026. Sem pipeline conectado, **não atualizavam sozinhos** quando a CCEE publicava dias novos.

**Fix**: pipeline automatizado puxando `PLD_MEDIA_DIARIA` direto do portal Dados Abertos da CCEE, com histórico completo 2021-2026, e a aba Market refeita do zero seguindo o padrão de Climate/Hydrology (chips de anos, modal, drag-zoom, tooltip universal, etc).

---

## Arquivos neste patch

| Arquivo | Destino no repo | Função |
|---|---|---|
| `pipelines/ccee_pld.py` | `pipelines/ccee_pld.py` | **NOVO** — busca PLD diário CCEE 2021-2026 e gera `data/pld.json` |
| `tabs/market.html` | `tabs/market.html` | **SUBSTITUI** — Market refeita do zero (1062 linhas) |
| `update-data.yml` | `.github/workflows/update-data.yml` | **SUBSTITUI** — adiciona step CCEE PLD ao workflow |
| `data/pld.json` | `data/pld.json` | **NOVO seed** — 141 KB, será sobrescrito na 1ª run do Action |

---

## O que o pipeline faz

`pipelines/ccee_pld.py`:

- Resolve UUIDs estáveis dos 6 CSVs anuais via CKAN `resource_show` (não precisa scrape do HTML)
- Anos: **2021, 2022, 2023, 2024, 2025, 2026** (cobertura total do dataset CCEE)
- Parse robusto do CSV `MES_REFERENCIA;SUBMERCADO;DIA;PLD_MEDIA_DIA` com fallback de encoding
- Mapeia submercados PT-BR → siglas internas: `SUDESTE→SECO`, `NORDESTE→NE`, `NORTE→N`, `SUL→SUL`
- Output `data/pld.json`:

```json
{
  "generated_at_utc": "...",
  "source": { "name": "CCEE Dados Abertos — PLD_MEDIA_DIARIA", ... },
  "submarkets": ["SECO", "SUL", "NE", "N"],
  "now": { "SECO": {"pld": 366.97, "date": "2026-05-18"}, ... },
  "daily_by_year": { "SECO": {"2021": [366 valores], ...}, ... },
  "monthly_avg":   { "SECO": {"2021": [12 médias], ...}, ... },
  "year_stats":    { "SECO": {"2021": {"avg":..., "min":..., "max":..., "std":..., "days":...}, ...}, ... }
}
```

---

## O que a Market nova entrega

### Visual (igual Climate/Hydrology)
- **Chips de anos**: 2021-2026 selecionáveis, com 5 presets (last3 / last5 / **drought** / all / clear)
- **Mode badge** auto: `DAILY` (1 ano), `WEEKLY` (2+ anos), `MONTHLY` (fallback)
- **4 mini-charts**: um por submercado (SECO/SUL/NE/N) com cores próprias
- **Modal fullscreen** (botão ⛶): chart grande ~1300×480 com mesma interatividade
- **Drag-zoom horizontal**: arrastar no chart pequeno OU no modal, brush azul, botão `↺ Reset zoom`
- **Tooltip universal**: crosshair vertical + valores por ano (com cores)
- **Cores dinâmicas por ano**: ano atual em cor do submercado (linha grossa), anteriores em escala de cinza
- **Loading/erro states** + botão `↻ Reload` com spinner

### Extras solicitados
- **(a) Histórico completo 2021+**: 6 anos no chip selector e na stats table
- **(c) Year stats table**: tabela com `avg / min / max / std` por submercado × ano
- **(d) Linhas de referência bandeira tarifária** (R$/MWh):
  - `< 100` Verde (verde claro tracejado)
  - `100–200` Amarela
  - `200–400` Vermelha 1
  - `> 400` Vermelha 2

### Insights automatizados
- Análise YoY SE/CO computada do `year_stats` (não hardcoded)
- Bandeira-equivalente do nível atual SE/CO
- Spread NE/N vs SE/CO automático (cheapest vs most exposed)

---

## Ordem de aplicação no GitHub

Use upload web (drag-drop) para substituir cada arquivo:

1. **`pipelines/ccee_pld.py`** → criar arquivo novo
2. **`tabs/market.html`** → substituir o existente
3. **`.github/workflows/update-data.yml`** → substituir
4. **`data/pld.json`** → criar arquivo novo (seed sintético — será sobrescrito na 1ª Action run)

Depois disso, executar manualmente o workflow em **Actions → update-data → Run workflow** para puxar os dados reais da CCEE pela 1ª vez. O `pld.json` será atualizado com dados reais e o site refletirá imediatamente.

---

## Verificação pós-deploy

### 1. Action rodou sem erro
- Em **Actions**, o run mais recente deve mostrar 8 steps verdes (todos os pipelines)
- Step `Run CCEE PLD pipeline` deve mostrar nos logs:
  ```
  [2021] parsed ~1,460 rows (skipped 0)
  [2022] parsed ~1,460 rows
  ...
  [2026] parsed ~XXX rows (YTD)
  Total records: ~9,000
  Wrote .../pld.json (~150 KB)
  ```

### 2. Arquivo commitado
- Em `data/pld.json`, o `source.name` deve dizer `"CCEE Dados Abertos — PLD_MEDIA_DIARIA"` (não mais `"INITIAL SEED — synthetic..."`)
- `source.fetch_errors` deve ser `[]`

### 3. Market mostra dados atualizados
- Abrir https://rtbarbosa3.github.io/dashsin/tabs/market.html
- KPI strip mostra o PLD do dia mais recente disponível (4 submercados)
- Chips mostram 2021-2026
- "Updated" no canto direito mostra data/hora da última run do Action (BRT)
- Clicar no ⛶ de qualquer chart abre o modal
- Arrastar no chart faz zoom

### 4. Teste rápido de regressão
- Mudar ano selecionado → mode badge alterna entre DAILY/WEEKLY corretamente
- Preset "Drought yrs" deve marcar **2021** (crise hídrica) + ano atual
- Year stats table mostra 4 colunas × 6 anos (24 cells de stats por linha)
- Stats SECO 2021 deve mostrar avg ≈ R$ 600 e max ≈ R$ 1.100 (refletindo crise hídrica)

---

## Notas técnicas

- **CKAN API**: a CCEE usa CKAN 2.10 com endpoint público `/api/3/action/resource_show?id=<uuid>`. Os UUIDs dos resources anuais são estáveis (não mudam entre uploads), por isso estão hardcoded no `PLD_RESOURCES`. Se a CCEE algum dia mudar os UUIDs, atualizar essa constante.
- **Encoding**: o CSV vem em UTF-8 mas testamos fallback para latin-1 caso a CCEE mude. Função `fetch_text` do `common.py` já lida com isso.
- **Robustez**: pipeline continua mesmo se 1 ano falhar (log em `source.fetch_errors`). Só aborta se NENHUM ano carregar.
- **Sintético seed**: o `pld.json` deste patch tem dados sintéticos com baselines aproximados (2021=R$ 642 SECO refletindo crise hídrica, 2022=R$ 78 piso, etc). **Será sobrescrito na 1ª Action run** com dados reais.

---

## Mudanças no `update-data.yml`

Apenas adicionado UM step entre `noaa_oni` e `aneel_bandeira`:

```yaml
- name: Run CCEE PLD pipeline (6 years × 4 submarkets)
  run: python pipelines/ccee_pld.py
```

Todo o resto (concurrency lock, git pull --rebase, push) permanece igual.
