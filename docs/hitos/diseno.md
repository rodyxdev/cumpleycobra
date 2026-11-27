# Pago por hitos: diseño (borrador para revisión)

Estado: **aprobado por Rodrigo el 24 de noviembre de 2026**, con las 5 decisiones de la sección 7 tal como se proponen. **Etapa 1 hecha** (24 de noviembre): contrato v2 `CAUBTDTWJKWKXH25LHXPES3ADTDRMBHYK4VOSWEWIBIYNLUINDR2K77K` desplegado en testnet, 32 tests en verde y un proyecto real de 3 hitos que usó las cuatro funciones nuevas. Evidencia en [`contracts/cumpleycobra/README.md`](../../contracts/cumpleycobra/README.md#v2-pago-por-hitos-24-de-noviembre-de-2026). Siguen las etapas 2 a 4.

## 1. La idea

Una opción más para el cliente, **no obligatoria**: dividir una tarea grande en **hitos**. Cada hito tiene sus propios criterios, su monto y su plazo, y se paga en cuanto se verifica. El cliente deposita todo al inicio, así que el programador sabe que el dinero existe. El cliente libera por partes, y entre un hito y otro hay retroalimentación sin salir de Cumple&Cobra.

Sirve para proyectos grandes o que necesitan revisión constante, y mantiene la conversación, las entregas, los veredictos y los pagos dentro de la plataforma y en la red, en vez de en WhatsApp o en correos.

**Por qué hitos y no criterio por criterio:** los criterios no son independientes («termina con cualquier lista» no vale nada si la función no existe). Si cada criterio se pagara por separado, un programador podría cobrar los fáciles y abandonar el resto. El hito agrupa los criterios que solo tienen sentido juntos.

Ejemplo:

| Hito | Criterios | Monto | Plazo |
| --- | --- | --- | --- |
| 1. Estructura y formulario | 1, 2, 3 | 30% | 7 días |
| 2. Lógica completa | 4, 5, 6 | 50% | 14 días |
| 3. Pruebas y despliegue | 7, 8 | 20% | 21 días |

La tarea simple de hoy (un depósito, un pago) **no cambia**.

## 2. Contrato: v2 desplegado aparte

- **El contrato desplegado (`CAWAZODO…LQRATQ`) no se toca.** Sigue con todas las tareas simples, incluidas las 20 de `/probar`.
- **v2 es el mismo código más las funciones de hitos.** El mismo crate `contracts/cumpleycobra` gana las funciones nuevas, y su WASM se despliega como **otra instancia** con otro ID, inicializada con el mismo árbitro y el mismo USDC.
  - Las funciones de hoy siguen idénticas, con sus mismos tests.
  - La app usa v1 para las tareas simples y v2 para las tareas por hitos.
  - Más adelante se puede decidir si las tareas simples también pasan a v2.
- **Regla del proyecto que se ajusta:** «lo que no cambia nunca: el contrato Soroban desplegado» pasa a «el contrato desplegado no se modifica; las funciones nuevas van en una versión nueva desplegada aparte». Requiere el visto bueno de Rodrigo.

### Tipos nuevos

```rust
// Estado de un hito: el mismo camino de ida que una tarea.
pub enum MilestoneStatus { Funded, Released, Refunded }

pub struct Milestone {
    pub amount: i128,             // unidades del token
    pub deadline: u64,            // timestamp del ledger
    pub rules_hash: BytesN<32>,   // criterios de ESTE hito
    pub status: MilestoneStatus,
}

pub struct Project {
    pub task_id: String,
    pub client: Address,
    pub freelancer: Option<Address>,  // se fija en el primer pago y ya no cambia
    pub milestones: Vec<Milestone>,
}

// Llave nueva: DataKey::Project(String), aparte de DataKey::Task(String).
```

### Funciones nuevas

| Función | Firma | Reglas |
| --- | --- | --- |
| `deposit_milestones(client, task_id, amounts: Vec<i128>, deadlines_secs: Vec<u64>, rules_hashes: Vec<BytesN<32>>)` | Cliente | De 2 a 10 hitos; las tres listas del mismo largo; cada monto > 0; plazos > 0 y que no bajen (el hito 2 no vence antes que el 1), sumados con `checked_add`; `task_id` nuevo (ni tarea ni proyecto existentes). Transfiere el **total** al contrato en una sola operación. Evento `deposit_milestones` |
| `release_milestone(task_id, index, freelancer, code_hash, verdict_hash)` | Árbitro | Solo un hito en `Funded` y antes de **su** plazo (`DeadlinePassed` si no). El primer pago fija al programador, y los siguientes solo le pueden pagar a él (`WrongFreelancer`). Cambia el estado y luego transfiere el monto de ese hito. Evento con los hashes |
| `client_release_milestone(task_id, index, freelancer)` | Cliente del proyecto | Aprobación manual de un hito (por ejemplo, tras un rechazo de la IA). Misma regla del programador fijo. Permitida también después del plazo de ese hito |
| `timeout_refund_milestone(task_id, index)` | Nadie (sin firma) | Solo un hito en `Funded` cuyo plazo ya pasó. El dinero de **ese** hito vuelve siempre al cliente. Los hitos ya pagados no se tocan |
| `get_project(task_id)` | Lectura | Cliente, programador, hitos con monto, plazo, `rules_hash` y estado |
| `add_milestone(task_id, amount, deadline_secs, rules_hash)` (v3) | Cliente del proyecto | Agrega un hito en `Funded` al final del proyecto y transfiere `amount` al contrato. Exige proyecto existente (`NotFound`), total ≤ 10 hitos (`InvalidMilestones`), `amount > 0` (`InvalidAmount`), plazo entre 1 s y 28 días con `checked_add` (`InvalidDeadline`) y vencimiento absoluto ≥ plazo del último hito (`InvalidMilestones`). Evento `add_milestone` |
| `top_up_milestone(task_id, index, amount)` (v3) | Cliente del proyecto | Aumenta el monto de un hito existente (`MilestoneNotFound`) que siga en `Funded` (`NotFunded`) y antes de su plazo (`DeadlinePassed`). Exige `amount > 0` y `checked_add` sobre el monto (`InvalidAmount`); transfiere `amount` al contrato. Evento `top_up_milestone` |
| `mutual_split_task(task_id, freelancer, freelancer_amount)` (v4) | Cliente + Programador | Reparto parcial atómico de una tarea simple en `Funded` (`0 < freelancer_amount < amount`): paga al programador y devuelve la diferencia al cliente |
| `mutual_split_milestone(task_id, index, freelancer, freelancer_amount)` (v4) | Cliente + Programador | Reparto parcial atómico de un hito en `Funded`, respetando al programador fijado del proyecto (`WrongFreelancer`) |
| `cancel_unassigned_task(task_id)` (v4) | Cliente + Árbitro | Cancela una tarea simple en `Funded` antes del plazo (`DeadlinePassed`) y devuelve el depósito íntegro al cliente |
| `cancel_unassigned_project(task_id)` (v4) | Cliente + Árbitro | Cancela un proyecto sin programador fijado (`AlreadyAssigned`), marca los hitos en `Funded` como `Refunded` y devuelve el total en una transferencia |
| `refund_all_expired_milestones(task_id)` (v4) | Nadie (sin firma) | Reembolsa en lote todos los hitos `Funded` cuyo plazo venció en una sola transferencia al cliente |
| `reduce_milestone(task_id, index, reduce_amount)` (v4) | Cliente + Programador (o Árbitro si no hay programador) | Recorta parcialmente un hito en `Funded` antes de su plazo y devuelve `reduce_amount` al cliente |
| `client_release_with_bonus(task_id, freelancer, bonus)` (v4) | Cliente | Aprobación manual de una tarea en `Funded` con un bono extra (`bonus > 0`) pagado en la misma transacción atómica |
| `batch_deposit(client, task_ids, amounts, deadlines_secs, rules_hashes)` (v4) | Cliente | Deposita de 2 a 10 tareas independientes en una sola llamada y una sola transferencia de USDC |
| `split_milestone(task_id, index, first_amount, first_deadline_secs, first_rules_hash, second_rules_hash)` (v4) | Cliente (y Programador si ya está fijado) | Divide un hito `Funded` en dos hitos consecutivos conservando el total, el tope de 10 hitos y el orden de plazos |
| `extend_milestone_deadline(task_id, index, extra_secs)` (v4) | Cliente | Prorroga hacia adelante el plazo de un hito `Funded`, dentro de 28 días desde ahora y sin rebasar el hito siguiente |
| `rotate_arbiter(new_arbiter)` (v4) | Árbitro actual + Nuevo árbitro | Rotación segura del árbitro en una sola transacción con doble firma (`SameArbiter` si coincide con el actual) |

Las cuatro primeras mueven dinero: no son «solo leer» ni «solo guardar un valor».

### Errores nuevos (se agregan; los de hoy nunca se renumeran)

| N.º | Error | Cuándo |
| --- | --- | --- |
| 10 | `InvalidMilestones` | Listas de distinto largo, menos de 2 o más de 10 hitos, o plazos que bajan |
| 11 | `MilestoneNotFound` | `index` fuera de rango |
| 12 | `WrongFreelancer` | Un pago a una dirección distinta del programador ya fijado |
| 13 | `AlreadyAssigned` | Intento de cancelar como no asignado un proyecto que ya tiene programador fijado (v4) |
| 14 | `SameArbiter` | Intento de rotar el árbitro hacia la misma dirección actual (v4) |

Los de hoy se reutilizan: `InvalidAmount`, `AlreadyExists`, `NotFound`, `NotFunded` (el hito ya no está en `Funded`), `DeadlinePassed`, `DeadlineNotReached`, `InvalidDeadline` y `NotInitialized`.

### Plazos y vida del almacenamiento

- Hoy el plazo máximo es de 7 días, para quedar lejos de los 30 días de TTL que se renuevan en cada escritura. Un proyecto por hitos necesita más.
- Propuesta: **plazo máximo de 28 días por hito.** Cada escritura renueva el TTL a 30 días.
- Riesgo a revisar: un proyecto sin actividad por más de 30 días dejaría archivada su entrada. En Soroban se puede restaurar, pero hay que probarlo antes de permitir plazos largos.

### Seguridad (lo que Rodrigo debe poder explicar)

1. **Un hito solo se paga una vez:** su estado deja `Funded` antes de transferir (checks-effects-interactions). Un segundo pago falla con `NotFunded`.
2. **El dinero de un proyecto no puede ir a dos programadores:** se fija en el primer pago.
3. **El reembolso de un hito vencido no afecta a los ya pagados** y solo va al cliente.
4. **El total depositado siempre cuadra:** pagados + reembolsados + pendientes = depositado. Hay un test que lo comprueba en cada camino.
5. **El orden entre hitos no lo impone el contrato.** Es flexible: el cliente puede aprobar el 2 antes que el 1. El orden «uno tras otro» lo aplica el backend si el cliente lo elige.

### Tests obligatorios antes de desplegar v2

- [ ] Camino feliz de 3 hitos: saldos finales correctos (cliente, contrato y programador).
- [ ] Un hito pagado dos veces falla y no mueve fondos.
- [ ] `release_milestone` firmado por un árbitro falso falla (sin `mock_all_auths`).
- [ ] El segundo hito a otra dirección falla con `WrongFreelancer`.
- [ ] `client_release_milestone` firmado por alguien que no es el cliente falla.
- [ ] Reembolso de un hito antes de su plazo falla; justo en el plazo funciona; a un tercero no le cambia el saldo.
- [ ] Reembolso de un hito ya pagado falla, y pagar un hito ya reembolsado también.
- [ ] Hito 1 pagado y hito 2 reembolsado: los saldos cuadran con el total.
- [ ] `release_milestone` exactamente en el plazo del hito falla con `DeadlinePassed`; un segundo antes funciona.
- [ ] `deposit_milestones` con listas de distinto largo, con 1 o 11 hitos, con un monto 0 o con plazos que bajan falla con su error.
- [ ] Un `task_id` repetido falla con `AlreadyExists`, entre proyectos y también entre proyecto y tarea.
- [ ] Índice fuera de rango falla con `MilestoneNotFound`.
- [ ] Los 11 tests de hoy siguen pasando sin cambios.
- [ ] (v3) Camino feliz: agregar un 4.º hito (`add_milestone`) y aumentar el hito 1 (`top_up_milestone`), saldos y eventos correctos, y al pagar todo el contrato queda en 0.
- [ ] (v3) `add_milestone` y `top_up_milestone` firmados por alguien que no es el cliente fallan (modo estricto, sin `mock_all_auths`).
- [ ] (v3) `add_milestone`: agregar el hito 11 falla (`InvalidMilestones`), plazo absoluto menor al del último hito falla (`InvalidMilestones`), monto 0/negativo falla (`InvalidAmount`) y plazo 0 o mayor a 28 días falla (`InvalidDeadline`).
- [ ] (v3) `top_up_milestone`: hito pagado o reembolsado falla con `NotFunded`, exactamente en su plazo falla con `DeadlinePassed`, índice fuera de rango falla con `MilestoneNotFound` y monto 0/negativo o desborde falla con `InvalidAmount`.
- [ ] (v3) El total siempre cuadra (`depositado = pagado + reembolsado + pendiente`) y se extiende el TTL tras ambas operaciones.

## 3. Backend

- **`POST /tasks` con `milestones` (opcional):** lista de `{title, criteria[], amount, deadline_minutes}`. Sin `milestones`, todo funciona igual que hoy.
  - El `amount` de la tarea es la suma de los hitos.
  - Cada hito es un acuerdo completo y se verifica por separado: por ejecución (con su propia suite oculta) o con el motor estático.
- **`rules_hash` de cada hito (`version: 3`):** el mismo objeto de hoy (v1 o v2) más `hito: {"proyecto": task_id, "indice": i, "de": n, "titulo"}`. Así cada hito tiene un hash distinto aunque repita criterios.
  - Ningún hash anterior cambia.
  - Se documenta en el README, como los demás.
- **Verificar un hito:** `POST /evaluate` y `POST /tasks/{id}/verificaciones` aceptan `milestone` (índice), sin cambiar ningún campo de respuesta existente.
  - Cada hito tiene sus 3 envíos, su caché y su `verdict_hash`.
  - El `verdict_hash` v2 ya incluye el `rules_hash`, así que distingue el hito sin cambiar su definición.
- **Pago:** `release_milestone` en v2, con las mismas guardias y reintentos de hoy (incluido el reintento ante `txBAD_SEQ`).
- **Orden secuencial (opcional, lo elige el cliente):** el backend no verifica el hito N hasta que el N-1 esté pagado. El contrato no lo impone.
- **Retroalimentación dentro de la plataforma:**
  - `POST /tasks/{id}/hitos/{n}/comentarios`, con `X-Client-Token` o `X-Freelancer-Token`: un hilo por hito, guardado en Postgres.
  - No toca dinero y es lo que evita salir a otros medios.
- **Entrega del código:** cada hito se entrega al cliente cuando ese hito se paga.
- **Detrás de `MILESTONES_ENABLED`** (apagado por defecto), con `MILESTONES_CONTRACT_ID` para el contrato v2.

## 4. Pantallas

- **Cliente, al crear la tarea:** casilla «Pagar por hitos (opcional)».
  - Abre una lista de hitos: título, criterios (los mismos editores de hoy), monto en pesos con su USDC y plazo.
  - Muestra el total y avisa si los hitos no suman lo que espera.
  - La IA puede **proponer** una división en hitos a partir del pedido, y el cliente decide.
- **Cliente, en su tarea:** una tarjeta por hito con su estado (Depositado, En revisión, Rechazado, Pagado o Reembolsado), su veredicto por criterio, el hilo de comentarios y «Aprobar manualmente» si se rechazó.
- **Programador:** ve todos los hitos antes de aceptar, que es parte del acuerdo, y entrega hito por hito. Cada hito tiene su terminal y su pago en stellar.expert.
- **Línea de estado:** muestra «2 de 3 hitos pagados», con lo cobrado y lo pendiente.

## 5. Plan por etapas

| Etapa | Qué | Cuándo | Cuenta para |
| --- | --- | --- | --- |
| 1 | Contrato v2: funciones, errores, eventos y los tests de arriba; desplegado en testnet; un proyecto real de 3 hitos invocado por script (depósito, 2 pagos y 1 reembolso) | 25–26 nov | Ship It: función nueva (+20 la primera, +10 cada una más) |
| 2 | Backend detrás de `MILESTONES_ENABLED`: crear, verificar y pagar por hito, más el hash v3 | después | — |
| 3 | Pantallas de cliente y programador | después | — |
| 4 | Comentarios por hito y división sugerida por la IA | después | — |

Cada etapa va en sus propios commits `ship-it: …` (solo la etapa 1 cae dentro del reto). **No es un avance del Instaward:** el SOW deja fuera las funciones nuevas del contrato, así que no se anota en `docs/instaward/seguimiento.md`.

## 6. Riesgos y límites honestos

- **Contrato sin auditoría:** v2 suma superficie de ataque. Se queda en testnet, como todo; mainnet sigue fuera.
- **La misma llave de árbitro** firma v1 y v2 (y staging). El reintento ante `txBAD_SEQ` cubre los choques de secuencia, pero sigue pendiente separar las llaves.
- **Los plazos largos** dependen del TTL (ver «Plazos y vida del almacenamiento»).
- **Más superficie en la app:** dos contratos y un estado por hito. Por eso va detrás de una variable, como el verificador.

## 7. Decisiones que necesito de Rodrigo

1. ¿Aceptas ajustar la regla del contrato: no se modifica el desplegado, y las funciones nuevas van en v2 aparte?
2. ¿Hitos con **su propio plazo** cada uno (lo que propongo) o un solo plazo para todo el proyecto (más simple)?
3. ¿Límites de **2 a 10 hitos** y **28 días máximo** por hito?
4. ¿El orden «uno tras otro» es opcional (lo que propongo) o siempre obligatorio?
5. ¿El nombre en pantalla es «hitos»?
