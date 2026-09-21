# Índice de passagens aéreas

Dez destinos, um benchmark por destino, um índice base 100. O app mede os dez no
mesmo instante e avisa quando **um deles se distorce em relação aos outros**.

```
python run.py demo      # conhece o app em 5 segundos
python run.py serve     # painel em http://localhost:10001
```

---

## O problema que a cesta resolve

Comparar um preço com o histórico da própria rota exige meses de coleta antes de
dizer qualquer coisa. Comparar com um valor fixo ignora a estação. E comparar só
contra um benchmark tem um ponto cego: quando câmbio ou combustível mexem o
mercado inteiro, **todos os destinos ficam baratos ao mesmo tempo** — e um
detector ingênuo dispara dez alertas que não são oportunidade nenhuma.

A cesta separa as duas coisas:

| Situação | Cesta | Destino | Leitura |
|---|---|---|---|
| Mercado caiu | 82 | 80 | Bom momento para comprar, mas nada de especial neste destino |
| Destino descolou | 101 | 78 | **Distorção** — promoção, guerra de tarifa ou erro |

É o mesmo raciocínio de um índice de preços: o número de um item só significa
alguma coisa ao lado do índice geral.

---

## Como o índice é calculado

**1. O benchmark.** Não é um número, é uma conta:

```
benchmark = base × sazonalidade[mês] × antecedência[dias] × cabine × origem × pax
```

`base` é o preço de referência da ida e volta em econômica saindo de São Paulo,
na média do ano. `sazonalidade` redistribui esse valor pelos doze meses — cada
linha tem média exatamente 1,00, então ela muda a distribuição sem mexer no
nível anual. `antecedência` é uma curva compartilhada, interpolada entre pontos.

**2. O índice.** `índice = 100 × preço / benchmark`. 100 é a referência; 78
significa 22% abaixo dela. Como o benchmark já desconta mês e antecedência,
viajar em julho ou comprar em cima da hora **não** faz o índice subir.

**3. A cesta.** Os dez destinos são cotados na mesma rodada, com a mesma
metodologia. A **mediana** dos dez é o índice de mercado — mediana, não média,
para que um destino despencando ou uma cotação quebrada não arraste o mercado.

**4. A distorção.** `distorção = índice do destino − índice da cesta`, em pontos.

### Do sinal ao alerta

Os dois sinais são medidos na mesma unidade — quantas **bandas de variação
normal do destino** o preço está abaixo — e o mais forte manda:

```
sinal_benchmark = (100 − índice) / banda
sinal_distorção = (cesta − índice) / banda × 1,15
sinal           = max(os dois)
```

O peso de 1,15 dá leve vantagem à distorção: ela é específica do destino,
enquanto o desvio puro pode ser movimento de mercado.

| Sinal | Nível | Quando a distorção manda | Quando o benchmark manda |
|---|---|---|---|
| ≥ 1,0 | 1 | descolando da cesta | abaixo do benchmark |
| ≥ 1,6 | 2 | **distorção clara** | bem abaixo do benchmark |
| ≥ 2,4 | 3 | **distorção forte** | muito abaixo do benchmark |
| índice ≤ 45 | 4 | suspeito — possível tarifa-erro | |

O rótulo muda conforme o sinal que disparou. Chamar de "distorção" um preço que
apenas acompanha um mercado barato seria impreciso, e o app não faz isso.

A **banda** é por destino: Buenos Aires oscila ±16 pontos, Tóquio ±10. O mesmo
índice 86 é sinal forte em Tóquio e ruído em Buenos Aires.

---

## A cesta

Saindo de São Paulo (GRU), escolhidos pelos corredores de maior demanda do
Brasil e por regiões distintas o bastante para que uma distorção em um não
contamine a leitura dos outros:

| | Destino | Região | Base | Banda | Meses mais baratos |
|---|---|---|---|---|---|
| LIS | Lisboa | Europa | R$ 4.200 | ±12 | mai, out, nov |
| MAD | Madri | Europa | R$ 4.400 | ±12 | mai, out, nov |
| FCO | Roma | Europa | R$ 5.200 | ±13 | mar, out, nov |
| CDG | Paris | Europa | R$ 5.000 | ±12 | mar, out, nov |
| JFK | Nova York | América do Norte | R$ 4.800 | ±13 | set, out, nov |
| MIA | Miami | América do Norte | R$ 4.300 | ±13 | mai, set, out |
| EZE | Buenos Aires | América do Sul | R$ 2.100 | ±16 | abr, mai, set |
| SCL | Santiago | América do Sul | R$ 2.600 | ±15 | abr, mai, out |
| CUN | Cancún | Caribe | R$ 3.900 | ±14 | mai, set, out |
| HND | Tóquio | Ásia | R$ 8.500 | ±10 | fev, mai, jun |

