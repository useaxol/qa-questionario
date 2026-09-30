# ED — Estudo de Distribuição: performance, CAT e cálculo de oportunidade

Fonte: deck oficial **IQVIA — Main Concepts / Conceitos Base de dados regular**.
Estes conceitos são a linguagem do ED. Usar os nomes exatos no deck do cliente.

## 1. O modelo de cálculo

Estrutura verificada célula a célula contra `MATRIZ PARA CÁLCULOS DE ED`. Uma linha por PDV.

### Entradas
| Campo | Conteúdo |
|---|---|
| `CODIGO` · `CNPJ` · `DESCRIÇÃO_DO_PDV` | identificação do PDV |
| `ESTADO` · `NOVO_TIPO` · `BANDEIRA` | dimensões brutas |
| `DEM_CLIENTE_MAT` · `DEM_CONC_MAT` | demanda do cliente e da concorrência, período atual |
| `DEM_CLIENTE_MAT_ANT` · `DEM_CONC_MAT_ANT` | idem, período anterior |

### Derivações
```
DEM_TOTAL        = DEM_CLIENTE + DEM_CONC
ATIVO_VENDA      = SE(DEM_TOTAL > 0; "S"; "N")
REGIÃO           = de-para UF → 5 regiões
CANAL            = de-para NOVO_TIPO → 4 canais
CLUSTER          = REGIÃO & CANAL                        [20 células]

PRESENÇA         = SE(DEM_CLIENTE >= 0,1; 1; 0)          [atual e anterior]
SHARE_PDV        = DEM_CLIENTE ÷ DEM_TOTAL
SHARE_CLUSTER    = SOMASE(cluster; DEM_CLIENTE) ÷ SOMASE(cluster; DEM_TOTAL)
DIF_ABSOLUTA     = SHARE_PDV − SHARE_CLUSTER             [p.p.]
DIF_RELATIVA     = SHARE_PDV ÷ SHARE_CLUSTER − 1         [%]

OPP_PDV          = SE(DIF_ABSOLUTA > 0; 0; DEM_TOTAL × ABS(DIF_ABSOLUTA))
```

Quatro pontos de atenção que a fórmula revela:

- **O share do cluster é agregado, não média de PDVs.** É `Σ demanda do cliente ÷ Σ demanda
  total` dentro do cluster. Os PDVs grandes pesam mais na régua — o que é correto, mas significa
  que a "média" contra a qual cada loja é comparada é puxada pelas lojas de alto giro.
- **A performance usa a diferença RELATIVA; a oportunidade usa a ABSOLUTA.** São colunas
  diferentes e não se substituem.
- **Oportunidade tem piso em zero.** PDV acima da média do cluster não gera oportunidade
  negativa — ele some da conta, não a reduz. Somar oportunidades nunca dá um número líquido.
- **Presença exige demanda ≥ 0,1**, não simplesmente maior que zero. Venda residual não conta
  como positivação.

### O cluster
**5 regiões × 4 canais = 20 células.** Os canais do cluster são Abrafarma, Outras Redes,
Assoc. & Franquias (colapsados numa célula só) e Independentes. O de-para de `NOVO_TIPO`:

| NOVO_TIPO | Canal |
|---|---|
| `R_ABRA` | ABRAFARMA |
| `R_OUTRAS` | OUT. REDES |
| `R_ASSOC` · `FRANQ` | ASSOC & FRANQ |
| `I` | INDEPS |

Mudar a definição de cluster muda toda a performance e toda a oportunidade. Declarar qual foi
usado.

### Exemplo do material conceitual
PDV X, canal Abrafarma, região Sudeste:

| | |
|---|---|
| Venda do mercado no PDV | 1.000 |
| Share do cliente no PDV | 10,0% |
| Share médio do cluster | 15,0% |
| Diferença absoluta | −5 p.p. |
| **Oportunidade** | **50** |

## 2. Performance do PDV — classificação A a F

Classificação pela **diferença relativa** entre o share do PDV e o share médio do cluster.

| Classe | Faixa de diferença relativa |
|---|---|
| **A** | acima de +20% |
| **B** | de +10% (exclusive) a +20% |
| **C** | de 0 (exclusive) a +10% |
| **D** | de −10% (exclusive) a 0 (inclusive) |
| **E** | de −20% (exclusive) a −10% |
| **F** | −20% ou pior |
| **Z** | PDV **não positivado** — presença = 0 no período atual |

- **A a F é desvio relativo, não share absoluto.** Um PDV classe A num cluster fraco pode ter
  share menor que um classe D num cluster forte. Nunca ler A–F como ranking de tamanho.
- **O PDV exatamente na média cai em D**, não em C. O material conceitual descreve C e D como
  "na média até 10% acima / abaixo"; a fórmula desempata para baixo.
- **Z é a outra metade da história.** No material de referência, 40,2 mil dos 61,3 mil PDVs eram
  Z. Reportar positivados e não positivados separadamente.

## 3. CAT — categorias de PDV

Os PDVs são ordenados por demanda total decrescente; calcula-se o **share acumulado** do
faturamento e corta-se em faixas de 12,5%:

