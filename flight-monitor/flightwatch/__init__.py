"""Monitor de passagens aéreas com detecção estatística de oportunidade.

Um preço só é "barato" em relação a alguma coisa. Este pacote constrói essa
referência a partir do histórico da própria rota — separando o efeito do
período do ano e o da antecedência da compra — e alerta quando uma cotação
cai significativamente abaixo dela.
"""

__version__ = "1.0.0"
__all__ = ["analytics", "airports", "charts", "config", "db", "models", "monitor", "seed"]
