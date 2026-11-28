#![no_std]

// Cumple&Cobra: acuerdo verificable para trabajo de código.
//
// El cliente deposita USDC amarrado a una tarea (`task_id`) y al hash de los
// criterios acordados (`rules_hash`). El árbitro (backend de Cumple&Cobra)
// libera el pago al programador solo después del veredicto del Motor de
// Análisis Estático de Código basado en LLM. Si la IA rechaza, el cliente
// puede aprobar manualmente. Si vence el plazo sin pago, cualquiera puede
// disparar el reembolso y el dinero solo puede volver al cliente.
//
// Base: `contracts/escrow` de CriptoUNAM-Team/Stellar-Guide, extendido.
//
// v2 (24 de noviembre de 2026): pago por hitos. Las funciones de la tarea
// simple no cambian; se agregan `deposit_milestones`, `release_milestone`,
// `client_release_milestone`, `timeout_refund_milestone` y `get_project`.
// El contrato v1 ya desplegado no se modifica: v2 se despliega aparte.
//
// v3 (25 de noviembre de 2026): extensión del pago por hitos. Ninguna función
// de v1 ni de v2 cambia; se agregan `add_milestone` y `top_up_milestone`.
//
// v4 (26 de noviembre de 2026): extensión del escrow (acuerdos parciales,
// cancelaciones con doble firma, reembolso en lote, recorte/división/prórroga
// de hitos, bono manual, depósito por lote y rotación segura del árbitro).
// Ninguna función de v1, v2 ni v3 cambia.
//
// v5 (26 de noviembre de 2026): el contrato conoce al programador ANTES de
// pagar. El árbitro lo registra cuando acepta los criterios
// (`assign_freelancer`, `assign_project_freelancer`) y, desde ese momento,
// ningún pago del cliente puede ir a otra dirección (`WrongFreelancer`) ni la
// tarea se puede cancelar como «sin asignar» (`AlreadyAssigned`). Sin
// asignación, todas las funciones anteriores se comportan exactamente igual.
// Se agregan además `extend_deadline`, `top_up_task`, `freelancer_refund` y la
// lectura por lote `get_tasks`.
//
// v6 (27 de noviembre de 2026): acuerdos entre las dos partes sobre una tarea
// ya depositada. Todo cambio que afecta al cliente y al programador exige la
// firma de ambos (y la de quien entra, cuando cambia una de las partes):
// `amend_rules`, `mutual_cancel`, `reassign_freelancer` y `transfer_client`.
// Más `release_partial` (el árbitro paga una parte cuando se cumplen algunos
// criterios), `tip` (propina tras el pago), `bump_ttl` (mantener viva una
// tarea), `get_stats` (totales del contrato) y `deposit_assigned` (depositar
// con el programador ya registrado). Disputas (`open_dispute`,
// `resolve_dispute`, `get_dispute`) y pausa de emergencia de los depósitos
// (`pause`, `unpause`). Sin usar estas funciones, todo se comporta igual que en v5.
//
// v7 (27 de noviembre de 2026): los proyectos por hitos reciben los mismos
// acuerdos que la tarea simple, con la misma regla de firmas de las dos partes:
// `amend_milestone_rules`, `release_milestone_partial`, `mutual_cancel_project`,
// `reassign_project_freelancer` y `transfer_project_client`. Disputas por hito
// (`open_milestone_dispute`, `resolve_milestone_dispute`) y retiro de una
// disputa por quien la abrió (`cancel_dispute`, `cancel_milestone_dispute`).
// Operaciones por lote: `release_batch`, `refund_batch` y `get_projects`.
//
// v8 (27 de noviembre de 2026): pago por tiempo. El cliente deposita para un
// programador y una duración, y el dinero se libera de forma lineal segundo a
// segundo (como un sueldo o un retainer): `deposit_stream`, `withdraw_stream`
// y `cancel_stream`. Garantía del programador: el programador registrado
// deposita una garantía que recupera si la tarea se paga (`post_bond`,
// `reclaim_bond`) y que pasa al cliente si la tarea termina reembolsada y el
// árbitro lo decide (`slash_bond`).
//
// v9 (27 de noviembre de 2026): `top_up_stream` (agregar dinero a un pago por
// tiempo sin cambiar su tarifa), `reassign_stream` (otro programador sigue el
// pago y el anterior cobra lo ganado), `slash_bond_partial` (repartir la
// garantía) y `release_with_fee` (pago con comisión de plataforma, máximo 10%).
//
// v10 (27 de noviembre de 2026): `top_up_bond` (el programador aumenta su
// garantía), `release_milestone_with_fee` (pago de un hito con comisión de
// plataforma) y `transfer_stream_client` (un pago por tiempo cambia de cliente
// con la firma de los tres).
//
// v11 (27 de noviembre de 2026): los pagos por tiempo reciben los acuerdos de
// la tarea simple (prorrogar, recortar, repartir, propina y disputa), y hay
// operaciones por lote para pagos por tiempo y para hitos, más la propina de
// un proyecto. En cada acuerdo sobre un pago por tiempo, el programador cobra
// primero lo ya ganado: ningún cambio le quita lo liberado.
//
// v12 (27 de noviembre de 2026): aprobación manual parcial del cliente (tarea
// y hito), garantía del programador para proyectos por hitos y retiro de
// varios pagos por tiempo a la vez.
//
// v13 (27 de noviembre de 2026): aprobación manual con comisión de plataforma
// (tarea y hito), patrocinio de terceros (un tercero aporta a una tarea, un
// hito o un pago por tiempo; el reembolso sigue siendo del cliente), aumento de
// la garantía de proyecto, prórroga de todos los hitos de un proyecto, retiro
// de un pago por tiempo a otra dirección, reembolso por lote de proyectos
// vencidos y reparto acordado de todo lo pendiente de un proyecto.
//
// v14 (27 de noviembre de 2026): nuevos mecanismos de escrow en USDC: concursos
// multi-ganador (`Bounty`), acuerdos por ciclos/retainer (`Retainer`),
// financiamiento colectivo con reembolso proporcional (`CrowdfundTask`), tareas
// en equipo con reparto automático en bps (`TeamTask`), pagos por tiempo con
// cliff (`StreamCliff`) y conversión entre acuerdos activos.
// Diseño: docs/hitos/diseno.md.

use soroban_sdk::{
    contract, contracterror, contractevent, contractimpl, contracttype, token, Address, BytesN,
    Env, String, Vec,
};

// ---------------------------------------------------------------------------
// TTL (tiempo de vida de las entradas en el ledger)
// ---------------------------------------------------------------------------
// Un ledger se cierra cada ~5 s, así que un día son ~17_280 ledgers.
// Cada vez que escribimos, si a la entrada le quedan menos de 7 días de vida,
// la extendemos a 30 días. Así ni la configuración (instancia) ni las tareas
// (persistentes) se archivan durante la vida útil de una tarea.
const DAY_IN_LEDGERS: u32 = 17_280;
const TTL_THRESHOLD: u32 = 7 * DAY_IN_LEDGERS;
const TTL_EXTEND_TO: u32 = 30 * DAY_IN_LEDGERS;

// ---------------------------------------------------------------------------
// Límites del pago por hitos
// ---------------------------------------------------------------------------
// Un proyecto tiene de 2 a 10 hitos (con 1 hito basta la tarea simple).
// Cada hito vence a más tardar 28 días después del depósito: así queda por
// debajo de los 30 días de TTL que se renuevan en cada escritura.
const MIN_MILESTONES: u32 = 2;
const MAX_MILESTONES: u32 = 10;
const MAX_MILESTONE_DEADLINE_SECS: u64 = 28 * 24 * 60 * 60;

// v5: una lectura por lote devuelve como máximo 20 tareas, para que la
// simulación no pase el límite de lecturas de una transacción de Soroban.
const MAX_BATCH_READ: u32 = 20;

// v6: una disputa abierta congela el reembolso por plazo, pero solo hasta 14
// días después del plazo. Si el árbitro no la resuelve en ese tiempo, el
// cliente vuelve a poder recuperar su dinero: nadie lo puede retener para siempre.
const DISPUTE_GRACE_SECS: u64 = 14 * 24 * 60 * 60;

// v9: comisión máxima de plataforma en `release_with_fee`: 1000 puntos base = 10%.
const MAX_FEE_BPS: u32 = 1000;

// ---------------------------------------------------------------------------
// Tipos guardados en el contrato
// ---------------------------------------------------------------------------

// Estado de una tarea. Solo existe un camino de ida:
// Funded -> Released (árbitro o cliente) o Funded -> Refunded (tras el plazo).
// Una tarea que ya no está en Funded no puede volver a mover dinero.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TaskStatus {
    Funded,
    Released,
    Refunded,
}

// Una tarea depositada. A diferencia del `Deal` de la base:
// - se identifica por un `task_id` de texto que genera el backend;
// - el programador (`freelancer`) no se conoce al depositar: se fija al liberar
//   o, desde v5, cuando el árbitro lo registra con `assign_freelancer`;
// - guarda el `rules_hash` (SHA-256 de los criterios acordados) y el plazo.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Task {
    pub task_id: String,
    pub client: Address,
    pub freelancer: Option<Address>,
    pub amount: i128,
    pub deadline: u64,
    pub rules_hash: BytesN<32>,
    pub status: TaskStatus,
}

// Estado de un hito: el mismo camino de ida que una tarea.
// Funded -> Released (árbitro o cliente) o Funded -> Refunded (tras SU plazo).
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MilestoneStatus {
    Funded,
    Released,
    Refunded,
}

// Un hito de un proyecto: su parte del dinero, su plazo y el hash de SUS
// criterios. Cada hito se paga o se reembolsa por separado.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Milestone {
    pub amount: i128,
    pub deadline: u64,
    pub rules_hash: BytesN<32>,
    pub status: MilestoneStatus,
}

// Un proyecto por hitos. El cliente deposita la suma de todos los hitos de
// una vez. El programador no se conoce al depositar: queda fijo en el PRIMER
// pago, y desde ahí ningún hito le puede pagar a otra dirección.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Project {
    pub task_id: String,
    pub client: Address,
    pub freelancer: Option<Address>,
    pub milestones: Vec<Milestone>,
}

// Configuración del contrato, devuelta por `get_config`.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Config {
    pub arbiter: Address,
    pub token: Address,
}

// v6: totales del contrato, devueltos por `get_stats`. `held` es lo que el
// contrato debe tener en USDC: lo que entró menos lo que salió.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Stats {
    pub deposited: i128,
    pub paid_out: i128,
    pub held: i128,
}

// v8: estado de un pago por tiempo.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum StreamStatus {
    Active,
    Canceled,
}

// v8: un pago por tiempo. `amount` se libera de forma lineal entre `start` y
// `end`; `withdrawn` es lo que el programador ya retiró. Al cancelar, `amount`
// queda en lo que el programador ganó hasta ese momento.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Stream {
    pub stream_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
    pub withdrawn: i128,
    pub start: u64,
    pub end: u64,
    pub status: StreamStatus,
}

// v8: garantía que el programador deposita sobre una tarea.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Bond {
    pub task_id: String,
    pub freelancer: Address,
    pub amount: i128,
}

// v14: concurso multi-ganador con fondo abierto. El árbitro premia a distintos
// ganadores mientras quede saldo y antes del plazo; lo sobrante vuelve al cliente.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Bounty {
    pub bounty_id: String,
    pub client: Address,
    pub remaining: i128,
    pub deadline: u64,
    pub rules_hash: BytesN<32>,
}

// v14: acuerdo recurrente por ciclos/sprints (`Retainer`). En cada ciclo se
// puede liberar `period_amount` (árbitro) o reembolsar si venció sin entrega.
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Retainer {
    pub retainer_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub period_amount: i128,
    pub period_secs: u64,
    pub start: u64,
    pub current_cycle: u32,
    pub total_cycles: u32,
}

// Llaves de almacenamiento.
// `Arbiter` y `Token` viven en el almacenamiento de instancia (configuración).
// `Task(task_id)` vive en almacenamiento persistente, una entrada por tarea.
// `Project(task_id)` también: una entrada por proyecto, con todos sus hitos.
// Un mismo `task_id` no puede ser a la vez tarea y proyecto.
#[contracttype]
#[derive(Clone)]
pub enum DataKey {
    Arbiter,
    Token,
    Task(String),
    Project(String),
    // v6: total que entró al contrato y total que salió (instancia).
    TotalIn,
    TotalOut,
    // v6: quién abrió la disputa de una tarea (persistente).
    Dispute(String),
    // v7: quién abrió la disputa de un hito (persistente).
    MilestoneDispute(String, u32),
    // v6: pausa de emergencia de los depósitos (instancia).
    Paused,
    // v8: un pago por tiempo (persistente).
    Stream(String),
    // v8: garantía del programador de una tarea (persistente).
    Bond(String),
    // v11: quién abrió la disputa de un pago por tiempo (persistente).
    StreamDispute(String),
    // v12: garantía del programador sobre un proyecto por hitos (persistente).
    ProjectBond(String),
    // v14: concurso multi-ganador (persistente).
    Bounty(String),
    // v14: acuerdo recurrente por ciclos (persistente).
    Retainer(String),
}

// ---------------------------------------------------------------------------
// Errores
// ---------------------------------------------------------------------------
// Los números son estables: el backend y la CLI los muestran como `Error(Contract, #N)`.
#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    NotInitialized = 1,
    AlreadyInitialized = 2,
    InvalidAmount = 3,
    AlreadyExists = 4,
    NotFound = 5,
    NotFunded = 6,
    DeadlineNotReached = 7,
    InvalidDeadline = 8,
    DeadlinePassed = 9,
    // v2, pago por hitos (los anteriores nunca se renumeran):
    // listas de distinto largo, menos de 2 o más de 10 hitos, o plazos que bajan.
    InvalidMilestones = 10,
    // El índice no corresponde a ningún hito del proyecto.
    MilestoneNotFound = 11,
    // Un hito intenta pagarle a una dirección distinta del programador ya fijado.
    WrongFreelancer = 12,
    // v4: el proyecto ya tiene un programador fijado (no se puede cancelar como no asignado).
    AlreadyAssigned = 13,
    // v4: la dirección propuesta para rotar el árbitro es igual al árbitro actual.
    SameArbiter = 14,
    // v5: la lectura por lote pide 0 tareas o más de 20.
    TooManyItems = 15,
    // v6: el valor nuevo es igual al actual (misma dirección o mismo rules_hash).
    NoChange = 16,
    // v6: quien abre la disputa no es el cliente ni el programador registrado.
    NotParty = 17,
    // v6: ya hay una disputa abierta (o congela el reembolso por plazo).
    DisputeOpen = 18,
    // v6: no hay disputa abierta que resolver.
    NoDispute = 19,
    // v6: los depósitos están en pausa de emergencia.
    Paused = 20,
    // v7: las listas de un lote no tienen el mismo largo.
    LengthMismatch = 21,
    // v8: todavía no se ha liberado nada nuevo que retirar.
    NothingToWithdraw = 22,
}

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------
// Se usa `#[contractevent]`, la forma recomendada en soroban-sdk 25
// (`env.events().publish(...)` está marcada como deprecada).
// El primer tópico es el nombre de la acción y el segundo el `task_id`, para
// que cualquiera pueda filtrar en el explorador todos los eventos de una tarea.

// Se inicializó el contrato con su árbitro y su token.
#[contractevent(topics = ["initialize"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InitializeEvent {
    pub arbiter: Address,
    pub token: Address,
}

// El cliente depositó el monto de una tarea y quedó guardado el `rules_hash`.
#[contractevent(topics = ["deposit"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DepositEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub amount: i128,
    pub deadline: u64,
    pub rules_hash: BytesN<32>,
}

// El árbitro liberó el pago. Publica `code_hash` y `verdict_hash` para que el
// pago sea auditable: cualquiera puede recalcular ambos hashes y compararlos.
#[contractevent(topics = ["release"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReleaseEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub amount: i128,
    pub code_hash: BytesN<32>,
    pub verdict_hash: BytesN<32>,
}

// El cliente aprobó manualmente (por ejemplo, tras un rechazo de la IA).
#[contractevent(topics = ["client_release"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClientReleaseEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
}

// Venció el plazo y el dinero volvió al cliente.
#[contractevent(topics = ["timeout_refund"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TimeoutRefundEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub amount: i128,
}

// El cliente depositó un proyecto por hitos: el total y cuántos hitos tiene.
#[contractevent(topics = ["deposit_milestones"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DepositMilestonesEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub total: i128,
    pub milestones: u32,
}

// El árbitro pagó un hito. Igual que `release`, publica `code_hash` y
// `verdict_hash` para que el pago de cada hito sea auditable.
#[contractevent(topics = ["release_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MilestoneReleaseEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub freelancer: Address,
    pub amount: i128,
    pub code_hash: BytesN<32>,
    pub verdict_hash: BytesN<32>,
}

// El cliente aprobó manualmente un hito.
#[contractevent(topics = ["client_release_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MilestoneClientReleaseEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
}

// Venció el plazo de un hito y su dinero volvió al cliente.
#[contractevent(topics = ["timeout_refund_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MilestoneRefundEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub client: Address,
    pub amount: i128,
}

// v3: el cliente agregó un hito nuevo a un proyecto existente.
#[contractevent(topics = ["add_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AddMilestoneEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub amount: i128,
    pub deadline: u64,
}

// v3: el cliente aumentó el monto de un hito existente que sigue en Funded.
#[contractevent(topics = ["top_up_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopUpMilestoneEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub amount: i128,
    pub new_amount: i128,
}

// v4: cliente y programador acordaron un reparto parcial de una tarea simple.
#[contractevent(topics = ["mutual_split_task"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MutualSplitTaskEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub freelancer_amount: i128,
    pub refund_amount: i128,
}

// v4: cliente y programador acordaron un reparto parcial de un hito.
#[contractevent(topics = ["mutual_split_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MutualSplitMilestoneEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub client: Address,
    pub freelancer: Address,
    pub freelancer_amount: i128,
    pub refund_amount: i128,
}

// v4: cliente y árbitro cancelaron una tarea simple sin asignar antes del plazo.
#[contractevent(topics = ["cancel_unassigned_task"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CancelTaskEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub amount: i128,
}

// v4: cliente y árbitro cancelaron un proyecto sin programador fijado y devolvieron lo pendiente.
#[contractevent(topics = ["cancel_unassigned_project"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CancelProjectEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub refunded_milestones: u32,
    pub total_refund: i128,
}

// v4: reembolso en lote de todos los hitos vencidos de un proyecto en una sola transferencia.
#[contractevent(topics = ["refund_all_expired"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RefundExpiredBatchEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub count: u32,
    pub total_refund: i128,
}

// v4: recorte parcial del monto de un hito activo con devolución de la diferencia al cliente.
#[contractevent(topics = ["reduce_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReduceMilestoneEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub reduced: i128,
    pub new_amount: i128,
}

// v4: el cliente aprobó manualmente una tarea y sumó un bono extra en la misma transacción.
#[contractevent(topics = ["client_release_bonus"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClientReleaseBonusEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
    pub bonus: i128,
}

// v4: el cliente depositó un lote de tareas independientes en una sola transferencia.
#[contractevent(topics = ["batch_deposit"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BatchDepositEvent {
    #[topic]
    pub client: Address,
    pub count: u32,
    pub total: i128,
}

// v4: un hito Funded se dividió en dos hitos cuya suma conserva el monto original.
#[contractevent(topics = ["split_milestone"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SplitMilestoneEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub first_amount: i128,
    pub second_amount: i128,
    pub first_deadline: u64,
    pub second_deadline: u64,
}

// v4: el cliente amplió el plazo de un hito Funded sin rebasar 28 días ni el hito siguiente.
#[contractevent(topics = ["extend_milestone_deadline"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExtendMilestoneDeadlineEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub old_deadline: u64,
    pub new_deadline: u64,
}

// v4: rotación atómica del árbitro confirmada por el árbitro actual y el nuevo.
#[contractevent(topics = ["rotate_arbiter"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RotateArbiterEvent {
    pub old_arbiter: Address,
    pub new_arbiter: Address,
}

// ---------------------------------------------------------------------------
// Contrato
// ---------------------------------------------------------------------------
// v5: el árbitro registró al programador que aceptó los criterios de una tarea.
#[contractevent(topics = ["assign_freelancer"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssignFreelancerEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
}

// v5: el árbitro registró al programador de un proyecto por hitos.
#[contractevent(topics = ["assign_project_freelancer"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssignProjectFreelancerEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
}

// v5: el cliente le dio más tiempo al programador.
#[contractevent(topics = ["extend_deadline"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExtendDeadlineEvent {
    #[topic]
    pub task_id: String,
    pub old_deadline: u64,
    pub new_deadline: u64,
}

