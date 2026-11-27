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
// criterios). Sin usar estas funciones, todo se comporta igual que en v5.
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
        // Solo el dueño de los fondos puede depositarlos.
        client.require_auth();

        // Validaciones: monto positivo, contrato inicializado, id nuevo.
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let token_addr = Self::token(&env)?;
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
        token::Client::new(&env, &token_addr).transfer(
            &client,
            &env.current_contract_address(),
            &amount,
        );

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
        let token_addr = Self::token(&env)?;
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
        token::Client::new(&env, &token_addr).transfer(
            &client,
            &env.current_contract_address(),
            &total,
        );

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
        // Primero se carga el proyecto para comprobar que existe y saber quién
        // es su cliente.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Solo el cliente del proyecto puede agregar hitos y depositar fondos.
        project.client.require_auth();

        // Contrato inicializado y límite máximo de hitos por proyecto.
        let token_addr = Self::token(&env)?;
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
        token::Client::new(&env, &token_addr).transfer(
            &project.client,
            &env.current_contract_address(),
            &amount,
        );

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
        // Primero se carga el proyecto para comprobar que existe y saber quién
        // es su cliente.
        let key = DataKey::Project(task_id.clone());
        let mut project = Self::load_project(&env, &key)?;

        // Solo el cliente del proyecto puede depositar más fondos en el hito.
        project.client.require_auth();

        // El hito debe existir, seguir en Funded y no haber vencido su plazo.
        let token_addr = Self::token(&env)?;
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
        token::Client::new(&env, &token_addr).transfer(
            &project.client,
            &env.current_contract_address(),
            &amount,
        );

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
                if now >= m.deadline {
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
        token_client.transfer(&env.current_contract_address(), &freelancer, &task.amount);
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

        let token_addr = Self::token(&env)?;
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
        token::Client::new(&env, &token_addr).transfer(
            &client,
            &env.current_contract_address(),
            &total,
        );

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
        let token_addr = Self::token(&env)?;
        token::Client::new(&env, &token_addr).transfer(
            &task.client,
            &env.current_contract_address(),
            &amount,
        );

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

    // -----------------------------------------------------------------------
    // Funciones internas (no se exponen en el contrato)
    // -----------------------------------------------------------------------

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
        Ok(())
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