A tabela inteira — inclusive os doze fatores mensais de cada destino — está em
`flightwatch/benchmarks.py` e aparece em `/benchmarks` no painel. Acrescentar um
destino é somar uma entrada em `DESTINATIONS`.

### Recalibração

A tabela é escrita à mão, e isso é uma escolha: é o que faz o app funcionar no
primeiro minuto. Mas preço envelhece. A recalibração inverte a fórmula em cada
cotação coletada:

```
base_implícita = preço / (sazonalidade × antecedência × cabine × origem × pax)
```

Tirar esses fatores põe cotações de meses e antecedências diferentes na mesma
régua; a mediana delas é o que o mercado diz que a base deveria ser.

```bash
python run.py recalibrate --dry-run   # mostra o que mudaria
python run.py recalibrate             # aplica
python run.py reset-calibration       # volta à tabela do código
```

Três travas: mínimo de 25 cotações, mínimo de 3 meses distintos de partida (sem
espalhamento a mediana só descreveria a época coletada) e passo máximo de 20%
por vez, para a base não perseguir um período atípico.

---

## Metodologia da medição

Fixa por design — mudá-la quebra a comparabilidade da série:

- origem **GRU**, ida e volta de **10 noites**, **econômica**, **1 passageiro**;
- três sondagens por destino: **30, 60 e 120 dias** antes da partida;
- o índice do destino é a **mediana das três**.

A contagem é ímpar de propósito: com número par a mediana cairia entre duas
sondagens e o índice mostrado no painel não corresponderia a cotação nenhuma.
Assim, o número do card, o do alerta e o da série são sempre o mesmo.

**Consumo de API:** 10 destinos × 3 sondagens = 30 chamadas por rodada. No
intervalo padrão de 24 h, **900 chamadas/mês** — folgado dentro da cota gratuita
da Amadeus (2.000). A 12 h sobe para 1.800, que ainda cabe com pouca folga.
`python run.py doctor` calcula isso para a sua configuração.

---

## Colocando para funcionar de verdade

```bash
pip install -r requirements.txt

export FLIGHTWATCH_PROVIDER=amadeus
export AMADEUS_CLIENT_ID=...
export AMADEUS_CLIENT_SECRET=...
export AMADEUS_HOST=https://api.amadeus.com   # o ambiente de teste tem dados limitados

python run.py doctor      # confere credencial, cota e faz uma consulta real
python run.py measure     # primeira medição
python run.py serve --with-scheduler
```

O `doctor` é o passo que separa "rodou" de "está medindo de verdade": ele
instancia o provedor, faz uma cotação real, calcula o consumo mensal e avisa se
você ainda está no simulador.

### Comandos

| Comando | O que faz |
|---|---|
| `measure` | mede a cesta e avalia distorções |
| `run --interval MIN` | mede continuamente |
| `basket` | mostra a última medição, sem cotar nada |
| `destination LIS` | benchmark, sazonalidade e leitura atual de um destino |
| `table` | a tabela de benchmark inteira, para auditoria |
| `recalibrate` | reajusta os preços-base com as cotações coletadas |
| `add LIS 2027-01-17 --return 2027-01-31` | acompanha uma viagem específica |
| `alerts [--json]` | alertas registrados |
| `doctor` | verifica credenciais, cota de API e configuração |
| `serve [--with-scheduler]` | painel web |
| `demo` | simula rodadas para conhecer o app |

### Viagens acompanhadas

A cesta mede o mercado; uma viagem acompanhada é a sua data concreta. Ela recebe
o mesmo tratamento — benchmark próprio (com a sua cabine, origem e número de
passageiros) e comparação com a cesta da rodada.

```bash
python run.py add LIS 2027-01-17 --return 2027-01-31 --label "Férias" --target 4200 --flex 2
```

Com `--flex`, entre as datas vizinhas vence o **menor índice**, não o menor
preço: uma data mais barata só por ser baixa estação não é oportunidade.

---

## Fontes de cotação

| Provedor | Uso |
|---|---|
| `amadeus` | API real (Flight Offers Search). Credencial gratuita. |
| `synthetic` | Simulador **ancorado na tabela de benchmark**. |

