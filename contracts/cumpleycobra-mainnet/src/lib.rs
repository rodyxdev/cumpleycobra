#![no_std]

// Cumple&Cobra, edición ligera para mainnet (misión especial de Ship It,
// 27 de noviembre de 2026).
//
// Es el mismo contrato de `contracts/cumpleycobra`, recortado a lo que usa la
// página `/mainnet`: en mainnet se paga por cada byte de código y por su renta,
// y el contrato completo (70 funciones, 63 KB) costaba unos 77 XLM solo de
// subida. Aquí quedan `initialize`, las cinco funciones que firma el cliente
// (`deposit`, `top_up_task`, `extend_deadline`, `client_release`,
// `timeout_refund`), `get_task` y la pausa de emergencia para cerrar la edición
// experimental al terminar el reto. Misma estructura `Task`, mismos números de
// error y mismas reglas que en testnet.

use soroban_sdk::{
    contract, contracterror, contractevent, contractimpl, contracttype, token, Address, BytesN,
    Env, String,
};

// ---------------------------------------------------------------------------
// TTL
// ---------------------------------------------------------------------------
// Las tareas de prueba duran minutos: basta con extender las entradas a 7 días
// cuando les quedan menos de 3. Menos renta que los 30 días de testnet.
const DAY_IN_LEDGERS: u32 = 17_280;
const TTL_THRESHOLD: u32 = 3 * DAY_IN_LEDGERS;
const TTL_EXTEND_TO: u32 = 7 * DAY_IN_LEDGERS;

// Tope de un plazo nuevo al prorrogar: 28 días desde ahora (igual que testnet).
const MAX_DEADLINE_SECS: u64 = 28 * 24 * 60 * 60;

// ---------------------------------------------------------------------------
// Tipos (iguales a los de testnet)
// ---------------------------------------------------------------------------

// Funded -> Released (cliente) o Funded -> Refunded (tras el plazo).
#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TaskStatus {
    Funded,
    Released,
    Refunded,
}

// Una tarea depositada, con el hash de los criterios acordados y su plazo.
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

// Configuración en la instancia; cada tarea, en su propia entrada persistente.
#[contracttype]
#[derive(Clone)]
pub enum DataKey {
    Arbiter,
    Token,
    Paused,
    Task(String),
}

// Los números coinciden con los del contrato de testnet: el frontend los traduce igual.
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
    NoChange = 16,
    Paused = 20,
}

// ---------------------------------------------------------------------------
// Eventos (mismos tópicos que en testnet)
// ---------------------------------------------------------------------------

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

#[contractevent(topics = ["top_up_task"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopUpTaskEvent {
    #[topic]
    pub task_id: String,
    pub added: i128,
    pub new_amount: i128,
}

#[contractevent(topics = ["extend_deadline"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExtendDeadlineEvent {
    #[topic]
    pub task_id: String,
    pub old_deadline: u64,
    pub new_deadline: u64,
}

#[contractevent(topics = ["client_release"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClientReleaseEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub freelancer: Address,
    pub amount: i128,
}

#[contractevent(topics = ["timeout_refund"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TimeoutRefundEvent {
    #[topic]
    pub task_id: String,
    pub client: Address,
    pub amount: i128,
}

#[contractevent(topics = ["pause"])]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PauseEvent {
    pub paused: bool,
}

#[contract]
pub struct CumpleYCobraMainnet;

#[contractimpl]
impl CumpleYCobraMainnet {
    // Una sola vez: guarda el árbitro (solo firma la pausa) y el token.
    pub fn initialize(env: Env, arbiter: Address, token: Address) -> Result<(), Error> {
        if env.storage().instance().has(&DataKey::Arbiter) {
            return Err(Error::AlreadyInitialized);
        }
        arbiter.require_auth();
        env.storage().instance().set(&DataKey::Arbiter, &arbiter);
        env.storage().instance().set(&DataKey::Token, &token);
        Self::extend_instance(&env);
        Ok(())
    }

    // El cliente deposita `amount` amarrado a `task_id` y al hash de los
    // criterios; el plazo es el timestamp del ledger + `deadline_secs`.
    pub fn deposit(
        env: Env,
        client: Address,
        task_id: String,
        amount: i128,
        deadline_secs: u64,
        rules_hash: BytesN<32>,
    ) -> Result<(), Error> {
        Self::not_paused(&env)?;
        client.require_auth();
        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }
        let key = DataKey::Task(task_id.clone());
        if env.storage().persistent().has(&key) {
            return Err(Error::AlreadyExists);
        }
        if deadline_secs == 0 {
            return Err(Error::InvalidDeadline);
        }
        let deadline = env
            .ledger()
            .timestamp()
            .checked_add(deadline_secs)
            .ok_or(Error::InvalidDeadline)?;

        // Efectos antes de la transferencia (checks-effects-interactions).
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
        Self::token_client(&env)?.transfer(&client, &env.current_contract_address(), &amount);

