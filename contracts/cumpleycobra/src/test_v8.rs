#![cfg(test)]

// Pruebas de v8: pago por tiempo (streams) y garantía del programador (bond).
// Mismo esquema que `test_v4.rs` a `test_v7.rs`: `Modo::Libre` usa
// `mock_all_auths`; `Modo::Estricto` nunca lo usa y cada firma es explícita.

extern crate std;

use super::test_v4::{setup, Ctx, Modo, DIA, MINT, START_TS, UNIT};
use super::test_v6::firmas;
use super::*;
use soroban_sdk::{
    testutils::{Ledger as _, MockAuth, MockAuthInvoke},
    IntoVal, Val, Vec,
};

fn sid(ctx: &Ctx, s: &str) -> String {
    String::from_str(&ctx.env, s)
}

// Pago por tiempo de 10 UNIT durante 10 días (1 UNIT por día).
fn stream(ctx: &Ctx, nombre: &str) -> String {
    let id = sid(ctx, nombre);
    ctx.c
        .deposit_stream(&ctx.client, &id, &ctx.freelancer, &(10 * UNIT), &(10 * DIA));
    id
}

// ---------------------------------------------------------------------------
// Lote 1: pago por tiempo
// ---------------------------------------------------------------------------

#[test]
fn v8_stream_libera_de_forma_lineal_y_el_programador_retira() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "stream-1");
    let s = ctx.c.get_stream(&id);
    assert_eq!((s.start, s.end, s.withdrawn), (START_TS, START_TS + 10 * DIA, 0));
    assert_eq!(ctx.token.balance(&ctx.contract_id), 10 * UNIT);

    // Al inicio no hay nada liberado.
    assert_eq!(ctx.c.try_withdraw_stream(&id), Err(Ok(Error::NothingToWithdraw)));

    // A los 3 días: 3 UNIT.
    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 3 * UNIT);
    assert_eq!(ctx.c.try_withdraw_stream(&id), Err(Ok(Error::NothingToWithdraw)));

    // A la mitad de un día más: medio UNIT.
    ctx.env.ledger().set_timestamp(START_TS + 3 * DIA + DIA / 2);
    assert_eq!(ctx.c.withdraw_stream(&id), UNIT / 2);

    // Después del final: lo que falta, y ni un centavo más.
    ctx.env.ledger().set_timestamp(START_TS + 30 * DIA);
    assert_eq!(ctx.c.withdraw_stream(&id), 10 * UNIT - 3 * UNIT - UNIT / 2);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 10 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.c.try_withdraw_stream(&id), Err(Ok(Error::NothingToWithdraw)));
    // Terminado, ya no se cancela.
    assert_eq!(ctx.c.try_cancel_stream(&id), Err(Ok(Error::NotFunded)));
}

#[test]
fn v8_deposit_stream_valida_monto_duracion_y_repetidos() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "stream-v");
    assert_eq!(
        ctx.c.try_deposit_stream(&ctx.client, &id, &ctx.freelancer, &UNIT, &DIA),
        Err(Ok(Error::AlreadyExists))
    );
    let otro = sid(&ctx, "stream-v2");
    assert_eq!(
        ctx.c.try_deposit_stream(&ctx.client, &otro, &ctx.freelancer, &0, &DIA),
        Err(Ok(Error::InvalidAmount))
    );
    assert_eq!(
        ctx.c.try_deposit_stream(&ctx.client, &otro, &ctx.freelancer, &UNIT, &0),
        Err(Ok(Error::InvalidDeadline))
    );
    assert_eq!(
        ctx.c.try_deposit_stream(&ctx.client, &otro, &ctx.freelancer, &UNIT, &(29 * DIA)),
        Err(Ok(Error::InvalidDeadline))
    );
    assert_eq!(
        ctx.c.try_deposit_stream(&ctx.client, &otro, &ctx.client, &UNIT, &DIA),
        Err(Ok(Error::NoChange))
    );
    ctx.c.pause();
    assert_eq!(
        ctx.c.try_deposit_stream(&ctx.client, &otro, &ctx.freelancer, &UNIT, &DIA),
        Err(Ok(Error::Paused))
    );
}