O simulador não inventa preços do nada: ele parte do próprio benchmark e aplica
três forças independentes — deriva de mercado (move os dez juntos), deriva do
destino e promoção relâmpago (movem um só). É por isso que ele serve de banco de
provas: como ele sabe qual destino colocou em promoção e quando mexeu o mercado
inteiro, os testes verificam se o app separa uma coisa da outra. O parâmetro
`bias` desloca o mercado de propósito, e um teste confirma que a recalibração
reencontra esse desvio.

Outro provedor é uma subclasse de `Provider` com um método `search`
(`flightwatch/providers/base.py`) registrada em `providers/__init__.py`.

---

## Alertas

Console, arquivo JSONL (`data/alerts.jsonl`) e webhook ao mesmo tempo. O payload
traz `text` e `content`, então funciona direto em Slack e Discord.

```
🔵 Madri por R$2.996 — índice 84 contra cesta em 102 (-19 pontos) — distorção clara
   GRU - São Paulo, Brasil → MAD - Madri, Espanha
   ida 05/11/2026 · volta 15/11/2026 · 60 dias de antecedência
   benchmark R$3.586 · índice 84 · sinal 1.8 banda(s) · nota 76/100
   • Índice 84 — 16% abaixo do benchmark de R$ 3.586 para nov comprando com 60 dias.
   • A cesta de 10 destinos está em 102; este destino está 19 pontos abaixo do mercado.
   • O desvio equivale a 1,8 banda(s) de variação normal do destino (±12%).
```

Todo alerta explica **qual dos dois sinais disparou** — sem isso, "índice 84"
não diz se vale a pena agir.

---

## API

| Rota | Descrição |
|---|---|
| `GET /api/basket` | última medição, com veredito de cada destino |
| `GET /api/index` | série do índice de mercado |
| `GET /api/destinations` | a tabela de benchmark com a base em uso |
| `GET /api/destinations/<iata>/history` | série do índice de um destino |
| `GET /api/watches` · `POST /api/watches` | viagens acompanhadas |
| `GET /api/alerts` · `POST /api/collect` | alertas e disparo de rodada |
| `GET /health` | saúde do serviço |

---

## Docker

```bash
docker build -t flightwatch .
docker run -p 10001:10001 -v flightwatch-data:/app/data flightwatch
```

O app funciona com o volume vazio — a referência de preço está no código. O
volume preserva a série do índice e a recalibração.

---

## Testes

```bash
cd tests && python3 -m unittest discover
```

130 testes, sem dependências além do Flask. Cobrem a integridade da tabela
(sazonalidade com média 1,00, meses baratos coerentes), a álgebra do benchmark,
os dois cenários que o app existe para separar, os limiares por banda, a
recalibração de um desvio conhecido, a consistência entre o índice do painel, o
do alerta e o da série, a deduplicação, o formulário, os gráficos e as rotas web.

---

## Estrutura

```
flightwatch/
  benchmarks.py    a tabela dos 10 destinos e a álgebra do benchmark
  indexing.py      índice, cesta, distorção e veredito
  calibration.py   recalibração da base a partir das cotações
  monitor.py       a rodada de medição
  stats.py         mediana, MAD e escala robusta
  providers/       amadeus (real) e synthetic (ancorado no benchmark)
  db.py            SQLite: cotações, snapshots do índice, alertas, calibração
  charts.py        SVG no servidor, sem JavaScript nem CDN
  web.py / cli.py  painel, API e linha de comando
  airports.py      207 aeroportos com coordenadas
```

Sem NumPy, pandas ou biblioteca de gráficos.

---

## Limites honestos

- **Os números da tabela são um ponto de partida, não verdade de mercado.**
  Partem de faixas observadas em 2025-2026 e são conservadores de propósito.
  Rode `recalibrate` depois de algumas semanas de coleta real.
- **A cesta é de São Paulo.** Outras origens brasileiras usam um fator de ajuste
  aproximado (`ORIGIN_FACTOR`), suficiente para ordenar, não para precificar.
- **Só os 10 destinos têm benchmark.** É a contrapartida de funcionar no
  primeiro minuto; acrescentar um destino é uma entrada em `DESTINATIONS`.
- **O simulador não é preço real.** Serve para demonstrar e testar.
- **Sem conversão de câmbio**: a tabela está em BRL e o app cota em BRL.
- Uma leitura marcada como *suspeita* costuma ser tarifa-erro: dura pouco e pode
  ser cancelada pela companhia.
