# BR Energy Terminal · dashsin

Painel operacional do sistema elétrico brasileiro, com dados oficiais do ONS e NOAA.
Live: https://rtbarbosa3.github.io/dashsin/

## Fontes de dados automatizadas (Fase 3)

| Aba | Variável | Fonte | Pipeline |
|---|---|---|---|
| Hidrologia | EAR diário por subsistema | ONS Dados Abertos | `pipelines/ons_ear_ena.py` |
| Hidrologia | ENA bruta + armazenável por subsistema | ONS Dados Abertos | `pipelines/ons_ear_ena.py` |
| Hidrologia | SIN agregado | derivado dos 4 subsistemas | `pipelines/ons_ear_ena.py` |
| Clima | ENA bruta diária por bacia (8 bacias) | ONS Dados Abertos | `pipelines/ons_ena_bacia.py` |
| Clima | ONI (El Niño / La Niña) | NOAA Climate Prediction Center | `pipelines/noaa_oni.py` |

## Pendente para futuras iterações (Fase 3b)

| Seção | Por que ainda é mockup | Fonte planejada |
|---|---|---|
| Anomalia agro por estado | Requer agregação satélite ou estações INMET | CHIRPS GeoTIFF ou INMET API |
| Capacity factor renováveis | Requer tracking de capacidade instalada por dia | ONS `geracao_eolica/solar_horaria` + `capacidade_geracao` |

## Schedule

GitHub Action `update-data` roda diariamente às **10h BRT (13h UTC)** com `continue-on-error: true` por pipeline (uma falha não bloqueia as outras). Trigger manual disponível em Actions > update-data > Run workflow.

## Estrutura

```
dashsin/
├── index.html              # entry point + tab navigation
├── tabs/
│   ├── market.html        # mercado / PLD (mockup)
│   ├── hydrology.html     # EAR / ENA real
│   ├── operation.html     # geração / IPDO (mockup)
│   ├── climate.html       # ENA bacia + ONI real, agro + renew mockup
│   └── acl.html           # ACL / biomassa (mockup)
├── data/                   # JSONs gerados pelos pipelines
│   ├── ear_ena.json
│   ├── ena_bacia.json
│   └── oni.json
├── pipelines/              # Python pipelines (rodam no GH Action)
│   ├── common.py
│   ├── ons_ear_ena.py
│   ├── ons_ena_bacia.py
│   └── noaa_oni.py
├── .github/workflows/
│   └── update-data.yml    # cron + workflow_dispatch
└── requirements.txt
```

## Stack
- Python 3.12 + requests (pipelines)
- HTML/CSS/JS vanilla (front)
- GitHub Pages (hosting) + GitHub Actions (data refresh)
