# Escopo de dados — qual base responde o quê

Preencher isto **antes** de abrir extração. O erro mais caro do projeto é descobrir no meio da
análise que a pergunta do briefing exige uma base que não foi contratada.

## Tabela de decisão

| Pergunta do briefing | Base | O que ela **não** responde |
|---|---|---|
| Qual o tamanho e o ritmo do canal farma? RX vs CH? | **PMB Mix** | Nada por canal, região ou loja |
| Como minha categoria se compara com as outras do canal? | **PMB Mix** (classificação oficial) | Nada por fabricante/marca dentro da minha cesta customizada |
| Qual meu share? Quem ganhou e perdeu? | **Mercado montado** | Comparação com outras categorias |
| Como isso se move por canal, região, UF, bandeira? | **Mercado montado** | Cobertura e giro por loja com dimensão de fabricante |
| Onde a cesta está concentrada por tipo de loja? | **Base de PDV** (CATs) | Onde **meu** produto está — não tem fabricante |
| Em quantas lojas estou? Onde não estou? Quanto vale entrar? | **ED — Estudo de Distribuição** | Por que o consumidor escolhe |
| Em quais lojas eu ataco, protejo ou deixo de lado? | **ED** — matriz CAT × performance | Nada sem dimensão de fabricante por PDV |
| Estou perdendo venda por falta de produto? | **Panorama de Estoque** | Se a demanda existe |
| Como está meu preço vs concorrente? Promo? Elasticidade? | **Mercado montado** + camada de pricing | Preço praticado por loja individual, salvo contratação específica |
| Quanto o online já pesa? Qual meu sortimento e preço lá? | **RDC** | Comparação direta com o físico sem ajuste de painel |
| Quem trocou de marca e por quê? Onde decide? | **Consumer Health Snapshot / Shopper** | Quanto isso vale em R$ |
| Como a rede X evolui e negocia? | **Tracking de Bandeiras / MDTR** | `[CONFIRMAR escopo]` |

## Perguntas de escopo a fazer no briefing

Nesta ordem, antes de qualquer análise:

1. **Qual é o mercado montado?** Quais sub-categorias e segmentos entram na cesta, e por quê.
   Quem definiu esse recorte e quando foi a última revisão.
2. **Qual a extração e a edição?** Nome do arquivo, `AAAAMM`, data de extração.
3. **Qual o período?** Quantos MATs, qual mês de corte, e se precisa de série mensal ou trimestral
   para datar viradas. Para elementos de crescimento, pedir **três períodos** — atual, anterior e
   anterior−1 — em unidades e valor: é o que o modelo oficial consome e o que permite comparar a
   composição do crescimento entre dois anos.
4. **Valor em quê?** R$ CPP nominal ou deflacionado. Se deflacionado, por qual índice.
5. **Quais dimensões vêm na extração?** Fabricante, marca, SKU, canal, região, UF, bandeira, PDV,
   CAT — item por item. Não presumir.
6. **Vamos ter ED?** Se a pergunta de negócio tem qualquer palavra de presença, cobertura,
   sortimento, execução ou "por que não vendemos em X", a resposta precisa ser sim. Tendo ED,
   fechar também **qual o cluster** da performance — o padrão é canal × região, e mudar o cluster
   muda todos os números de oportunidade.
7. **Vamos ter estoque?** Se o cliente reclama de demanda perdida ou se a categoria tem ruptura
   histórica alta.
8. **Vamos ter pricing além do regular?** O sell-out regular já dá preço médio e índice de preço.
   Elasticidade, promo e arquitetura de preço por embalagem exigem camada adicional.
9. **Vamos ter dado de consumidor?** Todo "por quê" de escolha termina aqui. Sem isso, a
   explicação de comportamento é hipótese e precisa ser apresentada como hipótese.
10. **O deck é para quem?** Trade, marketing, diretoria, convenção de vendas. Muda profundidade,
    número de slides e o nível de detalhe de SKU.

## Registro de escopo (colar no projeto)

```
CLIENTE:
MERCADO MONTADO:        [segmentos que entram]
CANAL:                  [Abrafarma / Assoc.&Franq. / Independentes / Outras redes / total]
REGIÕES:                [5 regiões / UFs / microrregiões]
PERÍODOS:               [MATs, mês de corte]
MÉTRICAS:               [R$ CPP nominal, unidades, preço médio]
BASES CONTRATADAS:      [PMB Mix / montado / PDV / ED / Estoque / RDC / Consumer]
DIMENSÕES DISPONÍVEIS:  [...]
LACUNAS CONHECIDAS:     [o que não vai ter resposta e será dito como tal]
AUDIÊNCIA:              [...]
```

A linha **LACUNAS CONHECIDAS** é obrigatória e vira o slide de next steps do deck: para cada
lacuna, qual estudo IQVIA responde.
