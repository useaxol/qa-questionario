# Monitor de passagens aéreas

Monitora rotas aéreas — qualquer origem e destino do mundo — e avisa quando uma
passagem fica barata **em relação ao próprio padrão dela**: o que aquela rota
costuma custar naquele período do ano, comprando com aquela antecedência.

Um preço só é "barato" contra alguma referência. R$ 4.000 em São Paulo–Lisboa é
caro em novembro e barato em julho. Comparar com o preço de ontem detecta
qualquer oscilação; comparar com um valor fixo ignora a estação. Este monitor
constrói a referência a partir do histórico da própria rota e só dispara quando
a cotação sai da faixa de variação normal.

---

## Como o preço padrão é estimado

Em escala logarítmica, com estatística robusta a outliers (mediana e MAD, não
média e desvio-padrão — uma tarifa-erro não deve mover a referência):

```
log(preço) = base_da_rota + índice_sazonal[semana] + fator_antecedência[faixa] + resíduo
```

O ajuste é feito por **backfitting**: cada efeito é estimado sobre o resíduo dos
outros, em três passadas, o que impede que "viagem de julho" e "comprei em cima
da hora" se confundam.

| Componente | O que captura | Como é estimado |
|---|---|---|
| `base_da_rota` | nível de preço da rota | mediana ponderada dos log-preços |
| `índice_sazonal[semana]` | período do ano **da viagem** | mediana por semana ISO, suavizada com as semanas vizinhas (kernel gaussiano, ±3 semanas) |
| `fator_antecedência` | dias até a partida | mediana por faixa (0-3, 4-7, … , 181+), suavizada com as faixas adjacentes |
| `resíduo` | o que sobra | dispersão típica da rota (MAD × 1,4826) |

Cada efeito sofre **encolhimento** proporcional ao volume de dados que o
sustenta (`n / (n + k)`). Com pouca história o efeito tende a zero: o sistema
prefere não afirmar nada a inventar uma sazonalidade que não viu.

### Do resíduo ao alerta

O sinal é o **z-score robusto**: `z = (log(preço) − log(esperado)) / escala`.
Um `z = −2` significa "duas vezes a variação típica desta rota abaixo do
esperado".

| Veredito | Limiar | Desconto mínimo |
|---|---|---|
| Boa oportunidade | z ≤ −0,90 | 4% |
| Ótima oportunidade | z ≤ −1,60 | 8% |
| Oportunidade excepcional | z ≤ −2,40 | 15% |
| Suspeito (possível tarifa-erro) | z ≤ −4,00 | 35% |

Três salvaguardas contra alarme falso:

1. **Confiança.** Os limiares são multiplicados por 1,0 / 1,18 / 1,5 conforme a
   história seja alta, média ou baixa. Com pouca base, exige-se sinal mais forte.
2. **Desconto mínimo absoluto**, para que uma rota barata e muito estável não
   alerte por causa de 2% de queda.
3. **Carência entre alertas** (padrão 12 h), furada apenas se o preço cair mais
   3% ou se a severidade subir.

Sem história suficiente (menos de 8 cotações) o veredito cai para uma comparação
relativa à mediana da própria série, marcada como confiança baixa — e o app diz
isso na tela, em vez de fingir precisão.

---

## Começando

```bash
pip install -r requirements.txt

python run.py seed-demo    # 7 rotas pelo mundo, com ~1 ano de histórico
python run.py serve        # painel em http://localhost:10001
```

O `seed-demo` usa o provedor simulado para reconstruir o passado — nenhuma API
pública de tarifa entrega histórico, e sem histórico não existe preço padrão.
Serve para avaliar o produto e o modelo no primeiro minuto, não para decidir
compra.

Para monitorar de verdade:

```bash
python run.py add GRU LIS 2027-01-17 --return 2027-01-31 \
    --label "Férias em Lisboa" --target 4200 --flex 2
python run.py collect                  # uma rodada agora
python run.py run --interval 180       # como serviço
python run.py serve --with-scheduler   # painel + coleta em segundo plano
```

### Comandos

| Comando | O que faz |
|---|---|
| `init` | cria o banco |
| `add` | passa a monitorar uma rota (`--backfill N` reconstrói N dias) |
| `list` | rotas monitoradas e o veredito atual |
| `collect [ids]` | uma rodada de cotação |
| `run --interval MIN` | coleta contínua |
| `backfill [id]` | reconstrói histórico (provedor simulado) |
| `bootstrap` | semeia quartis históricos publicados pela Amadeus |
| `report ID` | sazonalidade e curva de antecedência da rota, no terminal |
| `alerts [--json]` | alertas registrados |
| `serve` | painel web |
| `purge --keep-days N` | descarta cotações antigas |

Exemplo do `report`:

```
Cotações no histórico da rota : 650
Preço base da rota            : R$5 485
Volatilidade típica           : ±13%

Sazonalidade por mês de viagem (vs média anual da rota)
  jan   +8.3%  ++++
  jul   +9.6%  ++++
  nov   -8.1%  ----
```

---

## Fontes de cotação

| Provedor | Uso | Backfill |
|---|---|---|
| `synthetic` | simulador determinístico: distância real entre aeroportos, estação no destino **e na origem**, feriados, curva de antecedência, promoções relâmpago | sim |
| `amadeus` | API real (Flight Offers Search + Itinerary Price Metrics) | não |

Para usar a Amadeus, credenciais gratuitas em
[developers.amadeus.com](https://developers.amadeus.com):

```bash
export FLIGHTWATCH_PROVIDER=amadeus
export AMADEUS_CLIENT_ID=...
export AMADEUS_CLIENT_SECRET=...
export AMADEUS_HOST=https://api.amadeus.com   # produção; teste tem dados limitados
python run.py bootstrap    # referência de mercado antes da primeira coleta
python run.py collect
```

Um terceiro provedor é só uma subclasse de `Provider` com um método `search`
(veja `flightwatch/providers/base.py`) registrada em `providers/__init__.py`.

O simulador também serve de banco de provas: como ele conhece a sazonalidade
"verdadeira", os testes verificam que o modelo a reencontra (correlação > 0,6
entre a curva estimada e a embutida).

---

## Alertas

Saem ao mesmo tempo por console, arquivo JSONL (`data/alerts.jsonl`, uma linha
por alerta) e webhook. O payload traz `text` e `content`, então funciona direto
em Slack e Discord:

```bash
export FLIGHTWATCH_WEBHOOK_URL=https://hooks.slack.com/services/...
```

```
🔵 São Paulo → Paris por R$17 144 (27% abaixo do padrão) — ótima oportunidade
   GRU → CDG · ida 16/02/2027 · volta 26/02/2027
   Executiva · 1 pax · preço esperado R$23 439 · z=-2.35 · nota 84/100
   • 27% abaixo do preço esperado para esta rota nesta época do ano.
   • Mais barata que 98% das cotações históricas do mesmo período do ano.
   • Baseado em 649 cotações da rota (156 no mesmo período do ano); confiança high.
```

Todo alerta vem com as razões em texto: o app explica por que aquilo é barato,
em vez de mostrar só um número.

---

## API

| Rota | Método | Descrição |
|---|---|---|
| `/api/watches` | GET | rotas e veredito atual |
| `/api/watches` | POST | cadastra uma rota |
| `/api/watches/<id>/history` | GET | série de cotações |
| `/api/alerts?limit=N` | GET | alertas |
| `/api/collect` | POST | dispara uma coleta |
| `/api/airports?q=` | GET | busca de aeroportos |
| `/health` | GET | saúde do serviço |

---

## Docker

```bash
docker build -t flightwatch .
docker run -p 10001:10001 -v flightwatch-data:/app/data flightwatch
```

O volume é importante: o histórico **é** o produto. Perder o banco significa
recomeçar sem referência de preço.

---

## Testes

```bash
cd tests && python3 -m unittest discover
```

105 testes, sem dependências além do Flask. Cobrem a estatística robusta, a
recuperação da sazonalidade e da curva de antecedência a partir de dados
simulados, os limiares de alerta, a deduplicação, a validação de formulário,
os provedores, os gráficos e as rotas web.

---

## Estrutura

```
flightwatch/
  analytics.py     modelo de preço padrão e diagnóstico (o núcleo)
  monitor.py       coleta, avaliação e alerta
  seed.py          backfill de histórico e carteira de demonstração
  providers/       synthetic (simulador) e amadeus (real)
  db.py            SQLite: rotas, cotações, alertas
  charts.py        SVG no servidor, sem JavaScript nem CDN
  web.py           painel e API
  cli.py           linha de comando
  airports.py      207 aeroportos com coordenadas, para distância e busca
```

Sem NumPy, pandas ou biblioteca de gráficos: o modelo cabe em estatística de
mediana feita à mão, e os gráficos saem como SVG com classes CSS — o que faz o
tema claro/escuro funcionar sem uma linha de JavaScript.

---

## Limites honestos

- **O provedor simulado não é preço real.** Serve para demonstrar, testar e
  reconstruir história. Decisão de compra pede o provedor real.
- **Histórico é pré-requisito.** Nas primeiras semanas o app diz "histórico em
  formação" em vez de dar um veredito que não pode sustentar.
- **Sem conversão de câmbio**: comparações acontecem dentro da mesma moeda.
- **Feriados móveis** (Carnaval, Páscoa) entram no simulador por aproximação de
  data fixa; o modelo estatístico os aprende do dado real quando ele existe.
- Uma queda marcada como *suspeita* costuma ser tarifa-erro: dura pouco e pode
  ser cancelada pela companhia.