```
SHARE_ACUM = SOMA(demanda dos PDVs até aqui) ÷ SOMA(demanda de todos)
CAT        = 1 se ACUM <= 12,5% ; 2 se <= 25% ; 3 se <= 37,5% ; 4 se <= 50%
             5 se <= 62,5% ; 6 se <= 75% ; 7 se <= 87,5% ; 8 se <= 100%
```

Cada CAT concentra 12,5% das vendas com número diferente de PDVs. Faixas de leitura:
**ALTO** = CAT 1–3, **BOM** = CAT 4–6, **BAIXO** = CAT 7–8.

O CAT é calculado **sobre o mercado-alvo do projeto** — muda se a cesta muda. Dois projetos do
mesmo cliente com cestas diferentes têm CATs diferentes para o mesmo PDV.

Composição típica por canal (ordem de grandeza do material de referência, ~55,8 mil PDVs):

| | CAT 1–6 | CAT 7–8 |
|---|---|---|
| PDVs | 8.469 | 51.814 |
| Abrafarma | 2% | 0% |
| Outras redes | 7% | 1% |
| Assoc. & Franquias | 62% | 34% |
| Independentes | 29% | 65% |

## 4. Matriz CAT × Performance — a ação por PDV

O cruzamento das duas dimensões diz **o que fazer em cada loja**. É a saída mais acionável do ED.

```
                        P E R F O R M A N C E
                 A    B    C  │  D    E    F    Z
              ┌───────────────┼──────────────────┐
     CAT 1    │                                  │
C    CAT 2    │                                  │
A    CAT 3    │                      A T A C A R │
T    CAT 4    │   P R O T E G E R                │
      ────    │               ├──────────────────┤
     CAT 5    │                                  │
     CAT 6    │                    A V A L I A R │
              ├───────────────┴──────────────────┤
     CAT 7    │      D E S P R I O R I Z A R     │
     CAT 8    │                                  │
              └──────────────────────────────────┘
```

| Bucket | Regra | O que significa | Ação |
|---|---|---|---|
| **PROTEGER** | CAT 1–6 × A/B/C | Loja relevante onde já se está na média do cluster ou acima | Defender posição |
| **ATACAR** | CAT 1–4 × D/E/F/Z | Loja de alto giro onde se está abaixo do cluster ou ausente | É aqui que a oportunidade se concretiza — prioridade máxima |
| **AVALIAR** | CAT 5–6 × D/E/F/Z | Loja de giro médio abaixo da média | Entra conforme custo de servir |
| **DESPRIORIZAR** | CAT 7–8 (qualquer performance, inclusive Z) | A maioria dos PDVs, com 25% das vendas | Não sustenta esforço individual |

Esta é a classificação de trabalho — a que sai nos slides de resultado e a que o time comercial
recebe. Usar esses quatro nomes, com esses cortes.

Validação do material de referência (61.328 PDVs): PROTEGER 2.981 · ATACAR 1.192 ·
AVALIAR 5.033 · DESPRIORIZAR 52.122. As quatro contagens fecham o universo exatamente.

Ao apresentar a matriz, trazer sempre as quatro contagens de PDV e conferir que somam o universo.
E lembrar que **Z entra em ATACAR nas CATs 1–4**: PDV de alto giro sem o produto é a maior
oportunidade unitária que existe, não uma loja "sem histórico".

## 4b. Tipo de oportunidade — distribuição ou giro/mix

Derivado direto da performance, em dois grupos apenas:

```
TIPO_OPP = SE(PERFORMANCE = "Z"; "DISTRIBUIÇÃO"; "GIRO/MIX")
```

| Tipo | Quem entra | O que a ação é |
|---|---|---|
| **DISTRIBUIÇÃO** | PDVs classe Z — não positivados | Negociação de entrada: o produto não está na loja |
| **GIRO/MIX** | PDVs positivados com performance abaixo do cluster | Execução, sortimento, ponto extra: o produto está lá e vende menos que deveria |

Não é uma classificação por número de categorias que o PDV carrega — é binária e sai da própria
coluna de performance. Reportar a oportunidade total aberta nesses dois blocos: são conversas
diferentes, com times diferentes.

## 4c. DN e DP — cobertura por marca

O modelo calcula, por **marca** e por **canal**, nos dois períodos:

```
presença da marca no PDV = SE(demanda da marca no PDV > 0; "S"; "N")

DN  (distribuição numérica) = CONT.SE(presença = "S")            → nº de PDVs
DP  (distribuição ponderada) = SOMASES(demanda do canal ; presença = "S")
                               ÷ demanda total do canal          → % da demanda coberta
ΔDN = PDVs com presença no atual − PDVs com presença no anterior
```

A leitura que esse bloco entrega: **DN baixa com DP alta** significa que a marca está nas lojas
que importam e falta capilaridade; **DN alta com DP baixa** significa presença pulverizada em
loja pequena, sem entrar onde o giro está. E o `ΔDN` diz se a marca ganhou ou perdeu ponto de
venda no ano — número que sell-out agregado não mostra.

