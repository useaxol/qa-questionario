# Catálogo de causas — o "por quê" de cada movimento

Todo movimento identificado tem que ser confrontado com este catálogo. A hipótese não se escolhe
por ser a mais elegante: **se testa contra o dado disponível**. Quando o dado não existe, a
hipótese entra no deck rotulada como hipótese e vira next step.

## Como usar

Para cada movimento, percorrer as três camadas na ordem: mecânica → mercado → contexto. Parar
quando o dado sustentar. Registrar a evidência ao lado da causa.

---

## Camada 1 — Mecânica (sempre checar primeiro, resolve a maioria)

| Hipótese | Como testar | Dado necessário |
|---|---|---|
| É preço, não volume | Decompor valor = volume × preço; olhar preço médio | Regular |
| É mix de benefício, não preço de tabela | Preço médio por segmento + Δ volume por segmento | Regular, nível segmento |
| É lançamento | Decomposição: parcela de itens novos | Regular, nível SKU/FCC |
| É canibalização | Itens novos altos **com** volume orgânico negativo | Regular, nível SKU |
| É sortimento | Nº de FCCs ativos, por ano | Regular, nível SKU |
| É mix de canal | Recalcular o total com o mix de canal do ano anterior | Montado, quebra de canal |
| É mix de tamanho/embalagem | Preço médio por gramatura/apresentação | Montado, nível SKU |
| É base de comparação | Série de 3+ MATs da mesma marca/segmento | Regular, série longa |
| É um único item ou marca | Ranking de Δ R$ absoluto, top 10 ganhos e perdas | Regular, nível marca/SKU |
| É descontinuação | Itens com venda em t-1 e zero em t | Regular, nível SKU |

## Camada 2 — Mercado e execução

| Hipótese | Como testar | Dado necessário |
|---|---|---|
| Falta distribuição | Cobertura % por canal/região/bandeira; PDVs classe `Z` (não positivados) | **ED** (ou base de PDV sem fabricante, como proxy da cesta) |
| Está na loja mas gira pouco | Performance D/E/F em PDVs positivados; oportunidade de giro/mix | **ED** |
| Perdeu ponto de venda no ano | ΔDN por marca e canal (PDVs com presença, atual vs anterior) | **ED**, bloco DN/DP |
| Está presente onde o giro não está | DN alta com DP baixa | **ED**, bloco DN/DP |
| É deficiência concentrada em poucas bandeiras | IMP. cliente vs IMP. categoria por bandeira + Δ share | **ED**, performance por bandeira |
| É posicionamento de preço | Distribuição do portfólio por tier (PREMIUM/HIGH/MEDIUM/LOW) × Δ volume por tier | Regular / montado |
| Perdeu venda por ruptura | Ruptura % e dias de estoque, por rede | **Panorama de Estoque** |
| Migrou para o online | Participação do online na categoria; sortimento e preço por player | **RDC** |
| É concentração de canal | Share de canal ao longo dos MATs; R$/loja; nº de lojas | Montado + CH Talks |
| É a rede que mudou de política | Variação por bandeira, aberta por segmento | Montado, dimensão bandeira |
| É campanha de associativismo | Pico mensal no canal Assoc.&Franquias sem eco nos outros | Montado, série mensal por canal |
| É tipo de loja | Variação do segmento por CAT | Base de PDV |
| É marca própria | Share e crescimento de MP na categoria | PMB Mix / montado |
| É geografia | Var. valor **e volume** por região e UF; peso e contribuição | Montado, região/UF |
| É gap de posição da marca na praça | Share por UF vs share nacional, com o mercado da UF crescendo | Montado, UF |
| É preço relativo | Índice de preço por segmento; share valor vs volume | Montado |
| É pressão promocional | Série de preço médio com quedas pontuais; mix de embalagem promocional | Camada de pricing |

## Camada 3 — Contexto (explica movimento estrutural, não mês)

| Hipótese | Como testar |
|---|---|
| Regulação | Cruzar a data da virada com a linha do tempo regulatória em `conceitos-iqvia.md` |
| Entrantes de canal | Farmácia em supermercado (Lei 15.357/2026), marketplaces, atacarejo |
| Mudança de bloco de consumo | Posição da categoria nas forças Cuidar / Prevenir / Embelezar |
| Expansão física do varejo | Nº de PDVs por canal e região; crescimento do canal vs crescimento de lojas |
| Patente / genérico | Fim de patente relevante no período (ex.: semaglutida, 2026) |
| Sazonalidade | Mesmo mês em 3+ anos |
| Inflação | Preço nominal vs real |
| Comportamento do shopper | Onde a marca é decidida, troca nos últimos 3 meses, canal de compra — **exige Consumer/Shopper** |

---

## Regras de disciplina

- **Correlação não é causa.** Duas curvas que viram no mesmo mês pedem um terceiro dado.
- **Uma causa por movimento, no slide.** Se há três candidatas e o dado não separa, dizer isso e
  apresentar as três — não escolher em silêncio.
- **Sempre aterrizar no negócio do cliente.** Fechar a causa com o que ela muda: portfólio, preço,
  negociação com rede, sortimento, execução de loja, verba.
- **Hipótese sem dado é hipótese.** Escrever "a leitura de venda mostra que houve troca de
  benefício, mas não quem trocou nem por quê" e mandar para next steps é mais forte do que
  especular.
- **Movimento sem consequência não vira slide.** Vai para anexo.
