# Catálogo e produtos indisponíveis

Busca com faixa de preço e os três casos de produto que existe mas não pode ser comprado: esgotado, descontinuado e pré-lançamento.

- **Data simulada:** terça-feira, 03/11/2026, 15:00 (horário de Campo Grande/MS). A loja está aberta agora, até as 18h.
- **Modelo:** openai · gpt-6-luna · esforço medium
- **Uso:** 4 turnos · 27466 tokens de entrada (22880 em cache) · 875 de saída · custo estimado US$ 0.001125
- **Gerado em:** 03/11/2026 18:05 por `python -m evals.exemplos` (conversa `exemplo-03-catalogo-e-indisponiveis`), sem edição manual

## Conversa

**Cliente:** Quais violões vocês têm disponíveis até R$ 1000?

**Emilio:**

> Temos 12 violões disponíveis até R$ 1.000:
>
> - Tagima Memphis AC-39 Nylon Natural — R$ 429,90 (R$ 408,41 no PIX)
> - Rozini RC-104 Nylon Estudante — R$ 459,90 (R$ 436,91 no PIX)
> - Shelby SN-100 Folk Aço Preto — R$ 549,00 (R$ 521,55 no PIX)
> - Giannini GF-1R Aço Folk Sunburst — R$ 579,90 (R$ 550,91 no PIX)
> - Yamaha C40 Nylon Natural — R$ 599,90 (R$ 569,91 no PIX)
> - Giannini GN-15 Nylon Cedr Natural — R$ 689,00 (R$ 654,55 no PIX)
> - Yamaha F310 Aço Natural — R$ 699,90 (R$ 664,91 no PIX)
> - Tagima Dallas Tuner Aço Natural — R$ 749,00 (R$ 711,55 no PIX)
> - Shelby SGD-195E Elétrico Aço Sunburst — R$ 799,00 (R$ 759,05 no PIX)
> - Yamaha C70 Nylon Natural — R$ 849,00 (R$ 806,55 no PIX)
> - Tagima Woodstock Dreadnought Natural — R$ 899,00 (R$ 854,05 no PIX)
> - Tagima TW-7 7 Cordas Aço Natural — R$ 999,00 (R$ 949,05 no PIX)
>
> Se quiser, posso te ajudar a escolher entre nylon, aço ou elétrico.

Ferramentas: `buscar_produtos(categoria="Violões", preco_max=1000, apenas_disponiveis=true)`, `buscar_produtos(categoria="Violões", preco_min=849.01, preco_max=1000, apenas_disponiveis=true)`

**Cliente:** E o Giannini GF-3D, vocês têm?

**Emilio:**

> O Giannini GF-3D Dreadnought Sunburst está no nosso catálogo, mas no momento está sem estoque.

Ferramentas: `buscar_produtos(termo="Giannini GF-3D", categoria="Violões", apenas_disponiveis=false)`

**Cliente:** E o Shelby SN-7C de 7 cordas?

**Emilio:**

> O Shelby SN-7C 7 Cordas Nylon Natural não está disponível e consta como descontinuado no nosso catálogo.

Ferramentas: `buscar_produtos(termo="Shelby SN-7C", categoria="Violões", apenas_disponiveis=false)`

**Cliente:** Por último: o ukulele Kala KA-ABP-CTG barítono já está à venda?

**Emilio:**

> Ainda não está à venda: o Kala KA-ABP-CTG Barítono Cedar está em pré-lançamento no nosso catálogo.

Ferramentas: `buscar_produtos(termo="Kala KA-ABP-CTG", categoria="Ukuleles", apenas_disponiveis=false)`