// v5: el cliente agregó dinero a una tarea depositada.
#[contractevent(topics = ["top_up_task"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopUpTaskEvent {
    #[topic]
    pub task_id: String,
    pub added: i128,
    pub new_amount: i128,
}

// v5: el programador asignado renunció y el depósito volvió al cliente.
#[contractevent(topics = ["freelancer_refund"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FreelancerRefundEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub client: Address,
    pub amount: i128,
}

// v6: cliente y programador cambiaron los criterios acordados.
#[contractevent(topics = ["amend_rules"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AmendRulesEvent {
    #[topic]
    pub task_id: String,
    pub old_rules_hash: BytesN<32>,
    pub new_rules_hash: BytesN<32>,
}

// v6: el árbitro pagó una parte de la tarea; el resto sigue en el contrato.
#[contractevent(topics = ["release_partial"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReleasePartialEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub amount: i128,
    pub remaining: i128,
    pub code_hash: BytesN<32>,
    pub verdict_hash: BytesN<32>,
}

// v6: cliente y programador cancelaron de común acuerdo.
#[contractevent(topics = ["mutual_cancel"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MutualCancelEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
}

// v6: la tarea pasó de un programador a otro con el acuerdo de los tres.
#[contractevent(topics = ["reassign_freelancer"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReassignFreelancerEvent {
    #[topic]
    pub task_id: String,
    pub old_freelancer: Address,
    pub new_freelancer: Address,
}

// v6: la tarea (y su derecho a reembolso) pasó a otro cliente.
#[contractevent(topics = ["transfer_client"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransferClientEvent {
    #[topic]
    pub task_id: String,
    pub old_client: Address,
    pub new_client: Address,
}

// v6: el cliente le dio una propina al programador de una tarea ya pagada.
#[contractevent(topics = ["tip"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TipEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
}

// v6: el cliente o el programador abrió una disputa.
#[contractevent(topics = ["open_dispute"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpenDisputeEvent {
    #[topic]
    pub task_id: String,
    pub opened_by: Address,
}

// v6: el árbitro resolvió la disputa y repartió el depósito.
#[contractevent(topics = ["resolve_dispute"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolveDisputeEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub freelancer_amount: i128,
    pub client: Address,
    pub refund_amount: i128,
}

// v6: el árbitro pausó o reanudó los depósitos.
#[contractevent(topics = ["pause"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PauseEvent {
    pub paused: bool,
}

// v7: cliente y programador cambiaron los criterios de un hito.
#[contractevent(topics = ["amend_milestone_rules"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AmendMilestoneRulesEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub old_rules_hash: BytesN<32>,
    pub new_rules_hash: BytesN<32>,
}

// v7: el árbitro pagó una parte de un hito; el resto sigue depositado.
#[contractevent(topics = ["release_milestone_partial"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReleaseMilestonePartialEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub freelancer: Address,
    pub amount: i128,
    pub remaining: i128,
    pub code_hash: BytesN<32>,
    pub verdict_hash: BytesN<32>,
}

// v7: cliente y programador cancelaron un proyecto de común acuerdo.
#[contractevent(topics = ["mutual_cancel_project"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MutualCancelProjectEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub count: u32,
    pub total_refund: i128,
}

// v7: el proyecto pasó de un programador a otro con el acuerdo de los tres.
#[contractevent(topics = ["reassign_project_freelancer"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReassignProjectFreelancerEvent {
    #[topic]
    pub task_id: String,
    pub old_freelancer: Address,
    pub new_freelancer: Address,
}

// v7: el proyecto (y sus reembolsos) pasó a otro cliente.
#[contractevent(topics = ["transfer_project_client"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransferProjectClientEvent {
    #[topic]
    pub task_id: String,
    pub old_client: Address,
    pub new_client: Address,
}

// v7: el cliente o el programador abrió una disputa sobre un hito.
#[contractevent(topics = ["open_milestone_dispute"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpenMilestoneDisputeEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub opened_by: Address,
}

// v7: el árbitro resolvió la disputa de un hito y repartió su monto.
#[contractevent(topics = ["resolve_milestone_dispute"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolveMilestoneDisputeEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub freelancer: Address,
    pub freelancer_amount: i128,
    pub client: Address,
    pub refund_amount: i128,
}

// v7: quien abrió una disputa la retiró (`index` = None en una tarea simple).
#[contractevent(topics = ["cancel_dispute"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CancelDisputeEvent {
    #[topic]
    pub task_id: String,
    pub index: Option<u32>,
    pub opened_by: Address,
}

// v8: el cliente abrió un pago por tiempo.
#[contractevent(topics = ["deposit_stream"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DepositStreamEvent {
    #[topic]
    pub stream_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
    pub start: u64,
    pub end: u64,
}

// v8: el programador retiró lo que ya se había liberado.
#[contractevent(topics = ["withdraw_stream"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WithdrawStreamEvent {
    #[topic]
    pub stream_id: String,
    pub freelancer: Address,
    pub amount: i128,
    pub withdrawn: i128,
}

// v8: el cliente canceló el pago por tiempo; lo ganado fue al programador y el
// resto volvió al cliente.
#[contractevent(topics = ["cancel_stream"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CancelStreamEvent {
    #[topic]
    pub stream_id: String,
    pub freelancer_amount: i128,
    pub refund_amount: i128,
}

// v8: el programador depositó una garantía sobre la tarea.
#[contractevent(topics = ["post_bond"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PostBondEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub amount: i128,
}

// v8: la garantía volvió al programador.
#[contractevent(topics = ["reclaim_bond"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReclaimBondEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub amount: i128,
}

// v8: la garantía pasó al cliente.
#[contractevent(topics = ["slash_bond"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SlashBondEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub client: Address,
    pub amount: i128,
}

// v9: el cliente agregó dinero a un pago por tiempo (y se recorrió su final).
#[contractevent(topics = ["top_up_stream"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopUpStreamEvent {
    #[topic]
    pub stream_id: String,
    pub added: i128,
    pub new_amount: i128,
    pub new_end: u64,
}

// v9: otro programador sigue el pago por tiempo; el anterior cobró lo ganado.
#[contractevent(topics = ["reassign_stream"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReassignStreamEvent {
    #[topic]
    pub stream_id: String,
    pub old_freelancer: Address,
    pub new_freelancer: Address,
    pub paid_to_old: i128,
    pub remaining: i128,
}

// v9: el árbitro repartió la garantía entre cliente y programador.
#[contractevent(topics = ["slash_bond_partial"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SlashBondPartialEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub client_amount: i128,
    pub freelancer: Address,
    pub freelancer_amount: i128,
}

// v9: pago del árbitro con comisión de plataforma.
#[contractevent(topics = ["release_with_fee"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReleaseWithFeeEvent {
    #[topic]
    pub task_id: String,
    pub freelancer: Address,
    pub freelancer_amount: i128,
    pub fee_to: Address,
    pub fee_amount: i128,
    pub code_hash: BytesN<32>,
    pub verdict_hash: BytesN<32>,
}

// v10: el programador aumentó su garantía.
#[contractevent(topics = ["top_up_bond"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopUpBondEvent {
    #[topic]
    pub task_id: String,
    pub added: i128,
    pub new_amount: i128,
}

// v10: el árbitro pagó un hito con comisión de plataforma.
#[contractevent(topics = ["release_milestone_with_fee"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReleaseMilestoneWithFeeEvent {
    #[topic]
    pub task_id: String,
    pub index: u32,
    pub freelancer: Address,
    pub freelancer_amount: i128,
    pub fee_to: Address,
    pub fee_amount: i128,
    pub code_hash: BytesN<32>,
    pub verdict_hash: BytesN<32>,
}

// v10: un pago por tiempo cambió de cliente.
#[contractevent(topics = ["transfer_stream_client"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TransferStreamClientEvent {
    #[topic]
    pub stream_id: String,
    pub old_client: Address,
    pub new_client: Address,
}

// v11: se cambió el periodo o el monto pendiente de un pago por tiempo (el
// programador cobró `paid` de lo ya ganado y `remaining` sigue fluyendo).
#[contractevent(topics = ["stream_change"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StreamChangeEvent {
    #[topic]
    pub stream_id: String,
    pub action: soroban_sdk::Symbol,
    pub paid: i128,
    pub refunded: i128,
    pub remaining: i128,
    pub end: u64,
}

// v11: propina sobre un pago por tiempo o un proyecto.
#[contractevent(topics = ["tip_v11"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TipV11Event {
    #[topic]
    pub id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
}

// v11: se abrió la disputa de un pago por tiempo.
#[contractevent(topics = ["open_stream_dispute"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpenStreamDisputeEvent {
    #[topic]
    pub stream_id: String,
    pub opened_by: Address,
}

// v12: el cliente aprobó manualmente una parte (tarea o hito; index None en tarea).
#[contractevent(topics = ["client_release_partial"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClientReleasePartialEvent {
    #[topic]
    pub task_id: String,
    pub index: Option<u32>,
    pub freelancer: Address,
    pub amount: i128,
    pub remaining: i128,
}

// v12: movimiento de la garantía de un proyecto.
#[contractevent(topics = ["project_bond"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProjectBondEvent {
    #[topic]
    pub task_id: String,
    pub action: soroban_sdk::Symbol,
    pub to_freelancer: i128,
    pub to_client: i128,
}

// v12: el programador retiró de varios pagos por tiempo a la vez.
#[contractevent(topics = ["withdraw_stream_batch"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WithdrawStreamBatchEvent {
    pub freelancer: Address,
    pub count: u32,
    pub total: i128,
}

// v13: operación genérica de v13 sobre una tarea, hito, proyecto o pago por tiempo.
#[contractevent(topics = ["v13"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct V13Event {
    #[topic]
    pub action: soroban_sdk::Symbol,
    #[topic]
    pub id: String,
    pub who: Address,
    pub amount: i128,
    pub extra: i128,
}

// v14: operación genérica de v14 sobre concursos, retainers, crowdfunding, equipos y conversiones.
#[contractevent(topics = ["v14"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct V14Event {
    #[topic]
    pub action: soroban_sdk::Symbol,
    #[topic]
    pub id: String,
    pub who: Address,
    pub amount: i128,
    pub extra: i128,
}

#[contract]
pub struct CumpleYCobraContract;

#[contractimpl]
impl CumpleYCobraContract {
    // Configura el árbitro (backend) y el token (SAC de USDC). Solo una vez.
    // Se exige la firma del árbitro: nadie puede nombrar como árbitro a una
    // cuenta que no controla.
    pub fn initialize(env: Env, arbiter: Address, token: Address) -> Result<(), Error> {
        if env.storage().instance().has(&DataKey::Arbiter) {
            return Err(Error::AlreadyInitialized);
        }
        arbiter.require_auth();

        env.storage().instance().set(&DataKey::Arbiter, &arbiter);
        env.storage().instance().set(&DataKey::Token, &token);
        Self::extend_instance(&env);

        InitializeEvent { arbiter, token }.publish(&env);
        Ok(())
    }

    // El cliente deposita `amount` (unidades del token, 1 USDC = 10_000_000)
    // para la tarea `task_id`. El plazo es el timestamp del ledger + `deadline_secs`.
    pub fn deposit(
        env: Env,
        client: Address,
        task_id: String,
        amount: i128,
        deadline_secs: u64,
        rules_hash: BytesN<32>,
    ) -> Result<(), Error> {
        // v6: los depósitos nuevos se detienen en pausa de emergencia.
        Self::not_paused(&env)?;
        // Solo el dueño de los fondos puede depositarlos.
        client.require_auth();

        // Validaciones: monto positivo, contrato inicializado, id nuevo.
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        Self::token(&env)?; // el contrato debe estar inicializado
        let key = DataKey::Task(task_id.clone());
        if env.storage().persistent().has(&key)
            || env.storage().persistent().has(&DataKey::Project(task_id.clone()))
        {
            return Err(Error::AlreadyExists);
        }

        // Plazo: un plazo de 0 segundos permitiría reembolsar al instante, así
        // que se rechaza. La suma usa `checked_add`: si desborda, es error.
        if deadline_secs == 0 {
            return Err(Error::InvalidDeadline);
        }
        let deadline = env
            .ledger()
            .timestamp()
            .checked_add(deadline_secs)
            .ok_or(Error::InvalidDeadline)?;

        // Efectos: se guarda la tarea en estado Funded, sin programador todavía.
        let task = Task {
            task_id: task_id.clone(),
            client: client.clone(),
            freelancer: None,
            amount,
            deadline,
            rules_hash: rules_hash.clone(),
            status: TaskStatus::Funded,
        };
        Self::save_task(&env, &key, &task);

        // Interacción: el USDC pasa del cliente al contrato.
        Self::collect(&env, &client, *&amount)?;

        DepositEvent {
            task_id,
            client,
            amount,
            deadline,
            rules_hash,
        }
        .publish(&env);
        Ok(())
    }

    // El árbitro libera el pago al programador tras un veredicto aprobado.
    // `code_hash` y `verdict_hash` quedan en el evento como evidencia.
    pub fn release(
        env: Env,
        task_id: String,
        freelancer: Address,
        code_hash: BytesN<32>,
        verdict_hash: BytesN<32>,
    ) -> Result<(), Error> {
        // Solo el árbitro configurado puede firmar esta llamada.
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        // Solo desde Funded: esto es lo que impide el doble pago.
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // v5: si ya hay programador asignado, solo se le puede pagar a él.
        Self::check_assigned(&task, &freelancer)?;

        // Solo antes del plazo. Si el timestamp del ledger ya alcanzó el plazo,
        // el árbitro ya no puede pagar: tras el plazo la única salida (además de
        // la aprobación manual del cliente) es `timeout_refund`, así que no hay
        // carrera entre un `release` tardío y el reembolso.
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }

        // Efectos antes de la transferencia (checks-effects-interactions).
        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        // Interacción: el contrato paga al programador.
        Self::pay(&env, &freelancer, task.amount)?;

