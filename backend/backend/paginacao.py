"""Paginação das listas da API: 20 por página, ou o tamanho pedido pela tela em ?tamanho= (1 a 100)."""
from rest_framework.pagination import PageNumberPagination


class Paginacao(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'tamanho'
    max_page_size = 100
