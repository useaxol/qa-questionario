# ED — Estudo de Distribuição: performance, CAT e cálculo de oportunidade

Fonte: deck oficial **IQVIA — Main Concepts / Conceitos Base de dados regular**.
Estes conceitos são a linguagem do ED. Usar os nomes exatos no deck do cliente.

## 1. Cálculo de oportunidade no MAT

**Definição.** Mede o potencial de crescimento com base na **participação média no segmento do
PDV**. Corresponde ao incremento necessário para o PDV atingir a participação média do seu
cluster no período analisado. Serve para localizar as deficiências da companhia e direcionar
esforço.

**Três passos, por PDV:**

```
1º  participação do cliente no PDV      B = venda do cliente no PDV ÷ venda do mercado no PDV
2º  participação média no cluster       C = share médio do cliente no (canal × região) do PDV
3º  oportunidade                        (C − B) × venda do mercado no PDV
```

Exemplo do material (PDV X, canal Abrafarma, região Sudeste):

| | |
|---|---|
| Venda do mercado no PDV | 1.000 |
| Venda do cliente (B) | 10,0% |
| Participação média do cluster (C) | 15,0% |
| Oportunidade em p.p. (C − B) | 5% |
| **Oportunidade em R$** | **50** |

Consequências de leitura:
- A oportunidade é **relativa ao próprio cluster**, não a uma meta arbitrária. Ela responde
  "quanto falta para esse PDV se comportar como a média dos seus pares" — por isso é defensável
  na conversa com o varejo.
- PDV **acima** da média do cluster tem oportunidade zero, não negativa. Ele entra em PROTEGER.
- Como o cluster é canal × região, **mudar a definição de cluster muda toda a oportunidade**.
  Registrar qual cluster foi usado.

## 2. Performance do PDV — classificação A a F

**Definição.** Market share do produto **naquele PDV** comparado ao market share médio da empresa
**no mesmo cluster**. O cluster é normalmente **região × canal**, mas pode ser customizado.

| Classe | Critério |
|---|---|
| **A** | Mais de 20% **acima** da média do cluster |
| **B** | Entre 10% e 20% acima da média |
| **C** | Na média, até 10% acima |
| **D** | Na média, até 10% abaixo |
| **E** | Entre 10% e 20% abaixo da média |
| **F** | Mais de 20% abaixo da média |
| **Z** | PDV **não positivado** — sem venda do produto do cliente |

- Regiões do cluster: Sul, Sudeste, Centro-Oeste, Nordeste, Norte.
- Canais do cluster: Abrafarma, Outras Redes, Associações, Franquias, Independentes.
- **A a F é desvio relativo à média, não share absoluto.** Um PDV classe A num cluster fraco pode
  ter share menor que um PDV classe D num cluster forte. Nunca ler A–F como ranking de tamanho.
- **Z é a outra metade da história.** No material de referência, 40,2 mil dos 61,3 mil PDVs eram Z:
  a oportunidade de distribuição (entrar) costuma competir em tamanho com a de giro (crescer onde
  já está). Reportar **positivados vs não positivados** separadamente.

## 3. CAT — categorias de PDV

**Definição.** As farmácias são agrupadas em **8 categorias, cada uma com o mesmo volume de
vendas (12,5%) e número diferente de PDVs.** Serve para identificar a importância do PDV para o
mercado-alvo e direcionar investimento onde o retorno é maior.

| Faixa | CATs | Leitura |
|---|---|---|
| **ALTO** | 1 · 2 · 3 | poucos PDVs, altíssimo giro |
| **BOM** | 4 · 5 · 6 | faixa intermediária |
| **BAIXO** | 7 · 8 | muitos PDVs, giro baixo |

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

## 5. Onde a oportunidade se desdobra

Depois de classificada, a oportunidade é aberta nos cortes que viram conversa comercial:

| Corte | Para quê |
|---|---|
| **Por bandeira (top 10)** | É a lista de negociação. O bloco "INDEPS" costuma ser o maior de todos e não tem interlocutor único |
| **Por UF e região** | Prioriza roteiro de campo. Trazer `# PDVs` ao lado de `oportunidade R$` |
| **Por CAT** | Confirma que o esforço está nas lojas que pagam |
| **Positivados vs não positivados** | Separa oportunidade de **giro/mix** de oportunidade de **distribuição** |
| **Op/PDV** | Oportunidade média por loja. É o número que decide se vale a visita |

### Giro/mix vs distribuição
A oportunidade de um PDV se classifica pelo **nº de categorias/segmentos do mercado-alvo que
aquele PDV já carrega**. Heurística do material (exemplo com 6 categorias):

| Categorias presentes no PDV | Natureza da oportunidade |
|---|---|
| 0 – 1 | **Distribuição** — o PDV mal entrou na cesta |
| 2 – 3 | **Mix** — falta completar o portfólio |
| 4 – 5 | **Giro** — está tudo lá, vende pouco |

Adaptar as faixas ao número de categorias do mercado montado do projeto e declarar a regra.
A separação importa porque a ação é diferente: distribuição é negociação de entrada, mix é
sortimento, giro é execução e ponto extra.

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
