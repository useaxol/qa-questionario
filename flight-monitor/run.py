#!/usr/bin/env python3
"""Ponto de entrada do monitor de passagens.

    python run.py seed-demo     # carteira de exemplo com histórico reconstruído
    python run.py serve         # painel web
    python run.py collect       # uma rodada de cotação
    python run.py --help
"""
import sys

from flightwatch.cli import main

if __name__ == "__main__":
    sys.exit(main())
