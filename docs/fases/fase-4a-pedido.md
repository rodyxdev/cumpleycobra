# Prueba real del pedido asistido

Modelo: `gemini-3.5-flash`. Inicio UTC: 2026-09-24T22:05:59.892555+00:00.

Máximo 8 llamadas/minuto; todos los intentos separados por al menos 8 s. Sin cadena.

| Borrador | A | B | C | D |
| --- | --- | --- | --- | --- |
| 1 | Aprobado (4.5 s, llm) | Rechazado (7.7 s, llm) | Rechazado (10.5 s, llm) | Rechazado (0.0 s, deterministic) |
| 2 | Aprobado (5.6 s, llm) | Rechazado (8.0 s, llm) | Rechazado (8.2 s, llm) | Rechazado (0.0 s, deterministic) |
| 3 | Aprobado (5.8 s, llm) | Rechazado (9.2 s, llm) | Rechazado (7.2 s, llm) | Rechazado (0.0 s, deterministic) |
| 4 | Aprobado (5.9 s, llm) | Rechazado (8.4 s, llm) | Rechazado (7.8 s, llm) | Rechazado (0.0 s, deterministic) |
| 5 | Aprobado (6.2 s, llm) | Rechazado (7.5 s, llm) | Rechazado (8.3 s, llm) | Rechazado (0.0 s, deterministic) |

## Borrador 1

Una función en Python que toma una lista de precios y un porcentaje de descuento, aplica dicho descuento a cada precio y retorna una nueva lista con los precios finales redondeados a 2 decimales, sin utilizar librerías externas.

`rules_hash`: `3c22bbc1e5114fc41ca96bf806c4a2fbafcef248e576dc0f95a21bb1c3f7810c`

1. La función acepta como argumentos una lista de valores numéricos que representan los precios y un valor numérico que representa el porcentaje de descuento.
2. La función calcula el descuento para cada precio aplicando la reducción porcentual correspondiente.
3. La función devuelve una lista con los precios resultantes, donde cada elemento está redondeado a dos decimales.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 10.0], descuento = 10` → salida: `[90.0, 45.0, 9.0]`
- Entrada: `precios = [19.99, 5.5], descuento = 20` → salida: `[15.99, 4.4]`

## Borrador 2

Una función en Python que toma una lista de precios y un porcentaje de descuento, aplica dicho descuento a cada precio y retorna una nueva lista con los precios finales redondeados a 2 decimales, sin utilizar librerías externas.

`rules_hash`: `3c22bbc1e5114fc41ca96bf806c4a2fbafcef248e576dc0f95a21bb1c3f7810c`

1. La función acepta como argumentos una lista de valores numéricos que representan los precios y un valor numérico que representa el porcentaje de descuento.
2. La función calcula el descuento para cada precio aplicando la reducción porcentual correspondiente.
3. La función devuelve una lista con los precios resultantes, donde cada elemento está redondeado a dos decimales.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 10.0], descuento = 10` → salida: `[90.0, 45.0, 9.0]`
- Entrada: `precios = [19.99, 5.5], descuento = 20` → salida: `[15.99, 4.4]`

## Borrador 3

Una función en Python que toma una lista de precios y un porcentaje de descuento, aplica dicho descuento a cada precio, redondea los resultados a dos decimales y devuelve la lista con los nuevos precios.

`rules_hash`: `f7d7b95e72786fd6d498c6d254465c8a91a6d9fc53df552dc71b6582305aa963`

1. La función acepta dos parámetros de entrada: una lista que contiene valores numéricos representando precios y un número que representa el porcentaje de descuento.
2. Para cada precio de la lista de entrada, se calcula el precio con el descuento aplicado mediante la fórmula de reducción porcentual correspondiente.
3. Cada uno de los precios calculados con el descuento aplicado se redondea a exactamente dos decimales.
4. La función retorna una lista con los precios resultantes en el mismo orden en el que se recibieron en la lista de entrada.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 20.0], descuento = 10` → salida: `[90.0, 45.0, 18.0]`
- Entrada: `precios = [10.55, 99.99], descuento = 15` → salida: `[8.97, 84.99]`

## Borrador 4

Una función en Python que toma una lista de precios y un porcentaje de descuento, aplica dicho descuento a cada precio, redondea los resultados a dos decimales y devuelve la lista con los nuevos precios.

`rules_hash`: `f7d7b95e72786fd6d498c6d254465c8a91a6d9fc53df552dc71b6582305aa963`

1. La función acepta dos parámetros de entrada: una lista que contiene valores numéricos representando precios y un número que representa el porcentaje de descuento.
2. Para cada precio de la lista de entrada, se calcula el precio con el descuento aplicado mediante la fórmula de reducción porcentual correspondiente.
3. Cada uno de los precios calculados con el descuento aplicado se redondea a exactamente dos decimales.
4. La función retorna una lista con los precios resultantes en el mismo orden en el que se recibieron en la lista de entrada.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 20.0], descuento = 10` → salida: `[90.0, 45.0, 18.0]`
- Entrada: `precios = [10.55, 99.99], descuento = 15` → salida: `[8.97, 84.99]`

## Borrador 5

Una función en Python que toma una lista de precios y un porcentaje de descuento, aplica dicho descuento a cada precio, redondea los resultados a dos decimales y devuelve la lista con los nuevos precios.

`rules_hash`: `f7d7b95e72786fd6d498c6d254465c8a91a6d9fc53df552dc71b6582305aa963`

1. La función acepta dos parámetros de entrada: una lista que contiene valores numéricos representando precios y un número que representa el porcentaje de descuento.
2. Para cada precio de la lista de entrada, se calcula el precio con el descuento aplicado mediante la fórmula de reducción porcentual correspondiente.
3. Cada uno de los precios calculados con el descuento aplicado se redondea a exactamente dos decimales.
4. La función retorna una lista con los precios resultantes en el mismo orden en el que se recibieron en la lista de entrada.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 20.0], descuento = 10` → salida: `[90.0, 45.0, 18.0]`
- Entrada: `precios = [10.55, 99.99], descuento = 15` → salida: `[8.97, 84.99]`
