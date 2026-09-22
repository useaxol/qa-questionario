# Métodos analíticos

## 1. Decomposição do crescimento — o método central

Todo Δ de valor entre dois MATs se decompõe em três elementos. É a leitura que diferencia "o
mercado cresceu" de "o mercado está trocando de itens".

**Estrutura verificada contra o modelo oficial** `Elementos de Crescimento` (planilha de
processamento IQV OnGoing). Cálculo no nível **FCC**, com três períodos de input — atual,
anterior e anterior−1 — em unidades e em valor.

### Classificação do item (por UNIDADES, não por valor)

```
launch = SE( un_atual > 0  E  un_anterior = 0 )        →  "S" / "N"
```

Um item é novo quando **não teve unidade** no período anterior. Comparar valor no lugar de
unidade dá resultado diferente e não é o critério do modelo.

### Os três elementos

```
preço_base   = valor_anterior ÷ un_anterior            [preço do período que serve de base]
preço_atual  = valor_atual    ÷ un_atual

Organic Growth  = SE(launch="N";  (un_atual − un_anterior) × preço_base;  0)
Launch          = SE(launch="S";  un_launch × preço_atual;  0)     ≡ valor_atual do item
Price Increase  = (valor_atual − valor_anterior) − Launch − Organic Growth
```

Três propriedades que a álgebra do modelo garante, e que valem como teste de qualquer
implementação:

| Caso | O que o modelo produz |
|---|---|
| Item novo | `Launch` = valor atual integral do item. Orgânico e preço ficam em zero |
| Item descontinuado (zera no atual) | Cai **inteiro** no orgânico, como `−valor_anterior`. Preço fica em zero |
| Item existente sem mudar volume | Todo o Δ vai para `Price Increase` |

Por isso **descontinuados não são um quarto elemento** — a convenção IQVIA tem três, e a perda de
base está dentro do orgânico. `scripts/decompor_crescimento.py` reporta descontinuados em linha
separada apenas para diagnóstico; ao levar para o slide, somar ao orgânico.

```
python3 scripts/decompor_crescimento.py extracao.xlsx \
    --base "MAT Jul'25" --atual "MAT Jul'26" \
    --item FCC --periodo MAT --valor Valor --unidades Unidades \
    --por Segmento --por Fabricante
```

### Rodar nos dois anos

O modelo oficial calcula a decomposição **duas vezes** — atual vs anterior, e anterior vs
anterior−1. É o que permite dizer se a *composição* do crescimento mudou, não só o ritmo: um ano
que crescia por volume orgânico e passa a crescer por lançamento conta uma história que o número
de topo esconde. Pedir três períodos na extração, não dois.

### Notas de execução

- "Item novo" é **ausência de unidade no período anterior**, nunca data de cadastro. Item que
  existia há dois anos, sumiu e voltou entra como launch.
- **No slide, apresentar nos três elementos da convenção IQVIA** — Organic Growth, Launch,
  Price Increase (ou Preço/Mix). É a régua que o cliente conhece.
- O terceiro elemento é **resíduo**: mistura aumento de preço, mix de benefício, mix de canal e
  mix de tamanho. **Nomear qual predomina** cruzando com preço médio por segmento e com tier de
  preço — não deixar como "preço/mix". Existe versão do modelo que separa preço de mix; quando
  ela não estiver em uso, a separação é argumentativa e precisa ser sustentada por outro corte.
- Rodar a decomposição **por segmento e por fabricante**, não só no total. É aí que aparece quem
  cresce por demanda e quem cresce por preço.

### Como ler o resultado

| Padrão | Diagnóstico |
|---|---|
| Orgânico positivo e dominante | A categoria ganha consumidor. Crescimento sustentável |
| Launch dominante, orgânico ≈ 0 | Renovação de portfólio. Depende de calendário de lançamento |
| Launch dominante, orgânico **negativo** | Lançamento substitui a própria base — canibalização |
| Preço dominante, volume negativo | Crescimento de fachada. Volume é o alerta |

## 2. Contribuição ao crescimento (p.p.)

```
contribuição_i (p.p.) = (valor_i,t − valor_i,t-1) / valor_total,t-1 × 100
```

A soma das contribuições reconstrói o crescimento total. Serve para dizer qual segmento, marca,
canal ou região **fez** o ano — e qual subtraiu.

Leitura que sempre rende slide: quando a contribuição de um único player é **maior que o
crescimento do mercado**, o mercado só cresceu porque ele cresceu. O conjunto dos demais está
negativo.

## 3. Ponte entre recortes (categoria oficial × cesta montada)

Obrigatório sempre que os dois recortes aparecem no mesmo deck. Formato:

| | R$ Mi | Var. ano | O que é |
|---|---|---|---|
| **CESTA MONTADA [cliente]** | 3.469,6 | +3,1% | Os segmentos que o cliente chama de seu mercado |
| (−) [bloco que sai] | −371,7 | −4,1% | Onde a IQVIA classifica esses itens |
| (+) [bloco que entra] | +557,5 | +8,7% | O que a categoria oficial tem e a cesta não |
| (+) [outros que entram] | +126,1 | −0,2% | |
| (±) Critério de cadastro (kits, multipacks) | +80,8 | — | Diferença de nível nos mesmos segmentos |
| **CATEGORIA [X] — IQVIA** | 3.862,3 | +9,5% | Classificação oficial do PMB Mix |