        ReleaseEvent {
            task_id,
            freelancer,
            amount: task.amount,
            code_hash,
            verdict_hash,
        }
        .publish(&env);
        Ok(())
    }

    // Aprobación manual: el cliente de la tarea decide pagar al programador
    // aunque la IA haya rechazado la entrega. Se permite incluso después del
    // plazo: es el propio cliente quien renuncia a su reembolso.
    pub fn client_release(env: Env, task_id: String, freelancer: Address) -> Result<(), Error> {
        // Primero se carga la tarea para saber quién es su cliente.
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // Solo el cliente que depositó puede aprobar manualmente.
        task.client.require_auth();

        // v5: con programador asignado, el cliente no puede pagarle a otra
        // dirección (por ejemplo, una suya) en lugar de al que hizo el trabajo.
        Self::check_assigned(&task, &freelancer)?;

        // Efectos antes de la transferencia.
        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        // Interacción: el contrato paga al programador.
        Self::pay(&env, &freelancer, task.amount)?;

        ClientReleaseEvent {
            task_id,
            client: task.client,
            freelancer,
            amount: task.amount,
        }
        .publish(&env);
        Ok(())
    }

    // Reembolso por plazo vencido. No pide firma: cualquiera puede dispararlo,
    // pero el dinero solo puede ir al cliente que depositó.
    pub fn timeout_refund(env: Env, task_id: String) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // Solo cuando el timestamp del ledger alcanzó el plazo.
        if env.ledger().timestamp() < task.deadline {
            return Err(Error::DeadlineNotReached);
        }

        // v6: con una disputa abierta, el reembolso espera a que el árbitro la
        // resuelva, pero nunca más de 14 días después del plazo.
        if Self::frozen(&env, &DataKey::Dispute(task_id.clone()), task.deadline)? {
            return Err(Error::DisputeOpen);
        }

        // Efectos antes de la transferencia.
        task.status = TaskStatus::Refunded;
        Self::save_task(&env, &key, &task);

        // Interacción: el dinero vuelve al cliente, nunca a quien llama.
        Self::pay(&env, &task.client, task.amount)?;

        TimeoutRefundEvent {
            task_id,
            client: task.client,
            amount: task.amount,
        }
        .publish(&env);
        Ok(())
    }

    // Lectura de una tarea: cliente, programador (si ya se pagó), monto,
    // plazo, `rules_hash` y estado. El backend la usa para sus guardias.
    pub fn get_task(env: Env, task_id: String) -> Result<Task, Error> {
        env.storage()
            .persistent()
            .get(&DataKey::Task(task_id))
            .ok_or(Error::NotFound)
    }

    // Lectura de la configuración, para verificar el despliegue.
    pub fn get_config(env: Env) -> Result<Config, Error> {
        Ok(Config {
            arbiter: Self::arbiter(&env)?,
            token: Self::token(&env)?,
        })
    }

    // -----------------------------------------------------------------------
    // v2: pago por hitos
    // -----------------------------------------------------------------------

    // El cliente deposita un proyecto por hitos. Las tres listas van en el
    // mismo orden: el hito `i` tiene `amounts[i]`, vence `deadlines_secs[i]`
    // segundos después del depósito y sus criterios tienen `rules_hashes[i]`.
    // Se transfiere el TOTAL de una vez: el programador sabe desde el inicio
    // que todo el dinero del proyecto existe.
    pub fn deposit_milestones(
        env: Env,
        client: Address,
        task_id: String,
        amounts: Vec<i128>,
        deadlines_secs: Vec<u64>,
        rules_hashes: Vec<BytesN<32>>,
    ) -> Result<(), Error> {
        // v6: los depósitos nuevos se detienen en pausa de emergencia.
        Self::not_paused(&env)?;
        // Solo el dueño de los fondos puede depositarlos.
        client.require_auth();

        // Las tres listas deben tener el mismo largo, de 2 a 10 hitos.
        let count = amounts.len();
        if count < MIN_MILESTONES
            || count > MAX_MILESTONES
            || deadlines_secs.len() != count
            || rules_hashes.len() != count
        {
            return Err(Error::InvalidMilestones);
        }

        // Contrato inicializado e id nuevo: ni proyecto ni tarea con ese id.
        Self::token(&env)?; // el contrato debe estar inicializado
        let key = DataKey::Project(task_id.clone());
        if env.storage().persistent().has(&key)
            || env.storage().persistent().has(&DataKey::Task(task_id.clone()))
        {
            return Err(Error::AlreadyExists);
        }

        // Cada hito: monto positivo; plazo entre 1 s y 28 días y que no baje
        // respecto al hito anterior (el hito 2 no vence antes que el 1).
        // Las sumas usan `checked_add`: si desbordan, es error.
        let now = env.ledger().timestamp();
        let mut milestones: Vec<Milestone> = Vec::new(&env);
        let mut total: i128 = 0;
        let mut previous_secs: u64 = 0;
        for i in 0..count {
            let amount = amounts.get(i).ok_or(Error::InvalidMilestones)?;
            let secs = deadlines_secs.get(i).ok_or(Error::InvalidMilestones)?;
            let rules_hash = rules_hashes.get(i).ok_or(Error::InvalidMilestones)?;
            if amount <= 0 {
                return Err(Error::InvalidAmount);
            }
            if secs == 0 || secs > MAX_MILESTONE_DEADLINE_SECS {
                return Err(Error::InvalidDeadline);
            }
            if secs < previous_secs {
                return Err(Error::InvalidMilestones);
            }
            previous_secs = secs;
            let deadline = now.checked_add(secs).ok_or(Error::InvalidDeadline)?;
            total = total.checked_add(amount).ok_or(Error::InvalidAmount)?;
            milestones.push_back(Milestone {
                amount,
                deadline,
                rules_hash,
                status: MilestoneStatus::Funded,
            });
        }

        // Efectos: el proyecto queda guardado con todos sus hitos en Funded.
        let project = Project {
            task_id: task_id.clone(),
            client: client.clone(),
            freelancer: None,
            milestones,
        };
        Self::save_project(&env, &key, &project);

        // Interacción: el total pasa del cliente al contrato.
        Self::collect(&env, &client, *&total)?;

        DepositMilestonesEvent {
            task_id,
            client,
            total,
            milestones: count,
        }
        .publish(&env);
        Ok(())
    }

    // El árbitro paga UN hito tras su veredicto aprobado. Mismas reglas que
    // `release`, aplicadas a ese hito: solo desde Funded y antes de su plazo.
    pub fn release_milestone(
        env: Env,
        task_id: String,
        index: u32,
        freelancer: Address,
        code_hash: BytesN<32>,
        verdict_hash: BytesN<32>,
    ) -> Result<(), Error> {
        // Solo el árbitro configurado puede firmar esta llamada.
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        // El hito debe existir y seguir en Funded (esto impide pagarlo dos veces).
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut milestone = Self::funded_milestone(&project, index)?;

        // Solo antes del plazo de ESE hito; después quedan el reembolso del
        // hito o la aprobación manual del cliente.
        if env.ledger().timestamp() >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }

        // El programador queda fijo en el primer pago del proyecto.
        Self::bind_freelancer(&mut project, &freelancer)?;

        // Efectos antes de la transferencia (checks-effects-interactions).
        milestone.status = MilestoneStatus::Released;
        project.milestones.set(index, milestone.clone());
        Self::save_project(&env, &key, &project);

        // Interacción: el contrato paga el monto de ese hito.
        Self::pay(&env, &freelancer, milestone.amount)?;

        MilestoneReleaseEvent {
            task_id,
            index,
            freelancer,
            amount: milestone.amount,
            code_hash,
            verdict_hash,
        }
        .publish(&env);
        Ok(())
    }

    // Aprobación manual de UN hito por el cliente (por ejemplo, tras un rechazo
    // de la IA). Se permite también después del plazo de ese hito: es el propio
    // cliente quien renuncia a su reembolso.
    pub fn client_release_milestone(
        env: Env,
        task_id: String,
        index: u32,
        freelancer: Address,
    ) -> Result<(), Error> {
        // Primero se carga el proyecto para saber quién es su cliente.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Solo el cliente que depositó puede aprobar manualmente.
        project.client.require_auth();

        // El hito debe existir y seguir en Funded; el programador, el de siempre.
        let mut milestone = Self::funded_milestone(&project, index)?;
        Self::bind_freelancer(&mut project, &freelancer)?;

        // Efectos antes de la transferencia.
        milestone.status = MilestoneStatus::Released;
        project.milestones.set(index, milestone.clone());
        Self::save_project(&env, &key, &project);

        // Interacción: el contrato paga el monto de ese hito.
        Self::pay(&env, &freelancer, milestone.amount)?;

        MilestoneClientReleaseEvent {
            task_id,
            index,
            client: project.client,
            freelancer,
            amount: milestone.amount,
        }
        .publish(&env);
        Ok(())
    }

    // Reembolso de UN hito vencido. No pide firma: cualquiera puede dispararlo,
    // pero el dinero solo puede ir al cliente. Los hitos ya pagados no se tocan.
    pub fn timeout_refund_milestone(env: Env, task_id: String, index: u32) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut milestone = Self::funded_milestone(&project, index)?;

        // Solo cuando el timestamp del ledger alcanzó el plazo de ese hito.
        if env.ledger().timestamp() < milestone.deadline {
            return Err(Error::DeadlineNotReached);
        }

        // v7: con una disputa abierta sobre el hito, su reembolso espera
        // (como en la tarea simple, nunca más de 14 días tras el plazo).
        if Self::frozen(
            &env,
            &DataKey::MilestoneDispute(task_id.clone(), index),
            milestone.deadline,
        )? {
            return Err(Error::DisputeOpen);
        }

        // Efectos antes de la transferencia.
        milestone.status = MilestoneStatus::Refunded;
        project.milestones.set(index, milestone.clone());
        Self::save_project(&env, &key, &project);

        // Interacción: el dinero de ese hito vuelve al cliente, nunca a quien llama.
        Self::pay(&env, &project.client, milestone.amount)?;

        MilestoneRefundEvent {
            task_id,
            index,
            client: project.client,
            amount: milestone.amount,
        }
        .publish(&env);
        Ok(())
    }

    // Lectura de un proyecto: cliente, programador (si ya hubo un pago) y sus
    // hitos con monto, plazo, `rules_hash` y estado.
    pub fn get_project(env: Env, task_id: String) -> Result<Project, Error> {
        Self::load_project(&env, &DataKey::Project(task_id))
    }

    // -----------------------------------------------------------------------
    // v3: agregar y aumentar hitos de un proyecto existente
    // -----------------------------------------------------------------------

    // El cliente agrega un hito nuevo al final de un proyecto existente y
    // deposita su monto en el contrato. Mantiene las mismas invariantes que
    // `deposit_milestones`: máximo 10 hitos en total, monto positivo, plazo
    // entre 1 s y 28 días, y vencimiento igual o posterior al del último hito.
    pub fn add_milestone(
        env: Env,
        task_id: String,
        amount: i128,
        deadline_secs: u64,
        rules_hash: BytesN<32>,
    ) -> Result<(), Error> {
        // v6: los depósitos nuevos se detienen en pausa de emergencia.
        Self::not_paused(&env)?;
        // Primero se carga el proyecto para comprobar que existe y saber quién
        // es su cliente.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Solo el cliente del proyecto puede agregar hitos y depositar fondos.
        project.client.require_auth();

        // Contrato inicializado y límite máximo de hitos por proyecto.
        Self::token(&env)?; // el contrato debe estar inicializado
        if project.milestones.len() >= MAX_MILESTONES {
            return Err(Error::InvalidMilestones);
        }

        // Validaciones de monto y plazo: monto positivo, plazo de 1 s a 28 días
        // con `checked_add`, y vencimiento no menor al del último hito.
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if deadline_secs == 0 || deadline_secs > MAX_MILESTONE_DEADLINE_SECS {
            return Err(Error::InvalidDeadline);
        }
        let deadline = env
            .ledger()
            .timestamp()
            .checked_add(deadline_secs)
            .ok_or(Error::InvalidDeadline)?;
        let last = project.milestones.last().ok_or(Error::InvalidMilestones)?;
        if deadline < last.deadline {
            return Err(Error::InvalidMilestones);
        }

        // Efectos antes de la transferencia (checks-effects-interactions):
        // se agrega el hito en Funded y se guarda extendiendo el TTL.
        let index = project.milestones.len();
        project.milestones.push_back(Milestone {
            amount,
            deadline,
            rules_hash,
            status: MilestoneStatus::Funded,
        });
        Self::save_project(&env, &key, &project);

        // Interacción: el USDC del nuevo hito pasa del cliente al contrato.
        Self::collect(&env, &project.client, *&amount)?;

        AddMilestoneEvent {
            task_id,
            index,
            amount,
            deadline,
        }
        .publish(&env);
        Ok(())
    }

    // El cliente aumenta el monto de un hito que todavía está en Funded y
    // antes de su plazo, transfiriendo la diferencia al contrato.
    pub fn top_up_milestone(
        env: Env,
        task_id: String,
        index: u32,
        amount: i128,
    ) -> Result<(), Error> {
        // v6: los depósitos nuevos se detienen en pausa de emergencia.
        Self::not_paused(&env)?;
        // Primero se carga el proyecto para comprobar que existe y saber quién
        // es su cliente.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Solo el cliente del proyecto puede depositar más fondos en el hito.
        project.client.require_auth();

        // El hito debe existir, seguir en Funded y no haber vencido su plazo.
        Self::token(&env)?; // el contrato debe estar inicializado
        let mut milestone = Self::funded_milestone(&project, index)?;
        if env.ledger().timestamp() >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }

        // Monto positivo y suma segura con `checked_add`.
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let new_amount = milestone
            .amount
            .checked_add(amount)
            .ok_or(Error::InvalidAmount)?;

        // Efectos antes de la transferencia (checks-effects-interactions):
        // se actualiza el monto del hito y se guarda extendiendo el TTL.
        milestone.amount = new_amount;
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        // Interacción: el aumento pasa del cliente al contrato.
        Self::collect(&env, &project.client, *&amount)?;

        TopUpMilestoneEvent {
            task_id,
            index,
            amount,
            new_amount,
        }
        .publish(&env);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v4: acuerdos parciales, cancelaciones, lotes y operación del escrow
    // -----------------------------------------------------------------------

    // Reparto parcial acordado para una tarea simple: cliente y programador
    // firman juntos para pagar `freelancer_amount` al programador y devolver el
    // resto al cliente en una sola transacción atómica. Se permite también tras
    // el plazo porque es el propio cliente quien renuncia al reembolso total.
    pub fn mutual_split_task(
        env: Env,
        task_id: String,
        freelancer: Address,
        freelancer_amount: i128,
    ) -> Result<(), Error> {
        // Primero se carga la tarea y se verifica que siga en Funded.
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // Doble autorización obligatoria: ambas partes confirman el reparto.
        task.client.require_auth();
        freelancer.require_auth();

        // v5: el reparto solo puede ser con el programador asignado.
        Self::check_assigned(&task, &freelancer)?;

        // El reparto debe ser estrictamente parcial: mayor a 0 y menor al total.
        if freelancer_amount <= 0 || freelancer_amount >= task.amount {
            return Err(Error::InvalidAmount);
        }
        let refund_amount = task
            .amount
            .checked_sub(freelancer_amount)
            .ok_or(Error::InvalidAmount)?;

        // Efectos antes de transferir (checks-effects-interactions) + TTL.
        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        // Interacciones: pago parcial al programador y devolución del resto al cliente.
        Self::pay(&env, &freelancer, freelancer_amount)?;
        Self::pay(&env, &task.client, refund_amount)?;

        MutualSplitTaskEvent {
            task_id,
            client: task.client,
            freelancer,
            freelancer_amount,
            refund_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Reparto parcial acordado para un hito de un proyecto: cliente y
    // programador firman juntos para liberar `freelancer_amount` al programador
    // y devolver la diferencia al cliente en una sola transacción atómica.
    pub fn mutual_split_milestone(
        env: Env,
        task_id: String,
        index: u32,
        freelancer: Address,
        freelancer_amount: i128,
    ) -> Result<(), Error> {
        // Se carga el proyecto y se verifica que el hito exista y siga en Funded.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut milestone = Self::funded_milestone(&project, index)?;

        // Doble autorización obligatoria: cliente y programador aprueban el reparto.
        project.client.require_auth();
        freelancer.require_auth();

        // Misma regla de identidad del proyecto: si ya hay programador fijado,
        // no se puede repartir a una dirección distinta.
        Self::bind_freelancer(&mut project, &freelancer)?;

        // Reparto estrictamente parcial sobre el monto del hito.
        if freelancer_amount <= 0 || freelancer_amount >= milestone.amount {
            return Err(Error::InvalidAmount);
        }
        let refund_amount = milestone
            .amount
            .checked_sub(freelancer_amount)
            .ok_or(Error::InvalidAmount)?;

        // Efectos antes de transferir (checks-effects-interactions) + TTL.
        milestone.status = MilestoneStatus::Released;
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        // Interacciones: transferencia atómica al programador y reembolso al cliente.
        Self::pay(&env, &freelancer, freelancer_amount)?;
        Self::pay(&env, &project.client, refund_amount)?;

        MutualSplitMilestoneEvent {
            task_id,
            index,
            client: project.client,
            freelancer,
            freelancer_amount,
            refund_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Cancelación antes del plazo de una tarea simple que ningún programador ha
    // aceptado: exige doble firma (cliente + árbitro) para que el cliente no
    // pueda retirar los fondos a espaldas de un programador que ya trabaja.
    pub fn cancel_unassigned_task(env: Env, task_id: String) -> Result<(), Error> {
        // La tarea debe existir y seguir en Funded.
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        let arbiter = Self::arbiter(&env)?;

        // Doble firma: cliente solicita cancelar y el árbitro confirma que nadie aceptó.
        task.client.require_auth();
        arbiter.require_auth();

        // v5: si el contrato ya registró a un programador, la tarea no está
        // «sin asignar»: el cliente tiene que pagar, repartir o esperar el plazo.
        if task.freelancer.is_some() {
            return Err(Error::AlreadyAssigned);
        }

        // Solo antes del plazo; después del plazo ya existe `timeout_refund`.
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }

        // Efectos antes de transferir (checks-effects-interactions) + TTL.
        task.status = TaskStatus::Refunded;
        Self::save_task(&env, &key, &task);

        // Interacción: el depósito vuelve íntegro al cliente.
        Self::pay(&env, &task.client, task.amount)?;

        CancelTaskEvent {
            task_id,
            client: task.client,
            amount: task.amount,
        }
        .publish(&env);
        Ok(())
    }

    // Cancelación antes del plazo de un proyecto por hitos que aún no tiene
    // programador fijado: exige doble firma (cliente + árbitro), marca todos
    // los hitos en Funded como Refunded y devuelve el total en una transferencia.
    pub fn cancel_unassigned_project(env: Env, task_id: String) -> Result<(), Error> {
        // Se carga el proyecto y el árbitro configurado.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let arbiter = Self::arbiter(&env)?;

        // Doble firma: cliente y árbitro aprueban cancelar el proyecto completo.
        project.client.require_auth();
        arbiter.require_auth();

        // Si ya hubo un pago (programador fijado), no se puede cancelar como no asignado.
        if project.freelancer.is_some() {
            return Err(Error::AlreadyAssigned);
        }

        // Recorre todos los hitos y acumula lo que sigue en Funded con `checked_add`.
        let mut refunded_milestones: u32 = 0;
        let mut total_refund: i128 = 0;
        for i in 0..project.milestones.len() {
            let mut m = project.milestones.get(i).ok_or(Error::MilestoneNotFound)?;
            if m.status == MilestoneStatus::Funded {
                total_refund = total_refund
                    .checked_add(m.amount)
                    .ok_or(Error::InvalidAmount)?;
                m.status = MilestoneStatus::Refunded;
                project.milestones.set(i, m);
                refunded_milestones += 1;
            }
        }
        if refunded_milestones == 0 {
            return Err(Error::NotFunded);
        }

        // Efectos antes de transferir (checks-effects-interactions) + TTL.
        Self::save_project(&env, &key, &project);

        // Interacción: una sola transferencia al cliente por todos los hitos cancelados.
        Self::pay(&env, &project.client, total_refund)?;

        CancelProjectEvent {
            task_id,
            client: project.client,
            refunded_milestones,
            total_refund,
        }
        .publish(&env);
        Ok(())
    }

    // Reembolso en lote de todos los hitos vencidos de un proyecto. Sin firma:
    // cualquiera puede dispararlo (como `timeout_refund_milestone`), los hitos
    // pagados o vigentes no se tocan y el dinero siempre vuelve al cliente en
    // una sola transferencia. Devuelve cuántos hitos se reembolsaron.
    pub fn refund_all_expired_milestones(env: Env, task_id: String) -> Result<u32, Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let now = env.ledger().timestamp();

        // Clasifica los hitos: cuenta cuántos siguen en Funded y marca los vencidos.
        let mut funded_seen: u32 = 0;
        let mut count: u32 = 0;
        let mut total_refund: i128 = 0;
        for i in 0..project.milestones.len() {
            let mut m = project.milestones.get(i).ok_or(Error::MilestoneNotFound)?;
            if m.status == MilestoneStatus::Funded {
                funded_seen += 1;
                // v7: un hito con disputa abierta todavía no se reembolsa.
                let disputed = Self::frozen(
                    &env,
                    &DataKey::MilestoneDispute(task_id.clone(), i),
                    m.deadline,
                )?;
                if now >= m.deadline && !disputed {
                    total_refund = total_refund
                        .checked_add(m.amount)
                        .ok_or(Error::InvalidAmount)?;
                    m.status = MilestoneStatus::Refunded;
                    project.milestones.set(i, m);
                    count += 1;
                }
            }
        }
        if funded_seen == 0 {
            return Err(Error::NotFunded);
        }
        if count == 0 {
            return Err(Error::DeadlineNotReached);
        }

        // Efectos antes de transferir (checks-effects-interactions) + TTL.
        Self::save_project(&env, &key, &project);

        // Interacción: una sola transferencia de USDC al cliente.
        Self::pay(&env, &project.client, total_refund)?;

        RefundExpiredBatchEvent {
            task_id,
            client: project.client,
            count,
            total_refund,
        }
        .publish(&env);
        Ok(count)
    }

    // Recorta el monto de un hito activo (Funded y antes de su plazo), dejando
    // un saldo positivo en el hito y devolviendo `reduce_amount` al cliente.
    // Exige doble firma: cliente + programador (si ya está fijado) o cliente +
    // árbitro (si aún no hay programador fijado), para impedir recortes unilaterales.
    pub fn reduce_milestone(
        env: Env,
        task_id: String,
        index: u32,
        reduce_amount: i128,
    ) -> Result<(), Error> {
        // Se carga el proyecto y se verifica que el hito exista y siga en Funded.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut milestone = Self::funded_milestone(&project, index)?;

        // Doble autorización: el cliente nunca puede recortar el monto solo.
        project.client.require_auth();
        match &project.freelancer {
            Some(fl) => fl.require_auth(),
            None => Self::arbiter(&env)?.require_auth(),
        }

        // Solo antes del plazo del hito y con recorte estrictamente parcial.
        if env.ledger().timestamp() >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }
        if reduce_amount <= 0 || reduce_amount >= milestone.amount {
            return Err(Error::InvalidAmount);
        }
        let new_amount = milestone
            .amount
            .checked_sub(reduce_amount)
            .ok_or(Error::InvalidAmount)?;

        // Efectos antes de transferir (checks-effects-interactions) + TTL.
        milestone.amount = new_amount;
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        // Interacción: la diferencia recortada vuelve al cliente.
        Self::pay(&env, &project.client, reduce_amount)?;

        ReduceMilestoneEvent {
            task_id,
            index,
            reduced: reduce_amount,
            new_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Aprobación manual con bono extra: el cliente libera el depósito de una
    // tarea en Funded y transfiere un bono adicional (`bonus > 0`) desde su
    // wallet al programador en una sola transacción atómica. Permitida también
    // tras el plazo, igual que `client_release`.
    pub fn client_release_with_bonus(
        env: Env,
        task_id: String,
        freelancer: Address,
        bonus: i128,
    ) -> Result<(), Error> {
        // Primero se carga la tarea y se exige que siga en Funded.
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // Solo el cliente de la tarea puede aprobar y pagar el bono.
        task.client.require_auth();

        // v5: el bono también va solo al programador asignado.
        Self::check_assigned(&task, &freelancer)?;

        // Bono estrictamente positivo y sin desborde al sumarse al monto.
        if bonus <= 0 {
            return Err(Error::InvalidAmount);
        }
        let _total_paid = task.amount.checked_add(bonus).ok_or(Error::InvalidAmount)?;
        let token_addr = Self::token(&env)?;

        // Efectos antes de las transferencias (checks-effects-interactions) + TTL.
        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        // Interacciones atómicas: el contrato libera `task.amount` y el cliente envía `bonus`.
        let token_client = token::Client::new(&env, &token_addr);
        Self::pay(&env, &freelancer, task.amount)?;
        token_client.transfer(&task.client, &freelancer, &bonus);

        ClientReleaseBonusEvent {
            task_id,
            client: task.client,
            freelancer,
            amount: task.amount,
            bonus,
        }
        .publish(&env);
        Ok(())
    }

    // Depósito por lote de 2 a 10 tareas simples independientes en una sola
    // transacción y una sola transferencia de USDC del cliente al contrato.
    // Valida unicidad de cada `task_id` contra tareas/proyectos existentes y
    // también dentro del mismo lote. Devuelve el monto total depositado.
    pub fn batch_deposit(
        env: Env,
        client: Address,
        task_ids: Vec<String>,
        amounts: Vec<i128>,
        deadlines_secs: Vec<u64>,
        rules_hashes: Vec<BytesN<32>>,
    ) -> Result<i128, Error> {
        // v6: los depósitos nuevos se detienen en pausa de emergencia.
        Self::not_paused(&env)?;
        // Solo el dueño de los fondos puede depositarlos.
        client.require_auth();

        // Entre 2 y 10 tareas y las cuatro listas con el mismo largo.
        let count = task_ids.len();
        if count < MIN_MILESTONES
            || count > MAX_MILESTONES
            || amounts.len() != count
            || deadlines_secs.len() != count
            || rules_hashes.len() != count
        {
            return Err(Error::InvalidMilestones);
        }

        Self::token(&env)?; // el contrato debe estar inicializado
        let now = env.ledger().timestamp();
        let mut total: i128 = 0;

        // Primera pasada: valida todas las entradas y unicidad antes de escribir.
        for i in 0..count {
            let task_id = task_ids.get(i).ok_or(Error::InvalidMilestones)?;
            let amount = amounts.get(i).ok_or(Error::InvalidMilestones)?;
            let secs = deadlines_secs.get(i).ok_or(Error::InvalidMilestones)?;
            if amount <= 0 {
                return Err(Error::InvalidAmount);
            }
            if secs == 0 {
                return Err(Error::InvalidDeadline);
            }
            now.checked_add(secs).ok_or(Error::InvalidDeadline)?;
            total = total.checked_add(amount).ok_or(Error::InvalidAmount)?;
            if env.storage().persistent().has(&DataKey::Task(task_id.clone()))
                || env
                    .storage()
                    .persistent()
                    .has(&DataKey::Project(task_id.clone()))
            {
                return Err(Error::AlreadyExists);
            }
            for j in 0..i {
                if task_ids.get(j).ok_or(Error::InvalidMilestones)? == task_id {
                    return Err(Error::AlreadyExists);
                }
            }
        }

        // Segunda pasada (efectos): guarda cada tarea en Funded extendiendo su TTL.
        for i in 0..count {
            let task_id = task_ids.get(i).ok_or(Error::InvalidMilestones)?;
            let amount = amounts.get(i).ok_or(Error::InvalidMilestones)?;
            let secs = deadlines_secs.get(i).ok_or(Error::InvalidMilestones)?;
            let rules_hash = rules_hashes.get(i).ok_or(Error::InvalidMilestones)?;
            let deadline = now.checked_add(secs).ok_or(Error::InvalidDeadline)?;
            let key = DataKey::Task(task_id.clone());
            let task = Task {
                task_id: task_id.clone(),
                client: client.clone(),
                freelancer: None,
                amount,
                deadline,
                rules_hash: rules_hash.clone(),
                status: TaskStatus::Funded,
            };
            Self::save_task(&env, &key, &task);
            DepositEvent {
                task_id,
                client: client.clone(),
                amount,
                deadline,
                rules_hash,
            }
            .publish(&env);
        }

        // Interacción: una sola transferencia por el total del lote al contrato.
        Self::collect(&env, &client, *&total)?;

        BatchDepositEvent {
            client,
            count,
            total,
        }
        .publish(&env);
        Ok(total)
    }

    // Divide un hito en Funded (y antes de su plazo) en dos hitos consecutivos
    // cuya suma de montos es exactamente igual al monto original, sin mover
    // USDC fuera del contrato. Si ya hay programador fijado, exige también su
    // firma para que el cliente no cambie criterios unilateralmente.
    pub fn split_milestone(
        env: Env,
        task_id: String,
        index: u32,
        first_amount: i128,
        first_deadline_secs: u64,
        first_rules_hash: BytesN<32>,
        second_rules_hash: BytesN<32>,
    ) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Cliente firma siempre; si el proyecto ya tiene programador fijado, también firma.
        project.client.require_auth();
        if let Some(fl) = &project.freelancer {
            fl.require_auth();
        }

        // Respetar el tope máximo de 10 hitos por proyecto.
        if project.milestones.len() >= MAX_MILESTONES {
            return Err(Error::InvalidMilestones);
        }

        let milestone = Self::funded_milestone(&project, index)?;
        let now = env.ledger().timestamp();
        if now >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }

        // División estrictamente parcial del monto del hito.
        if first_amount <= 0 || first_amount >= milestone.amount {
            return Err(Error::InvalidAmount);
        }
        let second_amount = milestone
            .amount
            .checked_sub(first_amount)
            .ok_or(Error::InvalidAmount)?;

        // Plazo del primer sub-hito: entre 1 s y 28 días, sin romper el orden
        // con el hito anterior ni superar el plazo del segundo sub-hito.
        if first_deadline_secs == 0 || first_deadline_secs > MAX_MILESTONE_DEADLINE_SECS {
            return Err(Error::InvalidDeadline);
        }
        let first_deadline = now
            .checked_add(first_deadline_secs)
            .ok_or(Error::InvalidDeadline)?;
        let second_deadline = milestone.deadline;
        if first_deadline > second_deadline {
            return Err(Error::InvalidMilestones);
        }
        if index > 0 {
            let prev = project
                .milestones
                .get(index - 1)
                .ok_or(Error::MilestoneNotFound)?;
            if first_deadline < prev.deadline {
                return Err(Error::InvalidMilestones);
            }
        }

        // Efectos: reemplaza `index` con el primer sub-hito e inserta el segundo en `index + 1`.
        project.milestones.set(
            index,
            Milestone {
                amount: first_amount,
                deadline: first_deadline,
                rules_hash: first_rules_hash,
                status: MilestoneStatus::Funded,
            },
        );
        project.milestones.insert(
            index + 1,
            Milestone {
                amount: second_amount,
                deadline: second_deadline,
                rules_hash: second_rules_hash,
                status: MilestoneStatus::Funded,
            },
        );
        Self::save_project(&env, &key, &project);

        SplitMilestoneEvent {
            task_id,
            index,
            first_amount,
            second_amount,
            first_deadline,
            second_deadline,
        }
        .publish(&env);
        Ok(())
    }

    // Amplía el plazo de un hito en Funded hacia adelante (`extra_secs > 0`).
    // Solo el cliente firma (nunca perjudica al programador), mantiene el nuevo
    // plazo en el futuro y por debajo de 28 días desde ahora (TTL de 30 días),
    // y exige no superar el plazo del hito siguiente. Devuelve el nuevo plazo.
    pub fn extend_milestone_deadline(
        env: Env,
        task_id: String,
        index: u32,
        extra_secs: u64,
    ) -> Result<u64, Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Solo el cliente del proyecto puede otorgar más tiempo.
        project.client.require_auth();

        let mut milestone = Self::funded_milestone(&project, index)?;
        if extra_secs == 0 {
            return Err(Error::InvalidDeadline);
        }

        let old_deadline = milestone.deadline;
        let new_deadline = old_deadline
            .checked_add(extra_secs)
            .ok_or(Error::InvalidDeadline)?;
        let now = env.ledger().timestamp();
        let max_allowed = now
            .checked_add(MAX_MILESTONE_DEADLINE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        if new_deadline <= now || new_deadline > max_allowed {
            return Err(Error::InvalidDeadline);
        }

        // Conserva el orden monótono con el hito siguiente si existe.
        if index + 1 < project.milestones.len() {
            let next = project
                .milestones
                .get(index + 1)
                .ok_or(Error::MilestoneNotFound)?;
            if new_deadline > next.deadline {
                return Err(Error::InvalidMilestones);
            }
        }

        // Efectos + extensión de TTL.
        milestone.deadline = new_deadline;
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        ExtendMilestoneDeadlineEvent {
            task_id,
            index,
            old_deadline,
            new_deadline,
        }
        .publish(&env);
        Ok(new_deadline)
    }

    // Rotación segura del árbitro en un paso con doble firma atómica: deben
    // firmar el árbitro actual y el nuevo árbitro. Así nunca se pierde el
    // control hacia una dirección equivocada ni queda estado pendiente colgado.
    pub fn rotate_arbiter(env: Env, new_arbiter: Address) -> Result<(), Error> {
        let old_arbiter = Self::arbiter(&env)?;
        if new_arbiter == old_arbiter {
            return Err(Error::SameArbiter);
        }

        // Doble autorización: el actual cede el rol y el nuevo demuestra control.
        old_arbiter.require_auth();
        new_arbiter.require_auth();

        // Actualiza la configuración en almacenamiento de instancia y extiende TTL.
        env.storage().instance().set(&DataKey::Arbiter, &new_arbiter);
        Self::extend_instance(&env);

        RotateArbiterEvent {
            old_arbiter,
            new_arbiter,
        }
        .publish(&env);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v5: el contrato conoce al programador antes de pagar
    // -----------------------------------------------------------------------

    // El árbitro registra al programador que aceptó los criterios de una tarea
    // simple. Lo firma el backend en `/accept`, cuando ya comprobó la
    // invitación. Es idempotente con la misma dirección; con otra, falla.
    pub fn assign_freelancer(env: Env, task_id: String, freelancer: Address) -> Result<(), Error> {
        // Solo el árbitro: es quien sabe quién aceptó la invitación.
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        // Solo mientras el dinero sigue en el contrato.
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        match &task.freelancer {
            // Repetir la asignación con la misma dirección no cambia nada.
            Some(bound) if *bound == freelancer => return Ok(()),
            // Nadie puede reemplazar al programador ya registrado.
            Some(_) => return Err(Error::AlreadyAssigned),
            None => {}
        }

        // Efecto: queda registrado (la tarea sigue en Funded) + TTL.
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        AssignFreelancerEvent { task_id, freelancer }.publish(&env);
        Ok(())
    }

    // Lo mismo para un proyecto por hitos: el programador queda fijo desde que
    // acepta, no desde el primer pago. Desde ahí `bind_freelancer` rechaza
    // cualquier pago de un hito a otra dirección.
    pub fn assign_project_freelancer(
        env: Env,
        task_id: String,
        freelancer: Address,
    ) -> Result<(), Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        match &project.freelancer {
            Some(bound) if *bound == freelancer => return Ok(()),
            Some(_) => return Err(Error::AlreadyAssigned),
            None => {}
        }

        // Debe quedar al menos un hito con dinero: asignar un proyecto cerrado
        // no tiene sentido.
        let mut any_funded = false;
        for m in project.milestones.iter() {
            if m.status == MilestoneStatus::Funded {
                any_funded = true;
            }
        }
        if !any_funded {
            return Err(Error::NotFunded);
        }

        project.freelancer = Some(freelancer.clone());
        Self::save_project(&env, &key, &project);

        AssignProjectFreelancerEvent { task_id, freelancer }.publish(&env);
        Ok(())
    }

    // El cliente le da más tiempo al programador: el plazo solo puede crecer.
    // Se permite incluso si el plazo ya venció y nadie disparó el reembolso,
    // porque es el propio cliente quien renuncia a su derecho a reembolso.
    // El nuevo plazo no puede quedar a más de 28 días del ledger actual, para
    // seguir por debajo de los 30 días de TTL que se renuevan al escribir.
    pub fn extend_deadline(env: Env, task_id: String, extra_secs: u64) -> Result<u64, Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // Solo el cliente que depositó.
        task.client.require_auth();

        if extra_secs == 0 {
            return Err(Error::InvalidDeadline);
        }
        let new_deadline = task
            .deadline
            .checked_add(extra_secs)
            .ok_or(Error::InvalidDeadline)?;
        let max_deadline = env
            .ledger()
            .timestamp()
            .checked_add(MAX_MILESTONE_DEADLINE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        if new_deadline > max_deadline {
            return Err(Error::InvalidDeadline);
        }

        let old_deadline = task.deadline;
        task.deadline = new_deadline;
        Self::save_task(&env, &key, &task);

        ExtendDeadlineEvent {
            task_id,
            old_deadline,
            new_deadline,
        }
        .publish(&env);
        Ok(new_deadline)
    }

    // El cliente agrega dinero a una tarea depositada (por ejemplo, porque
    // amplió el alcance o quiere asegurar un pago mayor). Solo antes del plazo:
    // después, el dinero ya puede volver al cliente con `timeout_refund`.
    // Devuelve el nuevo monto.
    pub fn top_up_task(env: Env, task_id: String, amount: i128) -> Result<i128, Error> {
        // v6: los depósitos nuevos se detienen en pausa de emergencia.
        Self::not_paused(&env)?;
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        task.client.require_auth();

        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        let new_amount = task.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;

        // Efectos antes de la interacción + TTL.
        task.amount = new_amount;
        Self::save_task(&env, &key, &task);

        // Interacción: el cliente transfiere el extra al contrato.
        Self::token(&env)?; // el contrato debe estar inicializado
        Self::collect(&env, &task.client, *&amount)?;

        TopUpTaskEvent {
            task_id,
            added: amount,
            new_amount,
        }
        .publish(&env);
        Ok(new_amount)
    }

    // El programador asignado renuncia a la tarea: el depósito vuelve íntegro
    // al cliente en el acto, sin esperar el plazo. Solo lo puede firmar el
    // programador registrado, y el dinero nunca va a quien firma.
    pub fn freelancer_refund(env: Env, task_id: String) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        // Sin programador asignado no hay a quién pedirle la renuncia.
        let freelancer = task.freelancer.clone().ok_or(Error::WrongFreelancer)?;
        freelancer.require_auth();

        // Efectos antes de transferir: la tarea se cierra como reembolsada.
        task.status = TaskStatus::Refunded;
        Self::save_task(&env, &key, &task);

        Self::pay(&env, &task.client, task.amount)?;

        FreelancerRefundEvent {
            task_id,
            freelancer,
            client: task.client,
            amount: task.amount,
        }
        .publish(&env);
        Ok(())
    }

    // Lectura por lote: de 1 a 20 tareas en una sola simulación. Cada posición
    // trae la tarea o `None` si ese `task_id` no existe. Sirve al backend y a
    // los paneles públicos para no hacer una llamada por tarea.
    pub fn get_tasks(env: Env, task_ids: Vec<String>) -> Result<Vec<Option<Task>>, Error> {
        if task_ids.is_empty() || task_ids.len() > MAX_BATCH_READ {
            return Err(Error::TooManyItems);
        }
        let mut out: Vec<Option<Task>> = Vec::new(&env);
        for id in task_ids.iter() {
            out.push_back(env.storage().persistent().get(&DataKey::Task(id)));
        }
        Ok(out)
    }

    // -----------------------------------------------------------------------
    // v6: acuerdos entre las dos partes
    // -----------------------------------------------------------------------

    // Cliente y programador renegocian los criterios: el `rules_hash` on-chain
    // cambia solo si los dos firman. Así el acuerdo verificable nunca cambia
    // por decisión de una sola parte. Exige programador registrado.
    pub fn amend_rules(env: Env, task_id: String, new_rules_hash: BytesN<32>) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        let freelancer = Self::assigned(&task)?;

        // Doble firma: los dos aceptan los criterios nuevos.
        task.client.require_auth();
        freelancer.require_auth();

        if task.rules_hash == new_rules_hash {
            return Err(Error::NoChange);
        }
        let old_rules_hash = task.rules_hash.clone();
        task.rules_hash = new_rules_hash.clone();
        Self::save_task(&env, &key, &task);

        AmendRulesEvent {
            task_id,
            old_rules_hash,
            new_rules_hash,
        }
        .publish(&env);
        Ok(())
    }

    // Pago parcial del árbitro: el motor aprobó una parte de los criterios y
    // se paga esa parte al programador registrado; el resto sigue en Funded y
    // se puede pagar después (o volver al cliente tras el plazo). Mismas reglas
    // que `release`: solo antes del plazo y solo al programador registrado.
    // Devuelve lo que queda en la tarea.
    pub fn release_partial(
        env: Env,
        task_id: String,
        amount: i128,
        code_hash: BytesN<32>,
        verdict_hash: BytesN<32>,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        let freelancer = Self::assigned(&task)?;

        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        // Estrictamente parcial: para pagar todo existe `release`.
        if amount <= 0 || amount >= task.amount {
            return Err(Error::InvalidAmount);
        }
        let remaining = task.amount.checked_sub(amount).ok_or(Error::InvalidAmount)?;

        // Efectos antes de transferir: baja el monto pendiente, sigue en Funded.
        task.amount = remaining;
        Self::save_task(&env, &key, &task);

        Self::pay(&env, &freelancer, amount)?;

        ReleasePartialEvent {
            task_id,
            freelancer,
            amount,
            remaining,
            code_hash,
            verdict_hash,
        }
        .publish(&env);
        Ok(remaining)
    }

    // Cancelación de común acuerdo: cliente y programador registrado firman y
    // el depósito vuelve íntegro al cliente, antes o después del plazo.
    pub fn mutual_cancel(env: Env, task_id: String) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        let freelancer = Self::assigned(&task)?;

        task.client.require_auth();
        freelancer.require_auth();

        task.status = TaskStatus::Refunded;
        Self::save_task(&env, &key, &task);

        Self::pay(&env, &task.client, task.amount)?;

        MutualCancelEvent {
            task_id,
            client: task.client,
            freelancer,
            amount: task.amount,
        }
        .publish(&env);
        Ok(())
    }

    // El programador registrado le pasa la tarea a otro. Firman los tres: el
    // cliente (acepta al nuevo), el programador actual (cede) y el nuevo
    // (demuestra que controla la dirección y acepta los criterios).
    pub fn reassign_freelancer(
        env: Env,
        task_id: String,
        new_freelancer: Address,
    ) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        let old_freelancer = Self::assigned(&task)?;

        if new_freelancer == old_freelancer {
            return Err(Error::NoChange);
        }
        task.client.require_auth();
        old_freelancer.require_auth();
        new_freelancer.require_auth();

        task.freelancer = Some(new_freelancer.clone());
        Self::save_task(&env, &key, &task);

        ReassignFreelancerEvent {
            task_id,
            old_freelancer,
            new_freelancer,
        }
        .publish(&env);
        Ok(())
    }

    // La tarea pasa a otro cliente (por ejemplo, la cuenta de una empresa).
    // Firman el cliente actual (cede), el nuevo (acepta) y, si ya hay
    // programador registrado, también él: cambia a quién le entrega y quién
    // puede aprobar manualmente. El reembolso, desde ahí, va al cliente nuevo.
    pub fn transfer_client(env: Env, task_id: String, new_client: Address) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;

        if new_client == task.client {
            return Err(Error::NoChange);
        }
        task.client.require_auth();
        new_client.require_auth();
        if let Some(freelancer) = &task.freelancer {
            freelancer.require_auth();
        }

        let old_client = task.client.clone();
        task.client = new_client.clone();
        Self::save_task(&env, &key, &task);

        TransferClientEvent {
            task_id,
            old_client,
            new_client,
        }
        .publish(&env);
        Ok(())
    }

    // El cliente le da una propina al programador de una tarea ya pagada. El
    // dinero va directo del cliente al programador (no pasa por el contrato),
    // pero queda un evento on-chain amarrado a la tarea.
    pub fn tip(env: Env, task_id: String, amount: i128) -> Result<(), Error> {
        let task: Task = env
            .storage()
            .persistent()
            .get(&DataKey::Task(task_id.clone()))
            .ok_or(Error::NotFound)?;
        task.client.require_auth();

        // Solo sobre una tarea pagada: antes de eso existe el bono.
        if task.status != TaskStatus::Released {
            return Err(Error::NotFunded);
        }
        let freelancer = Self::assigned(&task)?;
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let token_addr = Self::token(&env)?;
        token::Client::new(&env, &token_addr).transfer(&task.client, &freelancer, &amount);

        TipEvent {
            task_id,
            client: task.client,
            freelancer,
            amount,
        }
        .publish(&env);
        Ok(())
    }

    // Cualquiera puede extender la vida en el ledger de una tarea o de un
    // proyecto (y de la instancia), para que no se archive mientras espera.
    // No cambia nada más ni mueve dinero.
    pub fn bump_ttl(env: Env, task_id: String) -> Result<(), Error> {
        let task_key = DataKey::Task(task_id.clone());
        let project_key = DataKey::Project(task_id);
        let key = if env.storage().persistent().has(&task_key) {
            task_key
        } else if env.storage().persistent().has(&project_key) {
            project_key
        } else {
            return Err(Error::NotFound);
        };
        env.storage()
            .persistent()
            .extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Ok(())
    }

    // Totales del contrato: cuánto USDC entró, cuánto salió y cuánto debe
    // tener guardado. Cualquiera puede compararlo con el saldo real del token.
    pub fn get_stats(env: Env) -> Stats {
        let deposited = Self::total(&env, &DataKey::TotalIn);
        let paid_out = Self::total(&env, &DataKey::TotalOut);
        Stats {
            deposited,
            paid_out,
            held: deposited - paid_out,
        }
    }

    // Depósito con el programador ya registrado desde el inicio, en una sola
    // transacción: firman el cliente (el dinero) y el programador (acepta).
    // Equivale a `deposit` seguido de la asignación, sin pasar por el árbitro.
    pub fn deposit_assigned(
        env: Env,
        client: Address,
        task_id: String,
        amount: i128,
        deadline_secs: u64,
        rules_hash: BytesN<32>,
        freelancer: Address,
    ) -> Result<(), Error> {
        freelancer.require_auth();
        if freelancer == client {
            return Err(Error::NoChange);
        }
        Self::deposit(env.clone(), client, task_id.clone(), amount, deadline_secs, rules_hash)?;

        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        AssignFreelancerEvent { task_id, freelancer }.publish(&env);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v6: disputas y pausa de emergencia
    // -----------------------------------------------------------------------

    // El cliente o el programador registrado abre una disputa antes del plazo.
    // No mueve dinero: solo congela el reembolso por plazo (hasta 14 días
    // después) para que el árbitro decida. Pagar, repartir o cancelar de común
    // acuerdo siguen permitidos y cierran la disputa en la práctica.
    pub fn open_dispute(env: Env, task_id: String, by: Address) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let task = Self::funded_task(&env, &key)?;
        let freelancer = Self::assigned(&task)?;
        by.require_auth();

        if by != task.client && by != freelancer {
            return Err(Error::NotParty);
        }
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        let dkey = DataKey::Dispute(task_id.clone());
        if env.storage().persistent().has(&dkey) {
            return Err(Error::DisputeOpen);
        }
        env.storage().persistent().set(&dkey, &by);
        env.storage()
            .persistent()
            .extend_ttl(&dkey, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::save_task(&env, &key, &task); // renueva el TTL de la tarea

        OpenDisputeEvent {
            task_id,
            opened_by: by,
        }
        .publish(&env);
        Ok(())
    }

    // El árbitro resuelve la disputa: `freelancer_amount` va al programador
    // registrado y el resto vuelve al cliente (cualquiera de los dos puede ser
    // 0). Se permite después del plazo: para eso se congeló el reembolso.
    pub fn resolve_dispute(env: Env, task_id: String, freelancer_amount: i128) -> Result<(), Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        let dkey = DataKey::Dispute(task_id.clone());
        if !env.storage().persistent().has(&dkey) {
            return Err(Error::NoDispute);
        }
        let freelancer = Self::assigned(&task)?;
        if freelancer_amount < 0 || freelancer_amount > task.amount {
            return Err(Error::InvalidAmount);
        }
        let refund_amount = task
            .amount
            .checked_sub(freelancer_amount)
            .ok_or(Error::InvalidAmount)?;

        // Efectos antes de transferir: la tarea se cierra y la disputa se borra.
        task.status = if freelancer_amount > 0 {
            TaskStatus::Released
        } else {
            TaskStatus::Refunded
        };
        Self::save_task(&env, &key, &task);
        env.storage().persistent().remove(&dkey);

        if freelancer_amount > 0 {
            Self::pay(&env, &freelancer, freelancer_amount)?;
        }
        if refund_amount > 0 {
            Self::pay(&env, &task.client, refund_amount)?;
        }

        ResolveDisputeEvent {
            task_id,
            freelancer,
            freelancer_amount,
            client: task.client,
            refund_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Quién abrió la disputa de una tarea, o `None` si no hay.
    pub fn get_dispute(env: Env, task_id: String) -> Option<Address> {
        env.storage().persistent().get(&DataKey::Dispute(task_id))
    }

    // Pausa de emergencia (solo el árbitro): detiene los depósitos nuevos y
    // las recargas. NUNCA detiene pagos ni reembolsos: el dinero ya
    // depositado siempre puede salir hacia el programador o el cliente.
    pub fn pause(env: Env) -> Result<(), Error> {
        Self::set_paused(&env, true)
    }

    // Reanuda los depósitos (solo el árbitro).
    pub fn unpause(env: Env) -> Result<(), Error> {
        Self::set_paused(&env, false)
    }

    // -----------------------------------------------------------------------
    // v7: acuerdos entre las dos partes en proyectos por hitos
    // -----------------------------------------------------------------------

    // Cliente y programador fijado cambian los criterios de UN hito.
    pub fn amend_milestone_rules(
        env: Env,
        task_id: String,
        index: u32,
        new_rules_hash: BytesN<32>,
    ) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let freelancer = Self::project_freelancer(&project)?;
        let mut milestone = Self::funded_milestone(&project, index)?;

        project.client.require_auth();
        freelancer.require_auth();

        if milestone.rules_hash == new_rules_hash {
            return Err(Error::NoChange);
        }
        let old_rules_hash = milestone.rules_hash.clone();
        milestone.rules_hash = new_rules_hash.clone();
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        AmendMilestoneRulesEvent {
            task_id,
            index,
            old_rules_hash,
            new_rules_hash,
        }
        .publish(&env);
        Ok(())
    }

    // Pago parcial de un hito por el árbitro, al programador fijado y antes
    // del plazo de ese hito. Devuelve lo que queda en el hito.
    pub fn release_milestone_partial(
        env: Env,
        task_id: String,
        index: u32,
        amount: i128,
        code_hash: BytesN<32>,
        verdict_hash: BytesN<32>,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let freelancer = Self::project_freelancer(&project)?;
        let mut milestone = Self::funded_milestone(&project, index)?;

        if env.ledger().timestamp() >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }
        if amount <= 0 || amount >= milestone.amount {
            return Err(Error::InvalidAmount);
        }
        let remaining = milestone
            .amount
            .checked_sub(amount)
            .ok_or(Error::InvalidAmount)?;

        milestone.amount = remaining;
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        Self::pay(&env, &freelancer, amount)?;

        ReleaseMilestonePartialEvent {
            task_id,
            index,
            freelancer,
            amount,
            remaining,
            code_hash,
            verdict_hash,
        }
        .publish(&env);
        Ok(remaining)
    }

    // Cancelación de común acuerdo de un proyecto: cliente y programador
    // fijado firman y TODOS los hitos que siguen en Funded vuelven al cliente
    // en una sola transferencia. Los hitos ya pagados no se tocan.
    pub fn mutual_cancel_project(env: Env, task_id: String) -> Result<u32, Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let freelancer = Self::project_freelancer(&project)?;

        project.client.require_auth();
        freelancer.require_auth();

        let mut count: u32 = 0;
        let mut total_refund: i128 = 0;
        for i in 0..project.milestones.len() {
            let mut m = project.milestones.get(i).ok_or(Error::MilestoneNotFound)?;
            if m.status == MilestoneStatus::Funded {
                total_refund = total_refund
                    .checked_add(m.amount)
                    .ok_or(Error::InvalidAmount)?;
                m.status = MilestoneStatus::Refunded;
                project.milestones.set(i, m);
                count += 1;
            }
        }
        if count == 0 {
            return Err(Error::NotFunded);
        }
        Self::save_project(&env, &key, &project);

        Self::pay(&env, &project.client, total_refund)?;

        MutualCancelProjectEvent {
            task_id,
            client: project.client,
            freelancer,
            count,
            total_refund,
        }
        .publish(&env);
        Ok(count)
    }

    // Otro programador sigue el proyecto. Firman los tres: el cliente, el
    // programador fijado (cede) y el nuevo (acepta). Debe quedar algún hito
    // con dinero: cambiar al programador de un proyecto cerrado no tiene sentido.
    pub fn reassign_project_freelancer(
        env: Env,
        task_id: String,
        new_freelancer: Address,
    ) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let old_freelancer = Self::project_freelancer(&project)?;
        Self::require_funded_milestone(&project)?;

        if new_freelancer == old_freelancer {
            return Err(Error::NoChange);
        }
        project.client.require_auth();
        old_freelancer.require_auth();
        new_freelancer.require_auth();

        project.freelancer = Some(new_freelancer.clone());
        Self::save_project(&env, &key, &project);

        ReassignProjectFreelancerEvent {
            task_id,
            old_freelancer,
            new_freelancer,
        }
        .publish(&env);
        Ok(())
    }

    // El proyecto pasa a otro cliente. Firman el cliente actual, el nuevo y,
    // si ya hay programador fijado, también él.
    pub fn transfer_project_client(
        env: Env,
        task_id: String,
        new_client: Address,
    ) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        Self::require_funded_milestone(&project)?;

        if new_client == project.client {
            return Err(Error::NoChange);
        }
        project.client.require_auth();
        new_client.require_auth();
        if let Some(freelancer) = &project.freelancer {
            freelancer.require_auth();
        }

        let old_client = project.client.clone();
        project.client = new_client.clone();
        Self::save_project(&env, &key, &project);

        TransferProjectClientEvent {
            task_id,
            old_client,
            new_client,
        }
        .publish(&env);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v7: disputas por hito y retiro de disputas
    // -----------------------------------------------------------------------

    // El cliente o el programador fijado abre una disputa sobre UN hito antes
    // de su plazo. Solo congela el reembolso por plazo de ese hito.
    pub fn open_milestone_dispute(
        env: Env,
        task_id: String,
        index: u32,
        by: Address,
    ) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let project = Self::load_project(&env, &key)?;
        let freelancer = Self::project_freelancer(&project)?;
        let milestone = Self::funded_milestone(&project, index)?;
        by.require_auth();

        if by != project.client && by != freelancer {
            return Err(Error::NotParty);
        }
        if env.ledger().timestamp() >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }
        let dkey = DataKey::MilestoneDispute(task_id.clone(), index);
        if env.storage().persistent().has(&dkey) {
            return Err(Error::DisputeOpen);
        }
        env.storage().persistent().set(&dkey, &by);
        env.storage()
            .persistent()
            .extend_ttl(&dkey, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::save_project(&env, &key, &project);

        OpenMilestoneDisputeEvent {
            task_id,
            index,
            opened_by: by,
        }
        .publish(&env);
        Ok(())
    }

    // El árbitro resuelve la disputa de un hito: `freelancer_amount` al
    // programador fijado y el resto al cliente. También tras el plazo.
    pub fn resolve_milestone_dispute(
        env: Env,
        task_id: String,
        index: u32,
        freelancer_amount: i128,
    ) -> Result<(), Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut milestone = Self::funded_milestone(&project, index)?;
        let dkey = DataKey::MilestoneDispute(task_id.clone(), index);
        if !env.storage().persistent().has(&dkey) {
            return Err(Error::NoDispute);
        }
        let freelancer = Self::project_freelancer(&project)?;
        if freelancer_amount < 0 || freelancer_amount > milestone.amount {
            return Err(Error::InvalidAmount);
        }
        let refund_amount = milestone
            .amount
            .checked_sub(freelancer_amount)
            .ok_or(Error::InvalidAmount)?;

        milestone.status = if freelancer_amount > 0 {
            MilestoneStatus::Released
        } else {
            MilestoneStatus::Refunded
        };
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);
        env.storage().persistent().remove(&dkey);

        if freelancer_amount > 0 {
            Self::pay(&env, &freelancer, freelancer_amount)?;
        }
        if refund_amount > 0 {
            Self::pay(&env, &project.client, refund_amount)?;
        }

        ResolveMilestoneDisputeEvent {
            task_id,
            index,
            freelancer,
            freelancer_amount,
            client: project.client,
            refund_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Quien abrió la disputa de una tarea simple la retira. El reembolso por
    // plazo vuelve a funcionar como siempre. También limpia una disputa que
    // quedó registrada en una tarea ya cerrada por otra vía.
    pub fn cancel_dispute(env: Env, task_id: String) -> Result<(), Error> {
        let dkey = DataKey::Dispute(task_id.clone());
        let opened_by: Address = env
            .storage()
            .persistent()
            .get(&dkey)
            .ok_or(Error::NoDispute)?;
        opened_by.require_auth();
        env.storage().persistent().remove(&dkey);
        Self::extend_instance(&env);

        CancelDisputeEvent {
            task_id,
            index: None,
            opened_by,
        }
        .publish(&env);
        Ok(())
    }

    // Lo mismo para la disputa de un hito.
    pub fn cancel_milestone_dispute(env: Env, task_id: String, index: u32) -> Result<(), Error> {
        let dkey = DataKey::MilestoneDispute(task_id.clone(), index);
        let opened_by: Address = env
            .storage()
            .persistent()
            .get(&dkey)
            .ok_or(Error::NoDispute)?;
        opened_by.require_auth();
        env.storage().persistent().remove(&dkey);
        Self::extend_instance(&env);

        CancelDisputeEvent {
            task_id,
            index: Some(index),
            opened_by,
        }
        .publish(&env);
        Ok(())
    }

    // Quién abrió la disputa de un hito, o `None` si no hay.
    pub fn get_milestone_dispute(env: Env, task_id: String, index: u32) -> Option<Address> {
        env.storage()
            .persistent()
            .get(&DataKey::MilestoneDispute(task_id, index))
    }

    // -----------------------------------------------------------------------
    // v7: operaciones por lote
    // -----------------------------------------------------------------------

    // El árbitro paga de 2 a 10 tareas aprobadas en una sola transacción. Cada
    // tarea sigue todas las reglas de `release` y además exige programador
    // registrado: en un lote nadie elige a quién se paga, va al registrado.
    // Si una sola tarea falla, se revierte todo el lote. Devuelve el total pagado.
    pub fn release_batch(
        env: Env,
        task_ids: Vec<String>,
        code_hashes: Vec<BytesN<32>>,
        verdict_hashes: Vec<BytesN<32>>,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let n = task_ids.len();
        if !(2..=10).contains(&n) {
            return Err(Error::TooManyItems);
        }
        if code_hashes.len() != n || verdict_hashes.len() != n {
            return Err(Error::LengthMismatch);
        }

        let now = env.ledger().timestamp();
        let mut total: i128 = 0;
        for i in 0..n {
            let task_id = task_ids.get(i).ok_or(Error::LengthMismatch)?;
            let key = DataKey::Task(task_id.clone());
            // Un id repetido falla aquí con NotFunded: no se paga dos veces.
            let mut task = Self::funded_task(&env, &key)?;
            let freelancer = Self::assigned(&task)?;
            if now >= task.deadline {
                return Err(Error::DeadlinePassed);
            }
            task.status = TaskStatus::Released;
            Self::save_task(&env, &key, &task);
            Self::pay(&env, &freelancer, task.amount)?;
            total = total.checked_add(task.amount).ok_or(Error::InvalidAmount)?;

            ReleaseEvent {
                task_id,
                freelancer,
                amount: task.amount,
                code_hash: code_hashes.get(i).ok_or(Error::LengthMismatch)?,
                verdict_hash: verdict_hashes.get(i).ok_or(Error::LengthMismatch)?,
            }
            .publish(&env);
        }
        Ok(total)
    }

    // Cualquiera reembolsa de una vez varias tareas vencidas (de 1 a 20), cada
    // una a SU cliente. Las que todavía no se pueden reembolsar (no existen, ya
    // se cerraron, no vencen o tienen una disputa que las congela) se omiten
    // sin fallar, para que sirva como tarea automática. Devuelve cuántas
    // reembolsó; si ninguna, `DeadlineNotReached`.
    pub fn refund_batch(env: Env, task_ids: Vec<String>) -> Result<u32, Error> {
        if task_ids.is_empty() || task_ids.len() > MAX_BATCH_READ {
            return Err(Error::TooManyItems);
        }
        let now = env.ledger().timestamp();
        let mut count: u32 = 0;
        for task_id in task_ids.iter() {
            let key = DataKey::Task(task_id.clone());
            let mut task: Task = match env.storage().persistent().get(&key) {
                Some(t) => t,
                None => continue,
            };
            if task.status != TaskStatus::Funded || now < task.deadline {
                continue;
            }
            if Self::frozen(&env, &DataKey::Dispute(task_id.clone()), task.deadline)? {
                continue;
            }
            task.status = TaskStatus::Refunded;
            Self::save_task(&env, &key, &task);
            Self::pay(&env, &task.client, task.amount)?;
            count += 1;

            TimeoutRefundEvent {
                task_id,
                client: task.client,
                amount: task.amount,
            }
            .publish(&env);
        }
        if count == 0 {
            return Err(Error::DeadlineNotReached);
        }
        Ok(count)
    }

    // Lectura por lote de proyectos: de 1 a 20, con `None` si no existe.
    pub fn get_projects(env: Env, task_ids: Vec<String>) -> Result<Vec<Option<Project>>, Error> {
        if task_ids.is_empty() || task_ids.len() > MAX_BATCH_READ {
            return Err(Error::TooManyItems);
        }
        let mut out: Vec<Option<Project>> = Vec::new(&env);
        for id in task_ids.iter() {
            out.push_back(env.storage().persistent().get(&DataKey::Project(id)));
        }
        Ok(out)
    }

    // -----------------------------------------------------------------------
    // v8: pago por tiempo
    // -----------------------------------------------------------------------

    // El cliente deposita `amount` para `freelancer`, que se libera de forma
    // lineal durante `duration_secs` (de 1 s a 28 días) desde ahora. No hay
    // criterios ni árbitro: es un pago por tiempo de trabajo acordado, que el
    // cliente puede cortar en cualquier momento con `cancel_stream`.
    pub fn deposit_stream(
        env: Env,
        client: Address,
        stream_id: String,
        freelancer: Address,
        amount: i128,
        duration_secs: u64,
    ) -> Result<(), Error> {
        Self::not_paused(&env)?;
        client.require_auth();

        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if freelancer == client {
            return Err(Error::NoChange);
        }
        if duration_secs == 0 || duration_secs > MAX_MILESTONE_DEADLINE_SECS {
            return Err(Error::InvalidDeadline);
        }
        let key = DataKey::Stream(stream_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        let start = env.ledger().timestamp();
        let end = start.checked_add(duration_secs).ok_or(Error::InvalidDeadline)?;

        let stream = Stream {
            stream_id: stream_id.clone(),
            client: client.clone(),
            freelancer: freelancer.clone(),
            amount,
            withdrawn: 0,
            start,
            end,
            status: StreamStatus::Active,
        };
        Self::save_stream(&env, &key, &stream);
        Self::collect(&env, &client, amount)?;

        DepositStreamEvent {
            stream_id,
            client,
            freelancer,
            amount,
            start,
            end,
        }
        .publish(&env);
        Ok(())
    }

    // El programador retira todo lo liberado que aún no ha retirado. Funciona
    // también después de que el cliente cancele (para cobrar lo ya ganado).
    // Devuelve lo que retiró.
    pub fn withdraw_stream(env: Env, stream_id: String) -> Result<i128, Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        stream.freelancer.require_auth();

        let available = Self::vested(&env, &stream)?
            .checked_sub(stream.withdrawn)
            .ok_or(Error::InvalidAmount)?;
        if available <= 0 {
            return Err(Error::NothingToWithdraw);
        }
        stream.withdrawn = stream
            .withdrawn
            .checked_add(available)
            .ok_or(Error::InvalidAmount)?;
        Self::save_stream(&env, &key, &stream);
        Self::pay(&env, &stream.freelancer, available)?;

        WithdrawStreamEvent {
            stream_id,
            freelancer: stream.freelancer,
            amount: available,
            withdrawn: stream.withdrawn,
        }
        .publish(&env);
        Ok(available)
    }

    // El cliente corta el pago por tiempo. En la misma transacción, el
    // programador recibe lo ganado hasta este segundo que no había retirado, y
    // el cliente recupera lo que todavía no se liberaba. Nadie pierde lo suyo.
    pub fn cancel_stream(env: Env, stream_id: String) -> Result<(), Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        stream.client.require_auth();
        if stream.status != StreamStatus::Active {
            return Err(Error::NotFunded);
        }
        // v11: con una disputa abierta, el cliente no puede cortar el pago por su cuenta.
        if env.storage().persistent().has(&DataKey::StreamDispute(stream_id.clone())) {
            return Err(Error::DisputeOpen);
        }
        let vested = Self::vested(&env, &stream)?;
        if vested >= stream.amount {
            // Ya se liberó todo: no hay nada que cancelar.
            return Err(Error::NotFunded);
        }
        let freelancer_amount = vested.checked_sub(stream.withdrawn).ok_or(Error::InvalidAmount)?;
        let refund_amount = stream.amount.checked_sub(vested).ok_or(Error::InvalidAmount)?;

        // Efectos: el pago queda en lo ganado y todo ya retirado.
        stream.status = StreamStatus::Canceled;
        stream.amount = vested;
        stream.withdrawn = vested;
        Self::save_stream(&env, &key, &stream);

        if freelancer_amount > 0 {
            Self::pay(&env, &stream.freelancer, freelancer_amount)?;
        }
        Self::pay(&env, &stream.client, refund_amount)?;

        CancelStreamEvent {
            stream_id,
            freelancer_amount,
            refund_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Lectura de un pago por tiempo.
    pub fn get_stream(env: Env, stream_id: String) -> Result<Stream, Error> {
        Self::load_stream(&env, &DataKey::Stream(stream_id))
    }

    // -----------------------------------------------------------------------
    // v8: garantía del programador
    // -----------------------------------------------------------------------

    // El programador registrado deposita una garantía sobre una tarea en
    // Funded, antes del plazo: le muestra al cliente que va en serio. Una sola
    // garantía por tarea.
    pub fn post_bond(env: Env, task_id: String, amount: i128) -> Result<(), Error> {
        Self::not_paused(&env)?;
        let task = Self::funded_task(&env, &DataKey::Task(task_id.clone()))?;
        let freelancer = Self::assigned(&task)?;
        freelancer.require_auth();

        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        let key = DataKey::Bond(task_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        let bond = Bond {
            task_id: task_id.clone(),
            freelancer: freelancer.clone(),
            amount,
        };
        env.storage().persistent().set(&key, &bond);
        env.storage()
            .persistent()
            .extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::collect(&env, &freelancer, amount)?;

        PostBondEvent {
            task_id,
            freelancer,
            amount,
        }
        .publish(&env);
        Ok(())
    }

    // El programador recupera su garantía cuando la tarea ya se pagó
    // (`Released`). Si la tarea terminó reembolsada, solo la recupera cuando
    // pasaron 14 días del plazo sin que el árbitro la diera al cliente.
    pub fn reclaim_bond(env: Env, task_id: String) -> Result<i128, Error> {
        let key = DataKey::Bond(task_id.clone());
        let bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        bond.freelancer.require_auth();

        let task: Task = env
            .storage()
            .persistent()
            .get(&DataKey::Task(task_id.clone()))
            .ok_or(Error::NotFound)?;
        match task.status {
            TaskStatus::Funded => return Err(Error::NotFunded),
            TaskStatus::Released => {}
            TaskStatus::Refunded => {
                let limit = task
                    .deadline
                    .checked_add(DISPUTE_GRACE_SECS)
                    .ok_or(Error::InvalidDeadline)?;
                if env.ledger().timestamp() < limit {
                    return Err(Error::DeadlineNotReached);
                }
            }
        }
        env.storage().persistent().remove(&key);
        Self::pay(&env, &bond.freelancer, bond.amount)?;

        ReclaimBondEvent {
            task_id,
            freelancer: bond.freelancer,
            amount: bond.amount,
        }
        .publish(&env);
        Ok(bond.amount)
    }

    // El árbitro da la garantía al cliente cuando la tarea terminó
    // reembolsada (el programador no entregó lo acordado). Nunca sobre una
    // tarea pagada: si el programador cumplió, su garantía es suya.
    pub fn slash_bond(env: Env, task_id: String) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Bond(task_id.clone());
        let bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        let task: Task = env
            .storage()
            .persistent()
            .get(&DataKey::Task(task_id.clone()))
            .ok_or(Error::NotFound)?;
        if task.status != TaskStatus::Refunded {
            return Err(Error::NotFunded);
        }
        env.storage().persistent().remove(&key);
        Self::pay(&env, &task.client, bond.amount)?;

        SlashBondEvent {
            task_id,
            freelancer: bond.freelancer,
            client: task.client,
            amount: bond.amount,
        }
        .publish(&env);
        Ok(bond.amount)
    }

    // Lectura de la garantía de una tarea, o `None` si no hay.
    pub fn get_bond(env: Env, task_id: String) -> Option<Bond> {
        env.storage().persistent().get(&DataKey::Bond(task_id))
    }

    // -----------------------------------------------------------------------
    // v9: más operaciones sobre pagos por tiempo, garantías y pagos
    // -----------------------------------------------------------------------

    // El cliente agrega `amount` a un pago por tiempo activo. Para no cambiar
    // la tarifa por segundo que se acordó, el final se recorre en proporción:
    // extra = amount × duración / monto actual. Lo ya liberado no disminuye.
    // El nuevo final no puede quedar a más de 28 días de ahora.
    pub fn top_up_stream(env: Env, stream_id: String, amount: i128) -> Result<u64, Error> {
        Self::not_paused(&env)?;
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        stream.client.require_auth();

        if stream.status != StreamStatus::Active || env.ledger().timestamp() >= stream.end {
            return Err(Error::NotFunded);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let duration = (stream.end - stream.start) as i128;
        let extra = amount
            .checked_mul(duration)
            .ok_or(Error::InvalidAmount)?
            / stream.amount;
        if extra <= 0 {
            return Err(Error::InvalidAmount);
        }
        let new_end = stream
            .end
            .checked_add(extra as u64)
            .ok_or(Error::InvalidDeadline)?;
        let max_end = env
            .ledger()
            .timestamp()
            .checked_add(MAX_MILESTONE_DEADLINE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        if new_end > max_end {
            return Err(Error::InvalidDeadline);
        }

        stream.amount = stream.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;
        stream.end = new_end;
        Self::save_stream(&env, &key, &stream);
        Self::collect(&env, &stream.client, amount)?;

        TopUpStreamEvent {
            stream_id,
            added: amount,
            new_amount: stream.amount,
            new_end,
        }
        .publish(&env);
        Ok(new_end)
    }

    // Otro programador sigue un pago por tiempo activo. Firman el cliente, el
    // programador actual y el nuevo. En la misma transacción el actual cobra
    // lo liberado que no había retirado, y lo que falta por liberar sigue
    // fluyendo hacia el nuevo desde este segundo hasta el mismo final.
    pub fn reassign_stream(
        env: Env,
        stream_id: String,
        new_freelancer: Address,
    ) -> Result<i128, Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        let now = env.ledger().timestamp();
        if stream.status != StreamStatus::Active || now >= stream.end {
            return Err(Error::NotFunded);
        }
        let old_freelancer = stream.freelancer.clone();
        if new_freelancer == old_freelancer || new_freelancer == stream.client {
            return Err(Error::NoChange);
        }
        stream.client.require_auth();
        old_freelancer.require_auth();
        new_freelancer.require_auth();

        let vested = Self::vested(&env, &stream)?;
        let paid_to_old = vested.checked_sub(stream.withdrawn).ok_or(Error::InvalidAmount)?;
        let remaining = stream.amount.checked_sub(vested).ok_or(Error::InvalidAmount)?;

        // El pago sigue con lo que falta, para el nuevo, desde ahora.
        stream.freelancer = new_freelancer.clone();
        stream.amount = remaining;
        stream.withdrawn = 0;
        stream.start = now;
        Self::save_stream(&env, &key, &stream);

        if paid_to_old > 0 {
            Self::pay(&env, &old_freelancer, paid_to_old)?;
        }

        ReassignStreamEvent {
            stream_id,
            old_freelancer,
            new_freelancer,
            paid_to_old,
            remaining,
        }
        .publish(&env);
        Ok(paid_to_old)
    }

    // El árbitro reparte la garantía de una tarea reembolsada: `client_amount`
    // al cliente como compensación y el resto de vuelta al programador. Para
    // darla toda al cliente existe `slash_bond`; aquí el reparto es parcial.
    pub fn slash_bond_partial(env: Env, task_id: String, client_amount: i128) -> Result<(), Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Bond(task_id.clone());
        let bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        let task: Task = env
            .storage()
            .persistent()
            .get(&DataKey::Task(task_id.clone()))
            .ok_or(Error::NotFound)?;
        if task.status != TaskStatus::Refunded {
            return Err(Error::NotFunded);
        }
        if client_amount <= 0 || client_amount >= bond.amount {
            return Err(Error::InvalidAmount);
        }
        let freelancer_amount = bond
            .amount
            .checked_sub(client_amount)
            .ok_or(Error::InvalidAmount)?;

        env.storage().persistent().remove(&key);
        Self::pay(&env, &task.client, client_amount)?;
        Self::pay(&env, &bond.freelancer, freelancer_amount)?;

        SlashBondPartialEvent {
            task_id,
            client: task.client,
            client_amount,
            freelancer: bond.freelancer,
            freelancer_amount,
        }
        .publish(&env);
        Ok(())
    }

    // Pago del árbitro con comisión de plataforma: el programador recibe el
    // monto menos `fee_bps` puntos base (máximo 10%) y la comisión va a
    // `fee_to`. Mismas reglas que `release`: tarea en Funded, antes del plazo
    // y, si hay programador registrado, solo a él.
    pub fn release_with_fee(
        env: Env,
        task_id: String,
        freelancer: Address,
        code_hash: BytesN<32>,
        verdict_hash: BytesN<32>,
        fee_to: Address,
        fee_bps: u32,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        Self::check_assigned(&task, &freelancer)?;
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        if fee_bps == 0 || fee_bps > MAX_FEE_BPS {
            return Err(Error::InvalidAmount);
        }
        if fee_to == freelancer || fee_to == task.client {
            return Err(Error::NoChange);
        }
        let fee_amount = task
            .amount
            .checked_mul(fee_bps as i128)
            .ok_or(Error::InvalidAmount)?
            / 10_000;
        if fee_amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let freelancer_amount = task
            .amount
            .checked_sub(fee_amount)
            .ok_or(Error::InvalidAmount)?;

        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);

        Self::pay(&env, &freelancer, freelancer_amount)?;
        Self::pay(&env, &fee_to, fee_amount)?;

        ReleaseWithFeeEvent {
            task_id,
            freelancer,
            freelancer_amount,
            fee_to,
            fee_amount,
            code_hash,
            verdict_hash,
        }
        .publish(&env);
        Ok(freelancer_amount)
    }

    // -----------------------------------------------------------------------
    // v10
    // -----------------------------------------------------------------------

    // El programador aumenta su garantía sobre una tarea que sigue en Funded y
    // antes del plazo (por ejemplo, para dar más confianza al ampliar el
    // alcance). Solo quien depositó la garantía. Devuelve el nuevo monto.
    pub fn top_up_bond(env: Env, task_id: String, amount: i128) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        let key = DataKey::Bond(task_id.clone());
        let mut bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        bond.freelancer.require_auth();

        let task = Self::funded_task(&env, &DataKey::Task(task_id.clone()))?;
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        bond.amount = bond.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;
        env.storage().persistent().set(&key, &bond);
        env.storage()
            .persistent()
            .extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::collect(&env, &bond.freelancer, amount)?;

        TopUpBondEvent {
            task_id,
            added: amount,
            new_amount: bond.amount,
        }
        .publish(&env);
        Ok(bond.amount)
    }

    // Pago de un hito por el árbitro con comisión de plataforma (1 a 1000
    // puntos base). Mismas reglas que `release_milestone`: hito en Funded,
    // antes de su plazo y al programador fijado del proyecto (o lo fija).
    pub fn release_milestone_with_fee(
        env: Env,
        task_id: String,
        index: u32,
        freelancer: Address,
        code_hash: BytesN<32>,
        verdict_hash: BytesN<32>,
        fee_to: Address,
        fee_bps: u32,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();

        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut milestone = Self::funded_milestone(&project, index)?;
        if env.ledger().timestamp() >= milestone.deadline {
            return Err(Error::DeadlinePassed);
        }
        if fee_bps == 0 || fee_bps > MAX_FEE_BPS {
            return Err(Error::InvalidAmount);
        }
        if fee_to == freelancer || fee_to == project.client {
            return Err(Error::NoChange);
        }
        Self::bind_freelancer(&mut project, &freelancer)?;
        let fee_amount = milestone
            .amount
            .checked_mul(fee_bps as i128)
            .ok_or(Error::InvalidAmount)?
            / 10_000;
        if fee_amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let freelancer_amount = milestone
            .amount
            .checked_sub(fee_amount)
            .ok_or(Error::InvalidAmount)?;

        milestone.status = MilestoneStatus::Released;
        project.milestones.set(index, milestone);
        Self::save_project(&env, &key, &project);

        Self::pay(&env, &freelancer, freelancer_amount)?;
        Self::pay(&env, &fee_to, fee_amount)?;

        ReleaseMilestoneWithFeeEvent {
            task_id,
            index,
            freelancer,
            freelancer_amount,
            fee_to,
            fee_amount,
            code_hash,
            verdict_hash,
        }
        .publish(&env);
        Ok(freelancer_amount)
    }

    // Un pago por tiempo activo cambia de cliente: desde ahí, lo que no se ha
    // liberado vuelve al cliente nuevo si se cancela, y solo él puede
    // recargarlo o cancelarlo. Firman el cliente actual, el nuevo y el
    // programador (cambia con quién está su acuerdo).
    pub fn transfer_stream_client(
        env: Env,
        stream_id: String,
        new_client: Address,
    ) -> Result<(), Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        if stream.status != StreamStatus::Active || env.ledger().timestamp() >= stream.end {
            return Err(Error::NotFunded);
        }
        if new_client == stream.client || new_client == stream.freelancer {
            return Err(Error::NoChange);
        }
        stream.client.require_auth();
        new_client.require_auth();
        stream.freelancer.require_auth();

        let old_client = stream.client.clone();
        stream.client = new_client.clone();
        Self::save_stream(&env, &key, &stream);

        TransferStreamClientEvent {
            stream_id,
            old_client,
            new_client,
        }
        .publish(&env);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v11: acuerdos sobre pagos por tiempo
    // -----------------------------------------------------------------------

    // Cliente y programador alargan un pago por tiempo activo. El programador
    // cobra en la misma transacción lo ganado y no retirado, y lo que falta se
    // libera desde ahora hasta el nuevo final (tope: 28 días desde ahora).
    pub fn extend_stream(env: Env, stream_id: String, extra_secs: u64) -> Result<u64, Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::active_stream(&env, &key)?;
        stream.client.require_auth();
        stream.freelancer.require_auth();
        if extra_secs == 0 {
            return Err(Error::InvalidDeadline);
        }
        let new_end = stream.end.checked_add(extra_secs).ok_or(Error::InvalidDeadline)?;
        let max = env
            .ledger()
            .timestamp()
            .checked_add(MAX_MILESTONE_DEADLINE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        if new_end > max {
            return Err(Error::InvalidDeadline);
        }
        let (paid, remaining) = Self::settle_earned(&env, &mut stream)?;
        stream.end = new_end;
        Self::save_stream(&env, &key, &stream);
        if paid > 0 {
            Self::pay(&env, &stream.freelancer, paid)?;
        }
        Self::stream_event(&env, stream_id, "extend", paid, 0, remaining, new_end);
        Ok(new_end)
    }

    // Cliente y programador recortan lo que falta por liberar: `reduce_amount`
    // vuelve al cliente y el resto sigue fluyendo hasta el mismo final. El
    // programador cobra antes lo ya ganado.
    pub fn reduce_stream(env: Env, stream_id: String, reduce_amount: i128) -> Result<i128, Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::active_stream(&env, &key)?;
        stream.client.require_auth();
        stream.freelancer.require_auth();
        let (paid, remaining) = Self::settle_earned(&env, &mut stream)?;
        if reduce_amount <= 0 || reduce_amount >= remaining {
            return Err(Error::InvalidAmount);
        }
        stream.amount = remaining - reduce_amount;
        Self::save_stream(&env, &key, &stream);
        if paid > 0 {
            Self::pay(&env, &stream.freelancer, paid)?;
        }
        Self::pay(&env, &stream.client, reduce_amount)?;
        Self::stream_event(&env, stream_id, "reduce", paid, reduce_amount, stream.amount, stream.end);
        Ok(stream.amount)
    }

    // Cliente y programador cierran el pago por tiempo con un reparto: el
    // programador recibe lo ganado más `freelancer_amount` de lo pendiente y
    // el resto vuelve al cliente, en una transacción.
    pub fn mutual_split_stream(
        env: Env,
        stream_id: String,
        freelancer_amount: i128,
    ) -> Result<(), Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::active_stream(&env, &key)?;
        stream.client.require_auth();
        stream.freelancer.require_auth();
        let (paid, remaining) = Self::settle_earned(&env, &mut stream)?;
        if freelancer_amount <= 0 || freelancer_amount >= remaining {
            return Err(Error::InvalidAmount);
        }
        let refund = remaining - freelancer_amount;
        Self::close_stream(&env, &key, &mut stream, freelancer_amount);
        Self::pay(&env, &stream.freelancer, paid + freelancer_amount)?;
        Self::pay(&env, &stream.client, refund)?;
        Self::stream_event(&env, stream_id, "split", paid + freelancer_amount, refund, 0, stream.end);
        Ok(())
    }

    // Propina del cliente al programador de un pago por tiempo (activo o
    // terminado). Va directo entre ellos y deja un evento amarrado al pago.
    pub fn tip_stream(env: Env, stream_id: String, amount: i128) -> Result<(), Error> {
        let stream = Self::load_stream(&env, &DataKey::Stream(stream_id.clone()))?;
        stream.client.require_auth();
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if stream.withdrawn <= 0 && Self::vested(&env, &stream)? <= 0 {
            // Todavía no ha ganado nada: para eso existe top_up_stream.
            return Err(Error::NothingToWithdraw);
        }
        token::Client::new(&env, &Self::token(&env)?).transfer(&stream.client, &stream.freelancer, &amount);
        TipV11Event { id: stream_id, client: stream.client, freelancer: stream.freelancer, amount }.publish(&env);
        Ok(())
    }

    // El cliente o el programador abre una disputa sobre un pago por tiempo
    // activo. Mientras esté abierta, el cliente no puede cancelarlo por su
    // cuenta (el dinero sigue liberándose); el árbitro la resuelve.
    pub fn open_stream_dispute(env: Env, stream_id: String, by: Address) -> Result<(), Error> {
        let stream = Self::active_stream(&env, &DataKey::Stream(stream_id.clone()))?;
        by.require_auth();
        if by != stream.client && by != stream.freelancer {
            return Err(Error::NotParty);
        }
        let dkey = DataKey::StreamDispute(stream_id.clone());
        if env.storage().persistent().has(&dkey) {
            return Err(Error::DisputeOpen);
        }
        env.storage().persistent().set(&dkey, &by);
        env.storage().persistent().extend_ttl(&dkey, TTL_THRESHOLD, TTL_EXTEND_TO);
        OpenStreamDisputeEvent { stream_id, opened_by: by }.publish(&env);
        Ok(())
    }

    // El árbitro resuelve la disputa de un pago por tiempo: el programador
    // recibe lo ganado más `freelancer_amount` de lo pendiente (puede ser 0) y
    // el resto vuelve al cliente. El pago queda cerrado.
    pub fn resolve_stream_dispute(
        env: Env,
        stream_id: String,
        freelancer_amount: i128,
    ) -> Result<(), Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        if stream.status != StreamStatus::Active {
            return Err(Error::NotFunded);
        }
        let dkey = DataKey::StreamDispute(stream_id.clone());
        if !env.storage().persistent().has(&dkey) {
            return Err(Error::NoDispute);
        }
        let (paid, remaining) = Self::settle_earned(&env, &mut stream)?;
        if freelancer_amount < 0 || freelancer_amount > remaining {
            return Err(Error::InvalidAmount);
        }
        let refund = remaining - freelancer_amount;
        Self::close_stream(&env, &key, &mut stream, freelancer_amount);
        env.storage().persistent().remove(&dkey);
        if paid + freelancer_amount > 0 {
            Self::pay(&env, &stream.freelancer, paid + freelancer_amount)?;
        }
        if refund > 0 {
            Self::pay(&env, &stream.client, refund)?;
        }
        Self::stream_event(&env, stream_id, "resolve", paid + freelancer_amount, refund, 0, stream.end);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v11: lotes y propina de proyecto
    // -----------------------------------------------------------------------

    // El cliente abre de 2 a 10 pagos por tiempo en una transacción y una sola
    // transferencia. Cada uno con las reglas de `deposit_stream`.
    pub fn batch_deposit_streams(
        env: Env,
        client: Address,
        stream_ids: soroban_sdk::Vec<String>,
        freelancers: soroban_sdk::Vec<Address>,
        amounts: soroban_sdk::Vec<i128>,
        durations_secs: soroban_sdk::Vec<u64>,
    ) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        client.require_auth();
        let n = stream_ids.len();
        if !(2..=10).contains(&n) {
            return Err(Error::TooManyItems);
        }
        if freelancers.len() != n || amounts.len() != n || durations_secs.len() != n {
            return Err(Error::LengthMismatch);
        }
        let start = env.ledger().timestamp();
        let mut total: i128 = 0;
        for i in 0..n {
            let id = stream_ids.get(i).ok_or(Error::LengthMismatch)?;
            let freelancer = freelancers.get(i).ok_or(Error::LengthMismatch)?;
            let amount = amounts.get(i).ok_or(Error::LengthMismatch)?;
            let duration = durations_secs.get(i).ok_or(Error::LengthMismatch)?;
            if amount <= 0 {
                return Err(Error::InvalidAmount);
            }
            if freelancer == client {
                return Err(Error::NoChange);
            }
            if duration == 0 || duration > MAX_MILESTONE_DEADLINE_SECS {
                return Err(Error::InvalidDeadline);
            }
            let key = DataKey::Stream(id.clone());
            // También detecta ids repetidos dentro del mismo lote.
            if env.storage().persistent().has(&key) {
                return Err(Error::AlreadyExists);
            }
            let end = start.checked_add(duration).ok_or(Error::InvalidDeadline)?;
            let stream = Stream {
                stream_id: id,
                client: client.clone(),
                freelancer,
                amount,
                withdrawn: 0,
                start,
                end,
                status: StreamStatus::Active,
            };
            Self::save_stream(&env, &key, &stream);
            total = total.checked_add(amount).ok_or(Error::InvalidAmount)?;
        }
        Self::collect(&env, &client, total)?;
        Ok(total)
    }

    // El cliente cancela de 1 a 20 pagos por tiempo suyos en una transacción;
    // cada uno con las reglas de `cancel_stream`. Los que no se pueden
    // cancelar (terminados, cancelados, de otro cliente o en disputa) se
    // omiten. Devuelve cuántos canceló.
    pub fn cancel_stream_batch(
        env: Env,
        client: Address,
        stream_ids: soroban_sdk::Vec<String>,
    ) -> Result<u32, Error> {
        client.require_auth();
        if stream_ids.is_empty() || stream_ids.len() > MAX_BATCH_READ {
            return Err(Error::TooManyItems);
        }
        let mut count: u32 = 0;
        for id in stream_ids.iter() {
            let key = DataKey::Stream(id.clone());
            let mut stream: Stream = match env.storage().persistent().get(&key) {
                Some(s) => s,
                None => continue,
            };
            if stream.client != client
                || stream.status != StreamStatus::Active
                || env.storage().persistent().has(&DataKey::StreamDispute(id.clone()))
            {
                continue;
            }
            let vested = Self::vested(&env, &stream)?;
            if vested >= stream.amount {
                continue;
            }
            let earned = vested - stream.withdrawn;
            let refund = stream.amount - vested;
            stream.status = StreamStatus::Canceled;
            stream.amount = vested;
            stream.withdrawn = vested;
            Self::save_stream(&env, &key, &stream);
            if earned > 0 {
                Self::pay(&env, &stream.freelancer, earned)?;
            }
            Self::pay(&env, &client, refund)?;
            Self::stream_event(&env, id, "cancel", earned, refund, 0, stream.end);
            count += 1;
        }
        if count == 0 {
            return Err(Error::NotFunded);
        }
        Ok(count)
    }

    // El árbitro paga de 2 a 10 hitos de un proyecto en una transacción y una
    // sola transferencia; cada hito con las reglas de `release_milestone`. Si
    // uno falla (repetido, vencido o ya cerrado) se revierte todo.
    pub fn release_milestones_batch(
        env: Env,
        task_id: String,
        indices: soroban_sdk::Vec<u32>,
        freelancer: Address,
        code_hashes: soroban_sdk::Vec<BytesN<32>>,
        verdict_hashes: soroban_sdk::Vec<BytesN<32>>,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();
        let n = indices.len();
        if !(2..=10).contains(&n) {
            return Err(Error::TooManyItems);
        }
        if code_hashes.len() != n || verdict_hashes.len() != n {
            return Err(Error::LengthMismatch);
        }
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        Self::bind_freelancer(&mut project, &freelancer)?;
        let now = env.ledger().timestamp();
        let mut total: i128 = 0;
        for i in 0..n {
            let index = indices.get(i).ok_or(Error::LengthMismatch)?;
            let mut m = Self::funded_milestone(&project, index)?;
            if now >= m.deadline {
                return Err(Error::DeadlinePassed);
            }
            m.status = MilestoneStatus::Released;
            total = total.checked_add(m.amount).ok_or(Error::InvalidAmount)?;
            project.milestones.set(index, m.clone());
            MilestoneReleaseEvent {
                task_id: task_id.clone(),
                index,
                freelancer: freelancer.clone(),
                amount: m.amount,
                code_hash: code_hashes.get(i).ok_or(Error::LengthMismatch)?,
                verdict_hash: verdict_hashes.get(i).ok_or(Error::LengthMismatch)?,
            }
            .publish(&env);
        }
        Self::save_project(&env, &key, &project);
        Self::pay(&env, &freelancer, total)?;
        Ok(total)
    }

    // Propina del cliente al programador fijado de un proyecto con al menos un
    // hito pagado. Va directo entre ellos, con evento amarrado al proyecto.
    pub fn tip_project(env: Env, task_id: String, amount: i128) -> Result<(), Error> {
        let project = Self::load_project(&env, &DataKey::Project(task_id.clone()))?;
        project.client.require_auth();
        let freelancer = Self::project_freelancer(&project)?;
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let mut any_released = false;
        for m in project.milestones.iter() {
            if m.status == MilestoneStatus::Released {
                any_released = true;
            }
        }
        if !any_released {
            return Err(Error::NotFunded);
        }
        token::Client::new(&env, &Self::token(&env)?).transfer(&project.client, &freelancer, &amount);
        TipV11Event { id: task_id, client: project.client, freelancer, amount }.publish(&env);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v12
    // -----------------------------------------------------------------------

    // Aprobación manual parcial: el cliente paga una parte de la tarea al
    // programador (el registrado, si lo hay) y el resto sigue en Funded para
    // pagarse o reembolsarse después. Se permite también tras el plazo.
    pub fn client_release_partial(
        env: Env,
        task_id: String,
        freelancer: Address,
        amount: i128,
    ) -> Result<i128, Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        task.client.require_auth();
        Self::check_assigned(&task, &freelancer)?;
        if amount <= 0 || amount >= task.amount {
            return Err(Error::InvalidAmount);
        }
        task.amount -= amount;
        Self::save_task(&env, &key, &task);
        Self::pay(&env, &freelancer, amount)?;
        ClientReleasePartialEvent { task_id, index: None, freelancer, amount, remaining: task.amount }.publish(&env);
        Ok(task.amount)
    }

    // Lo mismo para un hito: el cliente paga una parte y el resto del hito
    // sigue en Funded. El programador queda fijo como en cualquier pago.
    pub fn client_release_milestone_partial(
        env: Env,
        task_id: String,
        index: u32,
        freelancer: Address,
        amount: i128,
    ) -> Result<i128, Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        project.client.require_auth();
        let mut m = Self::funded_milestone(&project, index)?;
        Self::bind_freelancer(&mut project, &freelancer)?;
        if amount <= 0 || amount >= m.amount {
            return Err(Error::InvalidAmount);
        }
        m.amount -= amount;
        let remaining = m.amount;
        project.milestones.set(index, m);
        Self::save_project(&env, &key, &project);
        Self::pay(&env, &freelancer, amount)?;
        ClientReleasePartialEvent { task_id, index: Some(index), freelancer, amount, remaining }.publish(&env);
        Ok(remaining)
    }

    // El programador fijado de un proyecto deposita una garantía mientras quede
    // algún hito con dinero. Una por proyecto.
    pub fn post_project_bond(env: Env, task_id: String, amount: i128) -> Result<(), Error> {
        Self::not_paused(&env)?;
        let project = Self::load_project(&env, &DataKey::Project(task_id.clone()))?;
        let freelancer = Self::project_freelancer(&project)?;
        freelancer.require_auth();
        Self::require_funded_milestone(&project)?;
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let key = DataKey::ProjectBond(task_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        let bond = Bond { task_id: task_id.clone(), freelancer: freelancer.clone(), amount };
        env.storage().persistent().set(&key, &bond);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::collect(&env, &freelancer, amount)?;
        Self::project_bond_event(&env, task_id, "post", amount, 0);
        Ok(())
    }

    // El programador recupera la garantía del proyecto cuando ya no queda
    // ningún hito con dinero y al menos uno se pagó.
    pub fn reclaim_project_bond(env: Env, task_id: String) -> Result<i128, Error> {
        let key = DataKey::ProjectBond(task_id.clone());
        let bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        bond.freelancer.require_auth();
        let project = Self::load_project(&env, &DataKey::Project(task_id.clone()))?;
        let (funded, released, _) = Self::milestone_counts(&project);
        if funded > 0 || released == 0 {
            return Err(Error::NotFunded);
        }
        env.storage().persistent().remove(&key);
        Self::pay(&env, &bond.freelancer, bond.amount)?;
        Self::project_bond_event(&env, task_id, "reclaim", bond.amount, 0);
        Ok(bond.amount)
    }

    // El árbitro reparte la garantía de un proyecto cerrado con algún hito
    // reembolsado: `client_amount` al cliente (hasta toda) y el resto de vuelta
    // al programador.
    pub fn slash_project_bond(env: Env, task_id: String, client_amount: i128) -> Result<(), Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();
        let key = DataKey::ProjectBond(task_id.clone());
        let bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        let project = Self::load_project(&env, &DataKey::Project(task_id.clone()))?;
        let (funded, _, refunded) = Self::milestone_counts(&project);
        if funded > 0 || refunded == 0 {
            return Err(Error::NotFunded);
        }
        if client_amount <= 0 || client_amount > bond.amount {
            return Err(Error::InvalidAmount);
        }
        let back = bond.amount - client_amount;
        env.storage().persistent().remove(&key);
        Self::pay(&env, &project.client, client_amount)?;
        if back > 0 {
            Self::pay(&env, &bond.freelancer, back)?;
        }
        Self::project_bond_event(&env, task_id, "slash", back, client_amount);
        Ok(())
    }

    // El programador retira lo liberado de 1 a 20 pagos por tiempo suyos en
    // una sola transferencia. Omite los que no son suyos o no tienen nada
    // nuevo; `NothingToWithdraw` si en total no hay nada.
    pub fn withdraw_stream_batch(
        env: Env,
        freelancer: Address,
        stream_ids: soroban_sdk::Vec<String>,
    ) -> Result<i128, Error> {
        freelancer.require_auth();
        if stream_ids.is_empty() || stream_ids.len() > MAX_BATCH_READ {
            return Err(Error::TooManyItems);
        }
        let mut total: i128 = 0;
        let mut count: u32 = 0;
        for id in stream_ids.iter() {
            let key = DataKey::Stream(id);
            let mut stream: Stream = match env.storage().persistent().get(&key) {
                Some(st) => st,
                None => continue,
            };
            if stream.freelancer != freelancer {
                continue;
            }
            let available = Self::vested(&env, &stream)? - stream.withdrawn;
            if available <= 0 {
                continue;
            }
            stream.withdrawn += available;
            Self::save_stream(&env, &key, &stream);
            total = total.checked_add(available).ok_or(Error::InvalidAmount)?;
            count += 1;
        }
        if total <= 0 {
            return Err(Error::NothingToWithdraw);
        }
        Self::pay(&env, &freelancer, total)?;
        WithdrawStreamBatchEvent { freelancer, count, total }.publish(&env);
        Ok(total)
    }

    // -----------------------------------------------------------------------
    // v13
    // -----------------------------------------------------------------------

    // Aprobación manual del cliente con comisión de plataforma (1 a 1000
    // puntos base): el programador recibe el monto menos la comisión, que va a
    // `fee_to`. Mismas reglas que `client_release` (también tras el plazo).
    pub fn client_release_with_fee(
        env: Env,
        task_id: String,
        freelancer: Address,
        fee_to: Address,
        fee_bps: u32,
    ) -> Result<i128, Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        task.client.require_auth();
        Self::check_assigned(&task, &freelancer)?;
        let (net, fee) = Self::split_fee(task.amount, fee_bps, &fee_to, &freelancer, &task.client)?;
        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);
        Self::pay(&env, &freelancer, net)?;
        Self::pay(&env, &fee_to, fee)?;
        Self::v13_event(&env, "client_fee", task_id, freelancer, net, fee);
        Ok(net)
    }

    // Lo mismo para un hito: el cliente aprueba manualmente con comisión.
    pub fn client_release_milestone_fee(
        env: Env,
        task_id: String,
        index: u32,
        freelancer: Address,
        fee_to: Address,
        fee_bps: u32,
    ) -> Result<i128, Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        project.client.require_auth();
        let mut m = Self::funded_milestone(&project, index)?;
        Self::bind_freelancer(&mut project, &freelancer)?;
        let (net, fee) = Self::split_fee(m.amount, fee_bps, &fee_to, &freelancer, &project.client)?;
        m.status = MilestoneStatus::Released;
        project.milestones.set(index, m);
        Self::save_project(&env, &key, &project);
        Self::pay(&env, &freelancer, net)?;
        Self::pay(&env, &fee_to, fee)?;
        Self::v13_event(&env, "client_milestone_fee", task_id, freelancer, net, fee);
        Ok(net)
    }

    // Un tercero (patrocinador) aporta USDC a una tarea depositada, antes del
    // plazo. El aporte se suma al pago; si la tarea se reembolsa, todo vuelve
    // al cliente (el patrocinio es un regalo al acuerdo, no un préstamo).
    pub fn contribute_task(env: Env, funder: Address, task_id: String, amount: i128) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        funder.require_auth();
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        if env.ledger().timestamp() >= task.deadline {
            return Err(Error::DeadlinePassed);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if funder == task.client {
            return Err(Error::NoChange);
        }
        task.amount = task.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;
        Self::save_task(&env, &key, &task);
        Self::collect(&env, &funder, amount)?;
        Self::v13_event(&env, "contribute_task", task_id, funder, amount, task.amount);
        Ok(task.amount)
    }

    // Patrocinio de un hito: un tercero aporta a un hito en Funded antes de
    // su plazo. Lo reembolsado vuelve al cliente del proyecto.
    pub fn contribute_milestone(
        env: Env,
        funder: Address,
        task_id: String,
        index: u32,
        amount: i128,
    ) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        funder.require_auth();
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let mut m = Self::funded_milestone(&project, index)?;
        if env.ledger().timestamp() >= m.deadline {
            return Err(Error::DeadlinePassed);
        }
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if funder == project.client {
            return Err(Error::NoChange);
        }
        m.amount = m.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;
        let new_amount = m.amount;
        project.milestones.set(index, m);
        Self::save_project(&env, &key, &project);
        Self::collect(&env, &funder, amount)?;
        Self::v13_event(&env, "contribute_milestone", task_id, funder, amount, new_amount);
        Ok(new_amount)
    }

    // Patrocinio de un pago por tiempo activo: el aporte se reparte en lo que
    // falta del periodo (el final no cambia, la tarifa sube). El programador
    // cobra antes lo ya ganado; si se cancela, lo no liberado vuelve al cliente.
    pub fn contribute_stream(env: Env, funder: Address, stream_id: String, amount: i128) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        funder.require_auth();
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::active_stream(&env, &key)?;
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if funder == stream.client || funder == stream.freelancer {
            return Err(Error::NoChange);
        }
        let (paid, remaining) = Self::settle_earned(&env, &mut stream)?;
        stream.amount = remaining.checked_add(amount).ok_or(Error::InvalidAmount)?;
        Self::save_stream(&env, &key, &stream);
        Self::collect(&env, &funder, amount)?;
        if paid > 0 {
            Self::pay(&env, &stream.freelancer, paid)?;
        }
        Self::v13_event(&env, "contribute_stream", stream_id, funder, amount, stream.amount);
        Ok(stream.amount)
    }

    // El programador aumenta la garantía de un proyecto mientras quede algún
    // hito con dinero.
    pub fn top_up_project_bond(env: Env, task_id: String, amount: i128) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        let key = DataKey::ProjectBond(task_id.clone());
        let mut bond: Bond = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        bond.freelancer.require_auth();
        let project = Self::load_project(&env, &DataKey::Project(task_id.clone()))?;
        Self::require_funded_milestone(&project)?;
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        bond.amount = bond.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;
        env.storage().persistent().set(&key, &bond);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::collect(&env, &bond.freelancer, amount)?;
        Self::v13_event(&env, "top_up_project_bond", task_id, bond.freelancer, amount, bond.amount);
        Ok(bond.amount)
    }

    // El cliente prorroga de una vez todos los hitos de un proyecto que siguen
    // en Funded, `extra_secs` cada uno (el orden de los plazos se conserva).
    // Ningún plazo puede quedar a más de 28 días de ahora. Devuelve cuántos.
    pub fn extend_project_deadlines(env: Env, task_id: String, extra_secs: u64) -> Result<u32, Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        project.client.require_auth();
        if extra_secs == 0 {
            return Err(Error::InvalidDeadline);
        }
        let max = env
            .ledger()
            .timestamp()
            .checked_add(MAX_MILESTONE_DEADLINE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        let mut count: u32 = 0;
        for i in 0..project.milestones.len() {
            let mut m = project.milestones.get(i).ok_or(Error::MilestoneNotFound)?;
            if m.status != MilestoneStatus::Funded {
                continue;
            }
            m.deadline = m.deadline.checked_add(extra_secs).ok_or(Error::InvalidDeadline)?;
            if m.deadline > max {
                return Err(Error::InvalidDeadline);
            }
            project.milestones.set(i, m);
            count += 1;
        }
        if count == 0 {
            return Err(Error::NotFunded);
        }
        Self::save_project(&env, &key, &project);
        Self::v13_event(&env, "extend_project", task_id, project.client, count as i128, extra_secs as i128);
        Ok(count)
    }

    // El programador retira lo liberado de un pago por tiempo hacia otra
    // dirección suya (por ejemplo, la de un exchange o la de su empresa).
    pub fn withdraw_stream_to(env: Env, stream_id: String, to: Address) -> Result<i128, Error> {
        let key = DataKey::Stream(stream_id.clone());
        let mut stream = Self::load_stream(&env, &key)?;
        stream.freelancer.require_auth();
        if to == stream.freelancer {
            return Err(Error::NoChange);
        }
        let available = Self::vested(&env, &stream)?
            .checked_sub(stream.withdrawn)
            .ok_or(Error::InvalidAmount)?;
        if available <= 0 {
            return Err(Error::NothingToWithdraw);
        }
        stream.withdrawn += available;
        Self::save_stream(&env, &key, &stream);
        Self::pay(&env, &to, available)?;
        Self::v13_event(&env, "withdraw_to", stream_id, to, available, stream.withdrawn);
        Ok(available)
    }

    // Cualquiera reembolsa de una vez los hitos vencidos de 1 a 10 proyectos,
    // cada uno a su cliente. Omite los hitos congelados por disputa y los
    // proyectos sin nada vencido. Devuelve cuántos hitos reembolsó.
    pub fn refund_expired_projects_batch(
        env: Env,
        task_ids: soroban_sdk::Vec<String>,
    ) -> Result<u32, Error> {
        if task_ids.is_empty() || task_ids.len() > 10 {
            return Err(Error::TooManyItems);
        }
        let now = env.ledger().timestamp();
        let mut total_count: u32 = 0;
        for task_id in task_ids.iter() {
            let key = DataKey::Project(task_id.clone());
            let mut project: Project = match env.storage().persistent().get(&key) {
                Some(p) => p,
                None => continue,
            };
            let mut refund: i128 = 0;
            for i in 0..project.milestones.len() {
                let mut m = project.milestones.get(i).ok_or(Error::MilestoneNotFound)?;
                if m.status != MilestoneStatus::Funded || now < m.deadline {
                    continue;
                }
                if Self::frozen(&env, &DataKey::MilestoneDispute(task_id.clone(), i), m.deadline)? {
                    continue;
                }
                refund = refund.checked_add(m.amount).ok_or(Error::InvalidAmount)?;
                m.status = MilestoneStatus::Refunded;
                project.milestones.set(i, m);
                total_count += 1;
            }
            if refund > 0 {
                Self::save_project(&env, &key, &project);
                Self::pay(&env, &project.client, refund)?;
                Self::v13_event(&env, "refund_projects", task_id, project.client.clone(), refund, 0);
            }
        }
        if total_count == 0 {
            return Err(Error::DeadlineNotReached);
        }
        Ok(total_count)
    }

    // Cliente y programador fijado cierran un proyecto con un reparto de todo
    // lo pendiente: `freelancer_amount` al programador y el resto al cliente,
    // en una transacción. Todos los hitos en Funded quedan cerrados.
    pub fn mutual_split_project(env: Env, task_id: String, freelancer_amount: i128) -> Result<(), Error> {
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;
        let freelancer = Self::project_freelancer(&project)?;
        project.client.require_auth();
        freelancer.require_auth();
        let mut pending: i128 = 0;
        for i in 0..project.milestones.len() {
            let mut m = project.milestones.get(i).ok_or(Error::MilestoneNotFound)?;
            if m.status == MilestoneStatus::Funded {
                pending = pending.checked_add(m.amount).ok_or(Error::InvalidAmount)?;
                m.status = MilestoneStatus::Released;
                project.milestones.set(i, m);
            }
        }
        if pending == 0 {
            return Err(Error::NotFunded);
        }
        if freelancer_amount <= 0 || freelancer_amount >= pending {
            return Err(Error::InvalidAmount);
        }
        Self::save_project(&env, &key, &project);
        Self::pay(&env, &freelancer, freelancer_amount)?;
        Self::pay(&env, &project.client, pending - freelancer_amount)?;
        Self::v13_event(&env, "split_project", task_id, freelancer, freelancer_amount, pending - freelancer_amount);
        Ok(())
    }

    // -----------------------------------------------------------------------
    // v14 (lote 1): concursos abiertos multi-ganador (`Bounty`)
    // -----------------------------------------------------------------------

    // El cliente abre un concurso con un fondo inicial (`amount`), un plazo
    // y el hash de las reglas. A diferencia de una tarea simple, permite
    // premiar a múltiples ganadores con montos parciales hasta agotar el fondo.
    pub fn open_bounty(
        env: Env,
        client: Address,
        bounty_id: String,
        amount: i128,
        deadline_secs: u64,
        rules_hash: BytesN<32>,
    ) -> Result<(), Error> {
        Self::not_paused(&env)?;
        client.require_auth();
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if deadline_secs == 0 || deadline_secs > MAX_MILESTONE_DEADLINE_SECS {
            return Err(Error::InvalidDeadline);
        }
        let key = DataKey::Bounty(bounty_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        let deadline = env
            .ledger()
            .timestamp()
            .checked_add(deadline_secs)
            .ok_or(Error::InvalidDeadline)?;
        let bounty = Bounty {
            bounty_id: bounty_id.clone(),
            client: client.clone(),
            remaining: amount,
            deadline,
            rules_hash,
        };
        env.storage().persistent().set(&key, &bounty);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::collect(&env, &client, amount)?;
        Self::v14_event(&env, "open_bounty", bounty_id, client, amount, deadline as i128);
        Ok(())
    }

    // Cualquier patrocinador (incluido el cliente) puede sumar USDC al fondo de
    // un concurso abierto antes de su plazo y mientras siga con saldo.
    pub fn top_up_bounty(
        env: Env,
        funder: Address,
        bounty_id: String,
        amount: i128,
    ) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        funder.require_auth();
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let key = DataKey::Bounty(bounty_id.clone());
        let mut bounty: Bounty = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        if bounty.remaining <= 0 {
            return Err(Error::NotFunded);
        }
        if env.ledger().timestamp() >= bounty.deadline {
            return Err(Error::DeadlinePassed);
        }
        bounty.remaining = bounty.remaining.checked_add(amount).ok_or(Error::InvalidAmount)?;
        env.storage().persistent().set(&key, &bounty);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::collect(&env, &funder, amount)?;
        Self::v14_event(&env, "top_up_bounty", bounty_id, funder, amount, bounty.remaining);
        Ok(bounty.remaining)
    }

    // El árbitro premia a un ganador (`amount <= remaining`) antes del plazo,
    // tras verificar su entrega. Puede llamarse varias veces para distintos
    // ganadores hasta agotar el fondo. Devuelve el saldo restante del concurso.
    pub fn award_bounty(
        env: Env,
        bounty_id: String,
        winner: Address,
        amount: i128,
        proof_hash: BytesN<32>,
    ) -> Result<i128, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();
        let key = DataKey::Bounty(bounty_id.clone());
        let mut bounty: Bounty = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        if bounty.remaining <= 0 {
            return Err(Error::NotFunded);
        }
        if env.ledger().timestamp() >= bounty.deadline {
            return Err(Error::DeadlinePassed);
        }
        if amount <= 0 || amount > bounty.remaining {
            return Err(Error::InvalidAmount);
        }
        let _ = proof_hash;
        bounty.remaining -= amount;
        env.storage().persistent().set(&key, &bounty);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::pay(&env, &winner, amount)?;
        Self::v14_event(&env, "award_bounty", bounty_id, winner, amount, bounty.remaining);
        Ok(bounty.remaining)
    }

    // Reembolso sin permisos cuando vence el plazo de un concurso: todo lo que
    // quedó sin premiar vuelve siempre al cliente que lo abrió.
    pub fn refund_bounty(env: Env, bounty_id: String) -> Result<i128, Error> {
        let key = DataKey::Bounty(bounty_id.clone());
        let mut bounty: Bounty = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        if bounty.remaining <= 0 {
            return Err(Error::NotFunded);
        }
        if env.ledger().timestamp() < bounty.deadline {
            return Err(Error::DeadlineNotReached);
        }
        let refund = bounty.remaining;
        bounty.remaining = 0;
        env.storage().persistent().set(&key, &bounty);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::pay(&env, &bounty.client, refund)?;
        Self::v14_event(&env, "refund_bounty", bounty_id, bounty.client, refund, 0);
        Ok(refund)
    }

    // -----------------------------------------------------------------------
    // v14 (lote 2): acuerdos recurrentes por ciclos (`Retainer`)
    // -----------------------------------------------------------------------

    // El cliente deposita de 2 a 12 ciclos fijos de `period_amount` para un
    // programador (`freelancer`). La duración total queda dentro de 28 días.
    pub fn create_retainer(
        env: Env,
        client: Address,
        retainer_id: String,
        freelancer: Address,
        period_amount: i128,
        period_secs: u64,
        cycles: u32,
    ) -> Result<i128, Error> {
        Self::not_paused(&env)?;
        client.require_auth();
        if freelancer == client {
            return Err(Error::NoChange);
        }
        if period_amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        if !(2..=12).contains(&cycles) {
            return Err(Error::InvalidMilestones);
        }
        let span = period_secs.checked_mul(cycles as u64).ok_or(Error::InvalidDeadline)?;
        if period_secs == 0 || span > MAX_MILESTONE_DEADLINE_SECS {
            return Err(Error::InvalidDeadline);
        }
        let key = DataKey::Retainer(retainer_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        let total = period_amount.checked_mul(cycles as i128).ok_or(Error::InvalidAmount)?;
        let start = env.ledger().timestamp();
        start.checked_add(span).ok_or(Error::InvalidDeadline)?;

        let retainer = Retainer {
            retainer_id: retainer_id.clone(),
            client: client.clone(),
            freelancer: freelancer.clone(),
            period_amount,
            period_secs,
            start,
            current_cycle: 0,
            total_cycles: cycles,
        };
        env.storage().persistent().set(&key, &retainer);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::collect(&env, &client, total)?;
        Self::v14_event(&env, "create_retainer", retainer_id, freelancer, total, cycles as i128);
        Ok(total)
    }

    // El árbitro libera el pago del ciclo vigente antes de que venza su plazo.
    // Devuelve cuántos ciclos quedan pendientes.
    pub fn release_retainer_cycle(
        env: Env,
        retainer_id: String,
        deliverable_hash: BytesN<32>,
    ) -> Result<u32, Error> {
        let arbiter = Self::arbiter(&env)?;
        arbiter.require_auth();
        let key = DataKey::Retainer(retainer_id.clone());
        let mut r: Retainer = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        if r.current_cycle >= r.total_cycles {
            return Err(Error::NotFunded);
        }
        let cycle_end = r
            .start
            .checked_add(r.period_secs.checked_mul((r.current_cycle + 1) as u64).ok_or(Error::InvalidDeadline)?)
            .ok_or(Error::InvalidDeadline)?;
        if env.ledger().timestamp() >= cycle_end {
            return Err(Error::DeadlinePassed);
        }
        let _ = deliverable_hash;
        r.current_cycle += 1;
        let left = r.total_cycles - r.current_cycle;
        env.storage().persistent().set(&key, &r);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::pay(&env, &r.freelancer, r.period_amount)?;
        Self::v14_event(&env, "release_retainer", retainer_id, r.freelancer, r.period_amount, left as i128);
        Ok(left)
    }

    // Cualquiera reembolsa un ciclo vencido sin liberar y avanza el contador
    // al siguiente ciclo. El dinero del ciclo perdido vuelve siempre al cliente.
    pub fn refund_expired_retainer_cycle(env: Env, retainer_id: String) -> Result<u32, Error> {
        let key = DataKey::Retainer(retainer_id.clone());
        let mut r: Retainer = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        if r.current_cycle >= r.total_cycles {
            return Err(Error::NotFunded);
        }
        let cycle_end = r
            .start
            .checked_add(r.period_secs.checked_mul((r.current_cycle + 1) as u64).ok_or(Error::InvalidDeadline)?)
            .ok_or(Error::InvalidDeadline)?;
        if env.ledger().timestamp() < cycle_end {
            return Err(Error::DeadlineNotReached);
        }
        r.current_cycle += 1;
        let left = r.total_cycles - r.current_cycle;
        env.storage().persistent().set(&key, &r);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::pay(&env, &r.client, r.period_amount)?;
        Self::v14_event(&env, "refund_retainer", retainer_id, r.client, r.period_amount, left as i128);
        Ok(left)
    }

    // Cliente y programador acuerdan cerrar los ciclos restantes del retainer:
    // todo lo pendiente vuelve al cliente en una sola transferencia.
    pub fn cancel_retainer(env: Env, retainer_id: String) -> Result<i128, Error> {
        let key = DataKey::Retainer(retainer_id.clone());
        let mut r: Retainer = env.storage().persistent().get(&key).ok_or(Error::NotFound)?;
        r.client.require_auth();
        r.freelancer.require_auth();
        if r.current_cycle >= r.total_cycles {
            return Err(Error::NotFunded);
        }
        let remaining_cycles = (r.total_cycles - r.current_cycle) as i128;
        let refund = r.period_amount.checked_mul(remaining_cycles).ok_or(Error::InvalidAmount)?;
        r.current_cycle = r.total_cycles;
        env.storage().persistent().set(&key, &r);
        env.storage().persistent().extend_ttl(&key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(&env);
        Self::pay(&env, &r.client, refund)?;
        Self::v14_event(&env, "cancel_retainer", retainer_id, r.client, refund, remaining_cycles);
        Ok(refund)
    }

    // -----------------------------------------------------------------------
    // Funciones internas (no se exponen en el contrato)
    // -----------------------------------------------------------------------

    fn v14_event(env: &Env, action: &str, id: String, who: Address, amount: i128, extra: i128) {
        V14Event {
            action: soroban_sdk::Symbol::new(env, action),
            id,
            who,
            amount,
            extra,
        }
        .publish(env);
    }

    // v13: separa `amount` en lo que recibe el programador y la comisión.
    fn split_fee(
        amount: i128,
        fee_bps: u32,
        fee_to: &Address,
        freelancer: &Address,
        client: &Address,
    ) -> Result<(i128, i128), Error> {
        if fee_bps == 0 || fee_bps > MAX_FEE_BPS {
            return Err(Error::InvalidAmount);
        }
        if fee_to == freelancer || fee_to == client {
            return Err(Error::NoChange);
        }
        let fee = amount.checked_mul(fee_bps as i128).ok_or(Error::InvalidAmount)? / 10_000;
        if fee <= 0 {
            return Err(Error::InvalidAmount);
        }
        Ok((amount - fee, fee))
    }

    fn v13_event(env: &Env, action: &str, id: String, who: Address, amount: i128, extra: i128) {
        V13Event {
            action: soroban_sdk::Symbol::new(env, action),
            id,
            who,
            amount,
            extra,
        }
        .publish(env);
    }

    // v12: cuántos hitos hay en Funded, Released y Refunded.
    fn milestone_counts(project: &Project) -> (u32, u32, u32) {
        let (mut f, mut r, mut d) = (0, 0, 0);
        for m in project.milestones.iter() {
            match m.status {
                MilestoneStatus::Funded => f += 1,
                MilestoneStatus::Released => r += 1,
                MilestoneStatus::Refunded => d += 1,
            }
        }
        (f, r, d)
    }

    fn project_bond_event(env: &Env, task_id: String, action: &str, to_freelancer: i128, to_client: i128) {
        ProjectBondEvent {
            task_id,
            action: soroban_sdk::Symbol::new(env, action),
            to_freelancer,
            to_client,
        }
        .publish(env);
    }

    // v11: pago por tiempo activo y sin terminar (`NotFunded` si no).
    fn active_stream(env: &Env, key: &DataKey) -> Result<Stream, Error> {
        let stream = Self::load_stream(env, key)?;
        if stream.status != StreamStatus::Active || env.ledger().timestamp() >= stream.end {
            return Err(Error::NotFunded);
        }
        Ok(stream)
    }

    // v11: separa lo ganado y no retirado (`paid`, a pagar al programador) de
    // lo que falta por liberar (`remaining`), y reinicia el pago desde ahora
    // con `remaining` como monto. No transfiere: lo hace quien llama.
    fn settle_earned(env: &Env, stream: &mut Stream) -> Result<(i128, i128), Error> {
        let vested = Self::vested(env, stream)?;
        let paid = vested.checked_sub(stream.withdrawn).ok_or(Error::InvalidAmount)?;
        let remaining = stream.amount.checked_sub(vested).ok_or(Error::InvalidAmount)?;
        stream.amount = remaining;
        stream.withdrawn = 0;
        stream.start = env.ledger().timestamp();
        Ok((paid, remaining))
    }

    // v11: cierra un pago por tiempo (tras settle_earned) dejando constancia
    // de lo que recibió el programador de lo pendiente.
    fn close_stream(env: &Env, key: &DataKey, stream: &mut Stream, freelancer_part: i128) {
        stream.status = StreamStatus::Canceled;
        stream.amount = freelancer_part;
        stream.withdrawn = freelancer_part;
        Self::save_stream(env, key, stream);
    }

    fn stream_event(env: &Env, stream_id: String, action: &str, paid: i128, refunded: i128, remaining: i128, end: u64) {
        StreamChangeEvent {
            stream_id,
            action: soroban_sdk::Symbol::new(env, action),
            paid,
            refunded,
            remaining,
            end,
        }
        .publish(env);
    }

    // v8: lo liberado de un pago por tiempo hasta ahora (lineal en el tiempo).
    // Un pago cancelado ya no libera más: su `amount` es lo ganado al cancelar.
    fn vested(env: &Env, stream: &Stream) -> Result<i128, Error> {
        if stream.status == StreamStatus::Canceled {
            return Ok(stream.amount);
        }
        let now = env.ledger().timestamp();
        if now >= stream.end {
            return Ok(stream.amount);
        }
        let elapsed = now.saturating_sub(stream.start) as i128;
        let duration = (stream.end - stream.start) as i128;
        stream
            .amount
            .checked_mul(elapsed)
            .ok_or(Error::InvalidAmount)
            .map(|x| x / duration)
    }

    fn load_stream(env: &Env, key: &DataKey) -> Result<Stream, Error> {
        env.storage().persistent().get(key).ok_or(Error::NotFound)
    }

    fn save_stream(env: &Env, key: &DataKey, stream: &Stream) {
        env.storage().persistent().set(key, stream);
        env.storage()
            .persistent()
            .extend_ttl(key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(env);
    }

    // v7: true si hay una disputa abierta en `dkey` y todavía no pasan 14 días
    // desde `deadline` (mientras tanto, el reembolso por plazo espera).
    fn frozen(env: &Env, dkey: &DataKey, deadline: u64) -> Result<bool, Error> {
        if !env.storage().persistent().has(dkey) {
            return Ok(false);
        }
        let limit = deadline
            .checked_add(DISPUTE_GRACE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        Ok(env.ledger().timestamp() < limit)
    }

    // v7: el programador fijado de un proyecto (`WrongFreelancer` si no hay).
    fn project_freelancer(project: &Project) -> Result<Address, Error> {
        project.freelancer.clone().ok_or(Error::WrongFreelancer)
    }

    // v7: `NotFunded` si ningún hito del proyecto sigue con dinero.
    fn require_funded_milestone(project: &Project) -> Result<(), Error> {
        for m in project.milestones.iter() {
            if m.status == MilestoneStatus::Funded {
                return Ok(());
            }
        }
        Err(Error::NotFunded)
    }

    // v6: cambia la pausa; `NoChange` si ya estaba en ese estado.
    fn set_paused(env: &Env, paused: bool) -> Result<(), Error> {
        let arbiter = Self::arbiter(env)?;
        arbiter.require_auth();
        let current: bool = env.storage().instance().get(&DataKey::Paused).unwrap_or(false);
        if current == paused {
            return Err(Error::NoChange);
        }
        env.storage().instance().set(&DataKey::Paused, &paused);
        Self::extend_instance(env);
        PauseEvent { paused }.publish(env);
        Ok(())
    }

    // v6: `Paused` si los depósitos están detenidos.
    fn not_paused(env: &Env) -> Result<(), Error> {
        if env.storage().instance().get(&DataKey::Paused).unwrap_or(false) {
            return Err(Error::Paused);
        }
        Ok(())
    }

    // v6: lee uno de los totales de la instancia (0 si nunca se escribió).
    fn total(env: &Env, key: &DataKey) -> i128 {
        env.storage().instance().get(key).unwrap_or(0)
    }

    // v6: suma `amount` a uno de los totales.
    fn add_total(env: &Env, key: &DataKey, amount: i128) -> Result<(), Error> {
        let next = Self::total(env, key)
            .checked_add(amount)
            .ok_or(Error::InvalidAmount)?;
        env.storage().instance().set(key, &next);
        Ok(())
    }

    // v6: toda entrada de USDC al contrato pasa por aquí y queda en `TotalIn`.
    fn collect(env: &Env, from: &Address, amount: i128) -> Result<(), Error> {
        let token_addr = Self::token(env)?;
        token::Client::new(env, &token_addr).transfer(
            from,
            &env.current_contract_address(),
            &amount,
        );
        Self::add_total(env, &DataKey::TotalIn, amount)
    }

    // v6: el programador registrado de una tarea (`WrongFreelancer` si no hay).
    fn assigned(task: &Task) -> Result<Address, Error> {
        task.freelancer.clone().ok_or(Error::WrongFreelancer)
    }

    // v5: si la tarea ya tiene programador registrado, `freelancer` debe ser
    // esa misma dirección. Sin registro (tareas de antes de v5), no restringe.
    fn check_assigned(task: &Task, freelancer: &Address) -> Result<(), Error> {
        match &task.freelancer {
            Some(bound) if bound != freelancer => Err(Error::WrongFreelancer),
            _ => Ok(()),
        }
    }

    // Lee el árbitro de la configuración.
    fn arbiter(env: &Env) -> Result<Address, Error> {
        env.storage()
            .instance()
            .get(&DataKey::Arbiter)
            .ok_or(Error::NotInitialized)
    }

    // Lee el token (SAC de USDC) de la configuración.
    fn token(env: &Env) -> Result<Address, Error> {
        env.storage()
            .instance()
            .get(&DataKey::Token)
            .ok_or(Error::NotInitialized)
    }

    // Extiende el TTL de la instancia (configuración y código del contrato).
    fn extend_instance(env: &Env) {
        env.storage()
            .instance()
            .extend_ttl(TTL_THRESHOLD, TTL_EXTEND_TO);
    }

    // Guarda una tarea y extiende el TTL de su entrada y de la instancia.
    fn save_task(env: &Env, key: &DataKey, task: &Task) {
        env.storage().persistent().set(key, task);
        env.storage()
            .persistent()
            .extend_ttl(key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(env);
    }

    // Carga una tarea y exige que siga en Funded.
    fn funded_task(env: &Env, key: &DataKey) -> Result<Task, Error> {
        let task: Task = env
            .storage()
            .persistent()
            .get(key)
            .ok_or(Error::NotFound)?;
        if task.status != TaskStatus::Funded {
            return Err(Error::NotFunded);
        }
        Ok(task)
    }

    // Guarda un proyecto y extiende el TTL de su entrada y de la instancia.
    fn save_project(env: &Env, key: &DataKey, project: &Project) {
        env.storage().persistent().set(key, project);
        env.storage()
            .persistent()
            .extend_ttl(key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(env);
    }

    // Carga un proyecto (NotFound si no existe).
    fn load_project(env: &Env, key: &DataKey) -> Result<Project, Error> {
        env.storage().persistent().get(key).ok_or(Error::NotFound)
    }

    // Devuelve el hito `index` y exige que siga en Funded.
    fn funded_milestone(project: &Project, index: u32) -> Result<Milestone, Error> {
        let milestone = project
            .milestones
            .get(index)
            .ok_or(Error::MilestoneNotFound)?;
        if milestone.status != MilestoneStatus::Funded {
            return Err(Error::NotFunded);
        }
        Ok(milestone)
    }

    // Fija al programador en el primer pago; en los siguientes exige que sea
    // la misma dirección. Así el dinero de un proyecto nunca se reparte entre
    // dos programadores.
    fn bind_freelancer(project: &mut Project, freelancer: &Address) -> Result<(), Error> {
        match &project.freelancer {
            None => {
                project.freelancer = Some(freelancer.clone());
                Ok(())
            }
            Some(bound) if bound == freelancer => Ok(()),
            Some(_) => Err(Error::WrongFreelancer),
        }
    }

    // Transfiere `amount` del contrato a `to`.
    fn pay(env: &Env, to: &Address, amount: i128) -> Result<(), Error> {
        let token_addr = Self::token(env)?;
        token::Client::new(env, &token_addr).transfer(
            &env.current_contract_address(),
            to,
            &amount,
        );
        // v6: toda salida de USDC del contrato queda en `TotalOut`.
        Self::add_total(env, &DataKey::TotalOut, amount)
    }
}

mod test;

// Pruebas del pago por hitos (v2 y v3).
mod test_hitos;

// Pruebas de las funciones nuevas de v4.
mod test_v4;

// Pruebas de v5 (programador registrado antes de pagar y funciones nuevas).
mod test_v5;

// Pruebas de v6 (acuerdos de dos partes, propina, estadísticas, disputas y pausa).
mod test_v6;

// Pruebas de v7 (acuerdos y disputas en hitos, operaciones por lote).
mod test_v7;

// Pruebas de v8 (pago por tiempo y garantía del programador).
mod test_v8;

// Pruebas de v9.
mod test_v9;

// Pruebas de v10.
mod test_v10;

// Pruebas de v11.
mod test_v11;

// Pruebas de v12.
mod test_v12;

// Pruebas de v13.
mod test_v13;

// Pruebas de v14.
mod test_v14;
