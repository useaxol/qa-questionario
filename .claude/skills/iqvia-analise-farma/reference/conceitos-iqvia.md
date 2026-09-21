# Conceitos e nomenclatura IQVIA — varejo farmacêutico Brasil

Referência de leitura. **Não inventar definição que não esteja aqui** — perguntar.
Marcas `[CONFIRMAR]` indicam definição que precisa ser fechada com o deck oficial de conceitos
IQVIA ou com o time.

## 1. Painéis e bases

### PMB Mix (Pharmaceutical Market Brazil — Mix)
Painel de sell-out do varejo farmacêutico no **nível SKU**, cobrindo **toda a cesta farmacêutica**:
Prescrição (RX) e Consumer Health (CH).

- **Vantagem:** visão única de todo o farma, com a classificação oficial IQVIA de
  categoria → sub-categoria → segmento. É onde a categoria do cliente se compara com as
  demais categorias do canal na mesma régua.
- **Limitação:** **não** traz quebra por canal, região, UF ou loja. Também não traz cesta
  customizada.
- **Edição:** identificada por `AAAAMM` (ex.: `202607` = fechamento de julho de 2026).
- É por aqui que toda análise começa. Só depois se desce para o mercado montado.

### Mercado montado (cesta montada)
Recorte **customizado do cliente** — os segmentos que o cliente considera seu mercado, montados
sob medida sobre a base de sell-out.

- **Vantagem:** traz as dimensões que a categoria oficial não carrega — **fabricante, marca, SKU,
  canal, região, UF, bandeira e loja (PDV)**. É onde se lê a competição.
- **Limitação:** não é comparável com as demais categorias do canal, e quase nunca coincide com a
  categoria oficial IQVIA (ver "Ponte entre recortes" em `metodos-analiticos.md`).

### FMB (Farmacêutico Mercado Brasileiro)
Painel de demanda do canal farma. Cobertura por stakeholder:

| Stakeholder | Cobertura do FMB |
|---|---|
| Varejo | **Média** — dá para ler movimentações macro; para aprofundar usar ED, MDTR, Tracking Bandeiras |
| Shopper | Baixa |
| Consumidor | Baixa |
| Paciente / Médico | Baixa |

Pela demanda é possível inferir preferência de cada stakeholder, mas entendimento real exige
estudo específico de shopper, consumidor ou paciente.

### Base de PDV
Universo de pontos de venda com venda da cesta no período (**≈ 94 mil PDVs ativos** — PDV ativo =
com venda de pelo menos uma SKU). Permite leitura loja a loja, por bandeira e por CAT.

> **Atenção recorrente:** a base de PDV normalmente **não tem dimensão de fabricante**. Ela mostra
> **onde a cesta está**, não onde o cliente está. Quem precisa do cliente loja a loja precisa de ED.

### ED — Estudo de Distribuição
Estudo de **cobertura, giro e oportunidade por ponto de venda**, com dimensão de fabricante e marca.

Responde: em quantas lojas o produto está, em quais redes/bandeiras não está, qual o giro por loja
onde está, e qual o tamanho da oportunidade de entrar. É a base certa para pergunta de
distribuição, presença e sortimento — não dá para responder distribuição com sell-out agregado.

### Panorama de Estoque
Dias de estoque e **ruptura (% de perda de venda sobre as vendas)**, por categoria e por rede.
Separa problema de demanda de problema de disponibilidade. Ruptura tipicamente vale muito mais em
reais do que o crescimento anual da cesta — é a única frente de ganho que não depende de disputar
share.

### RDC — Retail Digital Commerce
Painel de e-commerce farma: participação do online, sortimento, preço e participação por player.
Medido **sobre o painel de provedores** (não sobre o total do canal) — nunca comparar % de RDC com
% de sell-out físico sem dizer isso.

### Consumer Health Snapshot / Shopper & Consumer Insights
Pesquisa com consumidores. Responde **quem** trocou, **por quê** e **onde** a decisão acontece —
o que nenhum dado de venda responde.

### CH Talks
Publicação anual IQVIA de Consumer Health. Fonte dos números de canal (nº de lojas, share de
canal) e do recorte de forças de consumo (Cuidar / Prevenir / Embelezar).