> Atenção: neste bloco a presença é `demanda > 0`, enquanto na aba de cálculo do PDV é
> `demanda >= 0,1`. Conferir qual critério vale antes de comparar contagens entre as duas abas.

## 5. Onde a oportunidade se desdobra

Depois de classificada, a oportunidade é aberta nos cortes que viram conversa comercial:

| Corte | Para quê |
|---|---|
| **Por bandeira (top 10)** | É a lista de negociação. O bloco "INDEPS" costuma ser o maior de todos e não tem interlocutor único |
| **Por UF e região** | Prioriza roteiro de campo. Trazer `# PDVs` ao lado de `oportunidade R$` |
| **Por CAT** | Confirma que o esforço está nas lojas que pagam |
| **Positivados vs não positivados** | Separa oportunidade de **giro/mix** de oportunidade de **distribuição** |
| **Op/PDV** | Oportunidade média por loja. É o número que decide se vale a visita |

Como a oportunidade tem piso em zero, qualquer soma é **bruta**: ela mede o que falta para os
PDVs deficitários chegarem à média do cluster, não um saldo líquido do mercado. Dizer isso na
fonte do slide.

O detalhe de giro/mix vs distribuição está em §4b — sai da coluna de performance, não de uma
regra à parte.


## 6. Performance por bandeira (leitura de share)

Gráfico padrão do ED: barra 100% por bandeira com `CLIENTE` vs `CONCORRÊNCIA`, acompanhado de
três colunas:

- **IMP. (%) CATEGORIA** — peso da bandeira no mercado-alvo
- **IMP. (%) CLIENTE** — peso da bandeira no faturamento do cliente
- **VAR. SHARE (p.p.)** — variação do share do cliente na bandeira

A leitura que esse slide entrega: **bandeira onde IMP. cliente < IMP. categoria é bandeira
sub-indexada** — o cliente pesa menos ali do que o mercado pesa. Cruzar com VAR. SHARE separa
quem já está reagindo de quem segue perdendo.

Rodar o mesmo gráfico para os quatro canais. No canal Independentes a quebra é **por UF**, não por
bandeira — independente não tem bandeira.

## 7. Tiers de preço

Classificação por **índice de preço** (mercado do segmento = 100):

| Tier | Índice de preço |
|---|---|
| **PREMIUM** | IP > 200 |
| **HIGH** | 120 < IP < 200 |
| **MEDIUM** | 80 < IP < 120 |
| **LOW** | IP < 80 |

Usar para ler a arquitetura de preço da categoria e onde o portfólio do cliente está posicionado —
e, cruzando com Δ volume por tier, se o mercado está premiumizando ou barateando.

## 8. Elementos de crescimento — convenção oficial IQVIA

Cálculo feito **no nível SKU/FCC**, em três elementos:

| Elemento | Definição IQVIA | Fórmula do modelo |
|---|---|---|
| **Organic Growth** | Crescimento de volume do período 1 para o período 2 | `SE(launch="N"; (un_atual − un_ant) × preço_ant; 0)` |
| **Launch (novos SKUs)** | SKUs cujo volume no período 1 é 0 e apresentam volume no período 2 | `SE(launch="S"; un_launch × preço_atual; 0)` ≡ valor atual do item |
| **Price Increase (preço/mix)** | Contribuição do preço ou do mix para o crescimento | `(valor_atual − valor_ant) − Launch − Organic` |

com `launch = SE(un_atual > 0 E un_ant = 0)` — **classificação por unidades, não por valor**.

**Apresentar sempre nesses três elementos** — é a convenção que o cliente já conhece.
Descontinuados caem inteiros no Organic Growth, como `−valor_anterior`; não são um quarto
elemento. `scripts/decompor_crescimento.py` os reporta em linha separada só para diagnóstico.

Mecânica completa, casos-limite e a prática de rodar nos dois anos:
`metodos-analiticos.md`, §1.

## 9. Armadilhas conhecidas do modelo

Conferir na planilha do projeto antes de rodar. Três divergências encontradas na versão auditada:

| Onde | O que acontece | Efeito |
|---|---|---|
| De-para UF → região, coluna `REGIÕES_NORMALIZADA` | **PI é mapeado como NORTE**; pelo IBGE é Nordeste | Infla Norte e desfalca Nordeste, no PDV e no cluster — e como o cluster é região × canal, muda performance e oportunidade de todo PDV do Piauí e dos demais do Norte |
| De-para `NOVO_TIPO` → canal | `N/I` vira **ABRAFARMA** na aba de cálculo do PDV e **INDEPS** na aba de DN/DP | Os mesmos PDVs caem em canais diferentes nas duas abas; contagens não batem entre elas |
| Critério de presença | `demanda >= 0,1` na aba de cálculo do PDV, `demanda > 0` na aba de DN/DP | DN pode contar PDV que a performance trata como `Z` |

Os de-para terminam em `"CHECARRRRR"` para valor não previsto — varrer essa string na planilha
antes de aceitar qualquer número: ela marca UF ou tipo de PDV que o modelo não soube classificar.
