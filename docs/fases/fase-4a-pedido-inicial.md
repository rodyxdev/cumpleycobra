# Prueba real del pedido asistido

Modelo: `gemini-3.5-flash`. Inicio UTC: 2026-09-24T21:56:20.898779+00:00.

Máximo 8 llamadas/minuto; todos los intentos separados por al menos 8 s. Sin cadena.

| Borrador | A | B | C | D |
| --- | --- | --- | --- | --- |
| 1 | Aprobado (3.7 s, llm) | Rechazado (8.4 s, llm) | Rechazado (8.1 s, llm) | Rechazado (0.0 s, deterministic) |
| 2 | Aprobado (6.1 s, llm) | Rechazado (8.3 s, llm) | Rechazado (8.3 s, llm) | Rechazado (0.0 s, deterministic) |
| 3 | Aprobado (5.9 s, llm) | Rechazado (7.8 s, llm) | Rechazado (8.3 s, llm) | Rechazado (0.0 s, deterministic) |
| 4 | Aprobado (5.5 s, llm) | Rechazado (8.7 s, llm) | Rechazado (7.5 s, llm) | Rechazado (0.0 s, deterministic) |
| 5 | Aprobado (6.2 s, llm) | Rechazado (8.3 s, llm) | Rechazado (11.3 s, llm) | Rechazado (0.0 s, deterministic) |

## Borrador 1

Una función en Python que recibe una lista de precios y un porcentaje de descuento, y retorna una nueva lista con los precios tras aplicarles el descuento, redondeados a dos decimales.

`rules_hash`: `d4ed148b7f7d4e57f05f32e6cd0ed59c31e99ecfafe776283bc212fe10b4c8db`

1. La función acepta dos parámetros: una lista de valores numéricos que representan los precios y un valor numérico que representa el porcentaje de descuento.
2. La función calcula el precio con descuento aplicando la fórmula de reducción porcentual para cada elemento de la lista.
3. Cada uno de los precios resultantes se redondea a dos decimales.
4. La función retorna una nueva lista con los precios calculados y redondeados en el mismo orden que la lista de entrada.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 20.5], descuento = 10` → salida: `[90.0, 45.0, 18.45]`
- Entrada: `precios = [10.0, 5.5], descuento = 15` → salida: `[8.5, 4.68]`

## Borrador 2

Una función en Python que recibe una lista de precios y un porcentaje de descuento, y retorna una nueva lista con los precios tras aplicarles el descuento, redondeados a dos decimales.

`rules_hash`: `d4ed148b7f7d4e57f05f32e6cd0ed59c31e99ecfafe776283bc212fe10b4c8db`

1. La función acepta dos parámetros: una lista de valores numéricos que representan los precios y un valor numérico que representa el porcentaje de descuento.
2. La función calcula el precio con descuento aplicando la fórmula de reducción porcentual para cada elemento de la lista.
3. Cada uno de los precios resultantes se redondea a dos decimales.
4. La función retorna una nueva lista con los precios calculados y redondeados en el mismo orden que la lista de entrada.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 20.5], descuento = 10` → salida: `[90.0, 45.0, 18.45]`
- Entrada: `precios = [10.0, 5.5], descuento = 15` → salida: `[8.5, 4.68]`

## Borrador 3

Implementar una función en Python que reciba una lista de precios y un porcentaje de descuento, aplique el descuento a cada precio, los redondee a dos decimales y devuelva la lista resultante.

`rules_hash`: `ce8be3299044e3f8503d8dbd004c888debe6aeb34ec37915d324c81aca690e0a`

1. Se define una función que acepta dos argumentos: una lista de precios y un valor numérico que representa el porcentaje de descuento.
2. La función calcula el precio con descuento aplicando la fórmula correspondiente para cada elemento de la lista de entrada.
3. Cada precio calculado con el descuento se redondea a exactamente dos decimales.
4. La función retorna una lista con los precios finales tras aplicar el descuento y el redondeo.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 25.5], descuento = 10` → salida: `[90.0, 45.0, 22.95]`
- Entrada: `precios = [10.0, 20.0], descuento = 15` → salida: `[8.5, 17.0]`

## Borrador 4

Implementar una función en Python que reciba una lista de precios y un porcentaje de descuento, aplique el descuento a cada precio, los redondee a dos decimales y devuelva la lista resultante.

`rules_hash`: `ce8be3299044e3f8503d8dbd004c888debe6aeb34ec37915d324c81aca690e0a`

1. Se define una función que acepta dos argumentos: una lista de precios y un valor numérico que representa el porcentaje de descuento.
2. La función calcula el precio con descuento aplicando la fórmula correspondiente para cada elemento de la lista de entrada.
3. Cada precio calculado con el descuento se redondea a exactamente dos decimales.
4. La función retorna una lista con los precios finales tras aplicar el descuento y el redondeo.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 25.5], descuento = 10` → salida: `[90.0, 45.0, 22.95]`
- Entrada: `precios = [10.0, 20.0], descuento = 15` → salida: `[8.5, 17.0]`

## Borrador 5

Una función en Python que recibe una lista de precios y un porcentaje de descuento, aplica el descuento correspondiente a cada precio, redondea cada resultado a dos decimales y retorna la lista con los nuevos precios.

`rules_hash`: `fb6abff911b837e2e4e65e9f17583d8db4be1c631e9287ab73bc0e9f3e015d9d`

1. La función debe aceptar dos parámetros: una lista de valores numéricos que representan los precios y un número que representa el porcentaje de descuento.
2. La función debe aplicar el porcentaje de descuento a cada uno de los precios de la lista de entrada.
3. Cada precio con el descuento aplicado debe ser redondeado a exactamente 2 decimales.
4. La función debe retornar una nueva lista con los precios resultantes tras aplicar el descuento y el redondeo.

Ejemplos:

- Entrada: `precios = [100.0, 50.0, 10.5], descuento = 10` → salida: `[90.0, 45.0, 9.45]`
- Entrada: `precios = [19.99, 5.5], descuento = 15` → salida: `[16.99, 4.68]`
