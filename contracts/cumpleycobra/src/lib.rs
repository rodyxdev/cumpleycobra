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

use soroban_sdk::{
    contract, contracterror, contractevent, contractimpl, contracttype, token, Address, BytesN,
    Env, String,
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
// - el programador (`freelancer`) no se conoce al depositar, se fija al liberar;
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
#[contracttype]
#[derive(Clone)]
pub enum DataKey {
    Arbiter,
    Token,
    Task(String),
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

// ---------------------------------------------------------------------------
// Contrato
// ---------------------------------------------------------------------------
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
        if env.storage().persistent().has(&key) {
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
    // Funciones internas (no se exponen en el contrato)
    // -----------------------------------------------------------------------

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
