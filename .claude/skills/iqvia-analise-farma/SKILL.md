---
name: iqvia-analise-farma
description: Monta análises e decks de mercado a partir de dados IQVIA do varejo farmacêutico brasileiro — PMB Mix, mercado montado, base de PDV, Estudo de Distribuição (ED), Panorama de Estoque, Retail Digital Commerce, Consumer Health Snapshot. Use quando houver briefing de cliente do farma e extrações IQVIA para analisar categoria, canal, share, preço, distribuição ou oportunidade — inclusive Market Trend View (MTV), reporte trimestral e apresentação de convenção. Não use para estudos primários de campo (quanti/quali).
---

# Análise de mercado farma com dados IQVIA

Seis passos. **Não montar slide antes do plano aprovado (passo 2).** A ordem importa: escopo de
dados → ponte entre recortes → plano → conferência → análise → deck.

Conceitos e nomenclatura: `reference/conceitos-iqvia.md` e, para tudo que vem do ED
(performance A–F, CAT, matriz de ação, cálculo de oportunidade, tiers de preço, elementos de
crescimento), `reference/conceitos-ed-oportunidade.md`. Nunca inventar definição de base, métrica
ou canal — se não estiver na referência, perguntar.

Exemplo do fluxo inteiro rodando, destrinchado slide a slide:
`reference/exemplo-deck-referencia.md`.

## Passo 0 — Definir o escopo de dados antes de abrir qualquer arquivo

Primeira pergunta de todo projeto: **quais bases entram?** Sell-out regular resolve a maioria dos
briefings, mas boa parte das perguntas de negócio só fecha com camada adicional.

| A pergunta do briefing é sobre | Base que responde |
|---|---|
| Tamanho, crescimento, share, preço médio, mix | PMB Mix + mercado montado |
| Onde o produto está / não está, cobertura, giro por loja | **Estudo de Distribuição (ED)** |
| Em quais lojas atacar, proteger ou despriorizar | **ED** — matriz CAT × performance |
| Ruptura, dias de estoque, disponibilidade | **Panorama de Estoque** |
| Pricing fino, elasticidade, promo, índice vs concorrente | Mercado montado + camada de pricing |
| E-commerce, sortimento e preço online | **Retail Digital Commerce (RDC)** |
| Quem trocou, por quê, onde decide | **Consumer Health Snapshot / Shopper** |

Tabela completa de decisão, com o que cada base **não** responde, em
`reference/bases-e-escopo.md`. Declarar o escopo por escrito e confirmar antes de seguir —
descobrir no meio da análise que falta ED custa o projeto.

## Passo 1 — Especificação e ponte entre recortes

Fixar e registrar num slide de especificação (modelo em `reference/narrativa-deck.md`):
mercado montado (o que está dentro da cesta), canal, regiões, períodos/MATs, métricas.

Depois, obrigatoriamente: **conferir a cesta montada do cliente contra a categoria oficial IQVIA.**
Quase nunca fecham. Quando não fecharem, montar a **tabela de ponte** — o que sai, o que entra,
diferença de critério de cadastro — e nomear cada linha (`reference/metodos-analiticos.md`,
seção "Ponte entre recortes").

Regra dura: **cada número é lido na base que o gerou. Os dois recortes nunca são somados nem
comparados entre si.**

## Passo 2 — Plano de análise (o funil)

Produzir `plano.md` com o funil abaixo, uma linha por slide previsto:

| # | Bloco | Pergunta | Base | Recorte | Métrica | Tier |

O funil padrão, de cima para baixo:

1. **Canal farma total** (PMB Mix) — tamanho, RX vs Consumer Health, nº de lojas, de onde vem o crescimento
2. **Movimentos estruturais do canal** — concentração, marca própria, entrantes, regulação, e-commerce
3. **A categoria do cliente dentro do Consumer Health** — ranking, crescimento curto × longo prazo
4. **Ponte** para o mercado montado
5. **A cesta montada** — valor/volume/preço, quebra de patamar datada, decomposição do crescimento
6. **Segmentos e arquitetura de benefício** — onde o dinheiro migrou dentro da categoria
7. **Fabricantes → marcas → SKUs** — quem explica o ano
8. **Canal × Região × UF** — onde o crescimento está
9. **PDV** — CAT, bandeira, cobertura loja a loja
10. **Camadas adicionais** — ED (performance, cobertura, matriz de ação, oportunidade por
    bandeira e UF), estoque, e-commerce, consumidor — as que entraram no passo 0
11. **Posição do cliente** e oportunidades dimensionadas em R$
12. **Next steps** — o que a IQVIA responde em seguida

