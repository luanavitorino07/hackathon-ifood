# Política comercial de descontos (DEMO)

> Documento FICTÍCIO para demonstração. Não representa política real da empresa, de restaurantes
> ou do iFood. Margens e taxas de conversão abaixo são hipóteses ilustrativas.

## Quando sugerir desconto
topics: desconto, incentivo, pedido mínimo, aprovação

Sugerir desconto somente em pedidos a partir de R$ 80,00 de subtotal e somente quando o lucro
esperado com o desconto for maior que sem ele. Toda sugestão de desconto exige aprovação do gestor
comercial: o agente nunca aplica desconto nem o inclui no total mostrado ao cliente. Orçamento e
restrições informados pelo cliente sempre prevalecem sobre qualquer tentativa de aumentar lucro.

## Parâmetros do desconto
topics: desconto, parâmetros, margem, conversão, lucro esperado

Valores usados pelo especialista em descontos ao avaliar uma sugestão.

```params
desconto_bps: 500
pedido_minimo_centavos: 8000
teto_desconto_centavos: 1500
margem_suposta_bps: 3000
conversao_sem_desconto_bps: 5000
conversao_com_desconto_bps: 6500
```

## Limites e exceções
topics: desconto, limites, exceções, restrições

Não sugerir desconto quando faltarem dados de preço confiáveis. Em atendimento real sem dados de margem
fornecidos pela empresa, a sugestão usa as hipóteses DEMO acima, é marcada como ilustrativa e serve só
para o gestor avaliar. Nunca prometer desconto ao cliente antes da
aprovação. Nunca combinar desconto com cupons do iFood sem regra explícita.