#[test]
fn v8_cancel_stream_reparte_lo_ganado_y_lo_no_liberado() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "stream-c");
    ctx.env.ledger().set_timestamp(START_TS + 2 * DIA);
    ctx.c.withdraw_stream(&id); // 2 UNIT
    ctx.env.ledger().set_timestamp(START_TS + 4 * DIA);
    ctx.c.cancel_stream(&id); // 2 UNIT más al programador, 6 de vuelta al cliente
    assert_eq!(ctx.token.balance(&ctx.freelancer), 4 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 4 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    let s = ctx.c.get_stream(&id);
    assert_eq!((s.status, s.amount, s.withdrawn), (StreamStatus::Canceled, 4 * UNIT, 4 * UNIT));

    // Cancelado: ya no libera más ni se cancela dos veces.
    ctx.env.ledger().set_timestamp(START_TS + 9 * DIA);
    assert_eq!(ctx.c.try_withdraw_stream(&id), Err(Ok(Error::NothingToWithdraw)));
    assert_eq!(ctx.c.try_cancel_stream(&id), Err(Ok(Error::NotFunded)));
    let st = ctx.c.get_stats();
    assert_eq!((st.held, st.deposited, st.paid_out), (0, 10 * UNIT, 10 * UNIT));
}

#[test]
fn v8_cancel_stream_sin_retiros_paga_lo_ganado_al_programador() {
    let ctx = setup(Modo::Libre);
    let id = stream(&ctx, "stream-c2");
    ctx.env.ledger().set_timestamp(START_TS + 5 * DIA);
    ctx.c.cancel_stream(&id);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 5 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 5 * UNIT);
    // Lo ganado ya se pagó al cancelar: no queda nada por retirar.
    assert_eq!(ctx.c.try_withdraw_stream(&id), Err(Ok(Error::NothingToWithdraw)));
}

#[test]
fn v8_stream_estricto_cada_parte_firma_lo_suyo() {
    let est = setup(Modo::Estricto);
    let id = sid(&est, "stream-estricto");
    let token_id = est.token.address.clone();
    let args: Vec<Val> = (&est.client, &id, &est.freelancer, 10 * UNIT, 10 * DIA).into_val(&est.env);
    est.env.mock_auths(&[MockAuth {
        address: &est.client,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "deposit_stream",
            args,
            sub_invokes: &[MockAuthInvoke {
                contract: &token_id,
                fn_name: "transfer",
                args: (&est.client, &est.contract_id, 10 * UNIT).into_val(&est.env),
                sub_invokes: &[],
            }],
        },
    }]);
    est.c
        .deposit_stream(&est.client, &id, &est.freelancer, &(10 * UNIT), &(10 * DIA));
    est.env.ledger().set_timestamp(START_TS + DIA);

    let args: Vec<Val> = (&id,).into_val(&est.env);
    // El cliente no retira por el programador.
    firmas(&est, &[&est.client], "withdraw_stream", args.clone());
    assert!(est.c.try_withdraw_stream(&id).is_err());
    firmas(&est, &[&est.freelancer], "withdraw_stream", args.clone());
    assert_eq!(est.c.withdraw_stream(&id), UNIT);
    // El programador no cancela por el cliente.
    firmas(&est, &[&est.freelancer], "cancel_stream", args.clone());
    assert!(est.c.try_cancel_stream(&id).is_err());
    firmas(&est, &[&est.client], "cancel_stream", args);
    est.c.cancel_stream(&id);
    assert_eq!(est.token.balance(&est.client), MINT - UNIT);
}

// ---------------------------------------------------------------------------
// Lote 2: garantía del programador
// ---------------------------------------------------------------------------

// Tarea de 4 UNIT con programador registrado; el programador recibe 3 UNIT
// para poder depositar garantías.
fn tarea_con_programador(ctx: &Ctx, nombre: &str, plazo: u64) -> String {
    let id = super::test_v4::deposit_simple(ctx, nombre, 4 * UNIT, plazo);
    ctx.c.assign_freelancer(&id, &ctx.freelancer);
    id
}

fn fondear_programador(ctx: &Ctx) {
    ctx.token.transfer(&ctx.client, &ctx.freelancer, &(3 * UNIT));
}

#[test]
fn v8_bond_vuelve_al_programador_si_la_tarea_se_paga() {
    let ctx = setup(Modo::Libre);
    fondear_programador(&ctx);
    let sin = super::test_v4::deposit_simple(&ctx, "bond-0", UNIT, DIA);
    assert_eq!(ctx.c.try_post_bond(&sin, &UNIT), Err(Ok(Error::WrongFreelancer)));

    let id = tarea_con_programador(&ctx, "bond-1", DIA);
    assert_eq!(ctx.c.try_post_bond(&id, &0), Err(Ok(Error::InvalidAmount)));
    ctx.c.post_bond(&id, &UNIT);
    assert_eq!(ctx.c.get_bond(&id).unwrap().amount, UNIT);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 2 * UNIT);
    assert_eq!(ctx.c.try_post_bond(&id, &UNIT), Err(Ok(Error::AlreadyExists)));

    // Con la tarea abierta no se recupera ni se pierde.
    assert_eq!(ctx.c.try_reclaim_bond(&id), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.c.try_slash_bond(&id), Err(Ok(Error::NotFunded)));

    ctx.c.client_release(&id, &ctx.freelancer);
    // Pagada: el árbitro ya no puede quitarle la garantía.
    assert_eq!(ctx.c.try_slash_bond(&id), Err(Ok(Error::NotFunded)));
    assert_eq!(ctx.c.reclaim_bond(&id), UNIT);
    assert_eq!(ctx.c.get_bond(&id), None);
    assert_eq!(ctx.token.balance(&ctx.freelancer), 3 * UNIT + 4 * UNIT);
    assert_eq!(ctx.c.try_reclaim_bond(&id), Err(Ok(Error::NotFound)));
}