### Outras ferramentas citadas em escopo
- **MDTR** — aprofundamento de varejo `[CONFIRMAR definição]`
- **Tracking de Bandeiras** — acompanhamento por bandeira de varejo `[CONFIRMAR definição]`

## 2. Segmentação por canal (classificação IQVIA)

Os PDVs são classificados em quatro canais para que a comparação seja precisa. Ordens de grandeza
de referência (base ABR/26, apenas PDVs ativos):

| Canal | PDVs | Critério | Exemplos |
|---|---|---|---|
| **Abrafarma** | ~11–12 mil | PDVs associados à Abrafarma — grandes redes; ~30 bandeiras | Raia Drogasil, São João, DPSP |
| **Outras redes** | ~5 mil | ≥ 6 CNPJs com a mesma raiz, sob a mesma bandeira; ~243 bandeiras | Preço Popular, Farma Conde, Ultrafarma |
| **Associativistas e Franquias** | ~29 mil | PDVs que se unem para ganhar poder de negociação com fornecedores e compartilhar gestão | Augefarma, Ultra Popular, Farmais |
| **Independentes** | ~49 mil | < 6 CNPJs com a mesma bandeira; agrupados em microrregiões | (sem bandeira identificada) |
| **Total** | **~94,2 mil** | | |

- **Abrafarma**: Associação Brasileira de Redes de Farmácias e Drogarias.
- **Associativismo**: a principal associação é a **FEBRAFAR** (Federação Brasileira das Redes
  Associativistas e Independentes de Farmácias). Benefícios ao associado: ferramentas de gestão de
  loja, cartão fidelidade, compra conjunta e visibilidade. A FEBRAFAR opera **"campanhas"** —
  compras em grande escala com negociação especial, que ela adquire e disponibiliza ao associado
  que quiser comprar. Campanha explica pico de sell-in/sell-out no canal e precisa ser considerada
  antes de ler um movimento do associativismo como tendência de demanda.
- Bandeira **`I`** na base de PDV = lojas independentes sem bandeira identificada.

## 3. Métricas

| Métrica | Definição |
|---|---|
| **R$ CPP** | Valor a preço ao consumidor. Padrão das análises; declarar sempre se é **nominal** ou deflacionado |
| **Volume** | Unidades |
| **MAT** | Ano móvel — 12 meses acumulados. `MAT Jul'26` = ago/25 a jul/26. Sempre nomear os meses na fonte |
| **CAGR** | Crescimento médio anual composto. Em base MAT de 5 pontos, CAGR de 4 anos |
| **Preço médio** | Valor ÷ unidades no período. **Não é preço de tabela** |
| **Índice de preço** | Preço médio do fabricante ÷ preço médio do segmento × 100 (mercado = 100) |
| **Share de valor / de volume** | Participação em R$ e em unidades. Ler os dois: a diferença entre eles é posicionamento de preço |
| **Δ p.p.** | Variação de share, em pontos percentuais. Share nunca varia em % |
| **Contribuição ao crescimento (p.p.)** | Δ R$ do recorte ÷ valor total do período base × 100. A soma das contribuições reconstrói o crescimento total |
| **FCC** | Código de item da IQVIA. "Item novo" = FCC sem venda no MAT anterior |
| **Sortimento ativo** | Nº de FCCs distintos com venda no período |

### CAT 1 a 8 — octis de valor de PDV
As lojas são ordenadas por faturamento da cesta e divididas em 8 faixas, **cada uma concentrando
12,5% do faturamento**. Logo, CAT1 tem poucas lojas de altíssimo giro e CAT8 tem a maioria das
lojas com giro baixo.

Uso: separa a disputa por share (nas CATs grandes, mercado maduro) da disputa por crescimento
(nas CATs intermediárias). A composição da cesta dentro da loja muda com o CAT — e um segmento
pode recuar nas lojas grandes e crescer a dois dígitos nas médias. **Nunca ler variação de
segmento só no agregado.**

## 4. Hierarquia de classificação IQVIA

