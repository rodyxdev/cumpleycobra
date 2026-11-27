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
