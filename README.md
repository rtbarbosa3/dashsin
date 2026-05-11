# BR Energy Terminal — DashSIN

Dashboard generalist do Sistema Interligado Nacional (SIN) brasileiro com 5 abas: Mercado (PLD), Hidrologia, Operação, Clima, ACL & Biomassa.

**Acesso público:** https://rtbarbosa3.github.io/dashsin/

## Estrutura

```
dashsin/
├── index.html              # Landing (redireciona para hydrology)
├── tabs/                   # As 5 abas do terminal
│   ├── market.html         # PLD por submercado, contexto multi-anos
│   ├── hydrology.html      # EAR/ENA, reservatórios, MWmed interativo
│   ├── operation.html      # Carga, mix, despacho térmico, intercâmbios
│   ├── climate.html        # 8 bacias de chuva, ENSO, anomalia agro
│   └── acl.html            # Forward, calendário, migração, biomassa
├── data/                   # JSONs gerados pelos pipelines (Fase 2)
├── pipelines/              # Scripts Python de coleta (Fase 2)
└── .github/workflows/      # GitHub Actions diários (Fase 2)
```

## Fontes de dados (em produção)

| Bloco | Fonte | Frequência |
|---|---|---|
| PLD diário | CCEE Dados Abertos · `pld_media_diaria_{ano}` | D+1 |
| EAR/ENA por subsistema | ONS Dados Abertos · `ear_subsistema_di` · `ena_subsistema_di` | 2x/dia (12h, 19h BRT) |
| IPDO (operação diária) | ONS · IPDO PDF | Diário |
| Precipitação por bacia | ONS · `prec_bacia` | Diário |
| ENSO ONI | NOAA Climate Prediction Center | Mensal |
| Leilões ANEEL | ANEEL Open Data | Por evento |
| Calendário CCEE | CCEE · calendário oficial | Mensal |
| Migração ACL | CCEE · `consumidores_livres` | Mensal |
| Geração biomassa | ONS · `geracao_termica_horaria` filtrada | Diário |

## Fases

- ✅ **Fase 1**: Estrutura de tabs com navegação funcional (dados mockup)
- 🚧 **Fase 2**: Pipeline Hidrologia (ONS EAR/ENA) com GitHub Action diário
- ⏳ **Fase 3**: Demais pipelines (PLD, IPDO, ONI, leilões, biomassa)
- ⏳ **Fase 4**: Refatoração para CSS/JS compartilhados

## Linguagens

EN (padrão) / PT-BR (toggle no topbar superior direito). Preferência fica salva em localStorage.

## Audiência

Clientes StoneX do agronegócio brasileiro — predominantemente consumidores puros ACL (80%) com parcela de geradores biomassa (20%).
