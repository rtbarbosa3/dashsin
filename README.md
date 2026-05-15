# BR Energy Terminal · dashsin

Painel operacional do sistema elétrico brasileiro, com dados oficiais do ONS, ANEEL, NASA POWER e NOAA.
Live: https://rtbarbosa3.github.io/dashsin/

## Fontes de dados automatizadas (Fase 4a)

| Aba | Variável | Fonte | Pipeline |
|---|---|---|---|
| Hidrologia | EAR diário por subsistema | ONS Dados Abertos | `pipelines/ons_ear_ena.py` |
| Hidrologia | ENA bruta + armazenável por subsistema | ONS Dados Abertos | `pipelines/ons_ear_ena.py` |
| Hidrologia | SIN agregado | derivado dos 4 subsistemas | `pipelines/ons_ear_ena.py` |
| Hidrologia | ENA bruta diária por bacia (8 bacias) | ONS Dados Abertos | `pipelines/ons_ena_bacia.py` |
| Clima | Precipitação por bacia (mm/mês) | NASA POWER (MERRA-2) | `pipelines/nasa_power_basin_precip.py` |
| Clima | ONI (El Niño / La Niña) | NOAA Climate Prediction Center | `pipelines/noaa_oni.py` |
| ACL | **Bandeira tarifária mensal + histórico 24m** | ANEEL Dados Abertos | `pipelines/aneel_bandeira.py` |
| ACL | **Tarifas homologadas B1 + A4 (TE + TUSD R$/kWh)** | ANEEL Dados Abertos | `pipelines/aneel_tarifas.py` |
| MMGD | **Capacidade instalada por UF, fonte, mês** | ANEEL Dados Abertos | `pipelines/aneel_mmgd.py` |

## Novidades da Fase 4a — bloco ANEEL

### 1. Bandeira tarifária na aba ACL
Card grande mostrando a bandeira em vigor (Verde, Amarela, Vermelha P1, Vermelha P2 ou Escassez Hídrica) com efeito de glow colorido. Ao lado, faixa horizontal de 24 cédulas coloridas representando o histórico do último ano e meio — útil pra ler regime de stress hidrológico e correlacionar com EAR. A bandeira lidera o PLD: quando o custo da geração térmica disparada precisa ser pago pelo cativo, a bandeira sobe.

### 2. Reajustes tarifários (B1 + A4) na aba ACL
Tabela com toggle entre **B1 (Residencial)** e **A4 (Industrial 2,3-25 kV)**, mostrando para cada uma das ~25 maiores distribuidoras: tarifa anterior, tarifa atual, % de reajuste e data da última homologação. Para o cliente ACL agro do StoneX o A4 é o mais relevante (refletindo a TUSD que mesmo no mercado livre é paga). Reajustes acima de 8% em vermelho, 4-8% em amarelo, abaixo de 4% em verde.

### 3. Nova aba dedicada **MMGD** (Micro/Mini Geração Distribuída)
Aba inteira sobre o boom de geração distribuída:
- **4 KPIs**: capacidade total instalada (GW), fonte dominante (solar lidera com ~97%), estado líder, e capacidade adicionada nos últimos 12 meses
- **Ranking por UF (27 estados)**: barras horizontais mostrando MW instalados e número de conexões. MG, SP e RS lideram
- **Donut por fonte**: solar fotovoltaica, eólica, biomassa, hídrica, outras — com legenda detalhada (MW + unidades + % do total)
- **Crescimento mensal últimos 24 meses**: gráfico de barras solar com tooltip ao hover

A relevância pro audience agro do StoneX: o boom solar gera questão estrutural pra commodity energia (não é coincidência que MMGD acelerou em paralelo aos picos de PLD).

## Separação conceitual

- **Hidrologia**: água/energia (MWmed) — EAR estoque, ENA afluência por subsistema e bacia
- **Clima**: variáveis atmosféricas (mm) — chuva precipitada por bacia e ENSO
- **ACL**: comercialização de energia — bandeira tarifária, reajustes de distribuidoras, curva forward, calendário CCEE, leilões (parcialmente real, parte mockup)
- **MMGD**: geração distribuída — capacidade instalada, mix de fontes, dinâmica de crescimento