        DepositEvent { task_id, client, amount, deadline, rules_hash }.publish(&env);
        Ok(())
    }

    // El cliente agrega dinero a una tarea depositada, antes del plazo.
    pub fn top_up_task(env: Env, task_id: String, amount: i128) -> Result<i128, Error> {
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
        task.amount = task.amount.checked_add(amount).ok_or(Error::InvalidAmount)?;
        Self::save_task(&env, &key, &task);
        Self::token_client(&env)?.transfer(&task.client, &env.current_contract_address(), &amount);

        TopUpTaskEvent { task_id, added: amount, new_amount: task.amount }.publish(&env);
        Ok(task.amount)
    }

    // El cliente da más tiempo: el plazo solo crece y nunca más de 28 días
    // desde ahora. Se permite tras vencer si nadie pidió el reembolso.
    pub fn extend_deadline(env: Env, task_id: String, extra_secs: u64) -> Result<u64, Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        task.client.require_auth();
        if extra_secs == 0 {
            return Err(Error::InvalidDeadline);
        }
        let new_deadline = task.deadline.checked_add(extra_secs).ok_or(Error::InvalidDeadline)?;
        let max = env
            .ledger()
            .timestamp()
            .checked_add(MAX_DEADLINE_SECS)
            .ok_or(Error::InvalidDeadline)?;
        if new_deadline > max {
            return Err(Error::InvalidDeadline);
        }
        let old_deadline = task.deadline;
        task.deadline = new_deadline;
        Self::save_task(&env, &key, &task);

        ExtendDeadlineEvent { task_id, old_deadline, new_deadline }.publish(&env);
        Ok(new_deadline)
    }

    // Aprobación manual: el cliente paga al programador (también tras el plazo).
    pub fn client_release(env: Env, task_id: String, freelancer: Address) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        task.client.require_auth();

        task.status = TaskStatus::Released;
        task.freelancer = Some(freelancer.clone());
        Self::save_task(&env, &key, &task);
        Self::pay(&env, &freelancer, task.amount)?;

        ClientReleaseEvent { task_id, client: task.client, freelancer, amount: task.amount }.publish(&env);
        Ok(())
    }

    // Reembolso por plazo vencido: sin firma, pero el dinero solo vuelve al cliente.
    pub fn timeout_refund(env: Env, task_id: String) -> Result<(), Error> {
        let key = DataKey::Task(task_id.clone());
        let mut task = Self::funded_task(&env, &key)?;
        if env.ledger().timestamp() < task.deadline {
            return Err(Error::DeadlineNotReached);
        }
        task.status = TaskStatus::Refunded;
        Self::save_task(&env, &key, &task);
        Self::pay(&env, &task.client, task.amount)?;

        TimeoutRefundEvent { task_id, client: task.client, amount: task.amount }.publish(&env);
        Ok(())
    }

    // Lectura de una tarea.
    pub fn get_task(env: Env, task_id: String) -> Result<Task, Error> {
        env.storage().persistent().get(&DataKey::Task(task_id)).ok_or(Error::NotFound)
    }

    // Pausa de emergencia (solo el árbitro): detiene depósitos y recargas,
    // nunca pagos ni reembolsos. Con ella se cierra la edición experimental.
    pub fn pause(env: Env) -> Result<(), Error> {
        Self::set_paused(&env, true)
    }

    pub fn unpause(env: Env) -> Result<(), Error> {
        Self::set_paused(&env, false)
    }

    // -----------------------------------------------------------------------
    // Funciones internas
    // -----------------------------------------------------------------------

    fn set_paused(env: &Env, paused: bool) -> Result<(), Error> {
        let arbiter: Address = env.storage().instance().get(&DataKey::Arbiter).ok_or(Error::NotInitialized)?;
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

    fn not_paused(env: &Env) -> Result<(), Error> {
        if env.storage().instance().get(&DataKey::Paused).unwrap_or(false) {
            return Err(Error::Paused);
        }
        Ok(())
    }

    fn token_client(env: &Env) -> Result<token::Client<'_>, Error> {
        let addr: Address = env.storage().instance().get(&DataKey::Token).ok_or(Error::NotInitialized)?;
        Ok(token::Client::new(env, &addr))
    }

    fn pay(env: &Env, to: &Address, amount: i128) -> Result<(), Error> {
        Self::token_client(env)?.transfer(&env.current_contract_address(), to, &amount);
        Ok(())
    }

    fn extend_instance(env: &Env) {
        env.storage().instance().extend_ttl(TTL_THRESHOLD, TTL_EXTEND_TO);
    }

    fn save_task(env: &Env, key: &DataKey, task: &Task) {
        env.storage().persistent().set(key, task);
        env.storage().persistent().extend_ttl(key, TTL_THRESHOLD, TTL_EXTEND_TO);
        Self::extend_instance(env);
    }

    fn funded_task(env: &Env, key: &DataKey) -> Result<Task, Error> {
        let task: Task = env.storage().persistent().get(key).ok_or(Error::NotFound)?;
        if task.status != TaskStatus::Funded {
            return Err(Error::NotFunded);
        }
        Ok(task)
    }
}

mod test;
