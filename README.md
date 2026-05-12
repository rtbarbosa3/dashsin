# BR Energy Terminal · dashsin

Painel operacional do sistema elétrico brasileiro, com dados oficiais do ONS, NASA POWER e NOAA.
Live: https://rtbarbosa3.github.io/dashsin/

## Fontes de dados automatizadas (Fase 3b)

| Aba | Variável | Fonte | Pipeline |
|---|---|---|---|
| Hidrologia | EAR diário por subsistema | ONS Dados Abertos | `pipelines/ons_ear_ena.py` |
| Hidrologia | ENA bruta + armazenável por subsistema | ONS Dados Abertos | `pipelines/ons_ear_ena.py` |
| Hidrologia | SIN agregado | derivado dos 4 subsistemas | `pipelines/ons_ear_ena.py` |
| Hidrologia | **ENA bruta diária por bacia (8 bacias)** | ONS Dados Abertos | `pipelines/ons_ena_bacia.py` |
| Clima | **Precipitação por bacia (mm/mês)** | NASA POWER (MERRA-2) | `pipelines/nasa_power_basin_precip.py` |
| Clima | ONI (El Niño / La Niña) | NOAA Climate Prediction Center | `pipelines/noaa_oni.py` |

## Separação conceitual

A partir da Fase 3b, **hidrologia e clima ficam separados pela natureza da variável**:

- **Hidrologia** mostra água/energia disponível no SIN — EAR (estoque), ENA (afluência) tanto por subsistema quanto por bacia. ENA é a energia equivalente da chuva que efetivamente chegou aos reservatórios após escoamento. Métrica em MWmed.
- **Clima** mostra variáveis meteorológicas atmosféricas — chuva precipitada (mm/mês por bacia, via satélite) e o ciclo ENSO (El Niño/La Niña). Métrica em mm.

A diferença prática entre as duas: chuva de 100mm sobre uma bacia íngreme com solo seco produz menos ENA do que 100mm sobre uma bacia plana já saturada. Por isso vale ver as duas.

## Pendente para futuras iterações

| Seção | Por que ainda é mockup | Fonte planejada |
|---|---|---|
| Anomalia agro por estado | Requer agregação satélite ou estações INMET por estado | CHIRPS GeoTIFF ou INMET API |
| Capacity factor renováveis | Requer tracking de capacidade instalada por dia | ONS `geracao_eolica/solar_horaria` + `capacidade_geracao` |

## Schedule

GitHub Action `update-data` roda diariamente às **10h BRT (13h UTC)** com `continue-on-error: true` por pipeline (uma falha não bloqueia as outras). Trigger manual disponível em Actions > update-data > Run workflow.

## Sobre NASA POWER

A fonte de precipitação por bacia é o **NASA POWER** (Prediction Of Worldwide Energy Resources), produto público da NASA Langley baseado em MERRA-2 (reanalise satelital com correção de viés contra estações). Para cada uma das 8 bacias o pipeline consulta um ponto centroide representativo e agrega chuva diária (variável `PRECTOTCORR`) em totais mensais. A MLT (média de longo termo) é calculada com janela 2014-2023 (10 anos).

Por que NASA POWER:
- O ONS descontinuou seu dataset público de precipitação por estação em 2021 (passou a usar dados de satélite internamente, não publicados em CSV)
- NASA POWER é a fonte global padrão para essa categoria de dado quando estações públicas não são adequadas
- API JSON simples, sem cadastro, com cobertura mundial

Limitação atual: cada bacia é representada por um único ponto centroide (~50 km de resolução da grade MERRA-2). Para bacias grandes como Paranaíba e Tocantins isso é uma aproximação. Em uma iteração futura podemos amostrar múltiplos pontos por bacia e fazer média ponderada.

## Estrutura

```
dashsin/
├── index.html              # entry point + tab navigation
├── tabs/
│   ├── market.html        # mercado / PLD (mockup)
│   ├── hydrology.html     # EAR + ENA (sub + bacia) — tudo real
│   ├── operation.html     # geração / IPDO (mockup)
│   ├── climate.html       # chuva por bacia + ONI real, agro + renew mockup
│   └── acl.html           # ACL / biomassa (mockup)
├── data/
│   ├── ear_ena.json       # ONS EAR/ENA subsistema + SIN agregado
│   ├── ena_bacia.json     # ONS ENA bruta por bacia
│   ├── precip_bacia.json  # NASA POWER chuva por bacia
│   └── oni.json           # NOAA ONI
├── pipelines/
│   ├── common.py
│   ├── ons_ear_ena.py
│   ├── ons_ena_bacia.py
│   ├── nasa_power_basin_precip.py
│   └── noaa_oni.py
├── .github/workflows/
│   └── update-data.yml    # cron diário + workflow_dispatch
└── requirements.txt
```

## Stack
- Python 3.12 + requests (pipelines)
- HTML/CSS/JS vanilla (front)
- GitHub Pages (hosting) + GitHub Actions (data refresh)