Regras:
- Cada linha tem **nome próprio** — quais marcas, em qual categoria IQVIA elas caem. "Diferença de
  classificação" não é explicação.
- Dizer explicitamente **quando usar cada recorte**: a categoria oficial compara com o resto do
  canal e abre a arquitetura de benefício; o montado lê a competição por fabricante, canal,
  região e loja.
- Fechar com a frase de disciplina: os dois nunca são somados nem comparados entre si.
- Quando a diferença de **ritmo** entre os dois recortes é grande, isolar a causa: recalcular a
  cesta sem o bloco divergente e mostrar quanto ela cresceria.

## 4. Datar a virada

Crescimento de MAT esconde mudança de patamar. Sempre que o MAT desacelera, rodar duas séries:

1. **Trimestres móveis** vs mesmo trimestre do ano anterior — valor e volume juntos.
2. **Mensal** vs mesmo mês do ano anterior.

Objetivo: dizer **em que mês** a curva virou e mostrar que não é um mês fora da curva — os meses
seguintes ficaram em outro patamar. Um mês isolado é ruído; oito meses seguidos são tendência.

Sempre checar contra: base de comparação, campanha de associativismo, mudança de política
comercial, entrada/saída de item grande, efeito de estoque no varejo.

## 5. Preço

```
preço médio   = valor ÷ unidades
índice de preço = PM do fabricante ÷ PM do segmento × 100
```

- Comparar índice de preço **por segmento**, nunca só no total: o índice total é mix de segmento.
- Classificar o portfólio em **tiers de preço** (PREMIUM / HIGH / MEDIUM / LOW — cortes em
  `conceitos-ed-oportunidade.md`, §7) e cruzar com Δ volume por tier: é assim que se prova se o
  mercado está premiumizando ou barateando.
- Cruzar share de valor com share de volume. Share de volume > share de valor = preço abaixo do
  mercado; o inverso = prêmio.
- Distinguir **ganho de preço** (mesma unidade mais cara) de **troca de benefício** (consumidor
  migra para unidade mais cara). A segunda é a mais comum em categoria premiumizando e tem
  implicação completamente diferente: não é aumento de tabela, é mudança de mix.
- Quando disponível, separar preço real de nominal. `preço real ≈ Δ preço médio − inflação`.

## 6. Arquitetura de benefício

Dentro da sub-categoria, abrir por **segmento de benefício** (ex.: sensíveis, whitening,
gengivite, infantil, linha regular) e montar:

| Segmento | R$ | Peso | Var. valor | Var. volume | Preço médio | Marcas que explicam |

O que se procura: segmento cujo preço médio é múltiplo do básico **e que ganha volume**. Esse é o
motor de valor da categoria. O espelho é a linha regular perdendo volume — o consumidor não
consome mais, consome diferente.

Teste de robustez: se um segmento cresce em valor **sem** ganhar volume, não há troca de
benefício — há só preço, e preço sozinho não sustenta.

## 7. Concentração e tipo de loja

- **CATs (octis de valor):** cada CAT = 12,5% do faturamento. Reportar nº de lojas, R$/loja/ano,
  variação no ano e composição do canal dentro de cada CAT.
- Ler a variação do segmento **por CAT**. Queda no agregado pode ser queda só nas lojas grandes,
  com crescimento de dois dígitos nas médias — diagnóstico e ação completamente diferentes
  (disputa de share num mercado que encolhe vs disputa por crescimento).
- **Bandeiras:** faturamento e variação por bandeira, aberto por segmento. Frequentemente as
  maiores bandeiras são as mais lentas — e é onde está o volume de negociação.
- **Matriz canal × região:** identificar a maior célula e o ritmo dela. Crescimento que vem só de
  células pequenas não recupera o total; dizer isso explicitamente e dimensionar em R$.

## 8. Dimensionar oportunidade

Toda oportunidade se apresenta com **mercado em disputa em R$** e ordenada por tamanho.

| Tipo de oportunidade | Como dimensionar |
|---|---|
| Share em segmento que cresce | distância p.p. para o líder × valor do segmento |
| Praça abaixo do padrão | (share nacional − share da praça) × cesta da praça |
| Distribuição / giro (ED) | **metodologia oficial**: `SE(dif > 0; 0; demanda_total_PDV × ABS(dif))`, com `dif = share_PDV − share_cluster`, somado nos PDVs-alvo. Soma é bruta, não líquida. Ver `conceitos-ed-oportunidade.md`, §1 |
| Ruptura | % de ruptura × faturamento da cesta |
| Segmento com baixa participação | valor do segmento × share-alvo realista |

Comparar sempre com uma régua: o crescimento anual que a cesta inteira entregou. Ruptura que vale
duas vezes o crescimento do ano é um argumento; "ruptura de 6%" não é.

**Teto de quatro leituras.** Ordenadas por tamanho do mercado em disputa, não por facilidade.

Quando há ED, a oportunidade não se estima — se calcula por PDV contra a média do cluster, e se
apresenta já classificada em PROTEGER / ATACAR / AVALIAR / DESPRIORIZAR, separando giro/mix de
distribuição. Toda a mecânica está em `conceitos-ed-oportunidade.md`.