**Tier**: `corpo` (entra na narrativa) ou `anexo`. Teto padrão: **25 a 30 slides de corpo.**
Tudo além disso vai para anexo. Deck de convenção ou de diretoria: 15 a 20.

**Parar aqui e pedir aprovação.** O plano é o contrato.

## Passo 3 — Conferir os dados antes de analisar

Para cada linha do plano, confirmar:
- o MAT declarado é o mesmo em todas as extrações (edição, mês de corte, nº de meses);
- valor está em R$ CPP e a mesma moeda/base nominal em todos os cortes;
- a soma das partes fecha o total (segmentos = categoria; canais = cesta; UFs = região);
- share de valor e share de volume são calculados sobre o mesmo universo;
- a base de PDV tem — ou **não tem** — dimensão de fabricante (normalmente não tem: ela mostra
  onde a cesta está, não onde o cliente está);
- itens novos foram identificados por ausência de venda no MAT anterior, não por data de cadastro.

Reportar divergências em bloco. **Não plotar número que não fecha.**

Quando o cliente manda planilha de cálculo (matriz de ED, elementos de crescimento), auditar a
lógica antes de aceitar os números: `python3 scripts/dump_formulas.py arquivo.xlsx` extrai só as
fórmulas — fórmula arrastada por milhares de linhas vira uma linha com a contagem, então uma
planilha de dezenas de MB cabe em poucos KB.

## Passo 4 — Analisar: movimento e depois causa

Todo movimento identificado passa por duas perguntas, nesta ordem:

1. **Quanto e onde?** — decompor sempre: valor = volume × preço; e crescimento =
   volume orgânico + descontinuados + itens novos + preço/mix. Fórmulas em
   `reference/metodos-analiticos.md`; cálculo pronto em `scripts/decompor_crescimento.py`.
2. **Por quê?** — testar as hipóteses causais do catálogo em
   `reference/catalogo-de-causas.md` contra os dados, não escolher a mais bonita.

Nunca parar no "o quê". Um slide que diz que a categoria cresceu 9,5% sem dizer de onde vem o
crescimento e o que isso muda para o cliente não entra no deck.

Ancorar a causa no **negócio do cliente**: o que a leitura muda em portfólio, preço,
negociação com rede, sortimento ou execução de loja. Se a leitura não muda decisão nenhuma,
o slide é anexo.

## Passo 5 — Montar o deck

Padrão de slide, obrigatório (detalhe e exemplos em `reference/narrativa-deck.md`):

- **Kicker** — o fato quantificado, com número: *"Em quatro anos o canal ganhou R$ 97 bilhões — um CAGR de 11,6% — com apenas 4,8% a mais de lojas"*
- **Título** — o que isso significa: *"O canal farma chegou a R$ 273,8 bilhões e cresce +10,4% ao ano"*
- **Fonte completa** — base, edição, definição de MAT, métrica e definição de qualquer cálculo derivado
- **Visual** — um gráfico que carrega o argumento + tabela de apoio com os números que sustentam
- **LEITURA —** parágrafo final: por que acontece e o que abre para o cliente

Três blocos, cada um aberto por uma pergunta e fechado por um slide de síntese. Bloco fecha com
ponte para o próximo. Construção do PPTX: usar a skill `pptx`; template e `modelos.json` vêm do
conhecimento do projeto.

## Passo 6 — Fechamento

Rodar o checklist de `reference/checklist-fechamento.md` antes de entregar. Ele cobre
consistência numérica, rastreabilidade de fonte, altura da narrativa e as perguntas que o cliente
vai fazer na sala.

## Regras que não mudam

- **Volume ao lado de valor, sempre.** Crescimento só em valor é meia informação — em categoria
  premiumizando, esconde queda de unidade.
- **Preço médio é valor ÷ unidades**, não preço de tabela. Movimento de preço médio pode ser
  aumento, mix de benefício, mix de canal ou mix de tamanho — nomear qual.
- **p.p. para share, % para variação.** Nunca "share cresceu 7%".
- **MAT contra MAT, mês contra o mesmo mês.** Nada de comparar MAT com ano fechado.
- **Base de comparação sempre checada.** Marca que cai 46% pode ter explodido no ano anterior.
- **Oportunidade se dimensiona em R$**, sobre o mercado em disputa, e se ordena por tamanho —
  não por facilidade de execução. Havendo ED, calcular pela metodologia oficial (share do PDV vs
  média do cluster), não estimar.
- **Elementos de crescimento no slide são três** — orgânico, novos SKUs, preço/mix. É a convenção
  que o cliente conhece.
- **Quatro leituras de oportunidade, no máximo.** Acima disso o cliente não leva nenhuma.