```
Mercado farmacêutico
├── Prescrição (RX)
└── Consumer Health (CH)
    ├── OTC
    ├── Personal Care        ← Higiene Oral, cabelos, corpo, face, banho, solar, desodorante
    ├── Patient Care
    └── Nutrition
        └── Categoria  →  Sub-categoria  →  Segmento
```

Pontos de atenção que geram descasamento com a cesta do cliente:
- **Antissépticos bucais terapêuticos** (Periogard líquido, Bismu-Jet, Periotrat, Malvona,
  Malvatricin) são classificados pela IQVIA em **MIP** — Tratamento de Infecção na Boca e
  Irritação na Garganta — e **não** em Higiene Oral.
- **Produtos para dentadura** (fixadores, limpadores) e **desodorantes bucais** estão na categoria
  Higiene Oral, mas costumam ficar fora da cesta montada.
- **Kits e multipacks** têm critério de cadastro próprio e produzem diferença de nível entre
  recortes.

A lição é geral: **antes de comparar recortes, mapear onde cada sub-categoria da cesta do cliente
mora na árvore IQVIA.**

## 5. Forças de consumo em Consumer Health (recorte CH Talks)

| Força | O que é | Exemplos de categoria |
|---|---|---|
| **Cuidar** | Tratar o sintoma | Dor, gripes, gastro |
| **Prevenir** | Bem-estar antes da doença | Vitaminas, nutrição, proteção solar |
| **Embelezar** | Autocuidado e beleza | Cabelos, corpo, face, **higiene oral** |

Serve para posicionar a categoria do cliente: dentro da farmácia, higiene oral é cuidado pessoal
(Embelezar) — não medicamento. Isso muda com quem ela compete por prateleira, por margem e por
verba.

## 6. Marcos regulatórios do varejo farma (linha do tempo)

Contexto que explica movimento estrutural do canal. Datas a confirmar com a fonte primária antes
de publicar.

| Ano | Marco |
|---|---|
| 1995 | Início do e-commerce no país |
| 2012 | Regulamentação dos serviços de saúde em farmácias; intercambialidade de similares; informatização do SNGPC |
| 2014 | MIPs voltam ao alcance do consumidor |
| 2016–17 | Início do e-commerce no varejo farma (Ultrafarma, Onofre) |
| 2020 | Pandemia: e-commerce dobra; prescrição eletrônica e telemedicina autorizadas; testes rápidos de Covid em farmácia |
| 2023 | Vacinação em farmácias; gestão de resíduos; ampliação da Farmácia Popular (absorventes, fraldas adultas, cobertura em cidades menores, gratuidade) |
| 2024 | Entrada de medicamentos especiais/hospitalares no varejo; atualização da RDC 471 (retenção de receita obrigatória para agonistas GLP-1) |
| 2025 | Continuidade da expansão do e-commerce e dos serviços em farmácia |
| 2026 | **Lei 15.357/2026** (mar/26) autoriza farmácia dentro de supermercado e permite à farmácia contratar plataforma para logística e entrega; entrada de marketplaces (Mercado Livre, Amazon, Rappi, iFood, Shopee); fim da patente da semaglutida |

Serviços em farmácia, como ordem de grandeza: ~8,8 mil salas clínicas em operação, ~12,3 mil
farmácias e clínicas cadastradas, ~R$ 1 bi em venda de serviços, ~750 mil vacinas aplicadas.

## 7. Vocabulário de uma linha

- **Sell-out** — venda da loja para o consumidor. É o que os painéis medem.
- **Marca própria (MP)** — marca de corporação de varejo identificada no painel. Concorrente
  estrutural novo na prateleira; cresce muito acima da média do bloco.
- **Ruptura** — perda de venda por indisponibilidade, em % das vendas.
- **Item novo / lançamento** — FCC sem venda no MAT anterior.
- **Volume orgânico** — variação de unidades **dos itens que já existiam**, avaliada a preço do
  ano anterior.
- **Cesta** — o mercado montado do cliente, quando usado como sujeito ("a cesta cresceu 3,1%").
- **Célula** — cruzamento de duas dimensões (ex.: Abrafarma × Sudeste).
- **Praça** — UF ou região comercial.