## Pendente para futuras iterações (Fase 4b)

| Seção | O que falta | Fonte planejada |
|---|---|---|
| Market — PLD diário | Hoje é mockup; passar a usar dados reais por submercado | CCEE Dados Abertos — `PLD_MEDIA_DIARIA` |
| ACL — Migração ACL | Hoje é mockup; passar a usar dados reais de consumidores livres | CCEE Dados Abertos — Infomercado / Consumidores Livres |
| Climate — Anomalia agro por estado | Mockup; requer agregação satélite por estado | CHIRPS GeoTIFF ou INMET API |
| Operation — Capacity factor renováveis | Mockup; requer tracking de capacidade instalada por dia | ONS `geracao_eolica/solar_horaria` |

## Schedule

GitHub Action `update-data` roda diariamente às **10h BRT (13h UTC)** com `continue-on-error: true` por pipeline (uma falha não bloqueia as outras). Trigger manual disponível em Actions > update-data > Run workflow.

⚠️ **Importante na primeira execução pós-deploy**: o pipeline `aneel_mmgd.py` faz download de um CSV gigante (~1-2 GB) e pode levar **10-30 minutos** rodando. O timeout foi setado em 30min. O pipeline `aneel_tarifas.py` também é grande (centenas de MB) e tem timeout de 20min. Ambos usam **streaming linha-a-linha** (não carregam o arquivo todo em memória), então não consomem RAM acima de ~100MB.

## Sobre os streaming pipelines (Fase 4a)

`common.py` ganhou a função `stream_csv_rows(url)` que faz iteração linha-a-linha de CSVs remotos sem carregar tudo em memória. Estratégia:

1. `requests.get(stream=True)` → não baixa antes de ler
2. `iter_lines(decode_unicode=False)` → recebe bytes raw por linha
3. Decodifica per-linha tentando `utf-8-sig`, `utf-8`, `latin-1`
4. Detecta delimitador (`;` vs `,`) na primeira linha
5. Parseia cada linha como CSV de 1 row e cede como dict

Isso permite processar o MMGD (cerca de 6 milhões de linhas de empreendimentos individuais) e o Tarifas Homologadas em GitHub Action grátis (7 GB RAM disponíveis).

Adicionalmente, o parser `to_float` foi corrigido pra lidar com locale BR onde `1.234,56` vira 1234.56 (não 1.23456). Detecção é por posição: o separador mais à direita é o decimal.

## Estrutura

```
dashsin/
├── tabs/
│   ├── market.html        # mercado / PLD (mockup — Fase 4b)
│   ├── hydrology.html     # EAR + ENA (sub + bacia) — REAL
│   ├── operation.html     # geração / IPDO (mockup)
│   ├── climate.html       # chuva por bacia + ONI REAL, agro + renew mockup
│   ├── acl.html           # ACL — bandeira + reajustes B1/A4 REAIS; resto mockup
│   └── mmgd.html          # MMGD — capacidade, fontes, crescimento mensal — REAL
├── data/
│   ├── ear_ena.json
│   ├── ena_bacia.json
│   ├── precip_bacia.json
│   ├── oni.json
│   ├── bandeira.json      # NOVO Fase 4a
│   ├── tarifas.json       # NOVO Fase 4a
│   └── mmgd.json          # NOVO Fase 4a
├── pipelines/
│   ├── common.py
│   ├── ons_ear_ena.py
│   ├── ons_ena_bacia.py
│   ├── nasa_power_basin_precip.py
│   ├── noaa_oni.py
│   ├── aneel_bandeira.py  # NOVO Fase 4a
│   ├── aneel_tarifas.py   # NOVO Fase 4a
│   └── aneel_mmgd.py      # NOVO Fase 4a
├── .github/workflows/
│   └── update-data.yml    # cron diário + workflow_dispatch
├── requirements.txt
└── README.md
```

## Stack
- Python 3.12 + requests (pipelines)
- HTML/CSS/JS vanilla (front)
- GitHub Pages (hosting) + GitHub Actions (data refresh)