#[test]
fn v8_bond_pasa_al_cliente_si_la_tarea_termina_reembolsada() {
    let ctx = setup(Modo::Libre);
    fondear_programador(&ctx);
    let id = tarea_con_programador(&ctx, "bond-2", 100);
    ctx.c.post_bond(&id, &(2 * UNIT));
    ctx.env.ledger().set_timestamp(START_TS + 100);
    assert_eq!(ctx.c.try_post_bond(&id, &UNIT), Err(Ok(Error::DeadlinePassed)));
    ctx.c.timeout_refund(&id);
    // Reembolsada: el programador no la recupera antes de 14 días…
    assert_eq!(ctx.c.try_reclaim_bond(&id), Err(Ok(Error::DeadlineNotReached)));
    // …y el árbitro la da al cliente.
    assert_eq!(ctx.c.slash_bond(&id), 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.client), MINT - 3 * UNIT + 2 * UNIT);
    assert_eq!(ctx.token.balance(&ctx.contract_id), 0);
    assert_eq!(ctx.c.get_stats().held, 0);
}

#[test]
fn v8_bond_sin_decision_del_arbitro_vuelve_al_programador_a_los_14_dias() {
    let ctx = setup(Modo::Libre);
    fondear_programador(&ctx);
    let id = tarea_con_programador(&ctx, "bond-3", 100);
    ctx.c.post_bond(&id, &UNIT);
    ctx.env.ledger().set_timestamp(START_TS + 100);
    ctx.c.timeout_refund(&id);
    ctx.env.ledger().set_timestamp(START_TS + 100 + 14 * DIA);
    assert_eq!(ctx.c.reclaim_bond(&id), UNIT);
    assert_eq!(ctx.c.try_slash_bond(&id), Err(Ok(Error::NotFound)));
}

#[test]
fn v8_bond_estricto_cada_parte_firma_lo_suyo() {
    let est = setup(Modo::Estricto);
    // Fondos y tarea con firmas explícitas.
    let token_id = est.token.address.clone();
    est.env.mock_auths(&[MockAuth {
        address: &est.client,
        invoke: &MockAuthInvoke {
            contract: &token_id,
            fn_name: "transfer",
            args: (&est.client, &est.freelancer, 3 * UNIT).into_val(&est.env),
            sub_invokes: &[],
        },
    }]);
    est.token.transfer(&est.client, &est.freelancer, &(3 * UNIT));
    let id = super::test_v4::deposit_simple(&est, "bond-estricto", 4 * UNIT, 100);
    firmas(&est, &[&est.arbiter], "assign_freelancer", (&id, &est.freelancer).into_val(&est.env));
    est.c.assign_freelancer(&id, &est.freelancer);

    // El cliente no puede depositar la garantía por el programador.
    firmas(&est, &[&est.client], "post_bond", (&id, UNIT).into_val(&est.env));
    assert!(est.c.try_post_bond(&id, &UNIT).is_err());
    est.env.mock_auths(&[MockAuth {
        address: &est.freelancer,
        invoke: &MockAuthInvoke {
            contract: &est.contract_id,
            fn_name: "post_bond",
            args: (&id, UNIT).into_val(&est.env),
            sub_invokes: &[MockAuthInvoke {
                contract: &token_id,
                fn_name: "transfer",
                args: (&est.freelancer, &est.contract_id, UNIT).into_val(&est.env),
                sub_invokes: &[],
            }],
        },
    }]);
    est.c.post_bond(&id, &UNIT);

    est.env.ledger().set_timestamp(START_TS + 100);
    est.c.timeout_refund(&id);
    let args: Vec<Val> = (&id,).into_val(&est.env);
    // Solo el árbitro la da al cliente.
    firmas(&est, &[&est.client], "slash_bond", args.clone());
    assert!(est.c.try_slash_bond(&id).is_err());
    firmas(&est, &[&est.arbiter], "slash_bond", args);
    est.c.slash_bond(&id);
    assert_eq!(est.token.balance(&est.client), MINT - 3 * UNIT + UNIT);
}
